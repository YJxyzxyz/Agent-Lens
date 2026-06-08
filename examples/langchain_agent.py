"""LangChain AgentLens 集成示例。

演示如何使用 AgentLensCallbackHandler 自动追踪 LangChain runnable。

运行方式::

    pip install -e ".[langchain]"
    python examples/langchain_agent.py

如果没有安装 langchain-core，本示例会打印安装提示并退出。
"""

from __future__ import annotations

import sys


def main() -> None:
    """演示 LangChain + AgentLens 集成。"""
    try:
        from langchain_core.runnables import RunnableLambda  # type: ignore[import-untyped]
    except ImportError:
        print("未安装 langchain-core。请运行:")
        print("  pip install -e '.[langchain]'")
        sys.exit(0)

    from agentlens import trace
    from agentlens.integrations.langchain import AgentLensCallbackHandler

    # 构建简单 runnable chain
    def step1(x: dict) -> dict:
        return {"query": x["question"], "results": ["doc1", "doc2"]}

    def step2(x: dict) -> str:
        return f"Answer based on {len(x['results'])} documents"

    chain = RunnableLambda(step1) | RunnableLambda(step2)
    handler = AgentLensCallbackHandler()

    with trace("langchain-demo"):
        result = chain.invoke(
            {"question": "What is AgentLens?"},
            config={"callbacks": [handler]},
        )
        print(f"Result: {result}")

    print("\n示例运行完成！使用以下命令查看追踪结果：")
    print("  agentlens list")
    print("  agentlens show <run_id>")


if __name__ == "__main__":
    main()
