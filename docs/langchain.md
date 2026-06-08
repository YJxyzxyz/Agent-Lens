# LangChain Integration

通过 LangChain callback handler 自动追踪 chain / LLM / tool 运行事件。

## 安装

```bash
pip install -e ".[langchain]"
```

## 基础用法

```python
from agentlens import trace
from agentlens.integrations.langchain import AgentLensCallbackHandler

handler = AgentLensCallbackHandler()

with trace("langchain-demo"):
    chain.invoke(
        {"question": "What is AgentLens?"},
        config={"callbacks": [handler]},
    )
```

## 记录的事件

| LangChain 事件 | AgentLens 事件 | 说明 |
|---------------|---------------|------|
| `on_llm_start/end` | `llm_call` | LLM 调用，含 model、prompts、output |
| `on_chain_start/end` | `tool_call` | Chain 执行，含 inputs、outputs |
| `on_tool_start/end` | `tool_call` | Tool 执行，含 input、output |
| `on_*_error` | `error` | 异常，含错误信息 |

每条事件 metadata 包含 `provider: "langchain"`、`run_id`、`parent_run_id`、`tags`、`duration_ms`。

## 安全

- `api_key`、`token`、`password` 等敏感字段自动脱敏
- 超长字符串自动截断
- 无 trace 上下文时 callback 不记录、不崩溃

> ⚠️ LangChain traces may include prompts, retrieved documents, tool inputs, and model outputs.
> Do not commit `.agentlens/runs`.
