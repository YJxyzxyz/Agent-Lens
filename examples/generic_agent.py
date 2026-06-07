"""Generic AgentLens 示例 — 无需 API key 即可运行。

演示 @traced 装饰器追踪任意 Python 函数，以及 file_read/file_write 事件。

运行方式::

    python examples/generic_agent.py

运行后使用::

    agentlens list
    agentlens show <run_id>
"""

from agentlens import record_file_write, trace, traced


@traced("search_web", event_type="tool_call")
def search_web(query: str) -> dict:
    """模拟搜索工具。"""
    return {
        "query": query,
        "results": [
            {"title": "RAG Survey 2024", "url": "https://arxiv.org/abs/2401.xxx"},
            {"title": "Benchmarking RAG Systems", "url": "https://arxiv.org/abs/2402.xxx"},
            {"title": "Evaluation Metrics for RAG", "url": "https://arxiv.org/abs/2403.xxx"},
        ],
    }


@traced("summarize", event_type="llm_call")
def summarize(text: str) -> str:
    """模拟 LLM 总结函数。"""
    return f"Summary: Found {text.count('RAG')} papers related to RAG evaluation."


@traced("calculate_score")
def calculate_score(summary: str) -> float:
    """模拟评分函数（未指定 event_type，默认 tool_call）。"""
    return 0.85


@trace("generic-agent-demo")
def main() -> str:
    """演示完整的 Agent 工作流。"""
    results = search_web("RAG evaluation benchmark")
    answer = summarize(str(results))
    score = calculate_score(answer)
    record_file_write("output/report.md", content_preview=f"Score: {score}\n\n{answer}")
    return answer


if __name__ == "__main__":
    result = main()
    print(f"最终结果: {result}")
    print("\n示例运行完成！使用以下命令查看追踪结果：")
    print("  agentlens list")
    print("  agentlens show <run_id>")
