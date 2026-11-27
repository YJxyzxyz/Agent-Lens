# DeepSeek 集成

AgentLens 通过 OpenAI-compatible API 自动追踪 DeepSeek 的 `chat.completions.create` 调用。

## 安装

```bash
pip install -e ".[deepseek]"
```

## 设置 API Key

```bash
# Linux / macOS
export DEEPSEEK_API_KEY="sk-..."

# Windows PowerShell
$env:DEEPSEEK_API_KEY="sk-..."
```

## 使用

```python
import os
from openai import OpenAI
from agentlens import trace
from agentlens.integrations.deepseek import instrument_deepseek

instrument_deepseek()

@trace("deepseek-demo")
def main():
    client = OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print(response.choices[0].message.content)

main()
```

异步客户端同样会被追踪。`instrument_deepseek()` / `instrument_openai_compatible()` 会同时 patch 同步和异步的 `chat.completions.create`，异步路径只 `await` 原始协程，不会卡住事件循环。`@trace` 可以直接装饰 `async def`。

```python
import asyncio
import os
from openai import AsyncOpenAI
from agentlens import trace
from agentlens.integrations.deepseek import instrument_deepseek

instrument_deepseek()

@trace("deepseek-async-demo")
async def main():
    client = AsyncOpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
    )
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print(response.choices[0].message.content)

asyncio.run(main())
```

`stream=True` 时返回的同步或异步流可以照常迭代。流正常读完、调用 `close()` / `aclose()`、退出上下文管理器，或中途失败时，AgentLens 写入**一条** `llm_call` 或 `error` 事件，而不是每个 chunk 一条。事件里包含已经读到的文本、`duration_ms`、首个内容 token 的 `ttft_ms`（如果已经读到），以及响应里的 `usage`（如果 provider 在最后一个 chunk 里返回了用量）。异步循环里如果 `break` 提前结束，先 `await stream.aclose()` 或使用 `async with`，事件才会在你查看 trace 之前落盘。

## 自动记录的事件

每次 `chat.completions.create` 调用自动写入 `llm_call` 事件：

- **input** — model、messages、temperature、max_tokens
- **output** — id、model、choices、usage
- **metadata** — provider、api 名称、请求模型 `model`、响应模型 `response_model`、耗时 `duration_ms`
- **endpoint** — 只记录 `base_url` 的 host 和 path。用户名、密码和 query（例如 `api_key`）不会写入 trace
- **tool_calls** — 只记录 id 和 name，`arguments` 固定写成 `[REDACTED]`

## 安全

- `api_key` 自动替换为 `[REDACTED]`
- 其他敏感字段（token、password、cookie）同样自动脱敏
- 超长字符串自动截断

## 其他 OpenAI-compatible Provider

`instrument_openai_compatible(provider="xxx")` 支持任何兼容 OpenAI API 的 provider：

```python
from agentlens.integrations.openai_compatible import instrument_openai_compatible

instrument_openai_compatible(provider="openai")
# 或自定义 provider
instrument_openai_compatible(provider="ollama")
```
