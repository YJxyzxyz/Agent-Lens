# LangChain Integration

通过 LangChain callback handler 自动追踪 chain / LLM / tool 运行事件。

`AgentLensCallbackHandler` 在安装了 `langchain-core` 时继承 LangChain 的 `BaseCallbackHandler`，所以 Runnable 的 `config={"callbacks": [handler]}` 会接受它。`LangChainCallbackHandler` 是同一个类的别名：

```python
from agentlens.integrations.langchain import (
    AgentLensCallbackHandler,
    LangChainCallbackHandler,
)

assert LangChainCallbackHandler is AgentLensCallbackHandler
```

未安装 `langchain-core` 时，handler 退化为普通对象，`import agentlens.integrations.langchain` 仍然成功。这时创建实例会抛出 `ImportError`，并提示安装依赖。

## 安装

```bash
pip install -e ".[langchain]"
```

## 基础用法

```python
from agentlens import trace
from agentlens.integrations.langchain import LangChainCallbackHandler

handler = LangChainCallbackHandler()

@trace("langchain-demo")
def run():
    return chain.invoke(
        {"question": "What is AgentLens?"},
        config={"callbacks": [handler]},
    )

run()
```

`AgentLensCallbackHandler()` 同样可用。

## 记录的事件

| LangChain 事件 | AgentLens 事件 | 默认名称 | 说明 |
|---------------|---------------|----------|------|
| `on_llm_start/end` | `llm_call` | `langchain.llm` | LLM 调用，含 model、prompts、output |
| `on_chain_start/end` | `tool_call` | `langchain.chain` | Chain 执行，含 inputs、outputs |
| `on_tool_start/end` | `tool_call` | `langchain.tool` | Tool 执行，含 input、output |
| `on_*_error` | `error` | 与对应调用相同 | 异常，含错误信息 |

名称优先取自 `serialized`：LLM 用 `serialized["kwargs"]["model"]`，chain / tool 用 `serialized["name"]`。`serialized` 为 `None`（例如 `RunnableLambda`）或缺少这些字段时，使用上表的默认名称，不会因为对 `None` 取属性而抛出 `AttributeError`。

每条事件 metadata 包含 `provider: "langchain"`、`run_id`、`parent_run_id`、`tags`、`duration_ms`。

## 安全

- `api_key`、`token`、`password` 等敏感字段自动脱敏
- 超长字符串自动截断
- 无 trace 上下文时 callback 不记录、不崩溃

> ⚠️ LangChain traces may include prompts, retrieved documents, tool inputs, and model outputs.
> Do not commit `.agentlens/runs`.
