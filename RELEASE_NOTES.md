# AgentLens v0.1.0-alpha

**Local flight recorder for AI agents.**

🔍 AgentLens 是 AI Agent 的黑匣子 — 以最小侵入的方式记录 Agent 的每一步运行事件，让你可以追踪、回放和调试 Agent 行为。全部本地运行，零云依赖。

---

## 核心功能

- 🎯 **`@trace`** — 一行装饰器自动记录 run 生命周期
- 📝 **`@traced`** — 追踪任意 Python 函数作为 Agent 步骤
- 🤖 **DeepSeek / OpenAI-compatible** — 自动追踪 `chat.completions.create`，API key 自动脱敏
- 💾 **JSONL 本地存储** — `.agentlens/runs/`，零云依赖
- 🖥️ **CLI** — `list`, `show`, `inspect`, `diff`, `view`
- 🌐 **Web Timeline Viewer** — 本地只读 Web UI

---

## 安装

```bash
pip install agentlens
# 或开发安装
git clone https://github.com/YJxyzxyz/Agent-Lens.git
cd Agent-Lens
pip install -e ".[dev]"
```

Web viewer 额外依赖: `pip install -e ".[web]"`
DeepSeek 额外依赖: `pip install -e ".[deepseek]"`

---

## 快速示例

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
# 查看追踪结果
agentlens list
agentlens show <run_id>
agentlens view
```

---

## 安全提醒

⚠️ trace 数据可能包含 LLM 输入输出、工具参数等敏感信息。
数据默认存储在本地 `.agentlens/runs/`，已被 `.gitignore` 排除。
**请勿提交包含敏感信息的 trace 文件到 Git。**

---

## 已知限制

- API 在 v1.0 前可能变更
- 暂不支持异步追踪
- Web viewer 为只读
- 暂不支持 run replay
- 暂不支持可视化 diff

---

## 反馈

- GitHub Issues: https://github.com/YJxyzxyz/Agent-Lens/issues
- 文档: https://github.com/YJxyzxyz/Agent-Lens/tree/main/docs
