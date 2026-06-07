"""DeepSeek AgentLens 集成示例。

演示如何使用 AgentLens 自动追踪 DeepSeek API 调用。

使用方法::

    pip install -e ".[deepseek]"

    # Linux / macOS
    export DEEPSEEK_API_KEY="sk-..."

    # Windows PowerShell
    $env:DEEPSEEK_API_KEY="sk-..."

    python examples/deepseek_agent.py

运行后可使用 CLI 查看追踪结果::

    agentlens list
    agentlens show <run_id>
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """演示 DeepSeek AgentLens 自动追踪。"""
    from openai import OpenAI

    from agentlens import trace
    from agentlens.integrations.deepseek import instrument_deepseek

    instrument_deepseek()

    @trace("deepseek-demo-agent")
    def run_agent() -> None:
        client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )

        # 第一轮
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": "Say hello in one sentence."},
            ],
        )
        print(f"Response: {response.choices[0].message.content}")

        # 第二轮
        response2 = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": "What is the capital of France?"},
            ],
            temperature=0.7,
            max_tokens=50,
        )
        print(f"Response: {response2.choices[0].message.content}")

    run_agent()
    print("\n示例运行完成！使用以下命令查看追踪结果：")
    print("  agentlens list")
    print("  agentlens show <run_id>")


if __name__ == "__main__":
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("错误: 请设置环境变量 DEEPSEEK_API_KEY")
        print("  Linux/macOS: export DEEPSEEK_API_KEY='sk-...'")
        print("  Windows: $env:DEEPSEEK_API_KEY='sk-...'")
        sys.exit(1)

    # 检查 openai 是否已安装
    try:
        import openai  # noqa: F401
    except ImportError:
        print("错误: 未安装 openai 包")
        print("  请运行: pip install -e '.[deepseek]'")
        sys.exit(1)

    main()
