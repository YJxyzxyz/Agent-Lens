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
agentlens tree <run_id>   # 按 parent_event_id 缩进的事件树
agentlens view            # Web 查看器
```

## 核心功能

- 🎯 **`@trace`** + **`@traced`** 装饰器
- 🤖 **DeepSeek / OpenAI-compatible** 自动追踪（同步与异步 `chat.completions.create`，含 streaming）
- 💾 **本地 JSONL 存储**
- 🌳 **事件树** — 事件带 `parent_event_id`，`agentlens tree <run_id>` 按父子关系缩进打印
- 🔗 **LangChain Callback** — `LangChainCallbackHandler`（`AgentLensCallbackHandler` 的别名）继承 `BaseCallbackHandler`
- 🖥️ **CLI**（list / show / tree / inspect / diff / view）
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

## 事件树

每条事件都有 `parent_event_id`，指向同一次 run 里的父事件。根事件（例如 `run_start`）是 `null`。这个字段写在该 run 的 JSONL 里，之后可以按 id 把树还原出来，不依赖父事件一定写在子事件前面。

父子关系只在当前 run 内用 `contextvars` 传递：

- `@trace` 写入 `run_start` 之后，把该事件设为当前父事件。这次 run 里直接记录的事件，包括 `run_end`、错误，以及没有包在 `@traced` 里的 `record_*`，都以它为父事件。
- `@traced` 在函数执行期间把自身的事件 id 设为当前父事件，函数内部再记录的事件成为它的子事件。函数结束后恢复原来的父事件。
- 开始一次新的 `@trace` 会清空父事件上下文。外层 run 的父事件不会进到另一次 run。
- `record_event(..., parent_event_id=...)` 可以显式指定父事件。传入 `None` 表示这条事件是根。不传则使用当前上下文。`parent_id` 仍可用，含义相同。

OpenAI-compatible / DeepSeek 自动追踪在**调用开始时**捕获当时的父事件。流式响应即使等到 trace 上下文结束后才读完，仍然挂在发起调用时的父事件上，不会改挂到之后的 run。

```bash
agentlens tree <run_id>
agentlens tree <run_id> --base-dir /path/to/runs
```

`tree` 不是 `view`，也不会给 `show` 增加 `--tree`。`show` 仍按记录顺序打印线性时间线，`view` 仍启动本地 Web 查看器。

缺失父事件时命令不丢事件，也不失败：

- `parent_event_id` 为空的事件是正常的根，打印在树的前面。
- `parent_event_id` 在这次 run 里不存在时，该事件和它的子树打印在顶层，事件行末尾标记 `[missing parent: id]`。
- 同一个缺失父 id 的事件分在一组，不同的缺失父 id 各自成组，组之间空一行。
- 子树里父事件还在的后代继续缩进在该事件下面，不再重复标记。
- 树的最后一行是摘要：`N orphans, M missing parents`。`N` 是孤儿事件数（不含它下面父事件仍在的后代），`M` 是不同缺失父 id 的数量。
- 一棵完整的树没有 `[missing parent: ...]`，摘要是 `0 orphans, 0 missing parents`。

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

## LangChain

`LangChainCallbackHandler` 与 `AgentLensCallbackHandler` 是同一个类。安装了 `langchain-core` 时它继承 LangChain 的 `BaseCallbackHandler`，可以直接放进 Runnable 的 `callbacks`。没安装时这个类退化为普通对象，`import agentlens.integrations.langchain` 仍然成功；创建实例会提示安装 `agentlens[langchain]`。

`serialized` 为 `None`（例如 `RunnableLambda`）时不会抛出 `AttributeError`。事件名回退为 `langchain.llm`、`langchain.chain`、`langchain.tool`。`serialized` 里如果带了 model 或 name，仍使用那些名字。

```python
from agentlens import trace
from agentlens.integrations.langchain import LangChainCallbackHandler

handler = LangChainCallbackHandler()

@trace("langchain-demo")
def run():
    return chain.invoke({"question": "..."}, config={"callbacks": [handler]})

run()
```

详见 [LangChain 集成](docs/langchain.md)。

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
- [x] 事件树 — `parent_event_id`、run 内 contextvar、`agentlens tree`
- [x] LangChain Callback — `LangChainCallbackHandler` 继承 `BaseCallbackHandler`；`serialized` 为 `None` 时回退到默认事件名
- [ ] **v0.2** — 更多 provider 集成
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
