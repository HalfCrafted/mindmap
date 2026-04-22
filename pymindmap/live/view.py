"""LiveMindMapView — pan/zoom/marquee/shift-connect against LiveNodeItem."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsView,
)

from ..commands import AddConnectionCmd, AddNodeCmd
from ..items import ConnectionItem
from ..model import Connection, Node

from .items import LiveNodeItem


ZOOM_MIN = 0.15
ZOOM_MAX = 3.5
ZOOM_FACTOR = 1.12
MARQUEE_FILL = "#7c7cf522"
MARQUEE_STROKE = "#7c7cf5"
PREVIEW_COLOR = "#7c7cf5"


class LiveMindMapView(QGraphicsView):
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
        self.setFrameShape(QGraphicsView.NoFrame)

        self._panning = False
        self._pan_start: Optional[QPointF] = None

        self._marquee: Optional[QGraphicsRectItem] = None
        self._marquee_origin: Optional[QPointF] = None

        self._connecting_from: Optional[LiveNodeItem] = None
        self._preview_path: Optional[QGraphicsPathItem] = None

    # ---- zoom -------------------------------------------------------------
    def wheelEvent(self, event):
        angle = event.angleDelta().y()
        if angle == 0:
            return
        factor = ZOOM_FACTOR if angle > 0 else 1 / ZOOM_FACTOR
        target = self.current_scale() * factor
        target = max(ZOOM_MIN, min(ZOOM_MAX, target))
        actual = target / self.current_scale()
        self.scale(actual, actual)
        self.zoom_changed.emit(self.current_scale())

    def current_scale(self) -> float:
        return self.transform().m11()

    def reset_view(self):
        self.setTransform(QTransform())
        self.centerOn(0, 0)
        self.zoom_changed.emit(1.0)

    def fit_all(self):
        items = [it for it in self.scene().items() if isinstance(it, LiveNodeItem)]
        if not items:
            return
        rect = items[0].sceneBoundingRect()
        for it in items[1:]:
            rect = rect.united(it.sceneBoundingRect())
        # Small, proportional padding — enough to breathe, not enough to
        # create a sea of dead space around a tight layout.
        pad = max(24.0, min(rect.width(), rect.height()) * 0.04)
        rect = rect.adjusted(-pad, -pad, pad, pad)
        self.fitInView(rect, Qt.KeepAspectRatio)
        self.zoom_changed.emit(self.current_scale())

    # ---- mouse ------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._begin_pan(event.pos())
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            node = _closest_live_node(item)
            mods = event.modifiers()

            if node is not None and (mods & Qt.ShiftModifier):
                self._start_connect(node, event.pos())
                event.accept()
                return

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
        item = self.itemAt(event.pos())
        if item is None:
            pt = self.mapToScene(event.pos())
            node = Node(id=self.scene().graph.allocate_id(), x=pt.x() - 90, y=pt.y() - 28,
                        text="New note", width=180, height=56)
            self.undo_stack.push(AddNodeCmd(self.scene(), node))
            it = self.scene().node_items.get(node.id)
            if it is not None:
                self.scene().clearSelection()
                it.setSelected(True)
            self.scene().request_edit(node.id)
            event.accept()
            return
        node = _closest_live_node(item)
        if node is not None:
            self.scene().request_edit(node.node.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
        self._marquee.setPen(QPen(QColor(MARQUEE_STROKE), 1, Qt.DashLine))
        self._marquee.setBrush(QBrush(QColor(MARQUEE_FILL)))
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
            if isinstance(it, (LiveNodeItem, ConnectionItem)):
                if rect.intersects(it.sceneBoundingRect()):
                    it.setSelected(True)
        self.scene().removeItem(self._marquee)
        self._marquee = None
        self._marquee_origin = None

    # ---- connect ----------------------------------------------------------
    def _start_connect(self, node: LiveNodeItem, pos):
        self._connecting_from = node
        self._preview_path = QGraphicsPathItem()
        pen = QPen(QColor(PREVIEW_COLOR), 2.0, Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        self._preview_path.setPen(pen)
        self._preview_path.setZValue(999)
        # Ignore mouse events on the preview so itemAt() never returns it,
        # which would otherwise mask the target node on release.
        self._preview_path.setAcceptedMouseButtons(Qt.NoButton)
        self._preview_path.setFlag(QGraphicsItem.ItemStacksBehindParent, False)
        self.scene().addItem(self._preview_path)
        self._update_preview(pos)

    def _update_preview(self, pos):
        if self._connecting_from is None or self._preview_path is None:
            return
        start = self._connecting_from.node.center()
        end = self.mapToScene(pos)
        path = QPainterPath()
        path.moveTo(start[0], start[1])
        dx = (end.x() - start[0]) * 0.5
        path.cubicTo(start[0] + dx, start[1], end.x() - dx, end.y(), end.x(), end.y())
        self._preview_path.setPath(path)

    def _finish_connect(self, pos):
        if self._connecting_from is None:
            return
        src = self._connecting_from
        self._connecting_from = None
        # Remove the preview BEFORE hit-testing so it can't mask the target.
        if self._preview_path is not None:
            self.scene().removeItem(self._preview_path)
            self._preview_path = None

        # Prefer scanning the whole stack at this point for a LiveNodeItem;
        # skips any other overlay item that might be on top.
        target = self._hit_live_node(pos)

        if target is not None and target is not src:
            # Don't duplicate an existing connection (either direction).
            for c in self.scene().graph.connections:
                if ((c.from_id == src.node.id and c.to_id == target.node.id)
                        or (c.from_id == target.node.id and c.to_id == src.node.id)):
                    return  # already connected — silently no-op
            conn = Connection(from_id=src.node.id, to_id=target.node.id)
            self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
            return

        # Fell onto empty canvas → create a new linked note there.
        pt = self.mapToScene(pos)
        node = Node(id=self.scene().graph.allocate_id(),
                    x=pt.x() - 90, y=pt.y() - 28,
                    text="New note", width=180, height=56)
        conn = Connection(from_id=src.node.id, to_id=node.id)
        self.undo_stack.beginMacro("Add linked note")
        self.undo_stack.push(AddNodeCmd(self.scene(), node))
        self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
        self.undo_stack.endMacro()
        self.scene().request_edit(node.id)

    def _hit_live_node(self, pos) -> Optional[LiveNodeItem]:
        """Walk items under *pos* top-to-bottom, return first LiveNodeItem."""
        for item in self.items(pos):
            node = _closest_live_node(item)
            if node is not None:
                return node
        return None


def _closest_live_node(item) -> Optional[LiveNodeItem]:
    while item is not None:
        if isinstance(item, LiveNodeItem):
            return item
        item = item.parentItem()
    return None
