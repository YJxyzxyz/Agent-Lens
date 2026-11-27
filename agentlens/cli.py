"""AgentLens CLI — 基于 Typer 的命令行工具。

提供 list / show / tree / inspect / stats / export / diff / view 子命令。
``show`` 是线性时间线，``tree`` 是按 parent_event_id 缩进的事件树，
``stats`` 和 ``export`` 从已有事件派生摘要与 JSON/CSV，
``diff`` 对齐两次 run 并打印全部差异，``view`` 启动本地 Web 查看器。
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from agentlens.diff import diff_events, diff_to_json, format_diff
from agentlens.events import TraceEvent
from agentlens.export import export_events
from agentlens.storage import JsonlTraceStore
from agentlens.summary import (
    format_run_summary,
    format_summary_list,
    summaries_to_csv,
    summaries_to_json,
    summarize_run,
)
from agentlens.tree import format_event_tree

app = typer.Typer(
    name="agentlens",
    help="AgentLens — AI Agent 追踪、回放和调试工具",
    add_completion=False,
)

console = Console()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_store(base_dir: Path | None = None) -> JsonlTraceStore:
    return JsonlTraceStore(base_dir=base_dir)


def _load_or_exit(store: JsonlTraceStore, run_id: str) -> list[TraceEvent]:
    events = store.load_run(run_id)
    if not events:
        console.print(f"[red]未找到 run: {run_id}[/red]")
        raise typer.Exit(code=1)
    return events


def _reject_bad_choice(value: str, allowed: set[str], label: str) -> None:
    if value not in allowed:
        names = "、".join(sorted(allowed))
        console.print(f"[red]不支持的{label}: {value}。可选 {names}。[/red]")
        raise typer.Exit(code=2)


def _emit(text: str, output: Path | None) -> None:
    """打印或写入文本。``text`` 已带结尾换行。"""
    if output is None:
        typer.echo(text, nl=False)
        return
    if output.exists() and output.is_dir():
        console.print(f"[red]输出路径是目录: {output}[/red]")
        raise typer.Exit(code=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    console.print(f"[green]已写入[/green] {output}")


# ---------------------------------------------------------------------------
# list 命令
# ---------------------------------------------------------------------------


@app.command("list")
def list_runs(
    base_dir: Path | None = typer.Option(
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
    base_dir: Path | None = typer.Option(
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
# tree 命令
# ---------------------------------------------------------------------------


@app.command("tree")
def tree_run(
    run_id: str = typer.Argument(..., help="要查看的 run_id"),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
) -> None:
    """按父子关系缩进打印 run 的事件树。"""
    store = _get_store(base_dir)
    events = store.load_run(run_id)

    if not events:
        console.print(f"[red]未找到 run: {run_id}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]Run:[/bold] {run_id}\n")
    console.print(format_event_tree(events), markup=False, highlight=False)
    console.print("")


# ---------------------------------------------------------------------------
# inspect 命令
# ---------------------------------------------------------------------------


@app.command("inspect")
def inspect_run(
    run_id: str = typer.Argument(..., help="要查看的 run_id"),
    base_dir: Path | None = typer.Option(
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
                    "parent_event_id",
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
# stats 命令
# ---------------------------------------------------------------------------


@app.command("stats")
def stats_runs(
    run_id: str | None = typer.Argument(
        None,
        help="要汇总的 run_id；省略则汇总全部 run",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
    fmt: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="输出格式：text、json 或 csv",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="写入文件；省略则打印到标准输出",
    ),
) -> None:
    """从已有事件打印统计摘要。不修改 JSONL。"""
    _reject_bad_choice(fmt, {"text", "json", "csv"}, "格式")
    store = _get_store(base_dir)

    if run_id is None:
        summaries = [summarize_run(store.load_run(item), run_id=item) for item in store.list_runs()]
        if fmt == "json":
            text = summaries_to_json(summaries, single=False)
        elif fmt == "csv":
            text = summaries_to_csv(summaries)
        else:
            text = format_summary_list(summaries)
        _emit(text, output)
        return

    events = _load_or_exit(store, run_id)
    summary = summarize_run(events, run_id=run_id)
    if fmt == "json":
        text = summaries_to_json([summary], single=True)
    elif fmt == "csv":
        text = summaries_to_csv([summary])
    else:
        text = format_run_summary(summary)
    _emit(text, output)


# ---------------------------------------------------------------------------
# export 命令
# ---------------------------------------------------------------------------


@app.command("export")
def export_run(
    run_id: str = typer.Argument(..., help="要导出的 run_id"),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
    fmt: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="导出格式：json 或 csv",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="写入文件；省略则打印到标准输出",
    ),
) -> None:
    """把一次 run 的事件导出为 JSON 数组或 CSV。不修改 JSONL。"""
    _reject_bad_choice(fmt, {"json", "csv"}, "格式")
    store = _get_store(base_dir)
    events = _load_or_exit(store, run_id)
    _emit(export_events(events, fmt), output)


# ---------------------------------------------------------------------------
# diff 命令
# ---------------------------------------------------------------------------


@app.command("diff")
def diff_runs(
    run_a: str = typer.Argument(..., help="左侧 run_id"),
    run_b: str = typer.Argument(..., help="右侧 run_id"),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
    align: str = typer.Option(
        "sequence",
        "--align",
        help="sequence 按 type/name 对齐；index 按记录位置对齐",
    ),
    fmt: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="输出格式：text 或 json",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="写入文件；省略则打印到标准输出",
    ),
) -> None:
    """对齐两个 run，比较 type、name、error、input、output，并打印全部差异。"""
    _reject_bad_choice(align, {"sequence", "index"}, "对齐方式")
    _reject_bad_choice(fmt, {"text", "json"}, "格式")
    store = _get_store(base_dir)
    events_a = _load_or_exit(store, run_a)
    events_b = _load_or_exit(store, run_b)
    if align == "index":
        result = diff_events(events_a, events_b, align="index")
    else:
        result = diff_events(events_a, events_b, align="sequence")
    if fmt == "json":
        text = diff_to_json(result, left_run_id=run_a, right_run_id=run_b)
    else:
        text = format_diff(result, left_run_id=run_a, right_run_id=run_b)
    _emit(text, output)


# ---------------------------------------------------------------------------
# view 命令
# ---------------------------------------------------------------------------


@app.command("view")
def view_runs(
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        "-h",
        help="绑定地址",
    ),
    port: int = typer.Option(
        8765,
        "--port",
        "-p",
        help="端口号",
    ),
    base_dir: Path | None = typer.Option(
        None,
        "--base-dir",
        "-d",
        help="存储根目录，默认 .agentlens/runs/",
    ),
) -> None:
    """启动本地 Web Timeline Viewer。"""
    try:
        from agentlens.viewer import start_viewer
    except ImportError:
        console.print(
            "[red]未安装 web 依赖。请运行:[/red]\n"
            "  pip install agentlens[web]\n"
            "或:\n"
            "  pip install fastapi uvicorn"
        )
        raise typer.Exit(code=1) from None

    start_viewer(host=host, port=port, base_dir=base_dir)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
