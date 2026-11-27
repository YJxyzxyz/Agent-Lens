"""DeepSeek integration 测试。"""

from __future__ import annotations

import inspect
from unittest import mock


class TestDeepSeekIntegration:
    """instrument_deepseek / uninstrument_deepseek 测试。"""

    def test_instrument_deepseek_calls_openai_compatible_with_deepseek_provider(self):
        """instrument_deepseek 调用通用 integration 并设置 provider='deepseek'。"""
        from agentlens.integrations import deepseek

        # patch deepseek 模块中导入的 instrument_openai_compatible 引用
        with mock.patch.object(deepseek, "instrument_openai_compatible") as mock_instrument:
            deepseek.instrument_deepseek()
            mock_instrument.assert_called_once_with(
                provider="deepseek",
                base_url_patterns=["api.deepseek.com", "deepseek"],
            )

        # 重置状态
        import agentlens.integrations.openai_compatible as mod

        mod._patched = False  # noqa: SLF001
        mod._original_create = None  # noqa: SLF001
        mod._original_acreate = None  # noqa: SLF001

    def test_uninstrument_deepseek_calls_uninstrument(self):
        """uninstrument_deepseek 调用通用 uninstrument。"""
        from agentlens.integrations import deepseek

        with mock.patch.object(deepseek, "uninstrument_openai_compatible") as mock_uninstrument:
            deepseek.uninstrument_deepseek()
            mock_uninstrument.assert_called_once()

    def test_instrument_deepseek_patches_async_create(self):
        """instrument_deepseek 同时替换 AsyncCompletions.create，uninstrument 能恢复。"""
        from openai.resources.chat.completions import AsyncCompletions

        from agentlens.integrations.deepseek import instrument_deepseek, uninstrument_deepseek
        from agentlens.integrations.openai_compatible import uninstrument_openai_compatible

        uninstrument_openai_compatible()
        original = AsyncCompletions.create
        instrument_deepseek()
        try:
            assert AsyncCompletions.create is not original
            assert inspect.iscoroutinefunction(AsyncCompletions.create)
        finally:
            uninstrument_deepseek()
        assert AsyncCompletions.create is original
