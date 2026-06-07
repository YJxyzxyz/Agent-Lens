# 贡献指南

感谢你对 AgentLens 的关注！我们欢迎所有形式的贡献。

## 开发环境

```bash
# 克隆仓库
git clone https://github.com/YJxyzxyz/Agent-Lens.git
cd Agent-Lens

# 创建虚拟环境
conda create -n agentlens python=3.11 -y
conda activate agentlens

# 安装开发依赖
pip install -e ".[dev]"
```

## 运行测试

```bash
pytest -v
```

## 代码质量

提交 PR 前请确保通过以下检查：

```bash
# 代码风格检查
ruff check .

# 格式化检查
ruff format --check .

# 类型检查
mypy agentlens
```

你也可以运行 `ruff format .` 自动格式化代码。

## 提交 Issue

- 使用 Bug Report 模板报告问题
- 使用 Feature Request 模板提议新功能
- 请勿在 issue 中粘贴包含敏感信息的 trace 数据

## 提交 PR

1. Fork 仓库并创建分支：`git checkout -b feat/your-feature`
2. 编写代码和测试
3. 确保所有检查通过
4. 提交 PR 到 `main` 分支，使用 PR 模板

## Good First Issues

如果你是第一次贡献，以下方向适合入门：

- 为现有函数补充更完善的 docstring
- 添加新的便捷记录函数（如 `record_file_read`）
- 改进 CLI 输出格式
- 编写更多测试用例
- 改进错误提示信息

## 项目结构

```
agentlens/          # 主包
  events.py         # Pydantic 事件模型
  storage.py        # JSONL 存储层
  context.py        # 上下文管理
  tracer.py         # 追踪 API
  cli.py            # CLI 工具
tests/              # 测试
examples/           # 示例
```

## 代码风格

- 使用 Python 3.10+ 语法
- 类型注解清晰
- 函数和类包含 docstring
- 保持实现简单，不过度设计
