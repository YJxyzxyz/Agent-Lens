"""回归检查沿用扁平序列 diff。不重新执行调用，也不比较事件树。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agentlens
from agentlens.cli import app
from agentlens.events import TraceEvent
from agentlens.regression import check_regression, format_regression
from agentlens.storage import JsonlTraceStore
from agentlens.tracer import trace, traced

runner = CliRunner()
START = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _event(run_id: str, event_type: str, name: str, **kwargs: object) -> TraceEvent:
    payload = {"run_id": run_id, "type": event_type, "name": name, **kwargs}
    return TraceEvent(**payload)  # type: ignore[arg-type]


def _pair() -> tuple[list[TraceEvent], list[TraceEvent]]:
    baseline = [
        _event("base", "run_start", "agent", id="b0"),
        _event("base", "tool_call", "search", id="b1", input={"q": "a"}, output={"n": 1}),
        _event("base", "run_end", "agent", id="b2"),
    ]
    candidate = [
        _event("cand", "run_start", "agent", id="c0", parent_event_id="other"),
        _event(
            "cand",
            "tool_call",
            "search",
            id="c1",
            parent_event_id="elsewhere",
            input={"q": "a"},
            output={"n": 1},
            metadata={"duration_ms": 50},
            started_at=START + timedelta(hours=1),
        ),
        _event("cand", "run_end", "agent", id="c2"),
    ]
    return baseline, candidate


class TestCheckRegression:
    def test_ignores_ids_time_parent_and_metadata(self) -> None:
        baseline, candidate = _pair()
        result = check_regression(baseline, candidate)
        assert result.passed
        assert result.diff.align == "sequence"
        text = format_regression(result)
        assert "结果: 通过" in text
        assert "首处差异" not in text
        assert "type、name、error、input、output 一致" in text

    def test_blank_error_matches_missing_error(self) -> None:
        baseline = [_event("base", "log", "note", error=None)]
        candidate = [_event("cand", "log", "note", error="")]
        assert check_regression(baseline, candidate).passed
        changed = [_event("cand", "log", "note", error="x")]
        failed = check_regression(
            baseline,
            changed,
            baseline_run_id="base",
            candidate_run_id="cand",
        )
        assert not failed.passed
        assert failed.diff.rows[0].fields == ("error",)
        text = format_regression(failed)
        assert "结果: 未通过" in text
        assert "#1 不同 (error)" in text

    def test_insertion_uses_flat_sequence_alignment(self) -> None:
        baseline, candidate = _pair()
        candidate.insert(1, _event("cand", "llm_call", "ask", input="q"))
        result = check_regression(
            baseline,
            candidate,
            baseline_run_id="base",
            candidate_run_id="cand",
        )
        assert [row.status for row in result.diff.rows] == [
            "same",
            "missing_left",
            "same",
            "same",
        ]
        assert result.passed is False
        text = format_regression(result)
        assert "仅候选 1" in text
        assert "#2 仅候选" in text
        assert "[llm_call] ask" in text

        positional = check_regression(baseline, candidate, align="index")
        assert [row.status for row in positional.diff.rows] == [
            "same",
            "changed",
            "changed",
            "missing_left",
        ]

    def test_calls_only_ignores_extra_log_and_error_events(self) -> None:
        baseline, candidate = _pair()
        candidate.append(_event("cand", "log", "extra"))
        candidate.append(_event("cand", "error", "boom", error="ValueError: x"))
        assert check_regression(baseline, candidate).passed is False
        filtered = check_regression(baseline, candidate, calls_only=True)
        assert filtered.passed
        assert filtered.diff.left_count == 1
        assert filtered.diff.right_count == 1
        assert "范围: 仅调用" in format_regression(filtered)

    def test_empty_runs_pass(self) -> None:
        result = check_regression([], [])
        assert result.passed
        assert result.baseline_run_id == ""
        assert result.candidate_run_id == ""

    def test_unsupported_align(self) -> None:
        with pytest.raises(ValueError, match="fuzzy"):
            check_regression([], [], align="fuzzy")  # type: ignore[arg-type]

    def test_two_traced_runs_with_the_same_return_pass(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)

        def record(run_id: str, query: str) -> None:
            @traced("search", event_type="tool_call")
            def search(value: str) -> dict[str, int]:
                return {"results": len(value)}

            @trace("agent", store=store, run_id=run_id)
            def main() -> dict[str, int]:
                return search(query)

            main()

        record("base", "ab")
        record("cand", "ab")
        baseline = store.load_run("base")
        candidate = store.load_run("cand")
        assert [event.id for event in baseline] != [event.id for event in candidate]
        result = check_regression(baseline, candidate)
        assert result.passed
        assert agentlens.check_regression is check_regression

        record("drift", "abc")
        drifted = check_regression(baseline, store.load_run("drift"))
        assert drifted.passed is False


class TestRegressionCommand:
    def test_failure_exits_1_and_keeps_jsonl(self, tmp_path: Path) -> None:
        baseline, candidate = _pair()
        candidate[1] = _event("cand", "tool_call", "search", input={"q": "b"})
        store = JsonlTraceStore(base_dir=tmp_path)
        for event in baseline + candidate:
            store.append_event(event)
        raw = (tmp_path / "base.jsonl").read_bytes()
        destination = tmp_path / "nested" / "report.txt"
        result = runner.invoke(
            app,
            [
                "regression",
                "base",
                "cand",
                "--base-dir",
                str(tmp_path),
                "--output",
                str(destination),
            ],
        )
        assert result.exit_code == 1, result.stdout
        report = destination.read_text(encoding="utf-8")
        assert "结果: 未通过" in report
        assert "input:" in report
        assert (tmp_path / "base.jsonl").read_bytes() == raw

    def test_pass_json_and_index_align(self, tmp_path: Path) -> None:
        baseline, candidate = _pair()
        store = JsonlTraceStore(base_dir=tmp_path)
        for event in baseline + candidate:
            store.append_event(event)
        result = runner.invoke(
            app,
            ["regression", "base", "cand", "--base-dir", str(tmp_path), "--format", "json"],
        )
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["passed"] is True
        assert payload["calls_only"] is False
        assert payload["diff"]["align"] == "sequence"
        assert payload["diff"]["first_difference"] is None
        assert payload["diff"]["compared_fields"] == [
            "type",
            "name",
            "error",
            "input",
            "output",
        ]

        candidate.append(_event("cand", "log", "tail"))
        store.append_event(candidate[-1])
        failed = runner.invoke(
            app,
            [
                "regression",
                "base",
                "cand",
                "--base-dir",
                str(tmp_path),
                "--align",
                "index",
                "--calls",
            ],
        )
        assert failed.exit_code == 0, failed.stdout
        assert "范围: 仅调用" in failed.stdout

    def test_missing_run_and_bad_align(self, tmp_path: Path) -> None:
        store = JsonlTraceStore(base_dir=tmp_path)
        store.append_event(_event("only", "log", "note"))
        missing = runner.invoke(app, ["regression", "only", "missing", "--base-dir", str(tmp_path)])
        assert missing.exit_code == 1
        assert "missing" in missing.stdout
        bad = runner.invoke(
            app,
            ["regression", "only", "only", "--base-dir", str(tmp_path), "--align", "tree"],
        )
        assert bad.exit_code == 2
