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

## 自动记录的事件

每次 `chat.completions.create` 调用自动写入 `llm_call` 事件：

- **input** — model、messages、temperature、max_tokens
- **output** — id、model、choices、usage
- **metadata** — provider: "deepseek"、api 名称

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
