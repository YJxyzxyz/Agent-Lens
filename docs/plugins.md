# 进程内插件

这是 v1.0 插件系统的第一片：在当前进程里显式注册一个 Python 对象。事件已经追加到该 run 的 JSONL 文件之后，对象会收到这条事件的只读通知。

没有插件市场，没有按目录或 entry point 自动发现，也不会下载或安装第三方包。

## 注册

```python
from agentlens import register_plugin
from agentlens.events import TraceEvent

class PrintPlugin:
    def on_event_appended(self, event: TraceEvent) -> None:
        print(event.type, event.name)

register_plugin(PrintPlugin())
```

`register_plugin` 只注册传入的那个对象。同一个对象再注册一次不会重复通知。可运行示例是 `examples/event_log_plugin.py`。

## 什么时候通知

`JsonlTraceStore.append_event` 把事件写入 JSONL 并关闭文件之后，才调用 `on_event_appended`。插件看到的是刚写入内容的副本。`load_run` 和 `list_runs` 不通知。

`replay`、`regression`、`diff`、统计、导出和 Web Viewer 不另外挂钩子。它们不写 JSONL。`@trace`、`@traced` 和 CLI 的默认行为也不变；一次追踪会通知，只是因为事件写进了 JSONL。

插件不应改存储，也不应重新执行 LLM 或工具调用，或把记录到的输出注入客户端或模型。插件抛出的异常会被记到 `agentlens.plugins` 的日志里，然后忽略。已经完成的写入和当前追踪继续。通知进行中再调用 `append_event` 时，嵌套的那次写入不会再次进入通知，以免递归。

通知里能看到刚记下的事件，其中可能有 LLM 输入输出或工具参数。不要把这些内容发出进程。
