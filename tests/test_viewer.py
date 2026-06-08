"""AgentLens Viewer 测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _make_store_with_events(tmp_path: Path, events: list[TraceEvent]) -> JsonlTraceStore:
    """创建带有预设事件的临时 store。"""
    store = JsonlTraceStore(base_dir=tmp_path / "runs")
    for ev in events:
        store.append_event(ev)
    return store


# ---------------------------------------------------------------------------
# get_run_summaries 测试
# ---------------------------------------------------------------------------


class TestGetRunSummaries:
    """get_run_summaries 纯函数测试。"""

    def test_empty_store_returns_empty_list(self, tmp_path):
        """空 store 返回空列表。"""
        from agentlens.viewer import get_run_summaries

        store = JsonlTraceStore(base_dir=tmp_path / "empty_runs")
        summaries = get_run_summaries(store)
        assert summaries == []

    def test_single_run_basic_info(self, tmp_path):
        """单个 run 的摘要包含基本信息。"""
        from agentlens.viewer import get_run_summaries

        events = [
            TraceEvent(run_id="run_001", type="run_start", name="test-agent"),
            TraceEvent(run_id="run_001", type="llm_call", name="gpt-4"),
            TraceEvent(run_id="run_001", type="run_end", name="test-agent"),
        ]
        store = _make_store_with_events(tmp_path, events)

        summaries = get_run_summaries(store)
        assert len(summaries) == 1
        assert summaries[0]["run_id"] == "run_001"
        assert summaries[0]["name"] == "test-agent"
        assert summaries[0]["event_count"] == 3
        assert summaries[0]["has_error"] is False

    def test_run_with_error_has_error_true(self, tmp_path):
        """包含 error 事件的 run 标记 has_error=True。"""
        from agentlens.viewer import get_run_summaries

        events = [
            TraceEvent(run_id="run_err", type="run_start", name="bad-agent"),
            TraceEvent(
                run_id="run_err",
                type="error",
                name="bad-agent",
                error="Something went wrong",
            ),
        ]
        store = _make_store_with_events(tmp_path, events)

        summaries = get_run_summaries(store)
        assert len(summaries) == 1
        assert summaries[0]["has_error"] is True

    def test_run_without_run_start_uses_unknown_name(self, tmp_path):
        """没有 run_start 事件时 name 显示 unknown。"""
        from agentlens.viewer import get_run_summaries

        events = [
            TraceEvent(run_id="run_no_start", type="log", name="just a log"),
        ]
        store = _make_store_with_events(tmp_path, events)

        summaries = get_run_summaries(store)
        assert summaries[0]["name"] == "unknown"


class TestGetRunDetail:
    """get_run_detail 测试。"""

    def test_returns_run_detail(self, tmp_path):
        """返回 run 详情包含 events 列表。"""
        from agentlens.viewer import get_run_detail

        events = [
            TraceEvent(run_id="run_det", type="run_start", name="det-agent"),
            TraceEvent(
                run_id="run_det",
                type="llm_call",
                name="gpt-4",
                input="hello",
                output="hi",
            ),
        ]
        store = _make_store_with_events(tmp_path, events)

        detail = get_run_detail(store, "run_det")
        assert detail["run_id"] == "run_det"
        assert detail["name"] == "det-agent"
        assert len(detail["events"]) == 2


class TestViewerCLI:
    """CLI view 命令测试。"""

    def test_view_command_missing_deps_shows_error(self):
        """未安装 web 依赖时给出清晰错误信息。"""
        from agentlens.viewer import start_viewer

        with mock.patch.dict(sys.modules, {"uvicorn": None}):
            with pytest.raises(ImportError, match="未安装 web 依赖"):
                start_viewer()


# ---------------------------------------------------------------------------
# FastAPI 路由测试
# ---------------------------------------------------------------------------


class TestViewerRoutes:
    """FastAPI 路由行为测试。"""

    def test_index_returns_html(self, tmp_path):
        """首页返回 200 且 content-type 为 text/html。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "AgentLens Timeline Viewer" in resp.text

    def test_index_no_query_error(self, tmp_path):
        """首页不因缺少 query 参数而返回 JSON error。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_diff_missing_params_shows_error(self, tmp_path):
        """/diff 缺少参数时返回 422 或 HTML 错误页。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/diff")
        # 缺少必填参数 → FastAPI 返回 422 validation error
        assert resp.status_code == 422

    def test_diff_not_found_shows_error(self, tmp_path):
        """/diff 的 run_id 不存在时返回错误页。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/diff?left=nonexistent&right=also_fake")
        assert resp.status_code == 200
        assert "Run not found" in resp.text

    def test_diff_valid_runs_returns_html(self, tmp_path):
        """/diff 对存在的 run 返回 200 HTML。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [
                TraceEvent(run_id="a", type="run_start", name="same-agent"),
                TraceEvent(run_id="a", type="log", name="step1"),
                TraceEvent(run_id="b", type="run_start", name="same-agent"),
                TraceEvent(run_id="b", type="log", name="step1"),
            ],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/diff?left=a&right=b")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Run Diff" in resp.text
        assert "No differences" in resp.text

    def test_diff_page_shows_first_difference(self, tmp_path):
        """/diff 页面包含 first difference 信息。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [
                TraceEvent(run_id="x", type="run_start", name="same-agent"),
                TraceEvent(run_id="x", type="tool_call", name="search"),
                TraceEvent(run_id="y", type="run_start", name="same-agent"),
                TraceEvent(run_id="y", type="llm_call", name="ask"),
            ],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/diff?left=x&right=y")
        assert resp.status_code == 200
        assert "First difference at step #2" in resp.text

    def test_diff_html_escapes_event_data(self, tmp_path):
        """/diff 页面对事件数据做 HTML escape 避免 XSS。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [
                TraceEvent(
                    run_id="safe",
                    type="tool_call",
                    name="safe",
                    input={"xss": "<script>alert(1)</script>"},
                ),
            ],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/diff?left=safe&right=safe")
        assert resp.status_code == 200
        # 原始 script 标签不应出现在 HTML 中
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text


