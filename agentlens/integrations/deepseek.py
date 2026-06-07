"""DeepSeek API 自动追踪集成。

对 DeepSeek API 的 ``chat.completions.create`` 调用自动记录 trace 事件。
DeepSeek API 兼容 OpenAI API 格式（base_url: https://api.deepseek.com）。

用法::

    from openai import OpenAI
    from agentlens import trace
    from agentlens.integrations.deepseek import instrument_deepseek

    instrument_deepseek()

    @trace("deepseek-demo")
    def main():
        client = OpenAI(api_key="...", base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "Hello"}],
        )
        print(response.choices[0].message.content)

    main()
"""

from __future__ import annotations

from agentlens.integrations.openai_compatible import (
    instrument_openai_compatible,
    uninstrument_openai_compatible,
)


def instrument_deepseek() -> None:
    """激活 DeepSeek API 自动追踪。

    内部调用通用的 OpenAI-compatible integration，
    设置 provider = ``"deepseek"``。
    """
    instrument_openai_compatible(
        provider="deepseek",
        base_url_patterns=["api.deepseek.com", "deepseek"],
    )


def uninstrument_deepseek() -> None:
    """停用 DeepSeek 自动追踪，恢复原始方法。"""
    uninstrument_openai_compatible()
