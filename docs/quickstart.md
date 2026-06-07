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

# 查看事件时间线
agentlens show <run_id>

# 查看完整 JSON
agentlens inspect <run_id>

# 启动 Web 查看器
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
- [通用函数追踪](generic-tracing.md)
- [Web Timeline Viewer](web-viewer.md)
