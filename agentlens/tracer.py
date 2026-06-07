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
    get_current_run_id,
    require_current_run_id,
    require_current_store,
    set_current_trace,
)
from agentlens.events import EventType, TraceEvent
from agentlens.serialization import safe_serialize
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


def record_file_read(
    path: str,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    """记录一次文件读取事件。

    Args:
        path: 文件路径。
        metadata: 附加信息，可选。

    Returns:
        创建的 TraceEvent。
    """
    meta = metadata or {}
    meta["path"] = path
    return record_event(
        type="file_read",
        name=path,
        metadata=meta,
    )


def record_file_write(
    path: str,
    content_preview: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> TraceEvent:
    """记录一次文件写入事件。

    Args:
        path: 文件路径。
        content_preview: 写入内容预览，最多保留 1000 字符。
        metadata: 附加信息，可选。

    Returns:
        创建的 TraceEvent。
    """
    meta = metadata or {}
    meta["path"] = path
    output: dict[str, Any] | None = None
    if content_preview is not None:
        output = {"content_preview": safe_serialize(content_preview, max_string_length=1000)}
    return record_event(
        type="file_write",
        name=path,
        output=output,
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# traced 装饰器
# ---------------------------------------------------------------------------


def traced(
    name: str | None = None,
    event_type: EventType = "tool_call",
    capture_input: bool = True,
    capture_output: bool = True,
    metadata: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """通用函数追踪装饰器 — 将函数调用记录为 Agent 运行中的一步。

    支持 ``@traced`` 和 ``@traced("name")`` 两种用法。

    用法::

        @traced
        def my_func():
            ...

        @traced("my-tool", event_type="tool_call")
        def my_tool():
            ...
    """
    # 支持不带括号的 @traced 用法
    if callable(name):
        func = name
        return _traced_impl(
            func, func.__name__, event_type, capture_input, capture_output, metadata
        )

    return lambda fn: _traced_impl(
        fn,
        name if name is not None else fn.__name__,
        event_type,
        capture_input,
        capture_output,
        metadata,
    )


def _traced_impl(
    func: F,
    event_name: str,
    event_type: EventType,
    capture_input: bool,
    capture_output: bool,
    user_metadata: dict[str, Any] | None,
) -> F:
    """traced 的实际实现。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # 没有 trace 上下文 → 直接执行，不记录
        run_id = get_current_run_id()
        if run_id is None:
            return func(*args, **kwargs)

        # 序列化 input
        safe_input: dict[str, Any] | None = None
        if capture_input:
            raw_input = {"args": list(args), "kwargs": dict(kwargs)}
            safe_input = safe_serialize(raw_input)

        started_at = datetime.now(timezone.utc)

        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            error_meta = user_metadata.copy() if user_metadata else {}
            error_meta["duration_ms"] = duration_ms
            record_event(
                type="error",
                name=event_name,
                input=safe_input,
                error=f"{type(exc).__name__}: {exc}",
                metadata=error_meta,
            )
            raise

        ended_at = datetime.now(timezone.utc)
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        safe_output: Any | None = None
        if capture_output:
            safe_output = safe_serialize(result)

        event_meta = user_metadata.copy() if user_metadata else {}
        event_meta["duration_ms"] = duration_ms

        record_event(
            type=event_type,
            name=event_name,
            input=safe_input,
            output=safe_output,
            metadata=event_meta,
        )

        return result

    return wrapper  # type: ignore[return-value]
