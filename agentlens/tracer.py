"""AgentLens 追踪 API — 装饰器与事件记录函数。

提供面向用户的追踪入口：
- ``@trace`` 装饰器：自动包裹函数，记录 run_start / run_end / error 事件。
- ``record_event`` / ``record_llm_call`` / ``record_tool_call`` / ``record_log``：
  在 active trace 上下文中手动追加事件。
"""

from __future__ import annotations

import functools
import secrets
import traceback as tb
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from agentlens.context import (
    require_current_run_id,
    require_current_store,
    set_current_trace,
)
from agentlens.events import EventType, TraceEvent
from agentlens.storage import JsonlTraceStore

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _generate_run_id() -> str:
    """生成唯一 run_id，格式: run_YYYYMMDD_HHMMSS_<随机8字符>"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    random_suffix = secrets.token_hex(4)
    return f"run_{timestamp}_{random_suffix}"


# ---------------------------------------------------------------------------
# trace 装饰器
# ---------------------------------------------------------------------------


def trace(
    name: str,
    *,
    store: JsonlTraceStore | None = None,
    run_id: str | None = None,
) -> Callable[[F], F]:
    """追踪装饰器 — 自动记录函数的 run_start / run_end / error 事件。

    用法::

        from agentlens import trace

        @trace("my-agent")
        def main():
            ...

        main()  # 每次调用都会产生一个新的 trace run

    Args:
        name: 追踪名称（如 Agent 名称），会记录在事件的 name 字段中。
        store: 可选的存储实例，不传则使用默认 JSONL 存储。
        run_id: 可选的自定义 run_id，不传则自动生成。

    Returns:
        装饰后的函数。
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _store = store if store is not None else JsonlTraceStore()
            _run_id = run_id if run_id is not None else _generate_run_id()

            with set_current_trace(_run_id, _store):
                # --- run_start ---
                start_time = datetime.now(timezone.utc)
                start_event = TraceEvent(
                    run_id=_run_id,
                    type="run_start",
                    name=name,
                    started_at=start_time,
                )
                _store.append_event(start_event)

                try:
                    result = func(*args, **kwargs)

                    # --- run_end ---
                    end_time = datetime.now(timezone.utc)
                    end_event = TraceEvent(
                        run_id=_run_id,
                        type="run_end",
                        name=name,
                        started_at=end_time,
                        ended_at=end_time,
                        output={"result": str(result)[:200] if result is not None else None},
                    )
                    _store.append_event(end_event)

                    return result

                except Exception as exc:
                    # --- error ---
                    error_event = TraceEvent(
                        run_id=_run_id,
                        type="error",
                        name=name,
                        error=f"{type(exc).__name__}: {exc}",
                        metadata={"traceback": tb.format_exc()},
                    )
                    _store.append_event(error_event)
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# 事件记录函数
# ---------------------------------------------------------------------------


def record_event(
    type: EventType,
    name: str,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
    parent_id: str | None = None,
) -> TraceEvent:
    """向当前 run 追加一条事件。

    Args:
        type: 事件类型。
        name: 事件名称。
        input: 事件输入，可选。
        output: 事件输出，可选。
        metadata: 附加元数据，可选。
        error: 错误信息，可选。
        parent_id: 父事件 ID，可选。

    Returns:
        创建并已存储的 TraceEvent 实例。

    Raises:
        RuntimeError: 当前无活跃 trace 上下文。
    """
    run_id = require_current_run_id()
    store = require_current_store()

    now = datetime.now(timezone.utc)
    event = TraceEvent(
        run_id=run_id,
        parent_id=parent_id,
        type=type,
        name=name,
        input=input,
        output=output,
        metadata=metadata or {},
        started_at=now,
        ended_at=now,
        error=error,
    )
    store.append_event(event)
    return event


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def record_llm_call(
    model: str,
    input: Any,
    output: Any,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    """记录一次 LLM 调用事件。

    Args:
        model: 模型名称，如 "gpt-4.1"。
        input: 发送给模型的消息或提示。
        output: 模型返回的响应。
        metadata: 附加信息（如 token 用量、延迟等），可选。

    Returns:
        创建的 TraceEvent。
    """
    return record_event(
        type="llm_call",
        name=model,
        input=input,
        output=output,
        metadata=metadata,
    )


def record_tool_call(
    name: str,
    input: Any,
    output: Any,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    """记录一次工具调用事件。

    Args:
        name: 工具名称，如 "search_web"。
        input: 工具输入参数。
        output: 工具返回结果。
        metadata: 附加信息，可选。

    Returns:
        创建的 TraceEvent。
    """
    return record_event(
        type="tool_call",
        name=name,
        input=input,
        output=output,
        metadata=metadata,
    )


def record_log(
    message: str,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    """记录一条日志事件。

    Args:
        message: 日志消息。
        metadata: 附加信息，可选。

    Returns:
        创建的 TraceEvent。
    """
    return record_event(
        type="log",
        name=message[:120],
        metadata=metadata,
    )
