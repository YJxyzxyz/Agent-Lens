# Roadmap Issues

以下是建议创建到 GitHub Issues 的功能条目。每项包含标题、类型、描述和验收标准。

---

### 1. Add visual run diff in Web Viewer

- **Type**: feature
- **Description**: 在 Web Timeline Viewer 中增加可视化 run diff 功能，让用户可以并排对比两次运行的差异。
- **Acceptance Criteria**:
  - 在 Web UI 中选择两个 run 进行对比
  - 高亮显示事件 type/name 不同的位置
  - 显示事件数量差异

### 2. Add LangChain callback handler

- **Type**: feature
- **Description**: 实现 LangChain callback handler，让 LangChain 用户无需修改代码即可自动追踪所有 chain / tool / LLM 调用。
- **Acceptance Criteria**:
  - `from agentlens.integrations.langchain import LangChainCallbackHandler`
  - 与现有 trace 上下文兼容
  - 记录 on_llm_start/end、on_tool_start/end、on_chain_start/end

### 3. Add async OpenAI-compatible tracing

- **Type**: feature
- **Description**: 支持 `AsyncOpenAI` 的自动追踪，覆盖 `await client.chat.completions.create(...)`。
- **Acceptance Criteria**:
  - `instrument_openai_compatible` 同时 patch 同步和异步方法
  - 异步调用时正确记录 llm_call 事件
  - 不阻塞 event loop

### 4. Add trace export as standalone HTML

- **Type**: feature
- **Description**: 支持将一次 run 导出为独立的 HTML 文件，方便分享（提醒用户脱敏）。
- **Acceptance Criteria**:
  - `agentlens export <run_id> --format html --output report.html`
  - HTML 文件内联所有 CSS/JS，可离线打开
  - 包含安全提醒

### 5. Add configurable redaction rules

- **Type**: feature
- **Description**: 允许用户自定义脱敏规则，添加额外的敏感字段名。
- **Acceptance Criteria**:
  - 支持环境变量或配置文件指定额外敏感 key
  - 支持自定义 redaction 函数
  - 不影响现有默认规则

### 6. Add Ollama example

- **Type**: example
- **Description**: 创建 Ollama 本地模型的使用示例，与 OpenAI-compatible integration 配合。
- **Acceptance Criteria**:
  - `examples/ollama_agent.py`
  - 展示使用 Ollama 本地模型的自动追踪

### 7. Add pytest plugin for agent regression tests

- **Type**: feature
- **Description**: 提供 pytest fixture，支持基于 trace 数据的回归测试。
- **Acceptance Criteria**:
  - `def test_agent(agentlens_run): ...` fixture
  - 可以断言 run 中不包含 error 事件
  - 可以断言 llm_call 次数、tool_call 名称
  - 可以对比两次运行的输出一致性

### 8. Add screenshot assets for README

- **Type**: docs
- **Description**: 为 README 和文档添加截图，展示 CLI 和 Web Viewer 的实际效果。
- **Acceptance Criteria**:
  - CLI list/show/inspect 截图
  - Web Viewer 首页和详情页截图
  - 截图放在 `docs/assets/` 目录
