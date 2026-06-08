"""LangChain callback handler 测试。

手动调用 callback 方法，不依赖真实 LangChain chain 或外部 LLM。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore


def _make_store_with_events(tmp_path: Path, events: list[TraceEvent]) -> JsonlTraceStore:
    store = JsonlTraceStore(base_dir=tmp_path / "runs")
    for ev in events:
        store.append_event(ev)
    return store


class TestLangChainHandlerErrors:
    """错误场景测试。"""

    def test_import_error_when_langchain_not_installed(self):
        """未安装 langchain-core 时实例化给出清晰错误。"""
        with mock.patch.dict(sys.modules, {"langchain_core": None}):
            from agentlens.integrations.langchain import AgentLensCallbackHandler

            with pytest.raises(ImportError, match="langchain-core"):
                AgentLensCallbackHandler()


class TestLangChainHandlerWithTrace:
    """在 trace 上下文中 handler 行为测试。"""

    def _handler_and_store(self, tmp_path):
        """创建 handler + store + trace 上下文。"""
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")
        return handler, store

    def test_on_llm_end_records_llm_call(self, tmp_path):
        """on_llm_start + on_llm_end 记录 llm_call 事件。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_001", store):
            handler.on_llm_start(
                {"kwargs": {"model": "gpt-4"}},
                ["Hello"],
                run_id="run-llm-1",
            )
            handler.on_llm_end(
                mock.MagicMock(),
                run_id="run-llm-1",
            )

        events = store.load_run("run_lc_001")
        llm_events = [e for e in events if e.type == "llm_call"]
        assert len(llm_events) == 1
        assert llm_events[0].name == "gpt-4"
        assert llm_events[0].metadata["provider"] == "langchain"
        assert "duration_ms" in llm_events[0].metadata

    def test_on_llm_error_records_error_and_clears_state(self, tmp_path):
        """on_llm_error 记录 error 并清理 state。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_002", store):
            handler.on_llm_start(
                {"kwargs": {"model": "gpt-4"}},
                ["Hello"],
                run_id="run-llm-err",
            )
            handler.on_llm_error(
                RuntimeError("timeout"),
                run_id="run-llm-err",
            )

        events = store.load_run("run_lc_002")
        error_events = [e for e in events if e.type == "error"]
        assert len(error_events) == 1
        assert "RuntimeError" in error_events[0].error
        # state 清理
        assert "run-llm-err" not in handler._runs  # noqa: SLF001

    def test_on_chain_end_records_tool_call(self, tmp_path):
        """on_chain_start + on_chain_end 记录 tool_call 事件。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_003", store):
            handler.on_chain_start(
                {"name": "MyChain"},
                {"question": "hi"},
                run_id="run-chain-1",
            )
            handler.on_chain_end(
                {"answer": "hello"},
                run_id="run-chain-1",
            )

        events = store.load_run("run_lc_003")
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].name == "MyChain"
        assert tool_events[0].metadata["provider"] == "langchain"

    def test_on_tool_end_records_tool_call(self, tmp_path):
        """on_tool_start + on_tool_end 记录 tool_call 事件。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_004", store):
            handler.on_tool_start(
                {"name": "search"},
                "query",
                run_id="run-tool-1",
            )
            handler.on_tool_end(
                {"results": 3},
                run_id="run-tool-1",
            )

        events = store.load_run("run_lc_004")
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].name == "search"

    def test_no_trace_context_no_crash(self):
        """没有 trace 上下文时 callback 不崩溃、不记录。"""
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        # 不应崩溃
        handler.on_llm_start({"kwargs": {"model": "x"}}, ["hi"], run_id="r1")
        handler.on_llm_end(mock.MagicMock(), run_id="r1")

    def test_sensitive_keys_redacted(self, tmp_path):
        """敏感字段被脱敏。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_005", store):
            handler.on_chain_start(
                {"name": "SensitiveChain"},
                {"api_key": "sk-secret", "query": "hi"},
                run_id="run-sens",
            )
            handler.on_chain_end(
                {"token": "bearer-xxx", "result": "ok"},
                run_id="run-sens",
            )

        events = store.load_run("run_lc_005")
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        e = tool_events[0]
        # api_key 在 input 中
        input_str = str(e.input)
        assert "[REDACTED]" in input_str or "api_key" not in input_str

    def test_duration_ms_present(self, tmp_path):
        """duration_ms 记录在 metadata 中。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_006", store):
            handler.on_tool_start(
                {"name": "timed"},
                "input",
                run_id="run-time",
            )
            handler.on_tool_end("output", run_id="run-time")

        events = store.load_run("run_lc_006")
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert "duration_ms" in tool_events[0].metadata

    def test_run_id_in_metadata(self, tmp_path):
        """run_id / parent_run_id 写入 metadata。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_007", store):
            handler.on_chain_start(
                {"name": "ParentChain"},
                {},
                run_id="parent-run",
                parent_run_id="grandparent-run",
            )
            handler.on_chain_end({}, run_id="parent-run")

        events = store.load_run("run_lc_007")
        tool_events = [e for e in events if e.type == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].metadata["run_id"] == "parent-run"
        assert tool_events[0].metadata["parent_run_id"] == "grandparent-run"

    def test_end_without_start_still_records(self, tmp_path):
        """start 信息缺失时 end 事件仍然能记录。"""
        from agentlens.context import set_current_trace
        from agentlens.integrations.langchain import AgentLensCallbackHandler

        handler = AgentLensCallbackHandler()
        store = JsonlTraceStore(base_dir=tmp_path / "runs")

        with set_current_trace("run_lc_008", store):
            # 没有 on_llm_start，直接 on_llm_end
            handler.on_llm_end(mock.MagicMock(), run_id="orphan-run")

        events = store.load_run("run_lc_008")
        llm_events = [e for e in events if e.type == "llm_call"]
        assert len(llm_events) == 1
        assert llm_events[0].name == "langchain.llm"
