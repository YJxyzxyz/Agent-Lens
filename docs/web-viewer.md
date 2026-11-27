# Web Timeline Viewer

AgentLens 内置本地 Web UI，在浏览器中浏览 trace 数据。

## 安装

```bash
pip install -e ".[web]"
```

## 启动

```bash
agentlens view
```

打开 http://127.0.0.1:8765

按父子关系缩进查看同一次 run 用命令行 `agentlens tree <run_id>`。`agentlens view` 仍然是这里的 Web 时间线，不会改成树状命令。

## 选项

```bash
# 自定义端口
agentlens view --port 8080

# 绑定所有网络接口
agentlens view --host 0.0.0.0

# 指定 trace 数据目录
agentlens view --base-dir /path/to/runs
```

## 页面功能

- **首页** — 所有 run 列表，显示名称、时间、事件数、错误状态
- **详情页** — 事件时间线，按类型着色。顶部显示事件数、错误数、耗时、LLM / 工具次数和 token，数字来自 `agentlens stats` 使用的同一份摘要
- **展开/折叠** — 点击事件查看 input / output / metadata JSON

## Visual Diff

对比两次 Agent 运行的事件差异：

1. 启动 `agentlens view`
2. 在首页勾选两个 run 的 checkbox
3. 点击 **Compare selected**
4. 或直接访问 URL：`http://127.0.0.1:8765/diff?left=<run_id>&right=<run_id>`

Diff 页面和 `agentlens diff` 使用同一套比较：

- 先按事件的 type 和 name 做序列对齐。中间多出来的一步不会把后面的事件整段标成不同
- 再比较 error、input、output。type/name 相同但输入输出不同时，行上会标出字段名
- 不比较 id、parent_event_id、时间戳和 metadata。耗时和 token 看详情页摘要或 `agentlens stats`
- 页面仍显示两侧事件数、第一处差异，以及相同 / 不同 / 缺失的计数
- 明细默认收起。点击一行展开 input/output/metadata，再点一次收起

## 安全说明

- 🔒 仅本地只读访问
- 🚫 不向任何远程服务发送数据
- 🚫 不提供删除、编辑、上传功能
- 🛡️ 所有用户数据经过 HTML escape 防 XSS
- 📦 无外部 CDN 依赖

## 截图占位符

> _截图将添加到后续版本中。_
> _欢迎贡献截图 PR！_
