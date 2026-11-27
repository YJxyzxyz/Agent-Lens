"""AgentLens 运行上下文管理。

使用 contextvars 保存当前 trace 的 run_id、store 和父事件 ID，支持并发安全。
父事件只在当前 run 的上下文里传递，进入新的 run 时会清空，不会串到其他 run。
"""

from __future__ import annotations

import contextvars
from collections.abc import Generator
from contextlib import contextmanager

from agentlens.storage import JsonlTraceStore

# ---------------------------------------------------------------------------
# Context 变量
# ---------------------------------------------------------------------------

_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_run_id", default=None
)
_current_store: contextvars.ContextVar[JsonlTraceStore | None] = contextvars.ContextVar(
    "current_store", default=None
)
_current_parent_event_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_parent_event_id", default=None
)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def get_current_run_id() -> str | None:
    """获取当前上下文的 run_id，若未设置则返回 None。"""
    return _current_run_id.get()


def get_current_store() -> JsonlTraceStore | None:
    """获取当前上下文的 store，若未设置则返回 None。"""
    return _current_store.get()


def get_current_parent_event_id() -> str | None:
    """获取当前上下文的父事件 ID。未设置时返回 None，表示下一条事件是根。"""
    return _current_parent_event_id.get()


def require_current_run_id() -> str:
    """获取当前上下文的 run_id，若未设置则抛出 RuntimeError。"""
    run_id = _current_run_id.get()
    if run_id is None:
        raise RuntimeError(
            "当前没有活跃的 trace 上下文。 请确保在 @trace 装饰的函数内调用 record_* 函数。"
        )
    return run_id


def require_current_store() -> JsonlTraceStore:
    """获取当前上下文的 store，若未设置则抛出 RuntimeError。"""
    store = _current_store.get()
    if store is None:
        raise RuntimeError(
            "当前没有活跃的 trace 上下文。 请确保在 @trace 装饰的函数内调用 record_* 函数。"
        )
    return store


@contextmanager
def set_current_trace(run_id: str, store: JsonlTraceStore) -> Generator[None, None, None]:
    """设置当前 trace 上下文的上下文管理器。

    进入一次 run 时会把父事件清空。嵌套的 ``@trace`` 或之后开始的另一次 run
    不会继承外层 span 的 ``parent_event_id``。

    Args:
        run_id: 运行 ID。
        store: 追踪事件存储实例。

    Yields:
        None
    """
    token_run_id = _current_run_id.set(run_id)
    token_store = _current_store.set(store)
    token_parent = _current_parent_event_id.set(None)
    try:
        yield
    finally:
        _current_parent_event_id.reset(token_parent)
        _current_store.reset(token_store)
        _current_run_id.reset(token_run_id)


@contextmanager
def set_current_parent_event_id(parent_event_id: str | None) -> Generator[None, None, None]:
    """在当前上下文中设置父事件 ID，退出时恢复进入前的值。

    传 None 表示这段代码里记录的事件是根事件，除非调用方显式传入别的父 ID。
    这个值只活在当前 contextvar 上下文里（包括由此创建的协程任务），
    不会写进其他 run。
    """
    token = _current_parent_event_id.set(parent_event_id)
    try:
        yield
    finally:
        _current_parent_event_id.reset(token)
