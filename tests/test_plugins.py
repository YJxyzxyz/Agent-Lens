"""进程内插件：显式注册，且只在 JSONL 写入成功后做只读通知。"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agentlens
from agentlens import (
    JsonlTraceStore,
    TracePlugin,
    check_regression,
    diff_events,
    events_to_csv,
    events_to_json,
    record_log,
    register_plugin,
    replay_run,
    summarize_run,
    trace,
)
from agentlens.cli import app
from agentlens.diff import diff_events as diff_events_module
from agentlens.events import TraceEvent
from agentlens.export import events_to_csv as events_to_csv_module
from agentlens.export import events_to_json as events_to_json_module
from agentlens.regression import check_regression as check_regression_module
from agentlens.replay import recorded_calls
from agentlens.replay import replay_run as replay_run_module
from agentlens.storage import JsonlTraceStore as StorageJsonlTraceStore
from agentlens.summary import summarize_run as summarize_run_module
from agentlens.viewer import compare_runs, get_run_detail, get_run_summaries, replay_frame
from examples.event_log_plugin import EventLogPlugin

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

EXISTING_EXPORTS = (
    "trace",
    "traced",
    "record_event",
    "record_llm_call",
    "record_tool_call",
    "record_log",
    "record_file_read",
    "record_file_write",
    "TraceEvent",
    "JsonlTraceStore",
    "RunSummary",
    "summarize_run",
    "events_to_json",
    "events_to_csv",
    "diff_events",
    "replay_run",
    "RunReplay",
    "ReplayStep",
    "ReplayError",
    "REPLAY_CALL_TYPES",
    "recorded_calls",
    "RecordedCalls",
    "check_regression",
    "RegressionResult",
)

UNCHANGED_MODULES = (
    "agentlens/tracer.py",
    "agentlens/replay.py",
    "agentlens/regression.py",
    "agentlens/diff.py",
    "agentlens/viewer.py",
    "agentlens/cli.py",
)


class RecordingPlugin:
    """记下通知，并可在通知里改副本、读已经落盘的 JSONL。"""

    def __init__(self, path_for: Path | None = None) -> None:
        self.events: list[TraceEvent] = []
        self.received_json: list[str] = []
        self.file_text: list[str] = []
        self.file_bytes: list[bytes] = []
        self.path_for = path_for

    def on_event_appended(self, event: TraceEvent) -> None:
        self.received_json.append(event.model_dump_json())
        if self.path_for is not None:
            file_path = self.path_for / f"{event.run_id}.jsonl"
            raw = file_path.read_bytes()
            self.file_bytes.append(raw)
            self.file_text.append(raw.decode("utf-8"))
        event.name = "mutated-by-plugin"
        event.metadata["touched"] = True
        self.events.append(event)


class RaisingPlugin:
    """通知时抛错。调度必须吞掉它。"""

    def on_event_appended(self, event: TraceEvent) -> None:
        raise RuntimeError(f"plugin failed on {event.name}")


def test_register_plugin_is_explicit_and_idempotent(tmp_path: Path) -> None:
    """未注册不会收到通知；同一对象重复注册只通知一次。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin()
    event = TraceEvent(run_id="run-reg", type="log", name="before")

    store.append_event(event)
    assert plugin.events == []

    register_plugin(plugin)
    register_plugin(plugin)
    again = TraceEvent(run_id="run-reg", type="log", name="after")
    store.append_event(again)

    assert [item.name for item in plugin.events] == ["mutated-by-plugin"]
    assert plugin.events[0].id == again.id
    assert isinstance(plugin, TracePlugin)


def test_two_plugins_run_in_registration_order(tmp_path: Path) -> None:
    """不同对象按注册顺序各收到一次通知。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    order: list[str] = []

    class Named:
        def __init__(self, label: str) -> None:
            self.label = label

        def on_event_appended(self, event: TraceEvent) -> None:
            order.append(f"{self.label}:{event.name}")

    register_plugin(Named("first"))
    register_plugin(Named("second"))
    store.append_event(TraceEvent(run_id="run-order", type="log", name="kept"))
    assert order == ["first:kept", "second:kept"]


def test_register_plugin_rejects_objects_without_the_hook() -> None:
    """没有 on_event_appended 的对象不能注册。"""
    with pytest.raises(TypeError, match="on_event_appended"):
        register_plugin(object())


def test_hook_fires_only_after_successful_jsonl_append(tmp_path: Path) -> None:
    """写入成功后，插件看到的是文件里已经有的那一行；写入失败则不通知。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin(path_for=tmp_path)
    register_plugin(plugin)

    event = TraceEvent(
        run_id="run-ok",
        type="tool_call",
        name="search",
        input={"q": "已写入"},
        metadata={"k": "v"},
    )
    store.append_event(event)

    assert plugin.file_text == [(tmp_path / "run-ok.jsonl").read_text(encoding="utf-8")]
    line = plugin.file_text[0].strip()
    assert line == event.model_dump_json()
    assert plugin.received_json == [line]
    assert plugin.file_text[0].count("\n") == 1

    failed = TraceEvent(run_id="run-fail", type="log", name="nope")
    store._file_path("run-fail").mkdir()
    with pytest.raises(OSError):
        store.append_event(failed)
    assert [item.run_id for item in plugin.events] == ["run-ok"]
    assert not (tmp_path / "run-fail.jsonl").is_file()


