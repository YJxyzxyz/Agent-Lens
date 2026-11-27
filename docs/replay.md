# 回放和回归检查

这两项从已经写入 `.agentlens/runs/*.jsonl` 的事件推导结果。它们不修改 JSONL，也不给 `TraceEvent` 增加字段。

回放读取记录顺序里的 type、name、input、output、error。它不重新执行 agent，不调用 LLM 或工具，也不向 provider 发请求。

```bash
agentlens replay <run_id>
agentlens replay <run_id> --calls
agentlens regression <baseline> <candidate>
```

`--base-dir` 与其他命令一样，用来指定存储目录。`--output` 把结果写入文件；省略时打印到标准输出。找不到 run 时退出码是 1，格式或对齐方式不认识时退出码是 2。

## replay

```bash
agentlens replay <run_id>
agentlens replay <run_id> --format json --output replay.json
agentlens replay <run_id> --calls
```

文本按 JSONL 的顺序打印每一步。编号从 `#1` 开始，对应事件在文件里的位置。某一步没有 input、output 或 error 时，对应的行省略。空字符串和缺失的 error 都视为没有 error。

标题后面的毫秒数是这一步自己的 `started_at` 到 `ended_at`。缺任一侧就不显示。这个数只用于阅读，回归检查不比较它。`parent=` 是记下的 `parent_event_id`。父 id 在本次 run 里不存在时，这一步仍然留在原位置，回放不因此丢掉事件。

`--calls` 只留下这些类型：

| 类型 | 是否进入调用回放 |
|------|------------------|
| `llm_call`、`tool_call`、`file_read`、`file_write`、`browser_action` | 是 |
| `run_start`、`run_end`、`log`、`error` | 否 |

过滤之后，步骤编号仍是它在完整记录里的编号。JSON 里的 `event_count` 是完整步数，`step_count` 是这份输出里的步数。

JSON 是一份派生文档，不是新的存储格式。每一步包含 `index`、`event_id`、`parent_event_id`、`type`、`name`、`input`、`output`、`error`、`duration_ms`。没有 metadata。脱敏后的 `[REDACTED]` 会原样出现，回放不会把它还原。

```python
from agentlens import replay_run

replay = replay_run(events, run_id="run-123")
```

文本和 JSON 分别是 `agentlens.replay.format_replay` 与 `agentlens.replay.replay_to_json`。

## recorded_calls

`recorded_calls` 把同一次记录里的调用做成一条磁带，供测试按顺序取出当时记下的结果。

```python
from agentlens import recorded_calls

tape = recorded_calls(events)
step = tape.take("tool_call", "search", {"query": "RAG"})
assert step.output == {"results": 3}
tape.assert_finished()
```

`take` 只接受下一条调用。type 或 name 不一致，或者传入的 input 和记录不一致时，抛出 `ReplayError`，并且磁带不前进。不传 input 时只核对 type 和 name。对象的键顺序不同不算 input 差异。相同的调用出现多次时，按 JSONL 顺序依次给出。

`assert_finished()` 在还有未取出的调用时抛出 `ReplayError`。`peek()` 查看下一条，不取出。

磁带返回的是已记录的 output。它不调用原来的函数，也不发起请求。

## regression

```bash
agentlens regression <baseline> <candidate>
agentlens regression <baseline> <candidate> --align index
agentlens regression <baseline> <candidate> --format json --output report.json
agentlens regression <baseline> <candidate> --calls
```

第一个 run 是基线，第二个是候选。默认 `--align sequence`，与 `agentlens diff` 使用同一种扁平序列对齐：

1. 用 `(type, name)` 对齐。某一次 run 中间多了一步时，后面能对上的事件仍算相同。
2. 对上的事件再比较 `type`、`name`、`error`、`input`、`output`。
3. 空字符串和缺失的 `error` 视为相同。`input` / `output` 里对象的键顺序不同不算差异。
4. 文本输出省略相同行，并列出每一处差异。

下面这些字段不参与检查，因为两次运行里它们通常本来就不同：

- `id`
- `parent_event_id`，以及事件树里的父子位置
- `started_at` / `ended_at`
- `metadata`（含 `duration_ms`、`usage`、token）

`--calls` 先丢掉 `REPLAY_CALL_TYPES` 以外的事件，再做同一种对齐。多出来的 log 或 error 不会让这次检查失败。默认比较全部事件，因此新的 `error` 事件会使检查失败。

退出码：

| 情况 | 退出码 |
|------|--------|
| 比较字段一致 | 0 |
| 候选与基线不一致，或找不到 run | 1 |
| 对齐方式或输出格式不认识 | 2 |

`agentlens diff` 在有差异时仍然退出 0。回归检查把同一种差异当成失败。

JSON 里 `passed` 是这次检查的结果。`diff` 的结构与 `diff` 命令的 JSON 相同：`only_in_left` 是仅基线，`only_in_right` 是仅候选。`calls_only` 为真时，`diff` 里的数量是过滤之后的调用数。

```python
from agentlens import check_regression
from agentlens.regression import format_regression

result = check_regression(baseline_events, candidate_events)
assert result.passed, format_regression(result)
```

## 这一版还没有做的事

- 不重新执行已记录的 LLM 或工具调用，也不把记录注入真实客户端。
- Web Viewer 没有逐步回放。
- 回归不做树形 diff。父子关系只显示在回放里，不参与通过或失败。
- 不比较 metadata、耗时和 token。那仍是 v0.3 里还没做的部分。
