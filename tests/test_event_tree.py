"""parent_event_id、contextvar 传递，以及 agentlens tree 的还原与展示。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentlens import JsonlTraceStore, record_event, record_log, trace, traced
from agentlens.cli import app
from agentlens.context import get_current_parent_event_id, get_current_run_id
from agentlens.events import TraceEvent
from agentlens.tree import build_event_tree, format_event_tree

FIXTURES = Path(__file__).parent / "fixtures"
MISSING_PARENT_RUN = "run_missing_parent"

EXPECTED_MISSING_PARENT_TREE = """\
[run_start] agent
  [tool_call] search
  [run_end] agent

[tool_call] orphan-a [missing parent: missing-a]
  [log] child-of-orphan
[log] orphan-b [missing parent: missing-a]

[log] other-orphan [missing parent: missing-b]
3 orphans, 2 missing parents"""

_SUMMARY_RE = re.compile(r"^(\d+) orphans, (\d+) missing parents$")
_MARKER_RE = re.compile(r"\[missing parent: ([^\]]+)\]")

runner = CliRunner()


def _load_fixture(run_id: str = MISSING_PARENT_RUN) -> list[TraceEvent]:
    store = JsonlTraceStore(base_dir=FIXTURES)
    return store.load_run(run_id)


def _assert_summary_matches_printed_tree(text: str) -> None:
    """摘要里的 N / M 必须和正文里实际印出的孤儿、缺失父 id 一致。"""
    lines = [line for line in text.splitlines() if line.strip()]
    summary = _SUMMARY_RE.match(lines[-1])
    assert summary is not None, lines[-1]
    orphan_count = int(summary.group(1))
    missing_parent_count = int(summary.group(2))

    body = "\n".join(lines[:-1])
    marker_ids = _MARKER_RE.findall(body)
    assert orphan_count == len(marker_ids)
    assert missing_parent_count == len(set(marker_ids))

    seen: list[str] = []
    for marker_id in marker_ids:
        if seen and seen[-1] == marker_id:
            continue
        assert marker_id not in seen
        seen.append(marker_id)


class TestMissingParentFixture:
    """tests/fixtures/run_missing_parent.jsonl 覆盖约定的孤儿展示。"""

    def test_fixture_prints_marker_grouping_and_orphan_subtree(self) -> None:
        text = format_event_tree(_load_fixture())
        assert text == EXPECTED_MISSING_PARENT_TREE

        lines = text.splitlines()
        orphan_index = next(
            i for i, line in enumerate(lines) if line.startswith("[tool_call] orphan-a")
        )
        child = lines[orphan_index + 1]
        assert child == "  [log] child-of-orphan"
        assert "[missing parent:" not in child
        assert child.startswith("  ")
        assert not lines[orphan_index].startswith(" ")

    def test_distinct_missing_parents_stay_in_separate_groups(self) -> None:
        text = format_event_tree(_load_fixture())
        blocks = text.rsplit("\n", 1)[0].split("\n\n")
        missing_blocks = [block for block in blocks if "[missing parent:" in block]
        assert len(missing_blocks) == 2
        assert "missing-a" in missing_blocks[0]
        assert "missing-b" not in missing_blocks[0]
        assert "orphan-a" in missing_blocks[0]
        assert "orphan-b" in missing_blocks[0]
        assert "child-of-orphan" in missing_blocks[0]
        assert missing_blocks[1].splitlines() == ["[log] other-orphan [missing parent: missing-b]"]

    def test_summary_counts_match_printed_output(self) -> None:
        _assert_summary_matches_printed_tree(format_event_tree(_load_fixture()))

    def test_cli_tree_command_prints_fixture_and_does_not_fail(self) -> None:
        result = runner.invoke(app, ["tree", MISSING_PARENT_RUN, "--base-dir", str(FIXTURES)])
        assert result.exit_code == 0, result.stdout
        assert f"Run: {MISSING_PARENT_RUN}" in result.stdout
        assert EXPECTED_MISSING_PARENT_TREE in result.stdout
        _assert_summary_matches_printed_tree(
            result.stdout.split(f"Run: {MISSING_PARENT_RUN}", 1)[1].strip()
        )

    def test_cli_tree_missing_run_exits(self) -> None:
        result = runner.invoke(app, ["tree", "does-not-exist", "--base-dir", str(FIXTURES)])
        assert result.exit_code == 1
        assert "does-not-exist" in result.stdout


class TestCompleteTree:
    """父事件都能在同一次 run 里找到时，不标记、摘要为 0。"""

    def test_traced_run_has_no_marker_and_zero_summary(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("search")
        def search() -> str:
            record_log("found")
            return "ok"

        @trace("agent", store=store, run_id="run_complete")
        def main() -> str:
            return search()

        assert main() == "ok"

        events = store.load_run("run_complete")
        raw = (tmp_path / "run_complete.jsonl").read_text(encoding="utf-8")
        assert '"parent_event_id"' in raw

        # 子事件先写入，父 span 后写入。还原不依赖这个顺序。
        names_in_file = [json.loads(line)["name"] for line in raw.splitlines()]
        assert names_in_file.index("found") < names_in_file.index("search")

        text = format_event_tree(events)
        assert "[missing parent:" not in text
        assert text.endswith("0 orphans, 0 missing parents")
        _assert_summary_matches_printed_tree(text)
        assert text == (
            "[run_start] agent\n"
            "  [tool_call] search\n"
            "    [log] found\n"
            "  [run_end] agent\n"
            "0 orphans, 0 missing parents"
        )

        tree = build_event_tree(events)
        assert tree.orphan_count == 0
        assert tree.missing_parent_count == 0
        assert [node.event.type for node in tree.roots] == ["run_start"]
        assert tree.missing_parents == []


class TestParentPropagation:
    """父事件通过 contextvar 在一次 run 内传递，不跨 run。"""

    def test_nested_spans_and_jsonl_round_trip(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("inner")
        def inner() -> None:
            record_log("leaf")

        @traced("outer")
        def outer() -> None:
            inner()

        @trace("agent", store=store, run_id="run_nested")
        def main() -> None:
            outer()
            record_log("after-outer")

        main()

        events = store.load_run("run_nested")
        by_name = {event.name: event for event in events}
        start = next(event for event in events if event.type == "run_start")
        assert start.parent_event_id is None
        assert by_name["outer"].parent_event_id == start.id
        assert by_name["inner"].parent_event_id == by_name["outer"].id
        assert by_name["leaf"].parent_event_id == by_name["inner"].id
        assert by_name["after-outer"].parent_event_id == start.id
        assert events[-1].type == "run_end"
        assert events[-1].parent_event_id == start.id

        reloaded = JsonlTraceStore(base_dir=tmp_path).load_run("run_nested")
        assert [event.parent_event_id for event in reloaded] == [
            event.parent_event_id for event in events
        ]
        tree = build_event_tree(reloaded)
        outer_node = tree.roots[0].children[0]
        assert outer_node.event.name == "outer"
        assert outer_node.children[0].event.name == "inner"
        assert outer_node.children[0].children[0].event.name == "leaf"

        assert get_current_run_id() is None
        assert get_current_parent_event_id() is None

    def test_explicit_parent_overrides_context_and_alias(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("box")
        def box() -> None:
            record_event(type="log", name="from-context")
            record_event(type="log", name="custom", parent_event_id="chosen")
            record_event(type="log", name="via-alias", parent_id="alias-parent")
            record_event(type="log", name="forced-root", parent_event_id=None)

        @trace("agent", store=store, run_id="run_override")
        def main() -> None:
            box()

        main()
        events = store.load_run("run_override")
        by_name = {event.name: event for event in events}
        assert by_name["from-context"].parent_event_id == by_name["box"].id
        assert by_name["custom"].parent_event_id == "chosen"
        assert by_name["via-alias"].parent_event_id == "alias-parent"
        assert by_name["via-alias"].parent_id == "alias-parent"
        assert by_name["forced-root"].parent_event_id is None

        text = format_event_tree(events)
        _assert_summary_matches_printed_tree(text)
        assert "[log] custom [missing parent: chosen]" in text
        assert "[log] via-alias [missing parent: alias-parent]" in text
        assert "[log] forced-root" in text
        assert "forced-root [missing parent:" not in text

    def test_new_run_does_not_inherit_parent(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @trace("outer", store=store, run_id="run_outer")
        def outer() -> None:
            @trace("inner", store=store, run_id="run_inner")
            def inner() -> None:
                record_log("inner-log")

            inner()
            record_log("outer-log")

        outer()

        outer_events = store.load_run("run_outer")
        inner_events = store.load_run("run_inner")
        outer_start = next(event for event in outer_events if event.type == "run_start")
        inner_start = next(event for event in inner_events if event.type == "run_start")
        outer_log = next(event for event in outer_events if event.name == "outer-log")
        inner_log = next(event for event in inner_events if event.name == "inner-log")

        assert inner_start.parent_event_id is None
        assert inner_log.parent_event_id == inner_start.id
        assert inner_log.parent_event_id != outer_start.id
        assert outer_log.parent_event_id == outer_start.id
        assert all(event.run_id == "run_inner" for event in inner_events)

    def test_traced_error_keeps_children_under_span(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("risky")
        def risky() -> None:
            record_log("before-fail")
            raise ValueError("nope")

        @trace("agent", store=store, run_id="run_error_span")
        def main() -> None:
            with pytest.raises(ValueError, match="nope"):
                risky()

        main()
        events = store.load_run("run_error_span")
        start = events[0]
        error = next(event for event in events if event.type == "error")
        before = next(event for event in events if event.name == "before-fail")
        assert error.name == "risky"
        assert error.parent_event_id == start.id
        assert before.parent_event_id == error.id

    @pytest.mark.asyncio
    async def test_async_parent_survives_await_and_concurrent_tasks(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("a")
        async def task_a() -> None:
            await asyncio.sleep(0.01)
            record_log("from-a")

        @traced("b")
        async def task_b() -> None:
            await asyncio.sleep(0.01)
            record_log("from-b")

        @trace("agent", store=store, run_id="run_async_tree")
        async def main() -> None:
            await asyncio.gather(task_a(), task_b())

        await main()
        events = store.load_run("run_async_tree")
        by_name = {event.name: event for event in events}
        start = next(event for event in events if event.type == "run_start")
        assert by_name["from-a"].parent_event_id == by_name["a"].id
        assert by_name["from-b"].parent_event_id == by_name["b"].id
        assert by_name["a"].parent_event_id == start.id
        assert by_name["b"].parent_event_id == start.id
        assert by_name["from-a"].parent_event_id != by_name["from-b"].parent_event_id

        text = format_event_tree(events)
        assert "[missing parent:" not in text
        assert text.endswith("0 orphans, 0 missing parents")

    def test_legacy_parent_id_field_reconstructs_tree(self, tmp_path: Path) -> None:
        """旧 JSONL 只写了 parent_id 时，读出来仍然能接上树。"""
        payload = {
            "id": "root",
            "run_id": "run_legacy",
            "parent_id": None,
            "type": "run_start",
            "name": "agent",
            "input": None,
            "output": None,
            "metadata": {},
            "started_at": "2026-01-01T00:00:00Z",
            "ended_at": None,
            "error": None,
        }
        child = {
            **payload,
            "id": "child",
            "parent_id": "root",
            "type": "log",
            "name": "legacy-child",
            "started_at": "2026-01-01T00:00:01Z",
            "ended_at": "2026-01-01T00:00:01Z",
        }
        path = tmp_path / "run_legacy.jsonl"
        path.write_text(
            json.dumps(payload) + "\n" + json.dumps(child) + "\n",
            encoding="utf-8",
        )
        events = JsonlTraceStore(base_dir=tmp_path).load_run("run_legacy")
        assert events[1].parent_event_id == "root"
        assert events[1].parent_id == "root"
        text = format_event_tree(events)
        assert text == ("[run_start] agent\n  [log] legacy-child\n0 orphans, 0 missing parents")
        assert '"parent_event_id"' not in path.read_text(encoding="utf-8")
