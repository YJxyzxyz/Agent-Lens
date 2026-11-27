"""统计摘要：只从已有事件推导，不改 JSONL。"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from agentlens.cli import app
from agentlens.events import ALL_EVENT_TYPES, TraceEvent
from agentlens.storage import JsonlTraceStore
from agentlens.summary import (
    format_run_summary,
    summaries_to_csv,
    summaries_to_json,
    summarize_run,
)

runner = CliRunner()
START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _event(event_type: str, name: str, **kwargs: object) -> TraceEvent:
    payload = {"run_id": "run-stats", "type": event_type, "name": name, **kwargs}
    return TraceEvent(**payload)  # type: ignore[arg-type]


def _store(tmp_path: Path, events: list[TraceEvent]) -> JsonlTraceStore:
    store = JsonlTraceStore(base_dir=tmp_path)
    for event in events:
        store.append_event(event)
    return store


class TestSummarizeRun:
    def test_empty_run(self) -> None:
        summary = summarize_run([], run_id="empty")
        assert summary.run_id == "empty"
        assert summary.name == "unknown"
        assert summary.event_count == 0
        assert summary.error_count == 0
        assert summary.duration_ms is None
        assert summary.prompt_tokens is None
        assert summary.completion_tokens is None
        assert summary.total_tokens is None
        assert summary.orphan_count == 0
        assert summary.missing_parent_count == 0
        assert summary.tool_names == ()

    def test_counts_duration_and_name(self) -> None:
        end = START + timedelta(milliseconds=1500)
        events = [
            _event("run_start", "demo", started_at=START, ended_at=START),
            _event("llm_call", "model-a", started_at=START),
            _event("tool_call", "search", started_at=START),
            _event("tool_call", "search", started_at=START),
            _event("file_read", "notes.md", started_at=START),
            _event("file_write", "out.md", started_at=START),
            _event("error", "demo", error="boom", started_at=START),
            _event("run_end", "demo", started_at=end, ended_at=end),
        ]
        summary = summarize_run(events)
        assert summary.name == "demo"
        assert summary.event_count == 8
        assert summary.llm_call_count == 1
        assert summary.tool_call_count == 2
        assert summary.tool_names == ("search",)
        assert summary.file_read_count == 1
        assert summary.file_write_count == 1
        assert summary.error_count == 1
        assert summary.duration_ms == 1500
        assert summary.started_at == START
        assert summary.ended_at == end
        assert set(summary.counts_by_type) == set(ALL_EVENT_TYPES)
        assert summary.counts_by_type["log"] == 0

    def test_duration_without_end_is_unknown(self) -> None:
        summary = summarize_run([_event("log", "note", started_at=START)])
        assert summary.started_at == START
        assert summary.ended_at is None
        assert summary.duration_ms is None

    def test_run_end_without_ended_at_uses_its_start(self) -> None:
        end = START + timedelta(seconds=2)
        events = [
            _event("run_start", "demo", started_at=START),
            _event("run_end", "demo", started_at=end),
        ]
        assert summarize_run(events).duration_ms == 2000

    def test_tokens_from_usage_and_metadata_tokens(self) -> None:
        events = [
            _event(
                "llm_call",
                "model-a",
                metadata={
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                    "tokens": 100,
                },
            ),
            _event(
                "llm_call",
                "model-b",
                metadata={"usage": {"input_tokens": 2, "output_tokens": 5}},
            ),
            _event("llm_call", "model-c", metadata={"tokens": 10}),
            _event(
                "llm_call", "model-d", metadata={"tokens": True, "usage": {"prompt_tokens": True}}
            ),
            _event("llm_call", "model-e", metadata={"usage": {"total_tokens": 10.0}}),
        ]
        summary = summarize_run(events)
        assert summary.prompt_tokens == 5
        assert summary.completion_tokens == 9
        # 7 from the first usage total, 2+5 from the second event, 10 from metadata.tokens,
        # and 10 from the float total. The boolean and the duplicate metadata.tokens are ignored.
        assert summary.total_tokens == 7 + 7 + 10 + 10

    def test_missing_token_side_stays_unknown(self) -> None:
        summary = summarize_run(
            [_event("llm_call", "model", metadata={"usage": {"total_tokens": 30}})]
        )
        assert summary.prompt_tokens is None
        assert summary.completion_tokens is None
        assert summary.total_tokens == 30

    def test_orphan_counts_match_event_tree(self) -> None:
        events = [
            _event("run_start", "demo", id="root"),
            _event("log", "orphan", id="child", parent_event_id="missing"),
        ]
        summary = summarize_run(events)
        assert summary.orphan_count == 1
        assert summary.missing_parent_count == 1

    def test_error_field_on_other_type_is_not_an_error_event(self) -> None:
        summary = summarize_run([_event("tool_call", "search", error="nope")])
        assert summary.error_count == 0
        assert summary.tool_call_count == 1

    def test_text_marks_unknown_tokens(self) -> None:
        text = format_run_summary(summarize_run([_event("log", "note")]))
        assert "Prompt tokens: -" in text
        assert "Total tokens: -" in text
        assert "Duration: -" in text
        assert "log: 1" in text


class TestStatsCommand:
    def test_text_json_and_csv_for_one_run(self, tmp_path: Path) -> None:
        end = START + timedelta(milliseconds=250)
        events = [
            TraceEvent(run_id="run-a", type="run_start", name="demo", started_at=START),
            TraceEvent(
                run_id="run-a",
                type="llm_call",
                name="model",
                metadata={"usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}},
            ),
            TraceEvent(run_id="run-a", type="run_end", name="demo", started_at=end, ended_at=end),
        ]
        _store(tmp_path, events)
        raw = (tmp_path / "run-a.jsonl").read_bytes()

        text = runner.invoke(app, ["stats", "run-a", "--base-dir", str(tmp_path)])
        assert text.exit_code == 0, text.stdout
        assert "Name: demo" in text.stdout
        assert "Duration: 250ms" in text.stdout
        assert "Total tokens: 3" in text.stdout
        assert (tmp_path / "run-a.jsonl").read_bytes() == raw

        as_json = runner.invoke(
            app, ["stats", "run-a", "--base-dir", str(tmp_path), "--format", "json"]
        )
        assert as_json.exit_code == 0, as_json.stdout
        payload = json.loads(as_json.stdout)
        assert payload["run_id"] == "run-a"
        assert payload["duration_ms"] == 250
        assert payload["counts_by_type"]["llm_call"] == 1

        destination = tmp_path / "out" / "stats.csv"
        as_csv = runner.invoke(
            app,
            [
                "stats",
                "run-a",
                "--base-dir",
                str(tmp_path),
                "--format",
                "csv",
                "--output",
                str(destination),
            ],
        )
        assert as_csv.exit_code == 0, as_csv.stdout
        row = next(csv.DictReader(destination.read_text(encoding="utf-8").splitlines()))
        assert row["run_id"] == "run-a"
        assert row["name"] == "demo"
        assert row["event_count"] == "3"
        assert row["duration_ms"] == "250"
        assert row["prompt_tokens"] == "1"
        assert row["completion_tokens"] == "2"
        assert row["total_tokens"] == "3"
        assert row["tool_names"] == ""
        assert row["started_at"] == START.isoformat()
        assert row["ended_at"] == end.isoformat()

    def test_all_runs_formats(self, tmp_path: Path) -> None:
        _store(
            tmp_path,
            [
                TraceEvent(run_id="b", type="run_start", name="beta"),
                TraceEvent(run_id="a", type="run_start", name="alpha"),
            ],
        )
        text = runner.invoke(app, ["stats", "--base-dir", str(tmp_path)])
        assert text.exit_code == 0, text.stdout
        assert "Runs: 2" in text.stdout
        assert "name=alpha" in text.stdout
        assert "name=beta" in text.stdout

        as_json = runner.invoke(app, ["stats", "--base-dir", str(tmp_path), "--format", "json"])
        payload = json.loads(as_json.stdout)
        assert [item["run_id"] for item in payload] == ["a", "b"]

        as_csv = runner.invoke(app, ["stats", "--base-dir", str(tmp_path), "--format", "csv"])
        assert as_csv.stdout.splitlines()[0].startswith("run_id,name,event_count")
        assert len(as_csv.stdout.splitlines()) == 3

    def test_no_runs(self, tmp_path: Path) -> None:
        text = runner.invoke(app, ["stats", "--base-dir", str(tmp_path)])
        assert text.exit_code == 0
        assert "暂无追踪记录" in text.stdout
        as_json = runner.invoke(app, ["stats", "--base-dir", str(tmp_path), "--format", "json"])
        assert json.loads(as_json.stdout) == []
        as_csv = runner.invoke(app, ["stats", "--base-dir", str(tmp_path), "--format", "csv"])
        assert as_csv.stdout.splitlines() == [
            "run_id,name,event_count,error_count,run_start_count,run_end_count,"
            "llm_call_count,tool_call_count,file_read_count,file_write_count,"
            "browser_action_count,log_count,duration_ms,prompt_tokens,completion_tokens,"
            "total_tokens,orphan_count,missing_parent_count,tool_names,started_at,ended_at"
        ]

    def test_missing_run_does_not_write_output(self, tmp_path: Path) -> None:
        destination = tmp_path / "missing.json"
        result = runner.invoke(
            app,
            ["stats", "nope", "--base-dir", str(tmp_path), "--output", str(destination)],
        )
        assert result.exit_code == 1
        assert "nope" in result.stdout
        assert not destination.exists()

    def test_bad_format_exits(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["stats", "--base-dir", str(tmp_path), "--format", "html"])
        assert result.exit_code == 2
        assert "html" in result.stdout

    def test_library_csv_and_json_round_trip(self) -> None:
        summary = summarize_run([_event("tool_call", "search"), _event("tool_call", "read")])
        payload = json.loads(summaries_to_json([summary], single=True))
        assert payload["tool_names"] == ["read", "search"]
        csv_text = summaries_to_csv([summary])
        assert "read|search" in csv_text
        assert csv_text.splitlines()[1].split(",")[4:6] == ["0", "0"]
