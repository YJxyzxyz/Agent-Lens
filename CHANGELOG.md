# Changelog

All notable changes to AgentLens will be documented in this file.

## Unreleased

### Features

- **Async OpenAI-compatible tracing** — `instrument_openai_compatible` 同时 patch 同步 `Completions.create` 和异步 `AsyncCompletions.create`。`await client.chat.completions.create(...)` 会记录 `llm_call`，异步实现只 await 原始协程，不调用同步方法，也不阻塞事件循环。`instrument_deepseek()` 走同一条路径。
- **Streaming chat completions** — 同步和异步 `stream=True` 会包装返回的流，在流结束、提前停止或中途失败时写入一条 `llm_call` 或 `error`。记录 `duration_ms`、`ttft_ms`、`usage`（如果响应里有）和 `stream_completed`。
- **Async `@trace` / `@traced`** — 协程函数的 trace 上下文保持到 await 结束。任务取消时记录 `CancelledError` 并继续向外抛出。
- OpenAI-compatible 事件额外记录请求模型与 `response_model`，以及脱敏后的 endpoint（只有 host 和 path）。助手消息里的 tool call 只保留 id 和 name，`arguments` 写成 `[REDACTED]`。

0.1.0 里「暂不支持异步追踪」的限制，对 `@trace` / `@traced` 和 OpenAI-compatible `chat.completions.create` 不再成立。其他异步入口（例如 `with_streaming_response`）还没有覆盖。

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
