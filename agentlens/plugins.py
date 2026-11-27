"""进程内插件 — 事件写入 JSONL 之后的只读通知。

只支持在当前进程里显式注册的 Python 对象。没有插件目录扫描、
entry point 发现、远程安装或插件市场。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Protocol, runtime_checkable

from agentlens.events import TraceEvent

logger = logging.getLogger(__name__)

__all__ = ["TracePlugin", "register_plugin"]


@runtime_checkable
class TracePlugin(Protocol):
    """写入 JSONL 之后的只读通知。

    插件只观察已经落盘的事件。它不应写存储，也不应重新执行 LLM 或工具调用。
    """

    def on_event_appended(self, event: TraceEvent) -> None:
        """事件已经追加到该 run 的 JSONL 文件之后调用。

        ``event`` 是已写入内容的副本。修改它不会写回文件，也不会改到调用方
        仍持有的那条事件。
        """
        ...


# 通知进行中再次进入时直接返回，避免插件里再写事件时无限递归。
_in_notify: ContextVar[bool] = ContextVar("agentlens_plugin_notify", default=False)
_plugins: list[TracePlugin] = []


def register_plugin(plugin: TracePlugin) -> None:
    """显式注册一个进程内插件。

    只注册传入的对象，不会扫描路径或入口点。同一个对象重复注册只保留一次。
    通知顺序与首次注册顺序相同。通知进行中新注册的插件从下一条事件开始收到通知。

    Args:
        plugin: 实现 ``on_event_appended(event)`` 的对象。

    Raises:
        TypeError: 对象没有可调用的 ``on_event_appended``。
    """
    hook = getattr(plugin, "on_event_appended", None)
    if not callable(hook):
        raise TypeError("plugin must define a callable on_event_appended(event) method")
    if any(existing is plugin for existing in _plugins):
        return
    _plugins.append(plugin)


def notify_event_appended(event: TraceEvent) -> None:
    """按注册顺序把刚写入的事件通知给插件。

    由 ``JsonlTraceStore.append_event`` 在 JSONL 写入成功后调用。
    插件抛出的异常在这里记录并忽略，不会传回写入或当前追踪。

    Args:
        event: 已经写入 JSONL 的事件。插件收到的是它的副本。
    """
    if not _plugins or _in_notify.get():
        return
    token = _in_notify.set(True)
    try:
        payload = event.model_dump_json()
        for plugin in tuple(_plugins):
            try:
                plugin.on_event_appended(TraceEvent.model_validate_json(payload))
            except Exception:
                logger.exception(
                    "plugin %s.on_event_appended failed",
                    type(plugin).__name__,
                )
    finally:
        _in_notify.reset(token)


def _clear_plugins() -> None:
    """清空注册表。供测试隔离使用，不是公开 API。"""
    _plugins.clear()
