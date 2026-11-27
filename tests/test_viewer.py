"""AgentLens Viewer 测试。"""

from __future__ import annotations

import html
import re
import socket
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
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
        """首页返回 200 且 content-type 为 text/html，包含核心文案。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "AgentLens" in resp.text
        assert "Local flight recorder" in resp.text

    def test_index_no_query_error(self, tmp_path):
        """首页不因缺少 query 参数而返回 JSON error。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_index_empty_state(self, tmp_path):
        """首页空状态包含 No runs yet 提示。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        app = create_app(base_dir=tmp_path / "runs")
        client = TestClient(app)
        resp = client.get("/")
        assert "No runs yet" in resp.text

    def test_index_has_compare_button(self, tmp_path):
        """首页有 run 列表时包含 Compare selected。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [TraceEvent(run_id="z", type="run_start", name="test")],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/")
        assert "Compare selected" in resp.text

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
        """/diff 对存在的 run 返回 200 HTML，含 summary cards。"""
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
        assert "Same" in resp.text
        assert "Changed" in resp.text
        assert "tr.diff-detail { display: none" in resp.text
        assert "diff-detail open" not in resp.text
        assert 'id="body-d0"' in resp.text
        assert "toggleEvent('d0')" in resp.text

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

    def test_detail_page_shows_summary_and_escapes_tool_names(self, tmp_path):
        """详情页展示派生统计，并转义工具名。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [
                TraceEvent(run_id="detail", type="run_start", name="demo"),
                TraceEvent(run_id="detail", type="llm_call", name="model"),
                TraceEvent(run_id="detail", type="tool_call", name="tool<script>name"),
            ],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/run/detail")
        assert resp.status_code == 200
        assert "LLM calls" in resp.text
        assert "Tool calls" in resp.text
        assert "Tokens" in resp.text
        assert "tool<script>name" not in resp.text
        assert "tool&lt;script&gt;name" in resp.text

    def test_diff_page_shows_payload_field_after_alignment(self, tmp_path):
        """插入的事件不会把后面的同名事件标成整段不同，payload 差异会标出字段。"""
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [
                TraceEvent(run_id="left", type="run_start", name="agent"),
                TraceEvent(run_id="left", type="tool_call", name="search", input={"q": "a"}),
                TraceEvent(run_id="right", type="run_start", name="agent"),
                TraceEvent(run_id="right", type="llm_call", name="ask"),
                TraceEvent(run_id="right", type="tool_call", name="search", input={"q": "b"}),
            ],
        )
        app = create_app(base_dir=store.base_dir)
        client = TestClient(app)
        resp = client.get("/diff?left=left&right=right")
        assert resp.status_code == 200
        assert "Aligned by type and name" in resp.text
        assert 'class="diff-fields">input</span>' in resp.text
        assert "First difference at step #2" in resp.text


# ---------------------------------------------------------------------------
# 详情页上的逐步查看
# ---------------------------------------------------------------------------

_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
_MISSING_PARENT = Path(__file__).parent / "fixtures" / "run_missing_parent.jsonl"


def _out_of_order_events() -> list[TraceEvent]:
    """子事件写在父事件前面，另一条的父事件不在本次记录里。

    文件顺序、时间顺序、树顺序三者不同。逐步查看必须跟文件顺序。
    """
    return [
        TraceEvent(
            id="child",
            run_id="ooo",
            parent_event_id="parent",
            type="tool_call",
            name="child-before-parent",
            output={"n": 1},
            started_at=_START + timedelta(seconds=5),
            ended_at=_START + timedelta(seconds=6),
        ),
        TraceEvent(
            id="orphan",
            run_id="ooo",
            parent_event_id="missing-parent",
            type="log",
            name="orphan-missing",
            output="[REDACTED]",
            started_at=_START + timedelta(seconds=1),
            ended_at=_START + timedelta(seconds=1),
        ),
        TraceEvent(
            id="parent",
            run_id="ooo",
            type="llm_call",
            name="parent-after-child",
            output="answer",
            started_at=_START,
            ended_at=_START + timedelta(milliseconds=10),
        ),
    ]


def _tree_order(events: list[TraceEvent]) -> list[str]:
    from agentlens.tree import build_event_tree

    tree = build_event_tree(events)
    ordered: list[str] = []

    def walk(node: object) -> None:
        ordered.append(node.event.id)  # type: ignore[attr-defined]
        for child in node.children:  # type: ignore[attr-defined]
            walk(child)

    for node in tree.roots:
        walk(node)
    for node in tree.detached:
        walk(node)
    for group in tree.missing_parents:
        for node in group.nodes:
            walk(node)
    return ordered


def _time_order(events: list[TraceEvent]) -> list[str]:
    ordered = sorted(events, key=lambda event: event.started_at)
    return [event.id for event in ordered]


def _timeline_html(page: str) -> str:
    match = re.search(
        r'<div class="timeline">(.*)</div>\s*<div class="footer">',
        page,
        re.S,
    )
    assert match is not None
    return match.group(1)


def _href(page: str, element_id: str) -> str | None:
    match = re.search(rf'id="{element_id}" href="([^"]+)"', page)
    if match is None:
        return None
    return html.unescape(match.group(1))


def _cards(fragment: str) -> list[dict[str, object]]:
    pattern = re.compile(r'<div class="([^"]*)" data-event-id="([^"]*)" data-index="(\d+)"([^>]*)>')
    found: list[dict[str, object]] = []
    for classes, event_id, index, rest in pattern.findall(fragment):
        found.append(
            {
                "id": event_id,
                "index": int(index),
                "current": 'data-replay-current="true"' in rest,
                "highlighted": "replay-current" in classes.split(),
                "missing": 'data-parent-missing="true"' in rest,
            }
        )
    return found


def _body_is_open(page: str, index: int) -> bool:
    match = re.search(rf'class="(event-card-body[^"]*)" id="body-ev{index}"', page)
    assert match is not None
    return "open" in match.group(1).split()


def _assert_read_only_page(page: str) -> None:
    assert "Read-only" in page
    assert 'method="post"' not in page
    assert "<select" not in page
    assert 'type="number"' not in page
    assert "/replay" not in page


def _assert_controls(
    page: str,
    *,
    step: int,
    seen: int,
    count: int,
    run_id: str,
) -> None:
    previous = _href(page, "replay-prev")
    nxt = _href(page, "replay-next")
    if step > 1:
        assert previous == f"/run/{run_id}?step={step - 1}&seen={seen}"
    else:
        assert previous is None
        assert 'id="replay-prev" disabled' in page
    if step < count:
        assert nxt == f"/run/{run_id}?step={step + 1}&seen={max(seen, step + 1)}"
    else:
        assert nxt is None
        assert 'id="replay-next" disabled' in page
    assert f'data-replay-mode="step" data-step="{step}" data-seen="{seen}"' in page
    assert f"第 {step} / 共 {count} 步" in page
    assert ">Current<" not in page
    assert ">当前<" not in page
    found = set(re.findall(r"\?step=(\d+)", page))
    expected: set[str] = set()
    if step > 1:
        expected.add(str(step - 1))
    if step < count:
        expected.add(str(step + 1))
    assert found == expected


def _visible_ids(page: str) -> list[str]:
    return [str(card["id"]) for card in _cards(_timeline_html(page))]


class TestReplayFrame:
    """逐步查看使用 replay 模块的原顺序，不重排。"""

    def test_visited_prefix_keeps_missing_parent_and_out_of_order_events(self) -> None:
        from agentlens.replay import replay_run
        from agentlens.viewer import ReplayStepOutOfRange, replay_frame

        events = _out_of_order_events()
        file_order = [event.id for event in events]
        assert _tree_order(events) == ["parent", "child", "orphan"]
        assert _time_order(events) == ["parent", "orphan", "child"]
        assert file_order != _tree_order(events)
        assert file_order != _time_order(events)
        assert [step.event_id for step in replay_run(events).steps] == file_order

        first = replay_frame(events, step=1, run_id="ooo")
        assert first["seen"] == 1
        assert [item["event_id"] for item in first["visible"]] == ["child"]
        assert first["visible"][0]["current"] is True
        assert first["visible"][0]["parent_missing"] is False
        assert first["visible"][0]["parent_event_id"] == "parent"
        assert first["has_previous"] is False

        second = replay_frame(events, step=2, seen=2, run_id="ooo")
        assert [item["event_id"] for item in second["visible"]] == ["child", "orphan"]
        assert [item["current"] for item in second["visible"]] == [False, True]
        assert second["visible"][1]["parent_missing"] is True
        assert second["order"] == file_order

        rewound = replay_frame(events, step=1, seen=2, run_id="ooo")
        assert [item["event_id"] for item in rewound["visible"]] == ["child", "orphan"]
        assert [item["current"] for item in rewound["visible"]] == [True, False]
        assert rewound["has_next"] is True

        played = replay_frame(events, step=3, run_id="ooo")
        assert [item["event_id"] for item in played["visible"]] == file_order
        assert [item["current"] for item in played["visible"]] == [False, False, True]
        assert played["has_next"] is False
        assert [event.id for event in events] == file_order

        with pytest.raises(ReplayStepOutOfRange):
            replay_frame(events, step=0, run_id="ooo")
        with pytest.raises(ReplayStepOutOfRange):
            replay_frame(events, step=4, run_id="ooo")
        with pytest.raises(ReplayStepOutOfRange):
            replay_frame(events, step=2, seen=1, run_id="ooo")


class TestStepwiseDetailPage:
    """上一步 / 下一步在原来的 run 详情页上，并且只读。"""

    def test_prev_next_accumulate_file_order_and_stay_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        events = _out_of_order_events()
        store = _make_store_with_events(tmp_path, events)
        path = store.base_dir / "ooo.jsonl"
        before = path.read_bytes()
        names_before = sorted(item.name for item in store.base_dir.iterdir())

        def _forbid_append(self: JsonlTraceStore, event: TraceEvent) -> None:
            raise AssertionError("stepwise replay wrote an event")

        def _forbid_connect(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("stepwise replay opened a connection")

        monkeypatch.setattr(JsonlTraceStore, "append_event", _forbid_append)
        monkeypatch.setattr(socket, "create_connection", _forbid_connect)
        monkeypatch.setattr(urllib.request, "urlopen", _forbid_connect)

        client = TestClient(create_app(base_dir=store.base_dir))
        timeline = client.get("/run/ooo")
        assert timeline.status_code == 200
        _assert_read_only_page(timeline.text)
        assert 'data-replay-mode="timeline"' in timeline.text
        assert "← Back to runs" in timeline.text
        assert _visible_ids(timeline.text) == ["child", "orphan", "parent"]
        assert [card["current"] for card in _cards(_timeline_html(timeline.text))] == [
            False,
            False,
            False,
        ]
        assert _href(timeline.text, "replay-prev") is None
        assert _href(timeline.text, "replay-next") == "/run/ooo?step=1&seen=1"
        assert "?step=2" not in timeline.text

        href: str | None = _href(timeline.text, "replay-next")
        page = ""
        step = 0
        while href is not None:
            resp = client.get(href)
            assert resp.status_code == 200
            page = resp.text
            step += 1
            _assert_read_only_page(page)
            _assert_controls(page, step=step, seen=step, count=3, run_id="ooo")
            cards = _cards(_timeline_html(page))
            assert [card["id"] for card in cards] == ["child", "orphan", "parent"][:step]
            assert [card["current"] for card in cards] == [False] * (step - 1) + [True]
            assert [card["highlighted"] for card in cards] == [card["current"] for card in cards]
            assert _body_is_open(page, step - 1)
            for index in range(step - 1):
                assert not _body_is_open(page, index)
            timeline_only = _timeline_html(page)
            if step == 1:
                assert "orphan-missing" not in timeline_only
                assert "parent-after-child" not in timeline_only
                assert "parent=parent" in timeline_only
            elif step == 2:
                assert "child-before-parent" in timeline_only
                assert "orphan-missing" in timeline_only
                assert "parent-after-child" not in timeline_only
                assert ">missing parent</span>" in timeline_only
            href = _href(page, "replay-next")

        assert step == 3
        full = _timeline_html(page)
        assert "child-before-parent" in full
        assert "orphan-missing" in full
        assert "parent-after-child" in full
        assert full.count(">missing parent</span>") == 1
        assert "[REDACTED]" in full
        assert _visible_ids(page) != _tree_order(events)
        assert _visible_ids(page) != _time_order(events)

        back = client.get(_href(page, "replay-prev") or "")
        assert back.status_code == 200
        _assert_controls(back.text, step=2, seen=3, count=3, run_id="ooo")
        cards = _cards(_timeline_html(back.text))
        assert [card["id"] for card in cards] == ["child", "orphan", "parent"]
        assert [card["current"] for card in cards] == [False, True, False]
        assert cards[1]["missing"] is True
        assert cards[0]["missing"] is False
        assert cards[2]["missing"] is False
        assert "parent-after-child" in _timeline_html(back.text)
        assert _body_is_open(back.text, 1)
        assert not _body_is_open(back.text, 0)
        assert not _body_is_open(back.text, 2)

        earlier = client.get(_href(back.text, "replay-prev") or "")
        _assert_controls(earlier.text, step=1, seen=3, count=3, run_id="ooo")
        assert _visible_ids(earlier.text) == ["child", "orphan", "parent"]
        assert [card["current"] for card in _cards(_timeline_html(earlier.text))] == [
            True,
            False,
            False,
        ]
        assert _href(earlier.text, "replay-next") == "/run/ooo?step=2&seen=3"
        assert path.read_bytes() == before
        assert sorted(item.name for item in store.base_dir.iterdir()) == names_before

    def test_missing_parent_fixture_stays_in_jsonl_order(self, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        events = [
            TraceEvent.model_validate_json(line)
            for line in _MISSING_PARENT.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        file_order = [event.id for event in events]
        assert file_order != _tree_order(events)
        base = tmp_path / "runs"
        base.mkdir()
        target = base / "run_missing_parent.jsonl"
        before = _MISSING_PARENT.read_bytes()
        target.write_bytes(before)

        client = TestClient(create_app(base_dir=base))
        timeline = client.get("/run/run_missing_parent")
        assert _visible_ids(timeline.text) == file_order

        href = _href(timeline.text, "replay-next")
        page = ""
        step = 0
        while href is not None:
            resp = client.get(href)
            assert resp.status_code == 200
            page = resp.text
            step += 1
            _assert_controls(
                page,
                step=step,
                seen=step,
                count=len(file_order),
                run_id="run_missing_parent",
            )
            assert _visible_ids(page) == file_order[:step]
            href = _href(page, "replay-next")
        assert step == len(file_order)
        assert _visible_ids(page) == file_order
        assert target.read_bytes() == before

        rewound = client.get(_href(page, "replay-prev") or "")
        _assert_controls(
            rewound.text,
            step=len(file_order) - 1,
            seen=len(file_order),
            count=len(file_order),
            run_id="run_missing_parent",
        )
        assert _visible_ids(rewound.text) == file_order

        orphan = client.get("/run/run_missing_parent?step=3")
        orphan_cards = _cards(_timeline_html(orphan.text))
        assert [card["id"] for card in orphan_cards] == ["root", "search", "orphan-a"]
        assert [card["current"] for card in orphan_cards] == [False, False, True]
        assert orphan_cards[2]["missing"] is True
        assert ">missing parent</span>" in _timeline_html(orphan.text)
        child = client.get("/run/run_missing_parent?step=4&seen=4")
        child_cards = _cards(_timeline_html(child.text))
        assert [card["id"] for card in child_cards] == ["root", "search", "orphan-a", "child"]
        assert child_cards[3]["current"] is True
        assert child_cards[3]["missing"] is False
        assert child_cards[2]["missing"] is True

    def test_single_event_disables_both_directions(self, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(
            tmp_path,
            [TraceEvent(id="only", run_id="one", type="log", name="only-event")],
        )
        client = TestClient(create_app(base_dir=store.base_dir))
        opened = client.get("/run/one?step=1")
        assert opened.status_code == 200
        assert "第 1 / 共 1 步" in opened.text
        assert ">Current<" not in opened.text
        assert ">当前<" not in opened.text
        assert 'id="replay-prev" disabled' in opened.text
        assert 'id="replay-next" disabled' in opened.text
        assert _href(opened.text, "replay-prev") is None
        assert _href(opened.text, "replay-next") is None
        cards = _cards(_timeline_html(opened.text))
        assert [card["id"] for card in cards] == ["only"]
        assert cards[0]["current"] is True
        assert cards[0]["highlighted"] is True

    def test_step_out_of_range_and_missing_run(self, tmp_path: Path) -> None:
        from fastapi.testclient import TestClient

        from agentlens.viewer import create_app

        store = _make_store_with_events(tmp_path, _out_of_order_events())
        client = TestClient(create_app(base_dir=store.base_dir))
        for query in ("step=0", "step=4", "step=-1", "step=2&seen=1", "step=1&seen=9"):
            resp = client.get(f"/run/ooo?{query}")
            assert resp.status_code == 200
            assert "Step out of range" in resp.text
            assert "child-before-parent" not in resp.text
        missing = client.get("/run/missing?step=1")
        assert missing.status_code == 200
        assert "Run not found" in missing.text
        separate = client.get("/run/ooo/replay")
        assert separate.status_code == 404

    def test_step_mode_escapes_event_text(self, tmp_path: Path) -> None:
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
                )
            ],
        )
        client = TestClient(create_app(base_dir=store.base_dir))
        resp = client.get("/run/safe?step=1")
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in resp.text
        assert "&lt;script&gt;" in resp.text
