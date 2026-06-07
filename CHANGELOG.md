# Changelog

All notable changes to AgentLens will be documented in this file.

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
