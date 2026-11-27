"""从已有 JSONL 回放时间线。不重新执行调用。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agentlens
from agentlens.cli import app
from agentlens.events import TraceEvent
from agentlens.replay import (
    ReplayError,
    format_replay,
    recorded_calls,
    replay_run,
    replay_to_json,
)
from agentlens.storage import JsonlTraceStore
from agentlens.tracer import trace, traced

runner = CliRunner()
START = datetime(2026, 4, 2, 3, 4, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "run_missing_parent.jsonl"


def _event(event_type: str, name: str, **kwargs: object) -> TraceEvent:
    payload = {"run_id": "run-1", "type": event_type, "name": name, **kwargs}
    return TraceEvent(**payload)  # type: ignore[arg-type]


def _sample() -> list[TraceEvent]:
    return [
        TraceEvent(
            id="root",
            run_id="run-1",
            type="run_start",
            name="agent",
            started_at=START,
            ended_at=START,
        ),
        TraceEvent(
            id="call",
            run_id="run-1",
            parent_event_id="root",
            type="tool_call",
            name="search",
            input={"b": 1, "a": "你好"},
            output={"ok": True},
            error="",
            metadata={"duration_ms": 999, "token": "secret"},
            started_at=START,
            ended_at=START + timedelta(milliseconds=40),
        ),
    ]


class TestReplayScript:
    def test_text_follows_record_order_and_omits_empty_fields(self) -> None:
        text = format_replay(replay_run(_sample()))
        assert text == (
            "Run: run-1（2 步）\n"
            "\n"
            "#1 [run_start] agent  0ms\n"
            "\n"
            "#2 [tool_call] search  parent=root  40ms\n"
            '    input: {"a": "你好", "b": 1}\n'
            '    output: {"ok": true}\n'
        )
        assert "secret" not in text
        assert "metadata" not in text

    def test_json_is_a_derived_document(self) -> None:
        payload = json.loads(replay_to_json(replay_run(_sample(), run_id="explicit")))
        assert payload["run_id"] == "explicit"
        assert payload["calls_only"] is False
        assert payload["event_count"] == 2
        assert payload["step_count"] == 2
        assert list(payload["steps"][1]) == [
            "index",
            "event_id",
            "parent_event_id",
            "type",
            "name",
            "input",
            "output",
            "error",
            "duration_ms",
        ]
        assert payload["steps"][1]["input"] == {"b": 1, "a": "你好"}
        assert payload["steps"][1]["error"] is None
        assert payload["steps"][1]["duration_ms"] == 40
        assert "metadata" not in payload["steps"][1]

    def test_calls_only_keeps_original_indexes(self) -> None:
        text = format_replay(replay_run(_sample()), calls_only=True)
        assert text.startswith("Run: run-1（1 条调用，共 2 步）")
        assert "#2 [tool_call] search" in text
        assert "run_start" not in text
        payload = json.loads(replay_to_json(replay_run(_sample()), calls_only=True))
        assert payload["step_count"] == 1
        assert payload["event_count"] == 2
        assert payload["steps"][0]["index"] == 1

    def test_string_input_and_blank_parent_stay_readable(self) -> None:
        event = {
            "id": "e",
            "run_id": "r",
            "type": "log",
            "name": "note",
            "parent_id": "",
            "input": "hello\nthere",
            "output": None,
        }
        text = format_replay(replay_run([event]))
        assert "parent=" not in text
        assert "input: hello\\nthere" in text
        assert "output:" not in text

    def test_legacy_parent_id_and_iso_duration(self) -> None:
        event = {
            "id": "e",
            "run_id": "r",
            "type": "llm_call",
            "name": "model",
            "parent_id": "p",
            "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:00:01.500Z",
        }
        step = replay_run([event]).steps[0]
        assert step.parent_event_id == "p"
        assert step.duration_ms == 1500

    def test_negative_or_uncomparable_duration_does_not_drop_the_step(self) -> None:
        negative = _event(
            "tool_call",
            "search",
            started_at=START,
            ended_at=START - timedelta(seconds=2),
        )
        assert replay_run([negative]).steps[0].duration_ms == 0
        mismatched = {
            "type": "tool_call",
            "name": "search",
            "started_at": "2026-01-01T00:00:00",
            "ended_at": "2026-01-01T00:00:01Z",
        }
        assert replay_run([mismatched]).steps[0].duration_ms is None
        assert replay_run([mismatched]).steps[0].name == "search"

    def test_missing_parent_fixture_keeps_every_recorded_line(self) -> None:
        events = [
            TraceEvent.model_validate_json(line)
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        replay = replay_run(events)
        assert [step.event_id for step in replay.steps] == [event.id for event in events]
        assert replay.steps[0].duration_ms is None
        assert replay.steps[2].parent_event_id == "missing-a"
        assert [step.name for step in recorded_calls(events).remaining()] == ["search", "orphan-a"]

    def test_empty_replay(self) -> None:
        text = format_replay(replay_run([]))
        assert text == "Run: （0 步）\n没有可回放的步骤。\n"


class TestRecordedCalls:
    def test_take_matches_input_without_regard_to_key_order(self) -> None:
        tape = recorded_calls(_sample())
        step = tape.take("tool_call", "search", {"a": "你好", "b": 1})
        assert step.output == {"ok": True}
        assert tape.exhausted
        tape.assert_finished()

    def test_mismatch_does_not_advance(self) -> None:
        events = _sample() + [_event("llm_call", "model", input="prompt", output="answer")]
        tape = recorded_calls(events)
        with pytest.raises(ReplayError, match="search"):
            tape.take("tool_call", "other")
        with pytest.raises(ReplayError, match="input"):
            tape.take("tool_call", "search", {"q": "no"})
        assert tape.peek() is not None
        assert tape.peek().name == "search"  # type: ignore[union-attr]
        tape.take("tool_call", "search")
        second = tape.take("llm_call", "model")
        assert second.output == "answer"
        with pytest.raises(ReplayError, match="已用完"):
            tape.take("tool_call", "search")

    def test_repeated_calls_are_consumed_in_record_order(self) -> None:
        events = [
            _event("tool_call", "search", input={"q": "a"}, output=1),
            _event("log", "note"),
            _event("tool_call", "search", input={"q": "a"}, output=2),
        ]
        tape = recorded_calls(events)
        assert tape.take("tool_call", "search").output == 1
        assert tape.take("tool_call", "search").output == 2
        tape.assert_finished()

    def test_unfinished_tape_names_the_remaining_calls(self) -> None:
        tape = recorded_calls(_sample())
        with pytest.raises(ReplayError, match=r"1 条已记录调用.*\[tool_call\] search"):
            tape.assert_finished()

    def test_traced_run_replays_the_redacted_recording(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        @traced("search", event_type="tool_call")
        def search(query: str, api_key: str) -> dict[str, int]:
            return {"results": len(query)}

        @trace("agent", store=store, run_id="fixed-replay")
        def main() -> dict[str, int]:
            return search("q", api_key="super-secret")

        assert main() == {"results": 1}
        events = store.load_run("fixed-replay")
        text = format_replay(replay_run(events))
        assert "super-secret" not in text
        assert "[REDACTED]" in text
        tape = recorded_calls(events)
        step = tape.take("tool_call", "search")
        assert step.input["kwargs"]["api_key"] == "[REDACTED]"
        assert step.output == {"results": 1}
        tape.assert_finished()
        assert agentlens.replay_run is replay_run
        assert agentlens.recorded_calls is recorded_calls


class TestReplayCommand:
    def test_cli_replays_without_rewriting_jsonl(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)
        for event in _sample():
            store.append_event(event)
        source = tmp_path / "run-1.jsonl"
        raw = source.read_bytes()
        result = runner.invoke(app, ["replay", "run-1", "--base-dir", str(tmp_path)])
        assert result.exit_code == 0, result.stdout
        assert "#2 [tool_call] search" in result.stdout
        assert "你好" in result.stdout
        assert source.read_bytes() == raw

        as_json = runner.invoke(
            app,
            ["replay", "run-1", "--base-dir", str(tmp_path), "--calls", "--format", "json"],
        )
        payload = json.loads(as_json.stdout)
        assert payload["calls_only"] is True
        assert [step["name"] for step in payload["steps"]] == ["search"]

    def test_missing_run_does_not_create_output(self, tmp_path: Path) -> None:
        destination = tmp_path / "out.txt"
        result = runner.invoke(
            app,
            ["replay", "missing", "--base-dir", str(tmp_path), "--output", str(destination)],
        )
        assert result.exit_code == 1
        assert not destination.exists()

    def test_bad_format(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["replay", "missing", "--base-dir", str(tmp_path), "--format", "html"]
        )
        assert result.exit_code == 2
