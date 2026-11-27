"""JSON / CSV 导出。JSON 不新增事件字段，CSV 只多一列派生耗时。"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from agentlens.cli import app
from agentlens.events import TraceEvent
from agentlens.export import events_to_csv, events_to_json, export_events
from agentlens.storage import JsonlTraceStore

runner = CliRunner()
START = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)


def _sample() -> list[TraceEvent]:
    end = START + timedelta(milliseconds=40)
    return [
        TraceEvent(
            id="root",
            run_id="run-export",
            type="run_start",
            name="导出",
            started_at=START,
            ended_at=START,
        ),
        TraceEvent(
            id="child",
            run_id="run-export",
            parent_event_id="root",
            type="tool_call",
            name='say "hi"',
            input={"b": 1, "a": "你好"},
            output={"ok": True},
            metadata={"duration_ms": 40},
            started_at=START,
            ended_at=end,
        ),
    ]


class TestExportLibrary:
    def test_json_matches_stored_event_objects(self) -> None:
        events = _sample()
        payload = json.loads(events_to_json(events))
        assert payload == [event.model_dump(mode="json") for event in events]
        assert "parent_event_id" in payload[1]
        assert "parent_id" not in payload[1]
        assert payload[1]["parent_event_id"] == "root"
        assert payload[0]["name"] == "导出"

    def test_csv_columns_duration_and_nested_json(self) -> None:
        text = events_to_csv(_sample())
        rows = list(csv.DictReader(text.splitlines()))
        assert list(rows[0]) == [
            "id",
            "run_id",
            "parent_event_id",
            "type",
            "name",
            "started_at",
            "ended_at",
            "duration_ms",
            "error",
            "input",
            "output",
            "metadata",
        ]
        assert rows[0]["duration_ms"] == "0"
        assert rows[0]["parent_event_id"] == ""
        assert rows[1]["parent_event_id"] == "root"
        assert rows[1]["duration_ms"] == "40"
        assert rows[1]["name"] == 'say "hi"'
        assert json.loads(rows[1]["input"]) == {"a": "你好", "b": 1}
        assert json.loads(rows[1]["metadata"]) == {"duration_ms": 40}
        assert rows[1]["error"] == ""

    def test_unsupported_format(self) -> None:
        try:
            export_events(_sample(), "html")
        except ValueError as exc:
            assert "html" in str(exc)
        else:
            raise AssertionError("html export should be rejected")


class TestExportCommand:
    def test_writes_json_and_csv_without_touching_jsonl(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)
        for event in _sample():
            store.append_event(event)
        source = tmp_path / "run-export.jsonl"
        raw = source.read_bytes()

        json_path = tmp_path / "nested" / "run.json"
        result = runner.invoke(
            app,
            [
                "export",
                "run-export",
                "--base-dir",
                str(tmp_path),
                "--format",
                "json",
                "--output",
                str(json_path),
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert json.loads(json_path.read_text(encoding="utf-8"))[1]["id"] == "child"
        assert source.read_bytes() == raw

        csv_result = runner.invoke(
            app,
            ["export", "run-export", "--base-dir", str(tmp_path), "--format", "csv"],
        )
        assert csv_result.exit_code == 0, csv_result.stdout
        assert "parent_event_id" in csv_result.stdout.splitlines()[0]
        assert "你好" in csv_result.stdout

    def test_missing_run_does_not_create_file(self, tmp_path: Path) -> None:
        destination = tmp_path / "out.json"
        result = runner.invoke(
            app,
            ["export", "missing", "--base-dir", str(tmp_path), "--output", str(destination)],
        )
        assert result.exit_code == 1
        assert not destination.exists()

    def test_bad_format(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["export", "missing", "--base-dir", str(tmp_path), "--format", "html"]
        )
        assert result.exit_code == 2
