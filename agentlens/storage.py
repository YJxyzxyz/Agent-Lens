"""AgentLens 存储层 — 基于本地 JSONL 文件的追踪数据持久化。

每个 run 对应一个 <run_id>.jsonl 文件，存储在 .agentlens/runs/ 目录下。
"""

from __future__ import annotations

import os
from pathlib import Path

from agentlens.events import TraceEvent

# ---------------------------------------------------------------------------
# 默认存储路径
# ---------------------------------------------------------------------------

DEFAULT_BASE_DIR = Path.cwd() / ".agentlens" / "runs"


# ---------------------------------------------------------------------------
# JSONL 存储实现
# ---------------------------------------------------------------------------


class JsonlTraceStore:
    """基于本地 JSONL 文件的追踪事件存储。

    用法::

        store = JsonlTraceStore()
        store.append_event(event)
        events = store.load_run("run_20260101_120000_abc123")
        runs = store.list_runs()
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        """初始化存储。

        Args:
            base_dir: 存储根目录，默认为当前工作目录下的 .agentlens/runs/。
        """
        self.base_dir = Path(base_dir) if base_dir is not None else DEFAULT_BASE_DIR
        os.makedirs(self.base_dir, exist_ok=True)

    # -- 文件路径 ------------------------------------------------------------

    def _file_path(self, run_id: str) -> Path:
        """返回某个 run 对应的 JSONL 文件路径。"""
        return self.base_dir / f"{run_id}.jsonl"

    # -- 核心操作 ------------------------------------------------------------

    def append_event(self, event: TraceEvent) -> None:
        """向对应 run 的 JSONL 文件追加一条事件。

        Args:
            event: 要追加的追踪事件。
        """
        file_path = self._file_path(event.run_id)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def load_run(self, run_id: str) -> list[TraceEvent]:
        """读取一次 run 的全部事件。

        Args:
            run_id: 运行 ID。

        Returns:
            按写入顺序排列的事件列表。若 run 不存在则返回空列表。
        """
        file_path = self._file_path(run_id)
        if not file_path.exists():
            return []

        events: list[TraceEvent] = []
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(TraceEvent.model_validate_json(line))
        return events

    def list_runs(self) -> list[str]:
        """列出所有已记录的 run_id。

        Returns:
            run_id 列表，按文件名字母序排列。
        """
        if not self.base_dir.exists():
            return []

        runs: list[str] = []
        for entry in sorted(self.base_dir.iterdir()):
            if entry.suffix == ".jsonl":
                runs.append(entry.stem)
        return runs
