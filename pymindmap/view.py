"""MindMapView: pan (middle-drag or space+left), zoom (wheel), box-select, drag-to-connect."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsView,
    QRubberBand,
)

from .commands import AddConnectionCmd, AddNodeCmd
from .geometry import route_bezier
from .items import ConnectionItem, NodeItem
from .model import Connection, Node
from .theme import THEME

ZOOM_MIN = 0.1
ZOOM_MAX = 5.0
ZOOM_FACTOR = 1.15


class MindMapView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

    def __init__(self, scene, undo_stack, parent=None):
        super().__init__(scene, parent)
        self.undo_stack = undo_stack
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)

        # Panning state
        self._panning = False
        self._pan_start: Optional[QPointF] = None

        # Rubber band (box select)
        self._marquee: Optional[QGraphicsRectItem] = None
        self._marquee_origin: Optional[QPointF] = None

        # Drag-to-connect state
        self._connecting_from: Optional[NodeItem] = None
        self._preview_path: Optional[QGraphicsPathItem] = None

    # ---- zoom -------------------------------------------------------------
    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = ZOOM_FACTOR if angle > 0 else 1 / ZOOM_FACTOR
        new_scale = self.current_scale() * factor
        new_scale = max(ZOOM_MIN, min(ZOOM_MAX, new_scale))
        actual = new_scale / self.current_scale()
        self.scale(actual, actual)
        self.zoom_changed.emit(self.current_scale())

    def current_scale(self) -> float:
        return self.transform().m11()

    def reset_view(self):
        self.setTransform(QTransform())
        self.centerOn(0, 0)
        self.zoom_changed.emit(1.0)

    def fit_all(self):
        s = self.scene()
        items = [it for it in s.items() if isinstance(it, NodeItem)]
        if not items:
            return
        rect = items[0].sceneBoundingRect()
        for it in items[1:]:
            rect = rect.united(it.sceneBoundingRect())
        rect = rect.adjusted(-80, -80, 80, 80)
        self.fitInView(rect, Qt.KeepAspectRatio)
        self.zoom_changed.emit(self.current_scale())

    # ---- mouse ------------------------------------------------------------
    def mousePressEvent(self, event):
        # Middle button: pan.
        if event.button() == Qt.MiddleButton:
            self._begin_pan(event.pos())
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            node = _closest_node_item(item)
            mods = event.modifiers()

            # Shift+drag from a node → create connection.
            if node is not None and (mods & Qt.ShiftModifier):
                self._start_connect(node, event.pos())
                event.accept()
                return

            # Left on empty space → marquee select.
            if item is None:
                self._start_marquee(event.pos(), additive=bool(mods & Qt.ShiftModifier))
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            self._do_pan(event.pos())
            event.accept()
            return
        if self._marquee is not None:
            self._update_marquee(event.pos())
            event.accept()
            return
        if self._connecting_from is not None:
            self._update_preview(event.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._panning:
            self._end_pan()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._marquee is not None:
            self._finish_marquee()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._connecting_from is not None:
            self._finish_connect(event.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Double-click empty space → create node.
        item = self.itemAt(event.pos())
        if item is None:
            pt = self.mapToScene(event.pos())
            node = Node(id=self.scene().graph.allocate_id(), x=pt.x() - 60, y=pt.y() - 20,
                        text="New node", width=120, height=60)
            self.undo_stack.push(AddNodeCmd(self.scene(), node))
            ni = self.scene().node_items[node.id]
            ni.setSelected(True)
            ni.start_edit()
            event.accept()
            return

        # Double-click on connection → add a waypoint at click position.
        ci = _closest_connection_item(item)
        if ci is not None:
            from .model import Waypoint
            from .commands import AddWaypointCmd
            pt = self.mapToScene(event.pos())
            # Insert waypoint, sorted by nearest-position on curve.
            wp = Waypoint(x=pt.x(), y=pt.y())
            self.undo_stack.push(AddWaypointCmd(self.scene(), ci, wp))
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    # ---- keyboard pan (space+drag is not required; middle-drag is primary) ----
    def keyPressEvent(self, event):
        # Middle-drag handles panning; keys handled by MainWindow via QAction shortcuts.
        super().keyPressEvent(event)

    # ---- pan --------------------------------------------------------------
    def _begin_pan(self, pos):
        self._panning = True
        self._pan_start = pos
        self.setCursor(Qt.ClosedHandCursor)

    def _do_pan(self, pos):
        if self._pan_start is None:
            return
        delta = pos - self._pan_start
        self._pan_start = pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())

    def _end_pan(self):
        self._panning = False
        self._pan_start = None
        self.setCursor(Qt.ArrowCursor)

    # ---- marquee ----------------------------------------------------------
    def _start_marquee(self, pos, *, additive: bool):
        if not additive:
            self.scene().clearSelection()
        self._marquee_origin = self.mapToScene(pos)
        self._marquee = QGraphicsRectItem(QRectF(self._marquee_origin, self._marquee_origin))
        self._marquee.setPen(QPen(QColor(THEME.marquee_stroke), 1, Qt.DashLine))
        self._marquee.setBrush(QBrush(QColor(THEME.marquee_fill)))
        self._marquee.setZValue(1000)
        self.scene().addItem(self._marquee)

    def _update_marquee(self, pos):
        if self._marquee is None or self._marquee_origin is None:
            return
        cur = self.mapToScene(pos)
        self._marquee.setRect(QRectF(self._marquee_origin, cur).normalized())

    def _finish_marquee(self):
        if self._marquee is None:
            return
        rect = self._marquee.rect()
        for it in self.scene().items():
            if isinstance(it, (NodeItem, ConnectionItem)):
                if rect.intersects(it.sceneBoundingRect()):
                    it.setSelected(True)
        self.scene().removeItem(self._marquee)
        self._marquee = None
        self._marquee_origin = None

    # ---- connect ----------------------------------------------------------
    def _start_connect(self, node: NodeItem, pos):
        self._connecting_from = node
        self._preview_path = QGraphicsPathItem()
        pen = QPen(QColor(THEME.conn_color), THEME.conn_width, Qt.DashLine)
        self._preview_path.setPen(pen)
        self._preview_path.setZValue(999)
        self.scene().addItem(self._preview_path)
        self._update_preview(pos)

    def _update_preview(self, pos):
        if self._connecting_from is None or self._preview_path is None:
            return
        start = self._connecting_from.node.center()
        end = self.mapToScene(pos)
        path = QPainterPath()
        path.moveTo(start[0], start[1])
        # Simple cubic preview
        dx = (end.x() - start[0]) * 0.5
        path.cubicTo(start[0] + dx, start[1], end.x() - dx, end.y(), end.x(), end.y())
        self._preview_path.setPath(path)

    def _finish_connect(self, pos):
        if self._connecting_from is None:
            return
        target_item = self.itemAt(pos)
        target = _closest_node_item(target_item)
        src = self._connecting_from
        self._connecting_from = None
        if self._preview_path is not None:
            self.scene().removeItem(self._preview_path)
            self._preview_path = None

        if target is not None and target is not src:
            conn = Connection(from_id=src.node.id, to_id=target.node.id)
            self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
        else:
            # Drag to empty space → create new node and connect.
            pt = self.mapToScene(pos)
            node = Node(id=self.scene().graph.allocate_id(),
                        x=pt.x() - 60, y=pt.y() - 20,
                        text="New node", width=120, height=60)
            conn = Connection(from_id=src.node.id, to_id=node.id)
            # One macro: add node, then add connection.
            self.undo_stack.beginMacro("Add node and connection")
            self.undo_stack.push(AddNodeCmd(self.scene(), node))
            self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
            self.undo_stack.endMacro()


def _closest_node_item(item) -> Optional[NodeItem]:
    """Walk up parent chain until we hit a NodeItem, or None."""
    while item is not None:
        if isinstance(item, NodeItem):
            return item
        item = item.parentItem()
    return None


def _closest_connection_item(item) -> Optional[ConnectionItem]:
    while item is not None:
        if isinstance(item, ConnectionItem):
            return item
        item = item.parentItem()
    return None
