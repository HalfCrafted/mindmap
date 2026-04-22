"""LiveMindMapScene — every mutation triggers a debounced auto-layout.

Design:
- Any model-changing operation calls ``schedule_layout()``.
- A short QTimer coalesces bursts of changes into a single F-R pass.
- Nodes currently being user-dragged are pinned for the next pass so the
  interaction isn't fighting the layout.
- After layout, positions are interpolated over ~350ms so the graph settles
  smoothly instead of snapping.
- LiveNodeItem sizes (and therefore layout input) depend on connection
  degree — recomputed at the start of each pass.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Optional, Set

from PyQt5.QtCore import (
    QEasingCurve,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsScene

from ..items import ConnectionItem, WaypointItem  # reuse bezier connection
from ..layout import fruchterman_reingold
from ..model import Connection, Graph, Node

from .items import LiveNodeItem


GRID_BG = "#0b0b10"
GRID_DOT = "#17171f"
GRID_SPACING = 28
LAYOUT_DEBOUNCE_MS = 120
LAYOUT_DURATION_MS = 400
LAYOUT_ITERATIONS = 240   # higher so the tighter packing fully converges


class LiveMindMapScene(QGraphicsScene):
    edit_requested = pyqtSignal(int)           # node id to open in sidebar
    layout_started = pyqtSignal()
    layout_finished = pyqtSignal()
    selection_info_changed = pyqtSignal()

    def __init__(self, graph: Optional[Graph] = None, parent: QObject | None = None):
        super().__init__(parent)
        self.graph: Graph = graph if graph is not None else Graph()
        self.setBackgroundBrush(QColor(GRID_BG))
        self.setSceneRect(QRectF(-50000, -50000, 100000, 100000))

        self.node_items: Dict[int, LiveNodeItem] = {}
        self.connection_items: List[ConnectionItem] = []
        self._waypoint_handles: list = []
        self._degree: Dict[int, int] = defaultdict(int)

        # BFS-tree bookkeeping for collapse feature.
        self._parent: Dict[int, Optional[int]] = {}
        self._children: Dict[int, Set[int]] = defaultdict(set)
        self._hidden: Set[int] = set()

        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._run_layout)

        self._layout_anim: Optional[QVariantAnimation] = None

        self._emphasis: Optional[Dict[int, float]] = None

        self._recompute_degrees()
        self._recompute_tree()
        self.rebuild_all()
        self.selectionChanged.connect(self._on_selection_changed)

    # ---- degree bookkeeping ----------------------------------------------
    def _recompute_degrees(self):
        self._degree = defaultdict(int)
        for c in self.graph.connections:
            self._degree[c.from_id] += 1
            self._degree[c.to_id] += 1

    def degree_of(self, nid: int) -> int:
        return self._degree.get(nid, 0)

    # ---- BFS tree / collapse bookkeeping ---------------------------------
    def _recompute_tree(self):
        """Root = highest-degree node. BFS assigns a parent to every reachable
        node; leftover components are rooted at their own highest-degree node.

        ``self._children`` then gives the "outer branches" each node owns —
        that's what gets hidden when a node is collapsed.
        """
        self._parent = {}
        self._children = defaultdict(set)
        if not self.graph.nodes:
            return

        adj: Dict[int, Set[int]] = defaultdict(set)
        for c in self.graph.connections:
            adj[c.from_id].add(c.to_id)
            adj[c.to_id].add(c.from_id)

        remaining = set(self.graph.nodes.keys())
        while remaining:
            # Pick a root for this connected component: highest degree, then
            # lowest id for deterministic tie-break.
            root = max(remaining, key=lambda nid: (self._degree[nid], -nid))
            self._parent[root] = None
            q = deque([root])
            remaining.discard(root)
            while q:
                cur = q.popleft()
                for nb in adj[cur]:
                    if nb in remaining:
                        self._parent[nb] = cur
                        self._children[cur].add(nb)
                        remaining.discard(nb)
                        q.append(nb)

        self._recompute_hidden()

    def _recompute_hidden(self):
        """Hidden set = closure of descendants of every collapsed node."""
        hidden: Set[int] = set()
        for nid, node in self.graph.nodes.items():
            if node.collapsed and self._children.get(nid):
                stack = list(self._children[nid])
                while stack:
                    x = stack.pop()
                    if x in hidden:
                        continue
                    hidden.add(x)
                    stack.extend(self._children.get(x, ()))
        self._hidden = hidden

    def has_descendants(self, node_id: int) -> bool:
        return bool(self._children.get(node_id))

    def is_hidden(self, node_id: int) -> bool:
        return node_id in self._hidden

    def apply_visibility(self):
        """Show/hide items based on ``self._hidden``."""
        for nid, item in self.node_items.items():
            item.setVisible(nid not in self._hidden)
        for ci in self.connection_items:
            visible = (ci.conn.from_id not in self._hidden
                       and ci.conn.to_id not in self._hidden)
            ci.setVisible(visible)

    def toggle_collapse(self, node_id: int):
        """Flip the collapsed flag on a node, refresh visibility + layout."""
        node = self.graph.nodes.get(node_id)
        if node is None or not self.has_descendants(node_id):
            return
        node.collapsed = not node.collapsed
        self._recompute_hidden()
        self.apply_visibility()
        # Let the affected node's card repaint its chevron.
        item = self.node_items.get(node_id)
        if item is not None:
            item.update()
        self.schedule_layout()

    # ---- rebuild ----------------------------------------------------------
    def rebuild_all(self):
        # Remove tracked items cleanly.
        for it in list(self.node_items.values()):
            self.removeItem(it)
        self.node_items.clear()
        for ci in list(self.connection_items):
            self.removeItem(ci)
        self.connection_items.clear()
        self._clear_waypoint_handles()

        self._recompute_degrees()
        self._recompute_tree()
        for node in self.graph.nodes.values():
            self._add_node_item(node)
        for conn in self.graph.connections:
            self._add_connection_item(conn)
        self.apply_visibility()

    def _add_node_item(self, node: Node) -> LiveNodeItem:
        item = LiveNodeItem(node, self)
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

    # ---- mutation API (layout-triggering) --------------------------------
    def add_node(self, node: Node) -> LiveNodeItem:
        self.graph.add_node(node)
        item = self._add_node_item(node)
        self._recompute_tree()
        self.apply_visibility()
        self.schedule_layout()
        return item

    def remove_node(self, node_id: int):
        for c in [c for c in self.graph.connections
                  if c.from_id == node_id or c.to_id == node_id]:
            self.remove_connection(c)
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.removeItem(item)
        self.graph.nodes.pop(node_id, None)
        self._recompute_degrees()
        self._recompute_tree()
        self.apply_visibility()
        self._refresh_node_sizes()
        self.schedule_layout()

    def add_connection(self, conn: Connection) -> ConnectionItem:
        self.graph.add_connection(conn)
        item = self._add_connection_item(conn)
        self._degree[conn.from_id] += 1
        self._degree[conn.to_id] += 1
        self._recompute_tree()
        self.apply_visibility()
        self._refresh_node_sizes()
        self.schedule_layout()
        return item

    def remove_connection(self, conn: Connection):
        for ci in list(self.connection_items):
            if ci.conn is conn:
                self.removeItem(ci)
                self.connection_items.remove(ci)
                break
        self.graph.remove_connection(conn)
        if conn.from_id in self._degree:
            self._degree[conn.from_id] = max(0, self._degree[conn.from_id] - 1)
        if conn.to_id in self._degree:
            self._degree[conn.to_id] = max(0, self._degree[conn.to_id] - 1)
        self._recompute_tree()
        self.apply_visibility()
        self._refresh_node_sizes()
        self._clear_waypoint_handles()
        self.schedule_layout()

    def _refresh_node_sizes(self):
        """Recompute all node sizes from current degrees + bodies."""
        for item in self.node_items.values():
            item.prepareGeometryChange()
            item.recompute_size()
            item.update()
        # Connections must re-route since endpoint bounds changed.
        for ci in self.connection_items:
            ci.rebuild_path()

    def refresh_connections_for(self, node_id: int):
        for ci in self.connection_items:
            if ci.conn.from_id == node_id or ci.conn.to_id == node_id:
                ci.rebuild_path()
        self._refresh_waypoint_positions()

    # ---- node edits from inspector ---------------------------------------
    def update_node(self, node_id: int, **attrs):
        """Apply attr updates from the inspector and relayout if needed."""
        n = self.graph.nodes.get(node_id)
        if n is None:
            return
        size_affecting = False
        for k, v in attrs.items():
            if hasattr(n, k):
                if k in ("text", "body") and getattr(n, k) != v:
                    size_affecting = True
                setattr(n, k, v)
        item = self.node_items.get(node_id)
        if item is not None:
            item.refresh()
        if size_affecting:
            self.schedule_layout()

    # ---- waypoint handles -------------------------------------------------
    def _clear_waypoint_handles(self):
        for h in self._waypoint_handles:
            if h.scene() is self:
                self.removeItem(h)
        self._waypoint_handles.clear()

    def rebuild_waypoint_handles(self, ci: ConnectionItem):
        self._clear_waypoint_handles()
        for i in range(len(ci.conn.waypoints)):
            h = WaypointItem(ci, i)
            self.addItem(h)
            self._waypoint_handles.append(h)

    def _refresh_waypoint_positions(self):
        for h in self._waypoint_handles:
            w = h.conn_item.conn.waypoints[h.index]
            h.setPos(w.x, w.y)

    def _on_selection_changed(self):
        self._clear_waypoint_handles()
        sel_conns = [it for it in self.selectedItems() if isinstance(it, ConnectionItem)]
        if len(sel_conns) == 1:
            self.rebuild_waypoint_handles(sel_conns[0])
        self.selection_info_changed.emit()

    # ---- layout pipeline --------------------------------------------------
    def schedule_layout(self):
        """Request a re-layout. Coalesces bursts of structural changes."""
        self._layout_timer.start(LAYOUT_DEBOUNCE_MS)

    def _run_layout(self):
        if not self.graph.nodes:
            return
        visible_ids = [nid for nid in self.graph.nodes if nid not in self._hidden]
        if not visible_ids:
            return

        starts = {nid: (self.graph.nodes[nid].x, self.graph.nodes[nid].y)
                  for nid in visible_ids}

        # Build a filtered subgraph containing only visible nodes and the
        # edges between them. We lay that out; hidden nodes keep their last
        # known positions (harmless — they're not drawn).
        sub = Graph()
        for nid in visible_ids:
            sub.nodes[nid] = self.graph.nodes[nid]
        for c in self.graph.connections:
            if c.from_id in sub.nodes and c.to_id in sub.nodes:
                sub.connections.append(c)

        ends = fruchterman_reingold(
            sub,
            iterations=LAYOUT_ITERATIONS,
            seed=_structure_seed(sub),
        )

        if not any(_moved(starts.get(nid), ends[nid]) for nid in ends):
            return

        self.layout_started.emit()
        self._animate_positions(starts, ends)

    def _animate_positions(self, starts: dict, ends: dict):
        if self._layout_anim is not None:
            self._layout_anim.stop()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(LAYOUT_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def on_frame(t):
            for nid, end in ends.items():
                s = starts.get(nid)
                if s is None:
                    continue
                nx = s[0] + (end[0] - s[0]) * t
                ny = s[1] + (end[1] - s[1]) * t
                n = self.graph.nodes.get(nid)
                if n is None:
                    continue
                n.x, n.y = nx, ny
                item = self.node_items.get(nid)
                if item is not None:
                    item.setPos(nx, ny)
            for ci in self.connection_items:
                ci.rebuild_path()

        def on_finished():
            self._layout_anim = None
            self.layout_finished.emit()

        anim.valueChanged.connect(on_frame)
        anim.finished.connect(on_finished)
        self._layout_anim = anim
        anim.start()

    # ---- emphasis (spreading activation / search) -------------------------
    def set_emphasis(self, activations: Optional[Dict[int, float]]):
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
            it.setOpacity(self._emphasis.get(nid, 0.12))
        for ci in self.connection_items:
            a = self._emphasis.get(ci.conn.from_id, 0.12)
            b = self._emphasis.get(ci.conn.to_id, 0.12)
            ci.setOpacity(min(a, b))

    def spreading_activation(self, node_id: int, max_depth: int = 2) -> Dict[int, float]:
        if node_id not in self.graph.nodes:
            return {}
        adj: Dict[int, Set[int]] = defaultdict(set)
        for c in self.graph.connections:
            adj[c.from_id].add(c.to_id)
            adj[c.to_id].add(c.from_id)
        depths: Dict[int, int] = {node_id: 0}
        q = deque([node_id])
        while q:
            cur = q.popleft()
            d = depths[cur]
            if d >= max_depth:
                continue
            for nb in adj[cur]:
                if nb not in depths:
                    depths[nb] = d + 1
                    q.append(nb)
        curve = [1.0, 0.7, 0.45, 0.3, 0.2]
        return {nid: curve[min(d, len(curve) - 1)] for nid, d in depths.items()}

    # ---- external edit hook ----------------------------------------------
    def request_edit(self, node_id: int):
        self.edit_requested.emit(node_id)

    # ---- background grid --------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(GRID_DOT), 1))
        spacing = GRID_SPACING
        left = int(rect.left()) - (int(rect.left()) % spacing)
        top = int(rect.top()) - (int(rect.top()) % spacing)
        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                painter.drawPoint(x, y)
                y += spacing
            x += spacing


def _moved(a, b) -> bool:
    if a is None or b is None:
        return True
    return abs(a[0] - b[0]) > 0.5 or abs(a[1] - b[1]) > 0.5


def _structure_seed(graph) -> int:
    """Deterministic seed from the set of node ids and edges.

    Identical graphs produce identical layouts, so selecting a node (or any
    non-structural interaction) never shifts anything. Add/remove a node or
    edge and the seed changes, producing a new layout.
    """
    nid_tuple = tuple(sorted(graph.nodes.keys()))
    edge_tuple = tuple(sorted((c.from_id, c.to_id) for c in graph.connections))
    return hash((nid_tuple, edge_tuple)) & 0x7FFFFFFF
