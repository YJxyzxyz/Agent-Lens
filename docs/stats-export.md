# 统计摘要、JSON/CSV 导出、diff

这三项都从已经写入 `.agentlens/runs/*.jsonl` 的事件推导结果。它们不修改 JSONL，也不给 `TraceEvent` 增加字段。

```bash
agentlens stats <run_id>
agentlens stats
agentlens export <run_id> --format json --output run.json
agentlens export <run_id> --format csv --output run.csv
agentlens diff <run_a> <run_b>
```

`--base-dir` 与其他命令一样，用来指定存储目录。`--output` 把结果写入文件；省略时打印到标准输出。找不到 run 时退出码是 1，格式或对齐方式不认识时退出码是 2。有差异的 diff 仍然退出 0。

## stats

```bash
agentlens stats <run_id>
agentlens stats <run_id> --format json
agentlens stats --format csv --output stats.csv
```

省略 run id 时，每个 run 一行。单个 run 的 JSON 是一个对象，全部 run 的 JSON 是一个数组。

文本摘要包含：

| 项 | 来源 |
|----|------|
| 名称 | 第一条 `run_start` 的 `name`，没有则是 `unknown` |
| 各类型次数 | 事件的 `type`。`Errors` 只数 `type == "error"` |
| 耗时 | 第一条 `run_start` 到最后一条 `run_end`。没有 `run_end` 时，用各事件 `ended_at` 的最大值。只有时间点、没有结束时间时，耗时是 `-` |
| 工具名 | `tool_call` 的 `name`，去重后按字母排序 |
| Token | `metadata.usage` 里的 `prompt_tokens` / `input_tokens`、`completion_tokens` / `output_tokens`、`total_tokens`。某一侧没记下就是 `-`，不是 0 |
| 孤儿 | 与 `agentlens tree` 相同：父 id 不在本次 run 里的事件数，以及不同的缺失父 id 数 |

一条事件如果同时有 prompt 和 completion、但没有 total，这条的 total 用两者之和。`metadata.tokens` 只在该条事件还没有 total 时计入 total。布尔值不算 token。

库函数：

```python
from agentlens import summarize_run

summary = summarize_run(events, run_id="run-123")
```

## export

```bash
agentlens export <run_id> --format json
agentlens export <run_id> --format csv --output run.csv
```

JSON 是一个数组。每个对象等于 `TraceEvent.model_dump(mode="json")`，因此和 JSONL 里对应的一行是同一组字段，包括 `parent_event_id`。这不是把存储改成单个 JSON 文件；`.jsonl` 仍然是记录格式。

CSV 列：

```text
id, run_id, parent_event_id, type, name, started_at, ended_at,
duration_ms, error, input, output, metadata
```

`duration_ms` 由该事件自己的 `started_at` 和 `ended_at` 算出，缺任一侧就留空。`input`、`output`、`metadata` 是单元格里的 JSON，对象的键按字母排序。

```python
from agentlens import events_to_csv, events_to_json
```

## diff

```bash
agentlens diff <run_a> <run_b>
agentlens diff <run_a> <run_b> --align index
agentlens diff <run_a> <run_b> --format json --output diff.json
```

默认 `--align sequence`：

1. 用 `(type, name)` 做序列对齐。某一次 run 中间多了一步时，后面能对上的事件仍算相同。
2. 对上的事件再比较 `type`、`name`、`error`、`input`、`output`。
3. 空字符串和缺失的 `error` 视为相同。`input` / `output` 里对象的键顺序不同不算差异。
4. 文本输出省略相同行，并列出每一处差异，不会停在第一处。

`--align index` 按记录位置逐条比较，多出来的尾部算仅左侧或仅右侧。

下面这些字段不参与 diff，因为两次运行里它们通常本来就不同：

- `id`
- `parent_event_id`
- `started_at` / `ended_at`
- `metadata`（含 `duration_ms`、`usage`、token）

耗时和 token 用 `agentlens stats` 看。Web Viewer 的 `/diff` 调用同一个 `diff_events`。

状态对应关系：

| 文本 | JSON `status` | 含义 |
|------|----------------|------|
| 不同 | `changed` | 两侧都有这一行，但比较字段不同 |
| 仅左侧 | `missing_right` | 只在左侧 run 里 |
| 仅右侧 | `missing_left` | 只在右侧 run 里 |

`first_difference` 是对齐结果里第一处差异的 0-based 行号。文本里的 `#2` 是同一行的 1-based 编号。

```python
from agentlens import diff_events

result = diff_events(left_events, right_events, align="sequence")
```

## 这一版还没有做的事

- 不比较 metadata，也不把耗时或 token 的数值差写进 diff。
- 没有图表，没有独立的统计页面，也没有 HTML 导出。
- 回放和回归检查见 [回放 / 回归](replay.md)。`diff` 有差异时仍然退出 0。