def test_hook_does_not_fire_on_load_run_or_list_runs(tmp_path: Path) -> None:
    """load_run 和 list_runs 是读，不通知。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin()
    register_plugin(plugin)

    assert store.load_run("missing") == []
    assert store.list_runs() == []
    assert plugin.events == []

    store.append_event(TraceEvent(run_id="run-read", type="log", name="once"))
    assert len(plugin.events) == 1

    assert len(store.load_run("run-read")) == 1
    assert store.list_runs() == ["run-read"]
    assert len(store.load_run("run-read")) == 1
    assert len(plugin.events) == 1


def test_hook_sees_written_event_and_does_not_write_storage(tmp_path: Path) -> None:
    """插件改到的是副本：调用方的事件、JSONL 和随后的 load_run 都保持原样。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin(path_for=tmp_path)
    register_plugin(plugin)
    event = TraceEvent(
        run_id="run-ro",
        type="log",
        name="original",
        input={"n": 1},
        metadata={"k": "v"},
    )

    store.append_event(event)

    written = (tmp_path / "run-ro.jsonl").read_bytes()
    assert plugin.file_bytes == [written]
    assert written.count(b"\n") == 1
    assert event.name == "original"
    assert event.input == {"n": 1}
    assert event.metadata == {"k": "v"}
    loaded = store.load_run("run-ro")
    assert len(loaded) == 1
    assert loaded[0].name == "original"
    assert loaded[0].metadata == {"k": "v"}
    assert plugin.events[0].name == "mutated-by-plugin"
    assert plugin.events[0].metadata["touched"] is True


def test_plugin_exception_does_not_break_append_or_tracing(tmp_path: Path) -> None:
    """插件异常不影响 append_event，也不打断 @trace 的写入和返回值。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    follower = RecordingPlugin()
    register_plugin(RaisingPlugin())
    register_plugin(follower)

    direct = TraceEvent(run_id="run-direct", type="log", name="direct")
    store.append_event(direct)
    assert store.load_run("run-direct")[0].id == direct.id
    assert [item.id for item in follower.events] == [direct.id]

    @trace("plugin-agent", store=store, run_id="run-trace")
    def run() -> str:
        record_log("kept")
        return "ok"

    assert run() == "ok"
    loaded = store.load_run("run-trace")
    assert [item.type for item in loaded] == ["run_start", "log", "run_end"]
    assert [item.type for item in follower.events] == ["log", "run_start", "log", "run_end"]

    @trace("plugin-agent", store=store, run_id="run-error")
    def fail() -> None:
        raise ValueError("user boom")

    with pytest.raises(ValueError, match="user boom"):
        fail()
    failed = store.load_run("run-error")
    assert failed[0].type == "run_start"
    error_events = [item for item in failed if item.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].error is not None
    assert "ValueError" in error_events[0].error


def test_reentrant_append_from_plugin_does_not_recurse(tmp_path: Path) -> None:
    """插件若违反只读约定再写事件，通知不会递归，原来的写入仍然完成。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    calls: list[str] = []

    class Writer:
        def on_event_appended(self, event: TraceEvent) -> None:
            calls.append(event.name)
            if event.name == "outer":
                store.append_event(TraceEvent(run_id="inner", type="log", name="inner"))

    register_plugin(Writer())
    store.append_event(TraceEvent(run_id="outer", type="log", name="outer"))

    assert calls == ["outer"]
    assert [item.name for item in store.load_run("outer")] == ["outer"]
    assert [item.name for item in store.load_run("inner")] == ["inner"]


def test_registry_is_not_attached_to_a_store(tmp_path: Path) -> None:
    """注册表在进程里，不挂在某一个 JsonlTraceStore 上。"""
    left = JsonlTraceStore(base_dir=tmp_path / "left")
    right = JsonlTraceStore(base_dir=tmp_path / "right")
    seen: list[str] = []

    class Mark:
        def on_event_appended(self, event: TraceEvent) -> None:
            seen.append(event.run_id)

    register_plugin(Mark())
    left.append_event(TraceEvent(run_id="run-left", type="log", name="L"))
    right.append_event(TraceEvent(run_id="run-right", type="log", name="R"))
    assert seen == ["run-left", "run-right"]


