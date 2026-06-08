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
  <a href="CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.1.0--alpha-orange" alt="Version"></a>
</p>

---

> ⚠️ **Alpha Release** — APIs 在 v1.0 前可能变更。欢迎反馈和贡献！

## 安装

```bash
pip install agentlens
```

或开发安装：

```bash
git clone https://github.com/YJxyzxyz/Agent-Lens.git
cd Agent-Lens
pip install -e ".[dev]"
```

可选依赖：

```bash
pip install -e ".[web]"         # Web Timeline Viewer
pip install -e ".[deepseek]"    # DeepSeek 自动追踪
pip install -e ".[langchain]"   # LangChain callback
```

AI Agent 越来越复杂。AgentLens 像飞机的黑匣子，以最小侵入的方式记录每一步运行事件。

## 最短示例

```python
from agentlens import trace, traced, record_file_write

@traced("search", event_type="tool_call")
def search(query: str):
    return {"results": 3}

@trace("my-agent")
def main():
    search("RAG evaluation")
    record_file_write("report.md", content_preview="done")

main()
```

```bash
agentlens list && agentlens show <run_id>
agentlens view   # Web 查看器
```

## 核心功能

- 🎯 **`@trace`** + **`@traced`** 装饰器
- 🤖 **DeepSeek / OpenAI-compatible** 自动追踪
- 💾 **本地 JSONL 存储**
- 🖥️ **CLI**（list / show / inspect / diff / view）
- 🌐 **Web Timeline Viewer** — run dashboard, event timeline, visual diff

## 文档

| 文档 | 说明 |
|------|------|
| [Quick Start](docs/quickstart.md) | 安装与运行示例 |
| [DeepSeek 集成](docs/deepseek.md) | DeepSeek / OpenAI-compatible 自动追踪 |
| [LangChain 集成](docs/langchain.md) | LangChain callback handler |
| [通用函数追踪](docs/generic-tracing.md) | `@traced` 使用指南 |
| [Web Viewer](docs/web-viewer.md) | 本地 Web UI + Visual Diff |
| [Changelog](CHANGELOG.md) | 版本更新记录 |
| [Release Notes](RELEASE_NOTES.md) | v0.1.0-alpha 发布说明 |

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

## DeepSeek / OpenAI-compatible

一行集成，自动追踪 live API 调用。详见 [DeepSeek 集成指南](docs/deepseek.md)。

## `@traced` 通用追踪

无需特定 SDK，追踪任意 Python 函数。详见 [通用函数追踪](docs/generic-tracing.md)。

## Web Timeline Viewer

本地只读 Web UI。详见 [Web Viewer 文档](docs/web-viewer.md)。

```bash
pip install -e ".[web]"
agentlens view
```

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
