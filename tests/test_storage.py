"""JsonlTraceStore 存储层测试。"""

import tempfile
from pathlib import Path

from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore


class TestJsonlTraceStore:
    """JSONL 存储的增删查测试。"""

    def test_append_and_load(self) -> None:
        """append_event 后 load_run 可以读取到事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            event = TraceEvent(run_id="run_001", type="log", name="test log")
            store.append_event(event)

            events = store.load_run("run_001")
            assert len(events) == 1
            assert events[0].run_id == "run_001"
            assert events[0].type == "log"
            assert events[0].name == "test log"

    def test_append_multiple_events(self) -> None:
        """可以向同一个 run 追加多个事件。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            for i in range(5):
                event = TraceEvent(run_id="run_002", type="log", name=f"log_{i}")
                store.append_event(event)

            events = store.load_run("run_002")
            assert len(events) == 5
            assert [e.name for e in events] == [f"log_{i}" for i in range(5)]

    def test_load_nonexistent_run(self) -> None:
        """读取不存在的 run 返回空列表。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))
            events = store.load_run("nonexistent")
            assert events == []

    def test_list_runs(self) -> None:
        """list_runs 可以列出所有 run_id。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonlTraceStore(base_dir=Path(tmpdir))

            store.append_event(TraceEvent(run_id="run_a", type="log", name="a"))
            store.append_event(TraceEvent(run_id="run_b", type="log", name="b"))
            store.append_event(TraceEvent(run_id="run_a", type="log", name="a2"))

            runs = store.list_runs()
            assert sorted(runs) == ["run_a", "run_b"]

    def test_directory_auto_created(self) -> None:
        """存储目录不存在时会自动创建。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "deeply" / "nested" / "runs"
            store = JsonlTraceStore(base_dir=base)
            store.append_event(TraceEvent(run_id="run_003", type="log", name="x"))
            assert base.exists()
            assert (base / "run_003.jsonl").exists()