def test_reads_replay_diff_regression_and_viewer_do_not_notify(tmp_path: Path) -> None:
    """回放、回归、diff、统计、导出、Viewer 和 CLI 读路径都不再发通知。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin()
    register_plugin(plugin)
    left = TraceEvent(run_id="left", type="log", name="same", input={"q": 1})
    right = TraceEvent(run_id="right", type="log", name="same", input={"q": 1})
    store.append_event(left)
    store.append_event(right)
    assert [item.id for item in plugin.events] == [left.id, right.id]

    left_events = store.load_run("left")
    right_events = store.load_run("right")
    assert store.list_runs() == ["left", "right"]
    replay_run(left_events)
    replay_run_module(left_events)
    recorded_calls(left_events)
    diff_events(left_events, right_events)
    diff_events_module(left_events, right_events)
    check_regression(left_events, right_events)
    check_regression_module(left_events, right_events)
    summarize_run(left_events)
    summarize_run_module(left_events)
    events_to_json(left_events)
    events_to_json_module(left_events)
    events_to_csv(left_events)
    events_to_csv_module(left_events)
    get_run_summaries(store)
    get_run_detail(store, "left")
    compare_runs([item.model_dump(mode="json") for item in left_events], [])
    replay_frame(left_events, step=1)

    base = ["--base-dir", str(tmp_path)]
    assert runner.invoke(app, ["list", *base]).exit_code == 0
    assert runner.invoke(app, ["show", "left", *base]).exit_code == 0
    assert runner.invoke(app, ["tree", "left", *base]).exit_code == 0
    assert runner.invoke(app, ["stats", "left", *base]).exit_code == 0
    assert runner.invoke(app, ["replay", "left", *base]).exit_code == 0
    assert runner.invoke(app, ["diff", "left", "right", *base]).exit_code == 0
    assert runner.invoke(app, ["regression", "left", "right", *base]).exit_code == 0

    assert [item.id for item in plugin.events] == [left.id, right.id]


def test_trace_notifies_once_per_appended_event(tmp_path: Path) -> None:
    """@trace 本身不再加钩子：通知次数等于成功写入的事件数。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    plugin = RecordingPlugin()
    register_plugin(plugin)

    @trace("counted", store=store, run_id="run-count")
    def run() -> None:
        record_log("hello")

    run()
    loaded = store.load_run("run-count")
    assert [item.type for item in plugin.events] == [item.type for item in loaded]
    assert [item.type for item in loaded] == ["run_start", "log", "run_end"]


def test_unchanged_modules_have_no_plugin_hook() -> None:
    """tracer、replay、regression、diff、Viewer、CLI 不注册也不分发插件。"""
    for relative in UNCHANGED_MODULES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "register_plugin" not in text
        assert "notify_event_appended" not in text
        assert "on_event_appended" not in text
        assert "agentlens.plugins" not in text

    append_source = inspect.getsource(StorageJsonlTraceStore.append_event)
    assert append_source.count("notify_event_appended") == 1
    for method in (StorageJsonlTraceStore.load_run, StorageJsonlTraceStore.list_runs):
        assert "notify_event_appended" not in inspect.getsource(method)
    storage_text = (ROOT / "agentlens" / "storage.py").read_text(encoding="utf-8")
    assert storage_text.count("notify_event_appended") == 2


def test_existing_public_exports_still_work() -> None:
    """新增 register_plugin / TracePlugin 时，原有公开导出仍可导入。"""
    assert agentlens.__version__ == "0.1.0"
    for name in EXISTING_EXPORTS:
        assert name in agentlens.__all__
        assert getattr(agentlens, name) is not None
    assert agentlens.register_plugin is register_plugin
    assert agentlens.TracePlugin is TracePlugin
    assert "register_plugin" in agentlens.__all__
    assert "TracePlugin" in agentlens.__all__


def test_example_plugin_uses_public_registration_api(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """示例插件通过公开的 register_plugin 接收已经写入的事件，且不改 JSONL。"""
    store = JsonlTraceStore(base_dir=tmp_path)
    register_plugin(EventLogPlugin())
    event = TraceEvent(run_id="run-example", type="log", name="from-example")
    before = event.model_dump_json()

    store.append_event(event)

    printed = capsys.readouterr().out
    assert printed == "[plugin] run-example log from-example\n"
    assert (tmp_path / "run-example.jsonl").read_text(encoding="utf-8").strip() == before
    assert event.model_dump_json() == before


def test_example_script_prints_after_writing_jsonl(tmp_path: Path) -> None:
    """示例脚本注册插件并完成一次追踪，打印发生在写入之后。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "event_log_plugin.py")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    runs = list((tmp_path / ".agentlens" / "runs").glob("*.jsonl"))
    assert len(runs) == 1
    body = runs[0].read_text(encoding="utf-8")
    assert "hello from the example plugin" in body
    printed = [line for line in result.stdout.splitlines() if line.startswith("[plugin]")]
    assert len(printed) == body.count("\n")
    assert any("hello from the example plugin" in line for line in printed)