# ---------------------------------------------------------------------------
# compare_runs 纯函数测试
# ---------------------------------------------------------------------------


class TestCompareRuns:
    """compare_runs 函数测试。"""

    def test_all_same_for_identical_sequences(self):
        """两个相同事件序列返回 all same。"""
        from agentlens.viewer import compare_runs

        events = [
            {"type": "run_start", "name": "agent"},
            {"type": "tool_call", "name": "search"},
        ]
        result = compare_runs(events, events)
        assert result["first_diff"] is None
        assert all(r["status"] == "same" for r in result["rows"])

    def test_changed_for_type_name_diff(self):
        """type 或 name 不同时返回 changed。"""
        from agentlens.viewer import compare_runs

        left = [{"type": "run_start", "name": "agent-a"}]
        right = [{"type": "run_start", "name": "agent-b"}]
        result = compare_runs(left, right)
        assert result["rows"][0]["status"] == "changed"
        assert result["first_diff"] == 0

    def test_missing_right_for_longer_left(self):
        """左边更长时返回 missing_right。"""
        from agentlens.viewer import compare_runs

        left = [
            {"type": "run_start", "name": "a"},
            {"type": "tool_call", "name": "search"},
        ]
        right = [{"type": "run_start", "name": "a"}]
        result = compare_runs(left, right)
        assert result["rows"][0]["status"] == "same"
        assert result["rows"][1]["status"] == "missing_right"

    def test_missing_left_for_longer_right(self):
        """右边更长时返回 missing_left。"""
        from agentlens.viewer import compare_runs

        left = [{"type": "run_start", "name": "a"}]
        right = [
            {"type": "run_start", "name": "a"},
            {"type": "tool_call", "name": "search"},
        ]
        result = compare_runs(left, right)
        assert result["rows"][0]["status"] == "same"
        assert result["rows"][1]["status"] == "missing_left"
