# Quick Start

## 安装

```bash
git clone https://github.com/YJxyzxyz/Agent-Lens.git
cd Agent-Lens
pip install -e ".[dev]"
```

## 运行示例

AgentLens 提供多个可直接运行的示例：

```bash
# 通用追踪示例（无需 API key）
python examples/generic_agent.py

# 基础追踪示例
python examples/simple_agent.py
```

## 查看追踪结果

运行示例后，追踪数据保存在 `.agentlens/runs/`：

```bash
# 列出所有 run
agentlens list

# 查看事件时间线（线性，按记录顺序）
agentlens show <run_id>

# 按 parent_event_id 缩进打印事件树
agentlens tree <run_id>

# 查看完整 JSON
agentlens inspect <run_id>

# 统计摘要（文本、JSON 或 CSV；不修改 JSONL）
agentlens stats <run_id>
agentlens stats --format csv --output stats.csv

# 导出事件。JSON 与 JSONL 的单行对象相同，CSV 多一列 duration_ms
agentlens export <run_id> --format json --output run.json
agentlens export <run_id> --format csv --output run.csv

# 对比两次 run。默认按 type/name 对齐，并比较 error、input、output
agentlens diff <run_a> <run_b>

# 按记录顺序回放一次 run，或用基线做回归检查。两者都不重新执行
agentlens replay <run_id>
agentlens regression <baseline> <candidate>

# 启动 Web 查看器（不是事件树；事件树用上面的 tree）
pip install -e ".[web]"
agentlens view
```

## 项目结构

```
.agentlens/runs/    # trace 数据（已 gitignore）
agentlens/           # SDK 源码
examples/            # 可运行示例
tests/               # 测试
docs/                # 文档
```

## 下一步

- [DeepSeek 集成指南](deepseek.md)
- [LangChain 集成](langchain.md)
- [通用函数追踪](generic-tracing.md)
- [统计 / 导出 / diff](stats-export.md)
- [回放 / 回归](replay.md)
- [进程内插件](plugins.md)
- [Web Timeline Viewer](web-viewer.md)
