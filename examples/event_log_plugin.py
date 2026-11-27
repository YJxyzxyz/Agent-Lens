"""进程内插件示例 — 事件写入 JSONL 之后打印一条只读通知。

插件不写存储，也不重新执行 LLM 或工具调用。
运行方式::

    python examples/event_log_plugin.py
"""

from agentlens import record_log, register_plugin, trace
from agentlens.events import TraceEvent


class EventLogPlugin:
    """打印已经写入 JSONL 的事件类型和名称。"""

    def on_event_appended(self, event: TraceEvent) -> None:
        print(f"[plugin] {event.run_id} {event.type} {event.name}")


def main() -> None:
    """注册示例插件，再跑一次会写入 JSONL 的追踪。"""
    register_plugin(EventLogPlugin())

    @trace("plugin-example")
    def run() -> None:
        record_log("hello from the example plugin")

    run()


if __name__ == "__main__":
    main()
    print("示例运行完成。插件只在事件写入 JSONL 之后收到通知。")
    print("  agentlens list")
    print("  agentlens show <run_id>")
