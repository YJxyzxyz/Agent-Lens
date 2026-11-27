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

## 异步函数

`@trace` 和 `@traced` 可以装饰 `async def`。上下文会保持到协程结束，所以函数里面的 `await` 仍然算同一次 run。

```python
import asyncio
from agentlens import trace, traced

@traced("fetch_page")
async def fetch_page(url: str) -> str:
    return url

@trace("async-agent")
async def main():
    page = await fetch_page("https://example.com")
    return page

asyncio.run(main())
```

## 事件树

`@trace` 和 `@traced` 会把父子关系记到每条事件的 `parent_event_id`，并写入该 run 的 JSONL。

- `@trace` 的 `run_start` 是根（`parent_event_id` 为 `null`）。函数体内直接记录的事件以这条 `run_start` 为父事件，`run_end` 也是。
- `@traced` 在函数执行期间成为当前父事件。里面再调用的 `@traced` 或 `record_*` 是它的子事件。
- 父事件 id 放在 contextvar 里，只对当前这次 run 生效。新的 `@trace` 会清空它，不会把外层 run 的父事件带进来。
- 需要指定别的父事件时用 `record_event(..., parent_event_id="...")`。传入 `None` 会强制这条事件成为根。

子事件可能先写入，对应的 `@traced` 事件后写入。还原树时按 id 查找，不要求父事件排在前面。

```bash
agentlens tree <run_id>
```

这是缩进后的事件树。`agentlens show <run_id>` 仍然是线性时间线，`agentlens view` 仍然是 Web 查看器。

如果某条事件的 `parent_event_id` 在这次 run 里不存在，`tree` 仍会打印该事件和它的子树，并在事件末尾加上 `[missing parent: id]`。同一个缺失 id 的事件放在一组，不同 id 分开。最后一行是 `N orphans, M missing parents`。父事件都能找到时没有这个标记，摘要是 `0 orphans, 0 missing parents`。

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
