"""OpenAI-compatible integration 测试。

使用 monkeypatch mock 测试，不发起真实 API 调用。
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _reset_instrument_state():
    """重置 openai_compatible 模块的 patch 状态（含恢复类方法）。"""
    import agentlens.integrations.openai_compatible as mod

    completions_cls = None
    async_cls = None
    try:
        from openai.resources.chat.completions import AsyncCompletions, Completions

        completions_cls = Completions
        async_cls = AsyncCompletions
    except ImportError:
        pass

    if completions_cls is not None and mod._original_create is not None:  # noqa: SLF001
        completions_cls.create = mod._original_create  # type: ignore[method-assign]  # noqa: SLF001
    if async_cls is not None and mod._original_acreate is not None:  # noqa: SLF001
        async_cls.create = mod._original_acreate  # type: ignore[method-assign]  # noqa: SLF001

    mod._patched = False  # noqa: SLF001
    mod._original_create = None  # noqa: SLF001
    mod._original_acreate = None  # noqa: SLF001


def _chunk(
    content: str | None = None,
    *,
    model: str = "deepseek-chat",
    usage: dict | None = None,
    tool_calls: list | None = None,
    finish: str | None = None,
    chunk_id: str = "chatcmpl-stream",
) -> mock.Mock:
    """构造带 model_dump 的假流式 chunk。"""
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool_calls is not None:
        delta["tool_calls"] = tool_calls
    payload: dict = {
        "id": chunk_id,
        "model": model,
        "created": 1717000000,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage is not None:
        payload["usage"] = usage
    chunk = mock.Mock()
    chunk.model_dump.return_value = payload
    return chunk


class _FakeSyncStream:
    """最小同步流，供 stream=True 测试使用。"""

    def __init__(self, chunks: list, fail_at: int | None = None) -> None:
        self._chunks = list(chunks)
        self._index = 0
        self._fail_at = fail_at
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._fail_at is not None and self._index == self._fail_at:
            raise RuntimeError("stream broke")
        if self._index >= len(self._chunks):
            raise StopIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        self.close()
        return False


class _FakeAsyncStream:
    """最小异步流，供 AsyncOpenAI stream=True 测试使用。"""

    def __init__(self, chunks: list, fail_at: int | None = None) -> None:
        self._chunks = list(chunks)
        self._index = 0
        self._fail_at = fail_at
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._fail_at is not None and self._index == self._fail_at:
            raise RuntimeError("stream broke")
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._index]
        self._index += 1
        await asyncio.sleep(0)
        return chunk

    async def close(self) -> None:
        self.closed = True

    async def aclose(self) -> None:
        await self.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        await self.close()
        return False


def _fake_create_response(*args, **kwargs) -> mock.MagicMock:  # noqa: ANN002, ANN003
    """构造 fake OpenAI chat completion 响应。"""
    resp = mock.MagicMock()
    resp.model_dump.return_value = {
        "id": "chatcmpl-fake-001",
        "model": kwargs.get("model", "unknown"),
        "created": 1717000000,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Hello! How can I help?"},
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    return resp


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestInstrumentOpenAICompatible:
    """instrument / uninstrument 功能测试。"""

    def test_import_error_when_openai_not_installed(self):
        """未安装 openai 时给出清晰错误信息。"""
        _reset_instrument_state()

        import builtins

        _orig_import = builtins.__import__

        def _block_openai(name, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            if name == "openai" or name.startswith("openai."):
                raise ImportError(f"No module named '{name}'")
            return _orig_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", _block_openai):
            from agentlens.integrations.openai_compatible import instrument_openai_compatible

            _reset_instrument_state()
            with pytest.raises(ImportError, match="未安装 openai"):
                instrument_openai_compatible(provider="test")

    def test_double_instrument_no_double_patch(self):
        """重复 instrument 不会重复 patch。"""
        import agentlens.integrations.openai_compatible as mod
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        instrument_openai_compatible(provider="test")
        assert mod._patched is True  # noqa: SLF001

        instrument_openai_compatible(provider="test")
        assert mod._patched is True  # noqa: SLF001

        uninstrument_openai_compatible()

    def test_uninstrument_restores_original(self):
        """uninstrument 可以恢复原始方法。"""
        from openai.resources.chat.completions import Completions

        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        original = Completions.create
        instrument_openai_compatible(provider="test")
        assert Completions.create is not original  # 已被 patch

        uninstrument_openai_compatible()
        assert Completions.create is original  # 已恢复


class TestPatchedCreateWithTrace:
    """在 trace 上下文中 patched create 的记录行为测试。"""

    def test_successful_call_records_llm_call(self, tmp_path):
        """成功调用时记录 llm_call 事件。"""
        from openai.resources.chat.completions import Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        with mock.patch.object(Completions, "create", side_effect=_fake_create_response):
            instrument_openai_compatible(provider="deepseek")
            store = JsonlTraceStore(base_dir=tmp_path)

            with set_current_trace("run_test_001", store):
                comp = Completions(client=mock.MagicMock())
                comp.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "Hello"}],
                )

            uninstrument_openai_compatible()

        events = store.load_run("run_test_001")
        llm_events = [e for e in events if e.type == "llm_call"]
        assert len(llm_events) >= 1
        assert llm_events[0].name == "deepseek-chat"
        assert llm_events[0].metadata["provider"] == "deepseek"
        assert llm_events[0].metadata["api"] == "chat.completions.create"

    def test_error_records_error_and_rethrows(self, tmp_path):
        """调用抛错时记录 error 事件并重新抛出。"""
        from openai.resources.chat.completions import Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        def _failing_create(self_comp, **kwargs):  # noqa: ANN001, ANN202
            raise RuntimeError("API connection timeout")

        with mock.patch.object(Completions, "create", side_effect=_failing_create):
            instrument_openai_compatible(provider="deepseek")
            store = JsonlTraceStore(base_dir=tmp_path)

            with set_current_trace("run_test_002", store):
                comp = Completions(client=mock.MagicMock())
                with pytest.raises(RuntimeError, match="API connection timeout"):
                    comp.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": "Hi"}],
                    )

            uninstrument_openai_compatible()

        events = store.load_run("run_test_002")
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) >= 1
        assert "RuntimeError" in error_events[0].error
        assert error_events[0].name == "deepseek.chat.completions.create"

    def test_no_trace_context_no_crash(self):
        """没有 trace 上下文时调用不记录事件，也不崩溃。"""
        from openai.resources.chat.completions import Completions

        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        with mock.patch.object(Completions, "create", side_effect=_fake_create_response):
            instrument_openai_compatible(provider="deepseek")

            comp = Completions(client=mock.MagicMock())
            response = comp.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Hello"}],
            )
            assert response is not None

            uninstrument_openai_compatible()


class TestInputSanitization:
    """输入脱敏测试。"""

    def test_sanitize_removes_sensitive_keys(self):
        """敏感 key（api_key, authorization 等）会被替换为 [REDACTED]。"""
        from agentlens.serialization import sanitize_mapping

        data = {
            "model": "deepseek-chat",
            "api_key": "sk-secret-12345",
            "messages": [{"role": "user", "content": "Hi"}],
            "authorization": "Bearer token-xxx",
            "temperature": 0.7,
            "token": "should-be-redacted",
            "secret": "also-redacted",
            "password": "mypass",
            "cookie": "session=abc",
        }
        result = sanitize_mapping(data)

        assert result["model"] == "deepseek-chat"
        assert result["api_key"] == "[REDACTED]"
        assert result["authorization"] == "[REDACTED]"
        assert result["token"] == "[REDACTED]"
        assert result["secret"] == "[REDACTED]"
        assert result["password"] == "[REDACTED]"
        assert result["cookie"] == "[REDACTED]"
        assert result["temperature"] == 0.7
        assert result["messages"] == [{"role": "user", "content": "Hi"}]

    def test_truncate_long_string(self):
        """超长字符串被截断。"""
        from agentlens.serialization import truncate_string

        long_str = "x" * 5000
        result = truncate_string(long_str, max_length=100)
        assert len(result) < len(long_str)
        assert result.endswith("...[truncated]")

    def test_truncate_short_string_unchanged(self):
        """短字符串不变。"""
        from agentlens.serialization import truncate_string

        short = "hello"
        assert truncate_string(short, max_length=100) == "hello"


class TestOutputSummary:
    """输出摘要测试。"""

    def test_output_summary_not_full_response(self):
        """输出摘要不保存完整响应对象，只提取关键字段。"""
        from agentlens.integrations.openai_compatible import _build_safe_output

        resp = _fake_create_response(model="deepseek-chat")
        summary = _build_safe_output(resp)
        assert isinstance(summary, dict)
        assert "id" in summary
        assert "model" in summary
        assert "choices" in summary
        assert "usage" in summary
        assert summary["choices"][0]["message"]["content"] == "Hello! How can I help?"
        assert "raw" not in summary

    def test_tool_call_arguments_are_redacted(self):
        """助手 tool call 只保留 id 和 name，arguments 不落盘。"""
        from agentlens.integrations.openai_compatible import _build_safe_output

        resp = mock.MagicMock()
        resp.model_dump.return_value = {
            "id": "chatcmpl-tool",
            "model": "deepseek-chat",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"q": "secret-query"}',
                                },
                            }
                        ],
                    },
                }
            ],
        }
        summary = _build_safe_output(resp)
        encoded = json.dumps(summary)
        assert "secret-query" not in encoded
        tool_call = summary["choices"][0]["message"]["tool_calls"][0]
        assert tool_call["id"] == "call_abc"
        assert tool_call["name"] == "search"
        assert tool_call["arguments"] == "[REDACTED]"


def _client_with_secret_url() -> mock.MagicMock:
    """base_url 带用户信息和 query key，trace 里只能留下 host 与 path。"""
    client = mock.MagicMock()
    client.base_url = "https://user:secret-pass@proxy.example:8443/v1?api_key=sk-live"
    return client


class TestAsyncOpenAICompatible:
    """AsyncOpenAI chat.completions.create 自动追踪。"""

    @pytest.mark.asyncio
    async def test_successful_async_call_records_llm_call(self, tmp_path):
        """await create 记录 llm_call，并带上 response_model 与脱敏 endpoint。"""
        from openai.resources.chat.completions import AsyncCompletions, Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        sync_called = False

        def _sync_create(self_comp, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            nonlocal sync_called
            sync_called = True
            return _fake_create_response(*args, **kwargs)

        async def _async_create(self_comp, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            await asyncio.sleep(0)
            resp = _fake_create_response(*args, **kwargs)
            payload = resp.model_dump.return_value
            payload["model"] = "deepseek-chat"
            resp.model_dump.return_value = payload
            return resp

        with (
            mock.patch.object(Completions, "create", side_effect=_sync_create),
            mock.patch.object(AsyncCompletions, "create", side_effect=_async_create),
        ):
            instrument_openai_compatible(provider="deepseek")
            try:
                assert inspect.iscoroutinefunction(AsyncCompletions.create)
                store = JsonlTraceStore(base_dir=tmp_path)
                client = _client_with_secret_url()
                with set_current_trace("run_async_001", store):
                    comp = AsyncCompletions(client=client)
                    await comp.create(
                        model="gateway-alias",
                        messages=[{"role": "user", "content": "Hello"}],
                    )
            finally:
                uninstrument_openai_compatible()

        assert sync_called is False
        events = store.load_run("run_async_001")
        llm_events = [event for event in events if event.type == "llm_call"]
        assert len(llm_events) == 1
        event = llm_events[0]
        assert event.name == "gateway-alias"
        assert event.metadata["provider"] == "deepseek"
        assert event.metadata["api"] == "chat.completions.create"
        assert event.metadata["model"] == "gateway-alias"
        assert event.metadata["response_model"] == "deepseek-chat"
        assert event.metadata["stream"] is False
        assert event.metadata["endpoint"] == {"host": "proxy.example:8443", "path": "/v1"}
        encoded = json.dumps(event.metadata)
        assert "secret-pass" not in encoded
        assert "sk-live" not in encoded
        assert event.started_at <= event.ended_at

    @pytest.mark.asyncio
    async def test_async_error_records_and_reraises(self, tmp_path):
        """异步调用失败时记录 error，并把原异常抛回去。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        async def _failing_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(0)
            raise RuntimeError("API connection timeout")

        with mock.patch.object(AsyncCompletions, "create", side_effect=_failing_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_async_err", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    with pytest.raises(RuntimeError, match="API connection timeout"):
                        await comp.create(model="deepseek-chat", messages=[])
            finally:
                uninstrument_openai_compatible()

        events = store.load_run("run_async_err")
        error_events = [event for event in events if event.type == "error"]
        assert len(error_events) == 1
        assert "RuntimeError" in error_events[0].error
        assert error_events[0].name == "deepseek.chat.completions.create"

    @pytest.mark.asyncio
    async def test_async_without_trace_context_does_not_crash(self):
        """没有 trace 上下文时，异步调用直接返回，不写事件。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            return _fake_create_response(**kwargs)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                comp = AsyncCompletions(client=mock.MagicMock())
                response = await comp.create(model="deepseek-chat", messages=[])
                assert response is not None
            finally:
                uninstrument_openai_compatible()

    @pytest.mark.asyncio
    async def test_async_create_does_not_block_event_loop(self, tmp_path):
        """异步 patch 在等待传输层时会把控制权交还事件循环。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        async def _slow_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(0.05)
            return _fake_create_response(**kwargs)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_slow_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                progressed_at: float | None = None

                async def _marker() -> float:
                    await asyncio.sleep(0)
                    return asyncio.get_running_loop().time()

                with set_current_trace("run_async_loop", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    marker = asyncio.create_task(_marker())
                    started = asyncio.get_running_loop().time()
                    await comp.create(model="deepseek-chat", messages=[])
                    finished = asyncio.get_running_loop().time()
                    progressed_at = await marker
            finally:
                uninstrument_openai_compatible()

        assert progressed_at is not None
        assert progressed_at < finished
        assert finished - started >= 0.04

    @pytest.mark.asyncio
    async def test_async_trace_decorator_sees_awaited_call(self, tmp_path):
        """@trace 包住 async 函数时，函数体内的 await create 仍在同一次 run 里。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore, trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(0)
            return _fake_create_response(**kwargs)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="openai")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)

                @trace("async-agent", store=store)
                async def run() -> str:
                    comp = AsyncCompletions(client=mock.MagicMock())
                    await comp.create(
                        model="gpt-4.1",
                        messages=[{"role": "user", "content": "Hi"}],
                    )
                    return "done"

                await run()
            finally:
                uninstrument_openai_compatible()

        events = store.load_run(store.list_runs()[0])
        assert [event.type for event in events] == ["run_start", "llm_call", "run_end"]
        assert events[1].name == "gpt-4.1"

    def test_uninstrument_restores_async_create(self):
        """uninstrument 同时恢复同步和异步原方法。"""
        from openai.resources.chat.completions import AsyncCompletions, Completions

        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        original_sync = Completions.create
        original_async = AsyncCompletions.create
        instrument_openai_compatible(provider="openai")
        try:
            assert Completions.create is not original_sync
            assert AsyncCompletions.create is not original_async
            assert inspect.iscoroutinefunction(AsyncCompletions.create)
        finally:
            uninstrument_openai_compatible()
        assert Completions.create is original_sync
        assert AsyncCompletions.create is original_async

    def test_sync_stream_records_one_logical_call(self, tmp_path):
        """同步 stream=True 在迭代结束后只写一条 llm_call。"""
        from openai.resources.chat.completions import Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [
            _chunk("Hel", model="deepseek-chat"),
            _chunk(
                "lo",
                model="deepseek-chat",
                finish="stop",
                usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            ),
        ]

        def _sync_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            assert kwargs["stream"] is True
            return _FakeSyncStream(chunks)

        with mock.patch.object(Completions, "create", side_effect=_sync_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_sync_stream", store):
                    comp = Completions(client=_client_with_secret_url())
                    stream = comp.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": "Hi"}],
                        stream=True,
                    )
                    assert store.load_run("run_sync_stream") == []
                    text = ""
                    for chunk in stream:
                        text += chunk.model_dump()["choices"][0]["delta"]["content"]
            finally:
                uninstrument_openai_compatible()

        assert text == "Hello"
        events = store.load_run("run_sync_stream")
        assert len(events) == 1
        event = events[0]
        assert event.type == "llm_call"
        assert event.output["choices"][0]["message"]["content"] == "Hello"
        assert event.metadata["stream"] is True
        assert event.metadata["stream_completed"] is True
        assert event.metadata["usage"]["total_tokens"] == 5
        assert isinstance(event.metadata["ttft_ms"], int)
        assert event.metadata["endpoint"]["host"] == "proxy.example:8443"
        assert "secret-pass" not in json.dumps(event.model_dump(mode="json"))

    @pytest.mark.asyncio
    async def test_async_stream_records_one_logical_call(self, tmp_path):
        """异步流合并为一条 llm_call，含 ttft、usage，且不阻塞读取。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [
            _chunk("Hel", model="deepseek-reasoner"),
            _chunk(
                "lo",
                model="deepseek-reasoner",
                finish="stop",
                usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            ),
        ]

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            await asyncio.sleep(0)
            return _FakeAsyncStream(chunks)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_async_stream", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    stream = await comp.create(
                        model="deepseek-chat",
                        messages=[{"role": "user", "content": "Hi"}],
                        stream=True,
                    )
                    assert store.load_run("run_async_stream") == []
                    parts: list[str] = []
                    async for chunk in stream:
                        parts.append(chunk.model_dump()["choices"][0]["delta"]["content"])
            finally:
                uninstrument_openai_compatible()

        assert parts == ["Hel", "lo"]
        events = store.load_run("run_async_stream")
        assert len(events) == 1
        event = events[0]
        assert event.type == "llm_call"
        assert event.name == "deepseek-chat"
        assert event.metadata["response_model"] == "deepseek-reasoner"
        assert event.metadata["stream"] is True
        assert event.metadata["stream_completed"] is True
        assert event.metadata["usage"]["total_tokens"] == 6
        assert isinstance(event.metadata["ttft_ms"], int)
        assert event.output["choices"][0]["message"]["content"] == "Hello"
        assert event.started_at <= event.ended_at

    @pytest.mark.asyncio
    async def test_async_stream_error_records_partial_output(self, tmp_path):
        """流中途失败时记录 error，保留已收到的文本，并继续抛出异常。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [_chunk("partial")]

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            return _FakeAsyncStream(chunks, fail_at=1)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_async_stream_err", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    stream = await comp.create(
                        model="deepseek-chat",
                        messages=[],
                        stream=True,
                    )
                    with pytest.raises(RuntimeError, match="stream broke"):
                        async for _chunk_item in stream:
                            pass
            finally:
                uninstrument_openai_compatible()

        events = store.load_run("run_async_stream_err")
        assert len(events) == 1
        event = events[0]
        assert event.type == "error"
        assert "RuntimeError" in event.error
        assert event.metadata["stream"] is True
        assert event.metadata["stream_completed"] is False
        assert event.output["choices"][0]["message"]["content"] == "partial"

    @pytest.mark.asyncio
    async def test_async_stream_redacts_tool_call_arguments(self, tmp_path):
        """流式 tool call 只保留 id 和 name，参数增量不进入 trace。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [
            _chunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "function": {"name": "search", "arguments": '{"q":'},
                    }
                ]
            ),
            _chunk(
                tool_calls=[{"index": 0, "function": {"arguments": '"secret-arg"}'}}],
                finish="tool_calls",
            ),
        ]

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            return _FakeAsyncStream(chunks)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_async_tools", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    stream = await comp.create(
                        model="deepseek-chat",
                        messages=[],
                        stream=True,
                    )
                    async for _chunk_item in stream:
                        pass
            finally:
                uninstrument_openai_compatible()

        event = store.load_run("run_async_tools")[0]
        encoded = json.dumps(event.model_dump(mode="json"))
        assert "secret-arg" not in encoded
        tool_call = event.output["choices"][0]["message"]["tool_calls"][0]
        assert tool_call["id"] == "call_1"
        assert tool_call["name"] == "search"
        assert tool_call["arguments"] == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_async_stream_break_records_partial_call(self, tmp_path):
        """提前停止迭代也会写下已经读到的内容。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [_chunk("Hel"), _chunk("lo")]

        async def _async_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            return _FakeAsyncStream(chunks)

        with mock.patch.object(AsyncCompletions, "create", side_effect=_async_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_async_break", store):
                    comp = AsyncCompletions(client=mock.MagicMock())
                    stream = await comp.create(
                        model="deepseek-chat",
                        messages=[],
                        stream=True,
                    )
                    async for _chunk_item in stream:
                        break
                    # async for 的 break 不会立刻关闭异步生成器，需要 close 才会刷出事件。
                    await stream.aclose()
            finally:
                uninstrument_openai_compatible()

        event = store.load_run("run_async_break")[0]
        assert event.type == "llm_call"
        assert event.metadata["stream_completed"] is False
        assert event.output["choices"][0]["message"]["content"] == "Hel"


class TestParentEventIdCapture:
    """OpenAI 调用在开始时捕获父事件，流结束时不再读 contextvar。"""

    def test_sync_call_uses_current_parent(self, tmp_path):
        from openai.resources.chat.completions import Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_parent_event_id, set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        with mock.patch.object(Completions, "create", side_effect=_fake_create_response):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_parent_sync", store):
                    with set_current_parent_event_id("span-1"):
                        comp = Completions(client=mock.MagicMock())
                        comp.create(model="deepseek-chat", messages=[])
            finally:
                uninstrument_openai_compatible()

        event = store.load_run("run_parent_sync")[0]
        assert event.parent_event_id == "span-1"

    def test_stream_keeps_parent_captured_at_call_start(self, tmp_path):
        from openai.resources.chat.completions import Completions

        from agentlens import JsonlTraceStore
        from agentlens.context import set_current_parent_event_id, set_current_trace
        from agentlens.integrations.openai_compatible import (
            instrument_openai_compatible,
            uninstrument_openai_compatible,
        )

        _reset_instrument_state()
        chunks = [_chunk("Hel"), _chunk("lo", finish="stop")]

        def _sync_create(self_comp, **kwargs):  # noqa: ANN001, ANN003
            return _FakeSyncStream(chunks)

        with mock.patch.object(Completions, "create", side_effect=_sync_create):
            instrument_openai_compatible(provider="deepseek")
            try:
                store = JsonlTraceStore(base_dir=tmp_path)
                with set_current_trace("run_parent_stream", store):
                    with set_current_parent_event_id("span-at-start"):
                        comp = Completions(client=mock.MagicMock())
                        stream = comp.create(model="deepseek-chat", messages=[], stream=True)
                    with set_current_parent_event_id("span-while-reading"):
                        for _item in stream:
                            pass
            finally:
                uninstrument_openai_compatible()

        event = store.load_run("run_parent_stream")[0]
        assert event.type == "llm_call"
        assert event.parent_event_id == "span-at-start"
