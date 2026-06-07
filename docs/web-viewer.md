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
- **详情页** — 事件时间线，按类型着色
- **展开/折叠** — 点击事件查看 input / output / metadata JSON

## 安全说明

- 🔒 仅本地只读访问
- 🚫 不向任何远程服务发送数据
- 🚫 不提供删除、编辑、上传功能
- 🛡️ 所有用户数据经过 HTML escape 防 XSS
- 📦 无外部 CDN 依赖

## 截图占位符

> _截图将添加到后续版本中。_
> _欢迎贡献截图 PR！_
