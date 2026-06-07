"""OpenAI-compatible integration 测试。

使用 monkeypatch mock 测试，不发起真实 API 调用。
"""

from __future__ import annotations

from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _reset_instrument_state():
    """重置 openai_compatible 模块的 patch 状态（含恢复类方法）。"""
    import agentlens.integrations.openai_compatible as mod

    # 如果当前是 patched 状态，先恢复原始方法
    if mod._patched and mod._original_create is not None:  # noqa: SLF001
        try:
            from openai.resources.chat.completions import Completions

            Completions.create = mod._original_create  # type: ignore[assignment]  # noqa: SLF001
        except ImportError:
            pass

    mod._patched = False  # noqa: SLF001
    mod._original_create = None  # noqa: SLF001


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
