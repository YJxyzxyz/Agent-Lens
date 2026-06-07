# AgentLens 🔍

> **AI Agent 的黑匣子** — 轻量级 Agent 运行追踪、回放和调试工具。

AgentLens 以最小侵入的方式记录 AI Agent 每一步运行事件，帮助你理解、调试和优化 Agent 行为。

---

## 安装

```bash
# 克隆项目
git clone https://github.com/your-org/agentlens.git
cd agentlens

# 创建虚拟环境（推荐）
conda create -n agentlens python=3.11 -y
conda activate agentlens

# 安装（开发模式）
pip install -e ".[dev]"
```

---

## 快速开始

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

if __name__ == "__main__":
    main()
```

运行后，追踪数据会自动保存到 `.agentlens/runs/` 目录下。

---

## CLI 使用

```bash
# 列出所有追踪记录
agentlens list

# 查看事件时间线（简洁格式）
agentlens show <run_id>

# 查看完整 JSON 事件
agentlens inspect <run_id>

# 对比两次运行
agentlens diff <run_a> <run_b>
```

---

## MVP 功能

- ✅ **事件追踪** — 支持 `run_start`、`run_end`、`llm_call`、`tool_call`、`file_read`、`file_write`、`browser_action`、`error`、`log` 共 9 种事件类型
- ✅ **`@trace` 装饰器** — 一行代码包裹函数，自动记录运行生命周期
- ✅ **便捷记录函数** — `record_llm_call`、`record_tool_call`、`record_log` 等开箱即用
- ✅ **本地 JSONL 存储** — 零依赖云服务，数据完全在本地
- ✅ **CLI 工具** — `list` / `show` / `inspect` / `diff` 四个命令快速查看和对比
- ✅ **并发安全** — 基于 `contextvars` 的上下文隔离
- ✅ **完整测试** — pytest 覆盖核心功能

---

## 项目结构

```
agentlens/
├── agentlens/
│   ├── __init__.py      # 包导出
│   ├── events.py        # 事件模型 (Pydantic)
│   ├── storage.py       # JSONL 存储层
│   ├── context.py       # 上下文管理 (contextvars)
│   ├── tracer.py        # 追踪 API (装饰器 + 记录函数)
│   └── cli.py           # CLI (Typer)
├── tests/
│   ├── test_events.py
│   ├── test_storage.py
│   └── test_tracer.py
├── examples/
│   └── simple_agent.py
├── pyproject.toml
├── README.md
└── .gitignore
```

---

## Roadmap

### v0.2 — 集成增强
- [ ] OpenAI SDK 自动插桩（`chat.completions.create` 拦截）
- [ ] LangChain Callback Handler
- [ ] 事件 parent_id 树形关联

### v0.3 — 可视化与分析
- [ ] 本地 Web Timeline Viewer（单页 HTML）
- [ ] 事件统计摘要（LLM 调用次数、Token 消耗、延迟分布）
- [ ] 导出为 JSON / CSV

### v0.4 — 回放与回归
- [ ] Run Replay（基于录制的事件重新执行）
- [ ] 回归测试（对比两次运行的输出一致性）
- [ ] 差异可视化（diff 增强）

### v1.0 — 生产就绪
- [ ] 插件系统（自定义事件类型、自定义存储后端）
- [ ] 性能优化（批量写入、压缩存储）
- [ ] 文档站点

---

## 开发

```bash
# 运行测试
pytest

# 运行示例
python examples/simple_agent.py

# 查看追踪结果
agentlens list
agentlens show <run_id>
```

---

## License

MIT
