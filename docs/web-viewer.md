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
- **逐步回放** — 同一详情页上的 Previous step / Next step。已经看过的事件留在时间线上，当前步高亮，计数为「第 N / 共 M 步」
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

## 逐步回放

逐步回放是 run 详情页上的一种查看方式，不是单独的页面，也没有新的路径。

1. 打开一次 run。页面列出 JSONL 里的全部事件，顺序与 `agentlens replay` 相同。
2. 点击 **Next step** 从第一条开始。时间线上先出现这一条，并用边框高亮它。计数显示「第 1 / 共 M 步」。
3. 再点 **Next step**，下一条追加到时间线末尾，高亮移到新的一条，计数变成「第 N / 共 M 步」。已经看过的事件留在原处，不是每次只留下当前一条。页面上没有单独的「当前」标记。
4. **Previous step** 把高亮移回上一条。已经出现在时间线上的事件仍然留着。
5. 第一条没有上一步，最后一条没有下一步。用浏览器后退，或再次打开不带步骤的详情页地址，可以回到没有高亮的完整时间线。

上一步和下一步只移动一条。页面上没有步骤输入框，也没有事件类型过滤。

- 只读已经记下的 JSONL。不重新执行 LLM 或工具调用，不发起请求，也不把记下的输出注入客户端或模型。
- 父事件缺失，或父事件比子事件更晚写入时，事件仍按文件里的原顺序出现。不按事件树重排，也不按时间重排。
- `agentlens diff` 和 `agentlens regression` 不因这个页面改变。

## 安全说明

- 🔒 仅本地只读访问
- 🚫 不向任何远程服务发送数据
- 🚫 不提供删除、编辑、上传功能
- 🛡️ 所有用户数据经过 HTML escape 防 XSS
- 📦 无外部 CDN 依赖

## 截图占位符

> _截图将添加到后续版本中。_
> _欢迎贡献截图 PR！_
