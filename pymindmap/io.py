"""JSON IO compatible with ScatterMind's format.

The original format stores nodes as ``[[id, {...}], ...]`` (Map entries) and
connections as flat dicts with optional cached ``_bezier`` geometry. We accept
that format and also a simplified ``{nodes: [...], connections: [...]}`` form.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

from .model import Connection, EdgeAnchor, Graph, Node, Waypoint

PathLike = Union[str, Path]


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
def _node_from_dict(d: dict) -> Node:
    # Prefer explicit width/height; fall back to w/h; fall back to defaults.
    width = d.get("width") or d.get("w") or 120
    height = d.get("height") or d.get("h") or 60
    width = float(width)
    height = float(height)
    return Node(
        id=int(d["id"]),
        x=float(d.get("x", 0)),
        y=float(d.get("y", 0)),
        text=str(d.get("text", "")),
        width=max(40.0, width),
        height=max(30.0, height),
        color=str(d.get("color", "none")),
        font_size=int(d.get("fontSize", 14)),
        align=str(d.get("align", "center")),
        bold=bool(d.get("bold", False)),
        italic=bool(d.get("italic", False)),
        body=str(d.get("body", "")),
        collapsed=bool(d.get("collapsed", False)),
    )


def _waypoint_from_dict(d: dict) -> Waypoint:
    hi = d.get("handleIn") or {}
    ho = d.get("handleOut") or {}
    return Waypoint(
        x=float(d["x"]),
        y=float(d["y"]),
        in_dx=float(hi.get("x", 0)),
        in_dy=float(hi.get("y", 0)),
        out_dx=float(ho.get("x", 0)),
        out_dy=float(ho.get("y", 0)),
    )


def _anchor_from_dict(d: Any) -> EdgeAnchor | None:
    if not d:
        return None
    return EdgeAnchor(
        edge=str(d.get("edge", "auto")),
        offset=float(d.get("offset", 0.5)),
    )


def load_graph(path: PathLike) -> Graph:
    path = Path(path)
    data = json.loads(path.read_text())
    return graph_from_dict(data)


def graph_from_dict(data: dict) -> Graph:
    g = Graph()

    raw_nodes = data.get("nodes", [])
    for entry in raw_nodes:
        # Accept [id, {...}] or just {...}.
        nd = entry[1] if isinstance(entry, (list, tuple)) and len(entry) == 2 else entry
        node = _node_from_dict(nd)
        g.nodes[node.id] = node
        g._next_id = max(g._next_id, node.id + 1)

    counter = data.get("nodeIdCounter")
    if isinstance(counter, int):
        g._next_id = max(g._next_id, counter + 1)

    for c in data.get("connections", []):
        if c.get("from") not in g.nodes or c.get("to") not in g.nodes:
            continue  # skip dangling refs
        conn = Connection(
            from_id=int(c["from"]),
            to_id=int(c["to"]),
            from_anchor=_anchor_from_dict(c.get("fromPos")),
            to_anchor=_anchor_from_dict(c.get("toPos")),
            waypoints=[_waypoint_from_dict(w) for w in c.get("waypoints", []) or []],
        )
        g.connections.append(conn)

    return g


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------
def _node_to_dict(n: Node) -> dict:
    d = {
        "id": n.id,
        "x": n.x,
        "y": n.y,
        "text": n.text,
        "color": n.color,
        "fontSize": n.font_size,
        "align": n.align,
        "bold": n.bold,
        "italic": n.italic,
        "width": n.width,
        "height": n.height,
        "w": round(n.width),
        "h": round(n.height),
    }
    if n.body:
        d["body"] = n.body
    if n.collapsed:
        d["collapsed"] = True
    return d


def _waypoint_to_dict(w: Waypoint) -> dict:
    out = {"x": w.x, "y": w.y}
    if w.in_dx or w.in_dy:
        out["handleIn"] = {"x": w.in_dx, "y": w.in_dy}
    if w.out_dx or w.out_dy:
        out["handleOut"] = {"x": w.out_dx, "y": w.out_dy}
    return out


def _anchor_to_dict(a: EdgeAnchor | None) -> dict | None:
    if a is None:
        return None
    return {"edge": a.edge, "offset": a.offset}


def graph_to_dict(g: Graph) -> dict:
    return {
        "version": 2,
        "nodes": [[n.id, _node_to_dict(n)] for n in g.nodes.values()],
        "connections": [
            {
                "from": c.from_id,
                "to": c.to_id,
                **({"fromPos": _anchor_to_dict(c.from_anchor)} if c.from_anchor else {}),
                **({"toPos": _anchor_to_dict(c.to_anchor)} if c.to_anchor else {}),
                **({"waypoints": [_waypoint_to_dict(w) for w in c.waypoints]} if c.waypoints else {}),
            }
            for c in g.connections
        ],
        "nodeIdCounter": g._next_id - 1,
    }


def save_graph(g: Graph, path: PathLike) -> None:
    Path(path).write_text(json.dumps(graph_to_dict(g), indent=2))
