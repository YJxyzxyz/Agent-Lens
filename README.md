<!--
  AgentLens — The open source flight recorder for AI agents.
-->
<p align="center">
  <h1 align="center">🔍 AgentLens</h1>
  <p align="center">
    <strong>The open source flight recorder for AI agents.</strong>
    <br/>
    AI Agent 的黑匣子 — 记录每一步，随时回放与调试。
  </p>
</p>

<p align="center">
  <a href="https://github.com/YJxyzxyz/Agent-Lens/actions"><img src="https://github.com/YJxyzxyz/Agent-Lens/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/agentlens"><img src="https://img.shields.io/pypi/v/agentlens" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
</p>

---

## 为什么需要 AgentLens？

AI Agent 越来越复杂：多轮 LLM 调用、工具调用链、文件操作……当 Agent 行为不符合预期时，你很难知道**它到底做了什么**。

AgentLens 像飞机的黑匣子一样，以最小侵入的方式记录 Agent 的每一步运行事件，
让你可以**追踪、回放和调试** Agent 的行为 — 全部本地运行，零云依赖。

## 核心功能

- 🎯 **`@trace` 一行装饰** — 包裹任何函数，自动记录运行生命周期
- 📝 **9 种事件类型** — `run_start`、`run_end`、`llm_call`、`tool_call`、`file_read`、`file_write`、`browser_action`、`error`、`log`
- 💾 **本地 JSONL 存储** — 数据完全在本地 `.agentlens/runs/`，无需任何云服务
- 🖥️ **CLI 工具** — `list` / `show` / `inspect` / `diff` 快速查看和对比
- 🔒 **并发安全** — 基于 `contextvars` 的上下文隔离

## 快速开始

```bash
pip install agentlens
```

```python
from agentlens import trace, record_llm_call, record_tool_call, record_log

@trace("my-agent")
def main():
    record_log("Agent started")
    record_llm_call(
        model="gpt-4.1",
        input="Plan a research task",
        output="I should search first."
    )
    record_tool_call(
        name="search_web",
        input={"query": "RAG evaluation"},
        output={"results": 3}
    )
    record_log("Agent finished")

main()
```

运行后，追踪数据自动保存到 `.agentlens/runs/`。

## CLI 示例

```bash
$ agentlens list
           AgentLens Runs
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃ Run ID                       ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ run_20260607_124820_ad2c5ef4 │
└───┴──────────────────────────────┘

$ agentlens show run_20260607_124820_ad2c5ef4
  [run_start] simple-agent
  [log]       Agent started
  [llm_call]  gpt-4.1
  [tool_call] search_web
  [run_end]   simple-agent
```

## 事件类型

| 事件类型 | 说明 | 示例 |
|----------|------|------|
| `run_start` | 运行开始 | Agent 启动 |
| `run_end` | 运行结束 | Agent 正常完成 |
| `llm_call` | LLM 调用 | 调用 GPT-4 |
| `tool_call` | 工具调用 | 搜索、计算 |
| `file_read` | 文件读取 | 读取配置 |
| `file_write` | 文件写入 | 保存结果 |
| `browser_action` | 浏览器操作 | 点击、导航 |
| `error` | 错误 | 异常发生 |
| `log` | 日志 | 自定义消息 |

## DeepSeek 集成

AgentLens 通过 OpenAI-compatible API 自动追踪 DeepSeek 调用。

```bash
pip install -e ".[deepseek]"
```

```python
from openai import OpenAI
from agentlens import trace
from agentlens.integrations.deepseek import instrument_deepseek

instrument_deepseek()

@trace("deepseek-demo")
def main():
    client = OpenAI(api_key="sk-...", base_url="https://api.deepseek.com")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hello"}],
    )
    print(response.choices[0].message.content)

main()
```

每次 `chat.completions.create` 调用会自动记录 `llm_call` 事件，包含 model、messages、usage 等信息（API key 自动脱敏）。

> ⚠️ **安全提醒**：不要提交 `.agentlens/runs` 到 Git，trace 文件可能包含对话内容。

## Generic Function Tracing

AgentLens 不依赖 DeepSeek、OpenAI、LangChain 或任何特定模型 provider。
你可以用 `@traced` 追踪任意 Python 函数，作为 Agent 运行中的一步。

```python
from agentlens import trace, traced, record_file_write

@traced("search_web", event_type="tool_call")
def search_web(query: str):
    return {"results": 3}

@traced("summarize", event_type="llm_call")
def summarize(text: str):
    return "summary..."

@trace("my-agent")
def main():
    results = search_web("RAG benchmark")
    answer = summarize(str(results))
    record_file_write("report.md", content_preview=answer)
    return answer

main()
```

`@traced` 自动捕获参数和返回值，脱敏敏感字段，记录执行耗时。

## Web Timeline Viewer

AgentLens 内置本地 Web 查看器，在浏览器中浏览 trace 数据。

```bash
pip install -e ".[web]"
agentlens view
```

启动后打开 http://127.0.0.1:8765 即可查看所有 run 的事件时间线。
支持自定义地址和端口：`agentlens view --host 0.0.0.0 --port 8080`。

> 🔒 仅本地只读访问，不向任何远程服务发送数据。

## 路线图

- [x] **v0.1** — 基础 tracing / JSONL 存储 / CLI / DeepSeek 集成 / Web Timeline Viewer
- [ ] **v0.2** — LangChain Callback / 事件树形关联 / 更多 provider 集成
- [ ] **v0.3** — 统计摘要 / JSON/CSV 导出 / diff 增强
- [ ] **v0.4** — Run Replay / 回归测试
- [ ] **v1.0** — 插件系统 / 性能优化 / 文档站点

## 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发环境搭建和 PR 流程。

## 安全提醒

⚠️ trace 数据可能包含 LLM 输入输出、工具参数等敏感信息。
数据默认存储在本地 `.agentlens/runs/`，已被 `.gitignore` 排除。
**请勿提交包含敏感信息的 trace 文件到 Git。**
详见 [SECURITY.md](SECURITY.md)。

## License

MIT
