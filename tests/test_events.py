"""TraceEvent 模型测试。"""

from datetime import datetime, timezone

from agentlens.events import TraceEvent


class TestTraceEvent:
    """TraceEvent 创建与字段测试。"""

    def test_create_minimal_event(self) -> None:
        """可以创建最小字段的 TraceEvent。"""
        event = TraceEvent(
            run_id="run_test_001",
            type="log",
            name="hello",
        )
        assert event.run_id == "run_test_001"
        assert event.type == "log"
        assert event.name == "hello"
        assert event.id  # 自动生成
        assert isinstance(event.started_at, datetime)
        assert event.metadata == {}
        assert event.error is None

    def test_create_full_event(self) -> None:
        """可以创建包含所有可选字段的 TraceEvent。"""
        now = datetime.now(timezone.utc)
        event = TraceEvent(
            run_id="run_test_002",
            parent_id="evt_abc",
            type="llm_call",
            name="gpt-4.1",
            input={"messages": [{"role": "user", "content": "hi"}]},
            output={"choices": [{"message": {"content": "hello"}}]},
            metadata={"tokens": 42},
            started_at=now,
            ended_at=now,
            error=None,
        )
        assert event.run_id == "run_test_002"
        assert event.parent_id == "evt_abc"
        assert event.type == "llm_call"
        assert event.name == "gpt-4.1"
        assert event.input == {"messages": [{"role": "user", "content": "hi"}]}
        assert event.output == {"choices": [{"message": {"content": "hello"}}]}
        assert event.metadata == {"tokens": 42}
        assert event.error is None

    def test_event_serialization(self) -> None:
        """TraceEvent 可以正确序列化和反序列化。"""
        event = TraceEvent(
            run_id="run_test_003",
            type="tool_call",
            name="search",
            input={"q": "test"},
            output={"results": []},
        )
        json_str = event.model_dump_json()
        restored = TraceEvent.model_validate_json(json_str)
        assert restored.run_id == event.run_id
        assert restored.type == event.type
        assert restored.name == event.name
        assert restored.input == event.input
        assert restored.output == event.output

    def test_error_event(self) -> None:
        """可以创建 error 类型事件并包含错误信息。"""
        event = TraceEvent(
            run_id="run_test_004",
            type="error",
            name="main",
            error="ValueError: something went wrong",
        )
        assert event.type == "error"
        assert event.error == "ValueError: something went wrong"
