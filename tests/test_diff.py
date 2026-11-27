"""增强后的 diff：序列对齐，并比较 error / input / output。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from agentlens.cli import app
from agentlens.diff import diff_events, format_diff
from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore
from agentlens.viewer import compare_runs

runner = CliRunner()
START = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _event(run_id: str, event_type: str, name: str, **kwargs: object) -> TraceEvent:
    payload = {"run_id": run_id, "type": event_type, "name": name, **kwargs}
    return TraceEvent(**payload)  # type: ignore[arg-type]


def _store(tmp_path: Path, events: list[TraceEvent]) -> None:
    store = JsonlTraceStore(base_dir=tmp_path)
    for event in events:
        store.append_event(event)


class TestDiffEvents:
    def test_identical_payload_ignores_ids_time_parent_and_metadata(self) -> None:
        left = _event(
            "a",
            "tool_call",
            "search",
            id="left-id",
            parent_event_id="parent-a",
            input={"b": 1, "a": 2},
            output={"ok": True},
            metadata={"duration_ms": 10, "usage": {"total_tokens": 1}},
            started_at=START,
        )
        right = _event(
            "b",
            "tool_call",
            "search",
            id="right-id",
            parent_event_id="parent-b",
            input={"a": 2, "b": 1},
            output={"ok": True},
            metadata={"duration_ms": 99},
            started_at=START + timedelta(hours=3),
            error="",
        )
        result = diff_events([left], [right])
        assert result.first_diff is None
        assert result.rows[0].status == "same"
        assert result.counts() == {
            "same": 1,
            "changed": 0,
            "only_in_left": 0,
            "only_in_right": 0,
        }

    def test_input_change_keeps_type_and_name(self) -> None:
        left = _event("a", "tool_call", "search", input={"q": "a"})
        right = _event("b", "tool_call", "search", input={"q": "b"}, output="x")
        result = diff_events([left], [right])
        assert result.rows[0].status == "changed"
        assert result.rows[0].fields == ("input", "output")

    def test_blank_error_matches_missing_error(self) -> None:
        left = _event("a", "log", "note", error=None)
        right = _event("b", "log", "note", error="")
        assert diff_events([left], [right]).rows[0].status == "same"
        changed = diff_events([left], [_event("b", "log", "note", error="x")])
        assert changed.rows[0].fields == ("error",)

    def test_sequence_align_does_not_cascade_an_insertion(self) -> None:
        left = [
            _event("a", "run_start", "agent"),
            _event("a", "tool_call", "search", input="q"),
            _event("a", "run_end", "agent"),
        ]
        right = [
            _event("b", "run_start", "agent"),
            _event("b", "llm_call", "ask"),
            _event("b", "tool_call", "search", input="q"),
            _event("b", "run_end", "agent"),
        ]
        result = diff_events(left, right, align="sequence")
        assert [row.status for row in result.rows] == [
            "same",
            "missing_left",
            "same",
            "same",
        ]
        assert result.counts()["only_in_right"] == 1
        assert result.first_diff == 1

        positional = diff_events(left, right, align="index")
        assert [row.status for row in positional.rows] == [
            "same",
            "changed",
            "changed",
            "missing_left",
        ]

    def test_index_tail_and_type_change(self) -> None:
        left = [_event("a", "run_start", "one"), _event("a", "log", "extra")]
        right = [_event("b", "run_start", "one")]
        result = diff_events(left, right, align="index")
        assert result.rows[0].status == "same"
        assert result.rows[1].status == "missing_right"

    def test_text_lists_every_difference(self) -> None:
        left = [_event("a", "log", "one"), _event("a", "log", "two")]
        right = [_event("b", "log", "ONE"), _event("b", "log", "TWO")]
        text = format_diff(diff_events(left, right), left_run_id="a", right_run_id="b")
        assert "#1 不同" in text
        assert "#2 不同" in text
        assert "首处差异: #1" in text
        assert text.index("#1 不同") < text.index("#2 不同")


class TestDiffCommand:
    def test_cli_reports_insertion_without_rewriting_jsonl(self, tmp_path: Path) -> None:
        events = [
            TraceEvent(run_id="left", type="run_start", name="agent"),
            TraceEvent(run_id="left", type="tool_call", name="search"),
            TraceEvent(run_id="left", type="run_end", name="agent"),
            TraceEvent(run_id="right", type="run_start", name="agent"),
            TraceEvent(run_id="right", type="llm_call", name="ask"),
            TraceEvent(run_id="right", type="tool_call", name="search"),
            TraceEvent(run_id="right", type="run_end", name="agent"),
        ]
        _store(tmp_path, events)
        raw = (tmp_path / "left.jsonl").read_bytes()
        result = runner.invoke(app, ["diff", "left", "right", "--base-dir", str(tmp_path)])
        assert result.exit_code == 0, result.stdout
        assert "相同 3，不同 0，仅左侧 0，仅右侧 1" in result.stdout
        assert "[llm_call] ask" in result.stdout
        assert "首处差异: #2" in result.stdout
        assert (tmp_path / "left.jsonl").read_bytes() == raw

        positional = runner.invoke(
            app, ["diff", "left", "right", "--base-dir", str(tmp_path), "--align", "index"]
        )
        assert "不同 2" in positional.stdout

        as_json = runner.invoke(
            app,
            ["diff", "left", "right", "--base-dir", str(tmp_path), "--format", "json"],
        )
        payload = json.loads(as_json.stdout)
        assert payload["first_difference"] == 1
        assert payload["counts"]["only_in_right"] == 1
        assert payload["compared_fields"] == ["type", "name", "error", "input", "output"]
        assert payload["rows"][1]["status"] == "missing_left"
        assert payload["rows"][1]["right"]["name"] == "ask"

    def test_same_runs(self, tmp_path: Path) -> None:
        event = TraceEvent(run_id="same", type="log", name="note", input={"q": "x"})
        _store(tmp_path, [event, event.model_copy(update={"run_id": "same-b", "id": "other"})])
        result = runner.invoke(app, ["diff", "same", "same-b", "--base-dir", str(tmp_path)])
        assert result.exit_code == 0, result.stdout
        assert "一致" in result.stdout
        assert "首处差异" not in result.stdout

    def test_missing_run(self, tmp_path: Path) -> None:
        _store(tmp_path, [TraceEvent(run_id="only", type="log", name="note")])
        result = runner.invoke(app, ["diff", "only", "missing", "--base-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "missing" in result.stdout

    def test_bad_align(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["diff", "a", "b", "--base-dir", str(tmp_path), "--align", "fuzzy"]
        )
        assert result.exit_code == 2


class TestViewerCompareUsesSharedDiff:
    def test_insertion_stays_aligned_for_the_web_diff(self) -> None:
        left = [
            {"type": "run_start", "name": "agent"},
            {"type": "tool_call", "name": "search"},
        ]
        right = [
            {"type": "run_start", "name": "agent"},
            {"type": "llm_call", "name": "ask"},
            {"type": "tool_call", "name": "search"},
        ]
        result = compare_runs(left, right)
        assert [row["status"] for row in result["rows"]] == ["same", "missing_left", "same"]
        assert result["first_diff"] == 1

    def test_payload_difference_is_changed(self) -> None:
        left = [{"type": "tool_call", "name": "search", "input": {"q": "a"}}]
        right = [{"type": "tool_call", "name": "search", "input": {"q": "b"}}]
        result = compare_runs(left, right)
        assert result["rows"][0]["status"] == "changed"
        assert result["rows"][0]["fields"] == ["input"]
