"""AgentLens 追踪 API — 装饰器与事件记录函数。

提供面向用户的追踪入口：
- ``@trace`` 装饰器：自动包裹函数，记录 run_start / run_end / error 事件。
- ``record_event`` / ``record_llm_call`` / ``record_tool_call`` / ``record_log``：
  在 active trace 上下文中手动追加事件。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import secrets
import traceback as tb
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from agentlens.context import (
    get_current_parent_event_id,
    get_current_run_id,
    require_current_run_id,
    require_current_store,
    set_current_parent_event_id,
    set_current_trace,
)
from agentlens.events import EventType, TraceEvent
from agentlens.serialization import safe_serialize
from agentlens.storage import JsonlTraceStore

F = TypeVar("F", bound=Callable[..., Any])


class _UnsetType:
    """区分「调用方没传父事件」和「调用方显式传入 None」。"""


_UNSET = _UnsetType()


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

    同步函数与 ``async def`` 协程函数都可以使用。协程函数会把 trace 上下文保持到
    ``await`` 结束，因此内部的 ``await client.chat.completions.create(...)`` 能被记录。

    用法::

        from agentlens import trace

        @trace("my-agent")
        def main():
            ...

        main()  # 每次调用都会产生一个新的 trace run

        @trace("async-agent")
        async def amain():
            ...

        await amain()

    Args:
        name: 追踪名称（如 Agent 名称），会记录在事件的 name 字段中。
        store: 可选的存储实例，不传则使用默认 JSONL 存储。
        run_id: 可选的自定义 run_id，不传则自动生成。

    Returns:
        装饰后的函数。
    """

    def decorator(func: F) -> F:
        def _prepare() -> tuple[JsonlTraceStore, str]:
            _store = store if store is not None else JsonlTraceStore()
            _run_id = run_id if run_id is not None else _generate_run_id()
            return _store, _run_id

        def _append_run_event(
            _store: JsonlTraceStore,
            _run_id: str,
            *,
            event_type: EventType,
            output: Any | None = None,
            error: str | None = None,
            metadata: dict[str, Any] | None = None,
            started_at: datetime | None = None,
            ended_at: datetime | None = None,
        ) -> TraceEvent:
            """写入一条 run 生命周期事件。父事件取自当前 run 的 contextvar。"""
            now = datetime.now(timezone.utc)
            event = TraceEvent(
                run_id=_run_id,
                parent_event_id=get_current_parent_event_id(),
                type=event_type,
                name=name,
                output=output,
                metadata=metadata or {},
                started_at=started_at or now,
                ended_at=ended_at,
                error=error,
            )
            _store.append_event(event)
            return event

        def _mark_start(_store: JsonlTraceStore, _run_id: str) -> TraceEvent:
            return _append_run_event(
                _store,
                _run_id,
                event_type="run_start",
                started_at=datetime.now(timezone.utc),
            )

        def _mark_end(_store: JsonlTraceStore, _run_id: str, result: Any) -> None:
            end_time = datetime.now(timezone.utc)
            _append_run_event(
                _store,
                _run_id,
                event_type="run_end",
                started_at=end_time,
                ended_at=end_time,
                output={"result": str(result)[:200] if result is not None else None},
            )

        def _mark_error(_store: JsonlTraceStore, _run_id: str, exc: BaseException) -> None:
            _append_run_event(
                _store,
                _run_id,
                event_type="error",
                error=f"{type(exc).__name__}: {exc}",
                metadata={"traceback": tb.format_exc()},
            )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _store, _run_id = _prepare()
                with set_current_trace(_run_id, _store):
                    start_event = _mark_start(_store, _run_id)
                    with set_current_parent_event_id(start_event.id):
                        try:
                            result = await func(*args, **kwargs)
                        except asyncio.CancelledError as exc:
                            try:
                                _mark_error(_store, _run_id, exc)
                            except Exception:
                                pass
                            raise
                        except Exception as exc:
                            _mark_error(_store, _run_id, exc)
                            raise
                        _mark_end(_store, _run_id, result)
                        return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _store, _run_id = _prepare()

            with set_current_trace(_run_id, _store):
                start_event = _mark_start(_store, _run_id)
                with set_current_parent_event_id(start_event.id):
                    try:
                        result = func(*args, **kwargs)
                    except Exception as exc:
                        _mark_error(_store, _run_id, exc)
                        raise
                    _mark_end(_store, _run_id, result)
                    return result

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# 事件记录函数
# ---------------------------------------------------------------------------


def _resolve_parent_event_id(
    parent_event_id: str | None | _UnsetType,
    parent_id: str | None | _UnsetType,
) -> str | None:
    """决定写入 JSONL 的父事件 ID。

    两个参数都没传时，使用当前 run 的 contextvar。显式传入的值（包括 None）
    优先于上下文。``parent_event_id`` 与 ``parent_id`` 同时传入时必须相同。
    """
    explicit: list[str | None] = []
    if not isinstance(parent_event_id, _UnsetType):
        explicit.append(parent_event_id)
    if not isinstance(parent_id, _UnsetType):
        explicit.append(parent_id)
    if not explicit:
        return get_current_parent_event_id()
    if len(explicit) == 2 and explicit[0] != explicit[1]:
        raise ValueError("parent_event_id 和 parent_id 不一致")
    return explicit[0]


