"""AgentLens CLI — 基于 Typer 的命令行工具。

提供 list / show / inspect / diff 四个子命令。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from agentlens.events import TraceEvent
from agentlens.storage import JsonlTraceStore

app = typer.Typer(
    name="agentlens",
    help="AgentLens — AI Agent 追踪、回放和调试工具",
    add_completion=False,
)

console = Console()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_store(base_dir: Optional[Path] = None) -> JsonlTraceStore:
    return JsonlTraceStore(base_dir=base_dir)


# ---------------------------------------------------------------------------
# list 命令
# ---------------------------------------------------------------------------

@app.command("list")
def list_runs(
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
) -> None:
    """列出所有 run_id。"""
    store = _get_store(base_dir)
    runs = store.list_runs()

    if not runs:
        console.print("[yellow]暂无追踪记录。[/yellow]")
        return

    table = Table(title="AgentLens Runs")
    table.add_column("#", style="dim")
    table.add_column("Run ID", style="cyan")

    for i, run_id in enumerate(runs, start=1):
        table.add_row(str(i), run_id)

    console.print(table)


# ---------------------------------------------------------------------------
# show 命令
# ---------------------------------------------------------------------------

@app.command("show")
def show_run(
    run_id: str = typer.Argument(..., help="要查看的 run_id"),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
) -> None:
    """以简洁格式打印 run 的事件时间线。"""
    store = _get_store(base_dir)
    events = store.load_run(run_id)

    if not events:
        console.print(f"[red]未找到 run: {run_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Run:[/bold] {run_id}\n")

    type_colors: dict[str, str] = {
        "run_start": "green",
        "run_end": "green",
        "llm_call": "blue",
        "tool_call": "magenta",
        "file_read": "yellow",
        "file_write": "yellow",
        "browser_action": "cyan",
        "error": "red",
        "log": "dim",
    }

    for event in events:
        color = type_colors.get(event.type, "white")
        marker = f"[{color}][{event.type}][/{color}]"
        name_part = event.name

        extras: list[str] = []
        if event.error:
            extras.append(f"error={event.error[:80]}")
        if event.type == "llm_call" and event.metadata:
            if "tokens" in event.metadata:
                extras.append(f"tokens={event.metadata['tokens']}")

        extra_str = f"  ({', '.join(extras)})" if extras else ""
        console.print(f"  {marker} {name_part}{extra_str}")

    console.print("")


# ---------------------------------------------------------------------------
# inspect 命令
# ---------------------------------------------------------------------------

@app.command("inspect")
def inspect_run(
    run_id: str = typer.Argument(..., help="要查看的 run_id"),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
    compact: bool = typer.Option(
        False,
        "--compact",
        "-c",
        help="紧凑输出（去除非关键字段）",
    ),
) -> None:
    """以完整 JSON 格式打印 run 的所有事件。"""
    store = _get_store(base_dir)
    events = store.load_run(run_id)

    if not events:
        console.print(f"[red]未找到 run: {run_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Run:[/bold] {run_id}\n")

    for event in events:
        data = event.model_dump(mode="json")
        if compact:
            # 只保留核心字段
            data = {
                k: v
                for k, v in data.items()
                if k
                in {
                    "id",
                    "type",
                    "name",
                    "input",
                    "output",
                    "error",
                    "started_at",
                    "ended_at",
                }
            }
        console.print_json(json.dumps(data, ensure_ascii=False, default=str))

    console.print("")


# ---------------------------------------------------------------------------
# diff 命令
# ---------------------------------------------------------------------------

@app.command("diff")
def diff_runs(
    run_a: str = typer.Argument(..., help="第一个 run_id"),
    run_b: str = typer.Argument(..., help="第二个 run_id"),
    base_dir: Optional[Path] = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
) -> None:
    """对比两个 run 的事件序列，输出第一处不同。"""
    store = _get_store(base_dir)
    events_a = store.load_run(run_a)
    events_b = store.load_run(run_b)

    if not events_a:
        console.print(f"[red]未找到 run: {run_a}[/red]")
        raise typer.Exit(code=1)
    if not events_b:
        console.print(f"[red]未找到 run: {run_b}[/red]")
        raise typer.Exit(code=1)

    len_a = len(events_a)
    len_b = len(events_b)

    # 比较长度
    if len_a != len_b:
        console.print(
            f"[yellow]事件数量不同:[/yellow] "
            f"{run_a} 有 {len_a} 个事件, "
            f"{run_b} 有 {len_b} 个事件"
        )

    # 逐事件比较 type 和 name
    min_len = min(len_a, len_b)
    diff_found = False
    for i in range(min_len):
        ea = events_a[i]
        eb = events_b[i]
        if ea.type != eb.type or ea.name != eb.name:
            console.print(
                f"[red]事件 #{i + 1} 不同:[/red]\n"
                f"  {run_a}: type={ea.type}, name={ea.name}\n"
                f"  {run_b}: type={eb.type}, name={eb.name}"
            )
            diff_found = True
            break

    if not diff_found and len_a == len_b:
        console.print("[green]两个 run 的事件序列完全一致。[/green]")
    elif not diff_found:
        console.print(
            f"[yellow]前 {min_len} 个事件一致，但总长度不同。[/yellow]"
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main() -> None:
    app()


if __name__ == "__main__":
    main()
