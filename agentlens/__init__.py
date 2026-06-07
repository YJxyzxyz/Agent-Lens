"""AgentLens — AI Agent 的黑匣子。

轻量级 Agent 运行追踪、回放和调试工具。
"""

from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore
from agentlens.tracer import (
    record_event,
    record_file_read,
    record_file_write,
    record_llm_call,
    record_log,
    record_tool_call,
    trace,
    traced,
)

__all__ = [
    "trace",
    "traced",
    "record_event",
    "record_llm_call",
    "record_tool_call",
    "record_log",
    "record_file_read",
    "record_file_write",
    "TraceEvent",
    "JsonlTraceStore",
]

__version__ = "0.1.0"
