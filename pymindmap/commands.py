"""QUndoCommand subclasses — the only place that should mutate the scene's graph."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, List, Tuple

from PyQt5.QtWidgets import QUndoCommand

from .model import Connection, Node, Waypoint

if TYPE_CHECKING:
    from .items import ConnectionItem
    from .scene import MindMapScene


class AddNodeCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", node: Node):
        super().__init__("Add node")
        self.scene = scene
        self.node = node

    def redo(self):
        self.scene.add_node(self.node)

    def undo(self):
        self.scene.remove_node(self.node.id)


class RemoveNodesCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", node_ids: List[int]):
        super().__init__(f"Remove {len(node_ids)} node(s)")
        self.scene = scene
        self.node_ids = list(node_ids)
        self._removed_nodes: List[Node] = []
        self._removed_conns: List[Connection] = []

    def redo(self):
        self._removed_nodes = []
        self._removed_conns = []
        # Capture connections touching these nodes first
        for c in list(self.scene.graph.connections):
            if c.from_id in self.node_ids or c.to_id in self.node_ids:
                self._removed_conns.append(deepcopy(c))
        for nid in self.node_ids:
            if nid in self.scene.graph.nodes:
                self._removed_nodes.append(deepcopy(self.scene.graph.nodes[nid]))
                self.scene.remove_node(nid)

    def undo(self):
        for n in self._removed_nodes:
            self.scene.add_node(n)
        for c in self._removed_conns:
            # only restore if both endpoints exist again
            if c.from_id in self.scene.graph.nodes and c.to_id in self.scene.graph.nodes:
                self.scene.add_connection(c)


class AddConnectionCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", conn: Connection):
        super().__init__("Add connection")
        self.scene = scene
        self.conn = conn

    def redo(self):
        self.scene.add_connection(self.conn)

    def undo(self):
        self.scene.remove_connection(self.conn)


class RemoveConnectionCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", conn: Connection):
        super().__init__("Remove connection")
        self.scene = scene
        self.conn = conn

    def redo(self):
        self.scene.remove_connection(self.conn)

    def undo(self):
        self.scene.add_connection(self.conn)


class ToggleConnectionDirectionCmd(QUndoCommand):
    """Cycle a connection's state: bidirectional → from→to → to→from → …

    Undo snapshots the previous ``directed`` flag and endpoint ids so we can
    restore the exact prior state, even after a from/to swap.
    """

    def __init__(self, scene: "MindMapScene", conn: Connection,
                 label: str = "Toggle connection direction"):
        super().__init__(label)
        self.scene = scene
        self.conn = conn
        self._prev_directed = conn.directed
        self._prev_from = conn.from_id
        self._prev_to = conn.to_id
        # Next state in the cycle.
        if not conn.directed:
            self._next_directed = True
            self._next_from = conn.from_id
            self._next_to = conn.to_id
        else:
            # Flip direction by swapping endpoints; once we've been both ways,
            # revert to undirected (next cycle hit).
            # To keep it simple: directed → undirected on second press.
            self._next_directed = False
            self._next_from = conn.from_id
            self._next_to = conn.to_id

    def redo(self):
        self.conn.directed = self._next_directed
        self.conn.from_id = self._next_from
        self.conn.to_id = self._next_to
        self.scene._recompute_tree()
        self.scene.apply_visibility()
        self.scene._refresh_node_sizes()
        self.scene.schedule_layout()

    def undo(self):
        self.conn.directed = self._prev_directed
        self.conn.from_id = self._prev_from
        self.conn.to_id = self._prev_to
        self.scene._recompute_tree()
        self.scene.apply_visibility()
        self.scene._refresh_node_sizes()
        self.scene.schedule_layout()


class SwapConnectionDirectionCmd(QUndoCommand):
    """Flip from_id / to_id on a directed connection (reverse the arrow)."""

    def __init__(self, scene: "MindMapScene", conn: Connection):
        super().__init__("Reverse connection")
        self.scene = scene
        self.conn = conn

    def _swap(self):
        self.conn.from_id, self.conn.to_id = self.conn.to_id, self.conn.from_id
        self.conn.from_anchor, self.conn.to_anchor = (
            self.conn.to_anchor, self.conn.from_anchor)
        self.scene._recompute_tree()
        self.scene.apply_visibility()
        self.scene._refresh_node_sizes()
        self.scene.schedule_layout()

    def redo(self):
        self._swap()

    def undo(self):
        self._swap()


class MoveNodesCmd(QUndoCommand):
    """Batch-move multiple nodes (used after a drag in the scene).

    Stores a list of (node_id, from_xy, to_xy) so it's reversible.
    """
    def __init__(self, scene: "MindMapScene",
                 moves: List[Tuple[int, Tuple[float, float], Tuple[float, float]]]):
        super().__init__("Move nodes")
        self.scene = scene
        self.moves = moves

    def redo(self):
        for nid, _frm, to in self.moves:
            self._apply(nid, to)

    def undo(self):
        for nid, frm, _to in self.moves:
            self._apply(nid, frm)

    def _apply(self, nid, xy):
        n = self.scene.graph.nodes.get(nid)
        if n is None:
            return
        n.x, n.y = xy
        it = self.scene.node_items.get(nid)
        if it is not None:
            it.setPos(xy[0], xy[1])
            it.notify_connections()


class EditNodeCmd(QUndoCommand):
    """Generic 'set one or more attributes on a node' command."""
    def __init__(self, scene: "MindMapScene", node_id: int, new_attrs: dict, label: str = "Edit node"):
        super().__init__(label)
        self.scene = scene
        self.node_id = node_id
        self.new_attrs = new_attrs
        self.old_attrs: dict = {}

    def redo(self):
        n = self.scene.graph.nodes.get(self.node_id)
        if n is None:
            return
        if not self.old_attrs:
            self.old_attrs = {k: getattr(n, k) for k in self.new_attrs}
        for k, v in self.new_attrs.items():
            setattr(n, k, v)
        item = self.scene.node_items.get(self.node_id)
        if item is not None:
            item.refresh()

    def undo(self):
        n = self.scene.graph.nodes.get(self.node_id)
        if n is None:
            return
        for k, v in self.old_attrs.items():
            setattr(n, k, v)
        item = self.scene.node_items.get(self.node_id)
        if item is not None:
            item.refresh()


class AddWaypointCmd(QUndoCommand):
    def __init__(self, scene: "MindMapScene", ci: "ConnectionItem", waypoint: Waypoint, index: int | None = None):
        super().__init__("Add waypoint")
        self.scene = scene
        self.ci = ci
        self.waypoint = waypoint
        self.index = index

    def redo(self):
        wps = self.ci.conn.waypoints
        if self.index is None:
            self.index = len(wps)
        wps.insert(self.index, self.waypoint)
        self.ci.rebuild_path()
        self.scene.rebuild_waypoint_handles(self.ci)

    def undo(self):
        wps = self.ci.conn.waypoints
        if 0 <= self.index < len(wps):
            del wps[self.index]
        self.ci.rebuild_path()
        self.scene.rebuild_waypoint_handles(self.ci)
