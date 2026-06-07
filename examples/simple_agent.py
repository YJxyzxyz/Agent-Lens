"""AgentLens 简单示例 — 模拟一个 AI Agent 的追踪流程。

运行方式::

    python examples/simple_agent.py
"""

from agentlens import record_llm_call, record_log, record_tool_call, trace


@trace("simple-agent")
def main() -> None:
    """模拟一个简单的 Agent 工作流。"""
    record_log("Agent started")

    # 模拟 LLM 规划
    record_llm_call(
        model="mock-model",
        input="Plan a research task",
        output="I should search first.",
    )

    # 模拟工具调用
    record_tool_call(
        name="search_web",
        input={"query": "RAG evaluation benchmark"},
        output={"results": 3},
    )

    # 模拟第二次 LLM 调用
    record_llm_call(
        model="mock-model",
        input="Summarize the search results",
        output="Found 3 relevant papers on RAG evaluation.",
    )

    record_log("Agent finished")


if __name__ == "__main__":
    main()
    print("示例运行完成！使用以下命令查看追踪结果：")
    print("  agentlens list")
    print("  agentlens show <run_id>")
