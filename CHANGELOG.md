# Changelog

All notable changes to AgentLens will be documented in this file.

## Unreleased

### Features

- **事件树** — 事件增加 `parent_event_id`（构造和读取仍接受 `parent_id`）。同一次 run 内，`@trace` / `@traced` 用 contextvar 传递父事件；新的 run 会清空该上下文，不会串到其他 run。JSONL 记下这个字段，父事件可以晚于子事件写入。`agentlens tree <run_id>` 按父子关系缩进打印。父 id 在本次 run 中不存在时，事件和子树留在顶层并标记 `[missing parent: id]`，按缺失 id 分组，最后一行摘要为 `N orphans, M missing parents`。`show` 仍是线性时间线，`view` 仍是 Web 查看器。
- **Async OpenAI-compatible tracing** — `instrument_openai_compatible` 同时 patch 同步 `Completions.create` 和异步 `AsyncCompletions.create`。`await client.chat.completions.create(...)` 会记录 `llm_call`，异步实现只 await 原始协程，不调用同步方法，也不阻塞事件循环。`instrument_deepseek()` 走同一条路径。
- **Streaming chat completions** — 同步和异步 `stream=True` 会包装返回的流，在流结束、提前停止或中途失败时写入一条 `llm_call` 或 `error`。记录 `duration_ms`、`ttft_ms`、`usage`（如果响应里有）和 `stream_completed`。
- **Async `@trace` / `@traced`** — 协程函数的 trace 上下文保持到 await 结束。任务取消时记录 `CancelledError` 并继续向外抛出。
- OpenAI-compatible 事件额外记录请求模型与 `response_model`，以及脱敏后的 endpoint（只有 host 和 path）。助手消息里的 tool call 只保留 id 和 name，`arguments` 写成 `[REDACTED]`。
- **LangChain callback** — `AgentLensCallbackHandler` 在安装了 `langchain-core` 时继承 `BaseCallbackHandler`；未安装时退化为普通对象，模块仍可导入，实例化会提示安装依赖。`LangChainCallbackHandler` 是同一个类的别名。`serialized` 为 `None`（例如 `RunnableLambda`）时不再抛出 `AttributeError`，事件名回退为 `langchain.llm`、`langchain.chain`、`langchain.tool`。

0.1.0 里「暂不支持异步追踪」的限制，对 `@trace` / `@traced` 和 OpenAI-compatible `chat.completions.create` 不再成立。其他异步入口（例如 `with_streaming_response`）还没有覆盖。0.1.0-alpha 的 “No LangChain or other framework integrations yet” 对 LangChain callback 不再成立。

## 0.1.0-alpha

Initial alpha release.

### Features

- **Python tracing SDK** — `@trace` decorator for automatic run lifecycle tracking
- **Generic function tracing** — `@traced` decorator for instrumenting any Python function
- **File event helpers** — `record_file_read` and `record_file_write`
- **Local JSONL storage** — Trace data saved in `.agentlens/runs/` with zero cloud dependency
- **CLI commands** — `list`, `show`, `inspect`, `diff`, `view`
- **Local Web Timeline Viewer** — FastAPI-based read-only web UI
- **DeepSeek / OpenAI-compatible** — Auto-tracing for `chat.completions.create`
- **Safe serialization** — Automatic redaction of API keys, tokens, passwords; string truncation
- **46 tests**, linting (ruff), formatting (ruff), type checking (mypy), GitHub Actions CI

### Known Limitations

- APIs may change before v1.0
- Async tracing is not supported yet
- Web viewer is read-only
- Run replay is not implemented yet
- Visual diff in web viewer is not implemented yet
- No LangChain or other framework integrations yet