def record_event(
    type: EventType,
    name: str,
    input: Any | None = None,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
    parent_id: str | None | _UnsetType = _UNSET,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    parent_event_id: str | None | _UnsetType = _UNSET,
    event_id: str | None = None,
) -> TraceEvent:
    """向当前 run 追加一条事件。

    未指定父事件时，使用当前 run 上下文里的 ``parent_event_id``。
    该上下文由 ``@trace`` / ``@traced`` 设置，并且在进入新的 run 时清空。

    Args:
        type: 事件类型。
        name: 事件名称。
        input: 事件输入，可选。
        output: 事件输出，可选。
        metadata: 附加元数据，可选。
        error: 错误信息，可选。
        parent_id: 父事件 ID 的兼容参数。不传则使用当前上下文；传入 None 表示根事件。
        started_at: 事件开始时间，可选。不传则使用当前时间。
        ended_at: 事件结束时间，可选。不传则使用当前时间。
        parent_event_id: 父事件 ID。语义与 ``parent_id`` 相同，同时传入时必须一致。
        event_id: 事件 ID，可选。不传则自动生成。嵌套 span 会预先分配 ID，
            让函数体内的子事件能指向这条尚未写盘的事件。

    Returns:
        创建并已存储的 TraceEvent 实例。

    Raises:
        RuntimeError: 当前无活跃 trace 上下文。
        ValueError: ``parent_event_id`` 与 ``parent_id`` 同时传入且不一致。
    """
    run_id = require_current_run_id()
    store = require_current_store()
    resolved_parent = _resolve_parent_event_id(parent_event_id, parent_id)

    now = datetime.now(timezone.utc)
    event_kwargs: dict[str, Any] = {}
    if event_id is not None:
        event_kwargs["id"] = event_id
    event = TraceEvent(
        run_id=run_id,
        parent_event_id=resolved_parent,
        type=type,
        name=name,
        input=input,
        output=output,
        metadata=metadata or {},
        started_at=started_at or now,
        ended_at=ended_at or now,
        error=error,
        **event_kwargs,
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
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> TraceEvent:
    """记录一次 LLM 调用事件。

    Args:
        model: 模型名称，如 "gpt-4.1"。
        input: 发送给模型的消息或提示。
        output: 模型返回的响应。
        metadata: 附加信息（如 token 用量、延迟等），可选。
        started_at: 调用开始时间，可选。
        ended_at: 调用结束时间，可选。

    Returns:
        创建的 TraceEvent。
    """
    return record_event(
        type="llm_call",
        name=model,
        input=input,
        output=output,
        metadata=metadata,
        started_at=started_at,
        ended_at=ended_at,
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

    支持 ``@traced`` 和 ``@traced("name")`` 两种用法，也支持 ``async def``。

    用法::

        @traced
        def my_func():
            ...

        @traced("my-tool", event_type="tool_call")
        def my_tool():
            ...

        @traced("fetch")
        async def fetch():
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
    """traced 的实际实现。同步函数与协程函数共用同一套记录逻辑。"""

    def _safe_input(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any | None:
        if not capture_input:
            return None
        return safe_serialize({"args": list(args), "kwargs": dict(kwargs)})

    def _metadata(started_at: datetime, ended_at: datetime) -> dict[str, Any]:
        event_meta = user_metadata.copy() if user_metadata else {}
        event_meta["duration_ms"] = max(0, int((ended_at - started_at).total_seconds() * 1000))
        return event_meta

    def _record_success(
        safe_input: Any | None,
        result: Any,
        started_at: datetime,
        ended_at: datetime,
        event_id: str,
        parent_event_id: str | None,
    ) -> None:
        safe_output = safe_serialize(result) if capture_output else None
        record_event(
            type=event_type,
            name=event_name,
            input=safe_input,
            output=safe_output,
            metadata=_metadata(started_at, ended_at),
            started_at=started_at,
            ended_at=ended_at,
            parent_event_id=parent_event_id,
            event_id=event_id,
        )

    def _record_failure(
        safe_input: Any | None,
        exc: BaseException,
        started_at: datetime,
        ended_at: datetime,
        event_id: str,
        parent_event_id: str | None,
    ) -> None:
        record_event(
            type="error",
            name=event_name,
            input=safe_input,
            error=f"{type(exc).__name__}: {exc}",
            metadata=_metadata(started_at, ended_at),
            started_at=started_at,
            ended_at=ended_at,
            parent_event_id=parent_event_id,
            event_id=event_id,
        )

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if get_current_run_id() is None:
                return await func(*args, **kwargs)

            parent_before = get_current_parent_event_id()
            event_id = uuid.uuid4().hex[:16]
            safe_input = _safe_input(args, kwargs)
            started_at = datetime.now(timezone.utc)
            try:
                with set_current_parent_event_id(event_id):
                    result = await func(*args, **kwargs)
            except asyncio.CancelledError as exc:
                ended_at = datetime.now(timezone.utc)
                try:
                    _record_failure(safe_input, exc, started_at, ended_at, event_id, parent_before)
                except Exception:
                    pass
                raise
            except Exception as exc:
                ended_at = datetime.now(timezone.utc)
                _record_failure(safe_input, exc, started_at, ended_at, event_id, parent_before)
                raise

            ended_at = datetime.now(timezone.utc)
            _record_success(safe_input, result, started_at, ended_at, event_id, parent_before)
            return result

        return async_wrapper  # type: ignore[return-value]

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # 没有 trace 上下文 → 直接执行，不记录
        if get_current_run_id() is None:
            return func(*args, **kwargs)

        parent_before = get_current_parent_event_id()
        event_id = uuid.uuid4().hex[:16]
        safe_input = _safe_input(args, kwargs)
        started_at = datetime.now(timezone.utc)

        try:
            with set_current_parent_event_id(event_id):
                result = func(*args, **kwargs)
        except Exception as exc:
            ended_at = datetime.now(timezone.utc)
            _record_failure(safe_input, exc, started_at, ended_at, event_id, parent_before)
            raise

        ended_at = datetime.now(timezone.utc)
        _record_success(safe_input, result, started_at, ended_at, event_id, parent_before)
        return result

    return wrapper  # type: ignore[return-value]
