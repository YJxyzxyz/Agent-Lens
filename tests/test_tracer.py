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


# ---------------------------------------------------------------------------
# traced 装饰器测试
# ---------------------------------------------------------------------------


class TestTracedDecorator:
    """traced 装饰器测试。"""

    def test_traced_records_tool_call(self) -> None:
        """traced 成功时记录 tool_call 事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("search_web", event_type="tool_call")
            def search_web(query: str) -> dict:
                return {"results": 3}

            @trace("traced-agent", store=store)
            def main() -> None:
                search_web("test query")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            assert tool_events[0].name == "search_web"
            assert tool_events[0].input["args"] == ["test query"]
            assert tool_events[0].output == {"results": 3}

    def test_traced_records_llm_call(self) -> None:
        """traced 可以记录 llm_call 类型事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("summarize", event_type="llm_call")
            def summarize(text: str) -> str:
                return f"Summary of: {text}"

            @trace("llm-traced-agent", store=store)
            def main() -> None:
                summarize("hello world")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            llm_events = [e for e in events if e.type == "llm_call"]
            assert len(llm_events) == 1
            assert llm_events[0].name == "summarize"

    def test_traced_no_trace_context_runs_normally(self) -> None:
        """没有 trace 上下文时 traced 直接执行原函数。"""
        from agentlens import traced

        call_count = 0

        @traced("side-effect-fn")
        def side_effect(x: int) -> int:
            nonlocal call_count
            call_count += 1
            return x * 2

        result = side_effect(5)
        assert result == 10
        assert call_count == 1

    def test_traced_exception_records_error_and_rethrows(self) -> None:
        """traced 包装函数抛错时记录 error 并重新抛出。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("risky-fn")
            def risky() -> None:
                raise ValueError("something is wrong")

            @trace("error-traced-agent", store=store)
            def main() -> None:
                with pytest.raises(ValueError, match="something is wrong"):
                    risky()

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            error_events = [e for e in events if e.type == "error"]
            assert len(error_events) == 1
            assert "ValueError" in error_events[0].error
            assert error_events[0].name == "risky-fn"

    def test_traced_sanitizes_sensitive_keys(self) -> None:
        """traced 自动脱敏敏感字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("login")
            def login(api_key: str, password: str) -> dict:
                return {"status": "ok"}

            @trace("sanitize-agent", store=store)
            def main() -> None:
                login(api_key="sk-secret", password="mypwd")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            # kwargs 中的敏感字段应被脱敏
            kwargs = tool_events[0].input.get("kwargs", {})
            assert kwargs.get("api_key") == "[REDACTED]"
            assert kwargs.get("password") == "[REDACTED]"

    def test_traced_truncates_long_strings(self) -> None:
        """traced 截断超长字符串。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("long-output-fn")
            def long_output() -> str:
                return "x" * 5000

            @trace("truncate-agent", store=store)
            def main() -> None:
                long_output()

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            output_str = str(tool_events[0].output)
            assert len(output_str) < 5000
            assert "...[truncated]" in output_str

    def test_traced_preserves_function_name(self) -> None:
        """traced 使用 functools.wraps 保留原函数名。"""
        from agentlens import traced

        @traced("my-tool")
        def my_function() -> str:
            """Docstring for my_function."""
            return "ok"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "Docstring for my_function."

    def test_traced_metadata_has_duration_ms(self) -> None:
        """traced 记录的 metadata 中包含 duration_ms。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced("timed-fn")
            def timed() -> str:
                return "done"

            @trace("duration-agent", store=store)
            def main() -> None:
                timed()

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            assert "duration_ms" in tool_events[0].metadata
            assert isinstance(tool_events[0].metadata["duration_ms"], int)

    def test_traced_uses_function_name_when_name_none(self) -> None:
        """name 为 None 时使用原函数名。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import traced

            @traced  # no explicit name
            def implicit_name_fn() -> str:
                return "ok"

            @trace("implicit-name-agent", store=store)
            def main() -> None:
                implicit_name_fn()

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            tool_events = [e for e in events if e.type == "tool_call"]
            assert len(tool_events) == 1
            assert tool_events[0].name == "implicit_name_fn"


# ---------------------------------------------------------------------------
# record_file_read / record_file_write 测试
# ---------------------------------------------------------------------------


class TestFileEventFunctions:
    """file_read / file_write 便捷函数测试。"""

    def test_record_file_read(self) -> None:
        """record_file_read 记录 file_read 事件并包含 path。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import record_file_read

            @trace("file-agent", store=store)
            def main() -> None:
                record_file_read("/data/config.json")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            file_events = [e for e in events if e.type == "file_read"]
            assert len(file_events) == 1
            assert file_events[0].name == "/data/config.json"
            assert file_events[0].metadata["path"] == "/data/config.json"

    def test_record_file_write_with_preview(self) -> None:
        """record_file_write 记录 file_write 事件，content_preview 最多 1000 字符。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import record_file_write

            @trace("write-agent", store=store)
            def main() -> None:
                record_file_write("output.md", content_preview="# Title\n\nContent here.")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            file_events = [e for e in events if e.type == "file_write"]
            assert len(file_events) == 1
            assert file_events[0].name == "output.md"
            assert file_events[0].metadata["path"] == "output.md"
            assert "content_preview" in file_events[0].output
            assert "# Title" in file_events[0].output["content_preview"]

    def test_record_file_write_without_preview(self) -> None:
        """record_file_write 可以不传 content_preview。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            from agentlens import record_file_write

            @trace("write-no-preview-agent", store=store)
            def main() -> None:
                record_file_write("large_file.bin")

            main()

            runs = store.list_runs()
            events = store.load_run(runs[0])

            file_events = [e for e in events if e.type == "file_write"]
            assert len(file_events) == 1
            assert file_events[0].name == "large_file.bin"
