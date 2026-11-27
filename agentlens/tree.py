"""从一次 run 的事件还原父子树，并格式化为缩进文本。

JSONL 里的 ``parent_event_id`` 是唯一需要的关系。父事件可以出现在子事件之后，
还原时按 id 查找，不依赖写入顺序。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from agentlens.events import TraceEvent


@dataclass
class EventTreeNode:
    """树中的一个事件及其直接子节点。"""

    event: TraceEvent
    children: list[EventTreeNode] = field(default_factory=list)


@dataclass
class MissingParentGroup:
    """父事件不在本次 run 中的一组顶层事件。同一个缺失 id 只出现一组。"""

    parent_event_id: str
    nodes: list[EventTreeNode] = field(default_factory=list)


@dataclass
class EventTree:
    """一次 run 的事件树。

    ``roots`` 是父事件为空的事件。``missing_parents`` 按缺失父 id 分组，
    组内是该 id 的直接子事件（孤儿）及其仍能接上的子树。
    ``detached`` 是父 id 存在、但从根和孤儿都走不到的事件（例如环），仍然保留。
    """

    roots: list[EventTreeNode] = field(default_factory=list)
    missing_parents: list[MissingParentGroup] = field(default_factory=list)
    detached: list[EventTreeNode] = field(default_factory=list)

    @property
    def orphan_count(self) -> int:
        """父事件不在本次 run 中的事件数。孤儿下面的子事件不算孤儿。"""
        return sum(len(group.nodes) for group in self.missing_parents)

    @property
    def missing_parent_count(self) -> int:
        """不同的缺失父事件 id 数量。"""
        return len(self.missing_parents)


def _normalize_parent(parent_event_id: str | None) -> str | None:
    """空父 id 视为根，不把它当成一个缺失的父事件。"""
    if parent_event_id is None or parent_event_id == "":
        return None
    return parent_event_id


def _link(
    event: TraceEvent, children_of: dict[str, list[TraceEvent]], stack: set[str]
) -> EventTreeNode:
    """把事件和它的后代接成节点。遇到环时停止下探，避免无限递归。"""
    node = EventTreeNode(event=event)
    if event.id in stack:
        return node
    stack.add(event.id)
    for child in children_of.get(event.id, []):
        if child is event:
            continue
        node.children.append(_link(child, children_of, stack))
    stack.remove(event.id)
    return node


def _mark_included(node: EventTreeNode, included: set[int]) -> None:
    included.add(id(node.event))
    for child in node.children:
        _mark_included(child, included)


def build_event_tree(events: list[TraceEvent]) -> EventTree:
    """按 ``parent_event_id`` 还原事件树。不丢事件，也不因缺失父事件而失败。"""
    known_ids = {event.id for event in events}
    children_of: dict[str, list[TraceEvent]] = defaultdict(list)
    root_events: list[TraceEvent] = []
    grouped: dict[str, list[TraceEvent]] = {}

    for event in events:
        parent = _normalize_parent(event.parent_event_id)
        if parent is None:
            root_events.append(event)
        elif parent in known_ids:
            children_of[parent].append(event)
        else:
            grouped.setdefault(parent, []).append(event)

    roots = [_link(event, children_of, set()) for event in root_events]
    missing_parents = [
        MissingParentGroup(
            parent_event_id=parent_id,
            nodes=[_link(event, children_of, set()) for event in orphans],
        )
        for parent_id, orphans in grouped.items()
    ]

    included: set[int] = set()
    for node in roots:
        _mark_included(node, included)
    for group in missing_parents:
        for node in group.nodes:
            _mark_included(node, included)

    detached: list[EventTreeNode] = []
    for event in events:
        if id(event) in included:
            continue
        node = _link(event, children_of, set())
        detached.append(node)
        _mark_included(node, included)

    return EventTree(roots=roots, missing_parents=missing_parents, detached=detached)


def _append_lines(
    node: EventTreeNode,
    depth: int,
    missing_parent: str | None,
    lines: list[str],
) -> None:
    indent = "  " * depth
    line = f"{indent}[{node.event.type}] {node.event.name}"
    if missing_parent is not None:
        line += f" [missing parent: {missing_parent}]"
    lines.append(line)
    for child in node.children:
        _append_lines(child, depth + 1, None, lines)


def format_event_tree(events: list[TraceEvent]) -> str:
    """把事件树格式化成缩进文本，并附上孤儿 / 缺失父事件摘要。

    父事件为空的树先打印。缺失父事件的事件留在顶层，按缺失 id 分组，
    组与组之间空一行。每条孤儿事件带 ``[missing parent: id]``。
    它的子树继续缩进，且不再标记。最后一行是
    ``N orphans, M missing parents``。完整的树这两项都是 0，正文里没有标记。
    """
    tree = build_event_tree(events)
    blocks: list[str] = []

    root_lines: list[str] = []
    for node in tree.roots:
        _append_lines(node, 0, None, root_lines)
    for node in tree.detached:
        _append_lines(node, 0, None, root_lines)
    if root_lines:
        blocks.append("\n".join(root_lines))

    for group in tree.missing_parents:
        group_lines: list[str] = []
        for node in group.nodes:
            _append_lines(node, 0, group.parent_event_id, group_lines)
        if group_lines:
            blocks.append("\n".join(group_lines))

    summary = f"{tree.orphan_count} orphans, {tree.missing_parent_count} missing parents"
    if not blocks:
        return summary
    return "\n\n".join(blocks) + "\n" + summary
