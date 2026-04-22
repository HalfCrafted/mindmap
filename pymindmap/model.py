"""Data model: Node, Connection, Waypoint, Graph.

The model is UI-agnostic — it can be used headlessly (tests, scripts) without Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Node:
    id: int
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    width: float = 120.0
    height: float = 60.0
    color: str = "none"          # "none" or "#rrggbb"
    font_size: int = 14
    align: str = "center"        # left | center | right
    bold: bool = False
    italic: bool = False
    body: str = ""                         # long-form notes, shown in inspector
    collapsed: bool = False                # live variant: hide BFS descendants

    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass
class Waypoint:
    x: float
    y: float
    # Bezier handle offsets, relative to (x,y). Zero means no smoothing.
    in_dx: float = 0.0
    in_dy: float = 0.0
    out_dx: float = 0.0
    out_dy: float = 0.0


@dataclass
class EdgeAnchor:
    """A connection endpoint anchored to a specific edge of a node."""
    edge: str = "auto"           # auto | top | right | bottom | left
    offset: float = 0.5          # 0..1 position along the edge


@dataclass
class Connection:
    from_id: int
    to_id: int
    from_anchor: Optional[EdgeAnchor] = None
    to_anchor: Optional[EdgeAnchor] = None
    waypoints: List[Waypoint] = field(default_factory=list)


@dataclass
class Graph:
    nodes: Dict[int, Node] = field(default_factory=dict)
    connections: List[Connection] = field(default_factory=list)
    _next_id: int = 1

    # ---- node ops ---------------------------------------------------------
    def add_node(self, node: Optional[Node] = None, **kwargs) -> Node:
        if node is None:
            node = Node(id=self.allocate_id(), **kwargs)
        else:
            if node.id in self.nodes:
                raise ValueError(f"node id {node.id} already exists")
            self._next_id = max(self._next_id, node.id + 1)
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: int) -> None:
        self.nodes.pop(node_id, None)
        self.connections = [
            c for c in self.connections if c.from_id != node_id and c.to_id != node_id
        ]

    def allocate_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    # ---- connection ops ---------------------------------------------------
    def add_connection(self, conn: Connection) -> Connection:
        if conn.from_id not in self.nodes or conn.to_id not in self.nodes:
            raise ValueError("connection endpoints must exist in graph")
        self.connections.append(conn)
        return conn

    def remove_connection(self, conn: Connection) -> None:
        try:
            self.connections.remove(conn)
        except ValueError:
            pass
