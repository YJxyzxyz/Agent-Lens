# Generic Function Tracing

AgentLens 不依赖任何特定模型 SDK。使用 `@traced` 可以追踪任意 Python 函数。

## `@trace` vs `@traced`

| 装饰器 | 用途 | 记录事件 |
|--------|------|----------|
| `@trace("name")` | 标记一个 **run** 的开始/结束 | `run_start` + `run_end` + `error` |
| `@traced("name")` | 标记 run 中的**一个步骤** | 由 `event_type` 指定 |

一个 run 包含一个 `@trace` 和多个 `@traced` 步骤。

## tool_call 示例

```python
from agentlens import trace, traced

@traced("search_web", event_type="tool_call")
def search_web(query: str):
    return {"query": query, "results": 3}

@trace("search-agent")
def main():
    results = search_web("RAG evaluation")
    return results

main()
```

## llm_call 示例

```python
@traced("summarize", event_type="llm_call")
def summarize(text: str) -> str:
    # 你的 LLM 调用逻辑
    return f"Summary of: {text[:50]}..."
```

## 文件事件

```python
from agentlens import record_file_read, record_file_write

record_file_read("data/input.json")
record_file_write("output/report.md", content_preview="# Results\n\nDone.")
```

## 自动安全处理

`@traced` 会自动：

- 脱敏 `api_key`、`token`、`password`、`secret`、`cookie` 等敏感字段
- 截断超长字符串（默认 4000 字符）
- 记录 `duration_ms` 执行耗时
- 无 trace 上下文时直接执行，不记录、不崩溃

## 高级用法

```python
# 不捕获参数
@traced("side-effect", capture_input=False, capture_output=False)
def side_effect_only():
    send_notification()

# 使用函数名作为事件名
@traced
def my_tool():
    ...

# 自定义 event_type
@traced("read-config", event_type="file_read")
def read_config(path: str):
    ...
```
