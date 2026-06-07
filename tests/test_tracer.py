"""追踪 API 测试 — trace 装饰器与 record_* 函数。"""

import tempfile
from pathlib import Path

import pytest

from agentlens import (
    JsonlTraceStore,
    record_llm_call,
    record_log,
    record_tool_call,
    trace,
)


class TestTraceDecorator:
    """trace 装饰器测试。"""

    def test_generates_run_start_and_run_end(self) -> None:
        """trace 装饰器会在函数执行前后写入 run_start 和 run_end 事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("test-agent", store=store)
            def my_func() -> str:
                return "done"

            my_func()

            runs = store.list_runs()
            assert len(runs) == 1
            run_id = runs[0]

            events = store.load_run(run_id)
            types = [e.type for e in events]
            assert "run_start" in types
            assert "run_end" in types
            assert types[0] == "run_start"
            assert types[-1] == "run_end"

    def test_records_error_on_exception(self) -> None:
        """函数抛出异常时会记录 error 事件，然后继续抛出。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("error-agent", store=store)
            def failing_func() -> None:
                raise ValueError("boom!")

            with pytest.raises(ValueError, match="boom!"):
                failing_func()

            runs = store.list_runs()
            assert len(runs) == 1
            events = store.load_run(runs[0])

            types = [e.type for e in events]
            assert types[0] == "run_start"
            assert "error" in types

            error_events = [e for e in events if e.type == "error"]
            assert len(error_events) == 1
            assert "ValueError" in error_events[0].error

    def test_trace_with_existing_run_id(self) -> None:
        """可以指定自定义 run_id。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("custom-agent", store=store, run_id="my-custom-run")
            def my_func() -> str:
                return "ok"

            my_func()

            runs = store.list_runs()
            assert "my-custom-run" in runs


class TestRecordFunctions:
    """record_* 便捷函数测试。"""

    def test_record_llm_call_inside_trace(self) -> None:
        """在 trace 上下文中调用 record_llm_call 可以写入 llm_call 事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("llm-agent", store=store)
            def my_func() -> None:
                record_llm_call(
                    model="gpt-4.1",
                    input="Hello",
                    output="Hi there!",
                    metadata={"tokens": 10},
                )

            my_func()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            llm_events = [e for e in events if e.type == "llm_call"]
            assert len(llm_events) == 1
            assert llm_events[0].name == "gpt-4.1"
            assert llm_events[0].input == "Hello"
            assert llm_events[0].output == "Hi there!"
            assert llm_events[0].metadata == {"tokens": 10}

    def test_record_tool_call_inside_trace(self) -> None:
        """在 trace 上下文中调用 record_tool_call。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("tool-agent", store=store)
            def my_func() -> None:
                record_tool_call(
                    name="search_web",
                    input={"query": "test"},
                    output={"results": 3},
                )

            my_func()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            assert tool_events[0].name == "search_web"

    def test_record_log_inside_trace(self) -> None:
        """在 trace 上下文中调用 record_log。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            @trace("log-agent", store=store)
            def my_func() -> None:
                record_log("Processing step 1")
                record_log("Processing step 2")

            my_func()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            log_events = [e for e in events if e.type == "log"]
            assert len(log_events) == 2

    def test_record_outside_trace_raises(self) -> None:
        """在没有 trace 上下文时调用 record_event 应抛出 RuntimeError。"""
        # 重置上下文（确保没有残留）
        import agentlens.context as ctx

        token_run = ctx._current_run_id.set(None)
        token_store = ctx._current_store.set(None)
        try:
            with pytest.raises(RuntimeError, match="当前没有活跃的 trace 上下文"):
                record_llm_call(model="test", input="hi", output="bye")
        finally:
            ctx._current_run_id.reset(token_run)
            ctx._current_store.reset(token_store)
