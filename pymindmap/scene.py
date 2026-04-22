"""MindMapScene: owns the Graph and the QGraphicsItems that render it."""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import QLineF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsScene

from .items import ConnectionItem, NodeItem, WaypointItem
from .model import Connection, Graph, Node, Waypoint
from .theme import THEME


class MindMapScene(QGraphicsScene):
    node_edited = pyqtSignal(int)          # emitted when a node's data changes
    selection_info_changed = pyqtSignal()

    def __init__(self, graph: Optional[Graph] = None, parent=None):
        super().__init__(parent)
        self.graph: Graph = graph if graph is not None else Graph()
        self.setBackgroundBrush(QColor(THEME.bg))
        # Large scene rect; pan/zoom via view. Items can extend beyond.
        self.setSceneRect(QRectF(-50000, -50000, 100000, 100000))

        self.node_items: Dict[int, NodeItem] = {}
        self.connection_items: List[ConnectionItem] = []
        self._waypoint_handles: List[WaypointItem] = []
        self._emphasis: Optional[Dict[int, float]] = None  # node_id -> opacity

        self.rebuild_all()
        self.selectionChanged.connect(self._on_selection_changed)

    # ---- rebuild ----------------------------------------------------------
    def rebuild_all(self):
        # Clear existing items we track
        for it in list(self.node_items.values()):
            self.removeItem(it)
        self.node_items.clear()
        for ci in list(self.connection_items):
            self.removeItem(ci)
        self.connection_items.clear()
        self._clear_waypoint_handles()

        for node in self.graph.nodes.values():
            self._add_node_item(node)
        for conn in self.graph.connections:
            self._add_connection_item(conn)

    def _add_node_item(self, node: Node) -> NodeItem:
        item = NodeItem(node, self)
        self.addItem(item)
        self.node_items[node.id] = item
        if self._emphasis is not None:
            item.setOpacity(self._emphasis.get(node.id, 0.15))
        return item

    def _add_connection_item(self, conn: Connection) -> ConnectionItem:
        item = ConnectionItem(conn, self)
        self.addItem(item)
        self.connection_items.append(item)
        if self._emphasis is not None:
            a = self._emphasis.get(conn.from_id, 0.15)
            b = self._emphasis.get(conn.to_id, 0.15)
            item.setOpacity(min(a, b))
        return item

    # ---- API used by commands --------------------------------------------
    def add_node(self, node: Node) -> NodeItem:
        self.graph.add_node(node)
        return self._add_node_item(node)

    def remove_node(self, node_id: int):
        # Remove connections that touched it (items + model handled together)
        doomed_conns = [c for c in self.graph.connections
                        if c.from_id == node_id or c.to_id == node_id]
        for c in doomed_conns:
            self.remove_connection(c)
        # Remove item
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)
        self.graph.nodes.pop(node_id, None)

    def add_connection(self, conn: Connection) -> ConnectionItem:
        self.graph.add_connection(conn)
        return self._add_connection_item(conn)

    def remove_connection(self, conn: Connection):
        # Remove item
        for ci in list(self.connection_items):
            if ci.conn is conn:
                self.removeItem(ci)
                self.connection_items.remove(ci)
                break
        self.graph.remove_connection(conn)
        self._clear_waypoint_handles()

    def refresh_connections_for(self, node_id: int):
        for ci in self.connection_items:
            if ci.conn.from_id == node_id or ci.conn.to_id == node_id:
                ci.rebuild_path()
        self._refresh_waypoint_positions()

    # ---- waypoint handles (shown only for selected connection) -----------
    def _clear_waypoint_handles(self):
        for h in self._waypoint_handles:
            if h.scene() is self:
                self.removeItem(h)
        self._waypoint_handles.clear()

    def rebuild_waypoint_handles(self, ci: ConnectionItem):
        self._clear_waypoint_handles()
        for i, _ in enumerate(ci.conn.waypoints):
            h = WaypointItem(ci, i)
            self.addItem(h)
            self._waypoint_handles.append(h)

    def _refresh_waypoint_positions(self):
        for h in self._waypoint_handles:
            w = h.conn_item.conn.waypoints[h.index]
            h.setPos(w.x, w.y)

    def _on_selection_changed(self):
        # Show waypoint handles for exactly one selected connection; hide otherwise.
        self._clear_waypoint_handles()
        selected_conns = [it for it in self.selectedItems() if isinstance(it, ConnectionItem)]
        if len(selected_conns) == 1:
            self.rebuild_waypoint_handles(selected_conns[0])
        self.selection_info_changed.emit()

    # ---- emphasis (spreading activation / search highlight) ---------------
    def set_emphasis(self, activations: Optional[Dict[int, float]]):
        """Set per-node opacity. None clears all emphasis (all full-opacity)."""
        self._emphasis = activations
        self._apply_emphasis()

    def clear_emphasis(self):
        self.set_emphasis(None)

    def _apply_emphasis(self):
        if self._emphasis is None:
            for it in self.node_items.values():
                it.setOpacity(1.0)
            for ci in self.connection_items:
                ci.setOpacity(1.0)
            return
        for nid, it in self.node_items.items():
            it.setOpacity(self._emphasis.get(nid, 0.15))
        for ci in self.connection_items:
            a = self._emphasis.get(ci.conn.from_id, 0.15)
            b = self._emphasis.get(ci.conn.to_id, 0.15)
            ci.setOpacity(min(a, b))

    def spreading_activation(self, node_id: int, max_depth: int = 3) -> Dict[int, float]:
        """BFS from ``node_id``, returning opacity per reachable node.

        Opacity falls off by depth; unreached nodes aren't in the result (the
        caller treats missing entries as "dimmed").
        """
        if node_id not in self.graph.nodes:
            return {}
        # Adjacency (undirected for spreading).
        adj: Dict[int, Set[int]] = {nid: set() for nid in self.graph.nodes}
        for c in self.graph.connections:
            if c.from_id in adj and c.to_id in adj:
                adj[c.from_id].add(c.to_id)
                adj[c.to_id].add(c.from_id)

        depths: Dict[int, int] = {node_id: 0}
        q = deque([node_id])
        while q:
            nid = q.popleft()
            d = depths[nid]
            if d >= max_depth:
                continue
            for nb in adj[nid]:
                if nb not in depths:
                    depths[nb] = d + 1
                    q.append(nb)

        # Depth → opacity curve.
        opacity_by_depth = [1.0, 0.75, 0.5, 0.3, 0.2, 0.15]
        result: Dict[int, float] = {}
        for nid, d in depths.items():
            idx = min(d, len(opacity_by_depth) - 1)
            result[nid] = opacity_by_depth[idx]
        return result

    # ---- background grid --------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        spacing = THEME.grid_spacing
        painter.setPen(QPen(QColor(THEME.grid_dot), 1))
        left = int(rect.left()) - (int(rect.left()) % spacing)
        top = int(rect.top()) - (int(rect.top()) % spacing)
        # Dots are cheap enough at reasonable zoom; Qt clips outside viewport.
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                painter.drawPoint(x, y)
                y += spacing
            x += spacing
