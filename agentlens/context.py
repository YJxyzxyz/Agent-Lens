"""AgentLens 运行上下文管理。

使用 contextvars 保存当前 trace 的 run_id 和 store，支持并发安全。
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Generator, Optional

from agentlens.storage import JsonlTraceStore

# ---------------------------------------------------------------------------
# Context 变量
# ---------------------------------------------------------------------------

_current_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_run_id", default=None
)
_current_store: contextvars.ContextVar[Optional[JsonlTraceStore]] = contextvars.ContextVar(
    "current_store", default=None
)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def get_current_run_id() -> Optional[str]:
    """获取当前上下文的 run_id，若未设置则返回 None。"""
    return _current_run_id.get()


def get_current_store() -> Optional[JsonlTraceStore]:
    """获取当前上下文的 store，若未设置则返回 None。"""
    return _current_store.get()


def require_current_run_id() -> str:
    """获取当前上下文的 run_id，若未设置则抛出 RuntimeError。"""
    run_id = _current_run_id.get()
    if run_id is None:
        raise RuntimeError(
            "当前没有活跃的 trace 上下文。"
            " 请确保在 @trace 装饰的函数内调用 record_* 函数。"
        )
    return run_id


def require_current_store() -> JsonlTraceStore:
    """获取当前上下文的 store，若未设置则抛出 RuntimeError。"""
    store = _current_store.get()
    if store is None:
        raise RuntimeError(
            "当前没有活跃的 trace 上下文。"
            " 请确保在 @trace 装饰的函数内调用 record_* 函数。"
        )
    return store


@contextmanager
def set_current_trace(run_id: str, store: JsonlTraceStore) -> Generator[None, None, None]:
    """设置当前 trace 上下文的上下文管理器。

    Args:
        run_id: 运行 ID。
        store: 追踪事件存储实例。

    Yields:
        None
    """
    token_run_id = _current_run_id.set(run_id)
    token_store = _current_store.set(store)
    try:
        yield
    finally:
        _current_run_id.reset(token_run_id)
        _current_store.reset(token_store)
