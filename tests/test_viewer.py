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
