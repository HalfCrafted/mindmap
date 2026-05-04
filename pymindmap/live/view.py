"""LiveMindMapView — pan/zoom/marquee/shift-connect against LiveNodeItem."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTransform,
)
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsView,
)

from ..commands import AddConnectionCmd, AddNodeCmd, RemoveConnectionCmd
from ..items import ConnectionItem
from ..model import Connection, Node

from .items import LiveNodeItem


ZOOM_MIN = 0.1
ZOOM_MAX = 4.0
# Per-notch zoom factor. Smaller = finer control, more notches needed to
# reach a target. Exponential so every pixel/degree of input applies the
# same multiplier — feels linear to the eye regardless of current zoom.
ZOOM_PER_120 = 1.12
MARQUEE_FILL = "#7c7cf522"
MARQUEE_STROKE = "#7c7cf5"
PREVIEW_COLOR = "#7c7cf5"
KNIFE_COLOR = "#ff5a5a"


class LiveMindMapView(QGraphicsView):
    zoom_changed = pyqtSignal(float)

    def __init__(self, scene, undo_stack, parent=None):
        super().__init__(scene, parent)
        self.undo_stack = undo_stack
        self.setRenderHints(
            QPainter.Antialiasing
            | QPainter.SmoothPixmapTransform
            | QPainter.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # ViewCenter resize anchor keeps the scene steady when the window is
        # resized / moved between displays; AnchorUnderMouse here would shift
        # the view every time the cursor happened to be over a resize edge.
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFrameShape(QGraphicsView.NoFrame)
        # Background cache deliberately disabled. CacheBackground stretches
        # the cached pixmap during zoom (scale changes) until Qt rebuilds
        # it on the next paint, which produces a visible "ghost" of the
        # pre-scale grid for one frame and can read as a directional
        # glitch on every wheel notch.
        self.setCacheMode(QGraphicsView.CacheNone)

        self._panning = False
        self._pan_start: Optional[QPointF] = None
        # Sub-pixel pan accumulator: scrollbars only accept ints, so trackpad
        # pixelDelta events that report fractional or 1-pixel motion would
        # otherwise stair-step. We integrate fractions across events.
        self._pan_accum_x: float = 0.0
        self._pan_accum_y: float = 0.0

        self._marquee: Optional[QGraphicsRectItem] = None
        self._marquee_origin: Optional[QPointF] = None

        self._connecting_from: Optional[LiveNodeItem] = None
        self._preview_path: Optional[QGraphicsPathItem] = None

        # Knife tool: Alt+Left-drag paints a polyline; on release, any
        # connection whose path the line crosses is cut.
        self._knife_points: list = []
        self._knife_preview: Optional[QGraphicsPathItem] = None

    # ---- zoom / wheel-pan -------------------------------------------------
    def wheelEvent(self, event):
        """Wheel = zoom. Shift+wheel = horizontal pan. Trackpad 2-finger
        scroll pans the canvas; hold Ctrl to zoom instead.

        Trackpad vs wheel is detected via ``event.phase()`` — trackpads
        emit ScrollBegin/Update/End/Momentum phases, real mouse wheels
        emit NoScrollPhase. ``pixelDelta`` is unreliable for this on
        Linux + libinput because high-resolution mouse wheels populate
        pixelDelta in their smooth-scroll mode, and the old check would
        misclassify every wheel notch as a trackpad pan.
        """
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        mods = event.modifiers()
        phase = event.phase()
        is_continuous = phase != Qt.NoScrollPhase

        # Optional debug — set MINDMAP_WHEEL_DEBUG=1 to log wheel decisions.
        import os
        if os.environ.get("MINDMAP_WHEEL_DEBUG"):
            import sys
            print(
                f"wheel: pixel={pixel.x(),pixel.y()} angle={angle.x(),angle.y()} "
                f"phase={int(phase)} continuous={is_continuous} mods={int(mods)}",
                file=sys.stderr, flush=True,
            )

        # Trackpad continuous scroll: pan unless Ctrl is held (pinch zoom).
        if is_continuous and not (mods & Qt.ControlModifier):
            delta = pixel if not pixel.isNull() else angle
            self._pan_by_pixels(delta.x(), delta.y())
            event.accept()
            return

        # Mouse-wheel path (or Ctrl+anything).
        dy = angle.y() if not angle.isNull() else pixel.y()
        dx = angle.x() if not angle.isNull() else pixel.x()
        if dy == 0 and dx == 0:
            return

        # Shift+wheel → horizontal pan (common convention on mouse wheels).
        if mods & Qt.ShiftModifier:
            if dx == 0:
                dx, dy = dy, 0
            self._pan_by_pixels(dx or 0, dy or 0)
            event.accept()
            return

        # Zoom, anchored to the cursor.
        factor = ZOOM_PER_120 ** (dy / 120.0)
        self._zoom_by(factor, event.pos())
        event.accept()

    def _zoom_by(self, factor: float, anchor_pos):
        """Apply ``factor`` to the current zoom, anchored at ``anchor_pos``.

        Instant — no animation, no chase. Each event produces its full
        scale change on the same paint as the input, so wheel input maps
        1:1 to visible motion with zero perceived latency.
        """
        cur = self.current_scale()
        target = max(ZOOM_MIN, min(ZOOM_MAX, cur * factor))
        if abs(target / cur - 1.0) < 1e-4:
            return
        anchor_scene = self.mapToScene(anchor_pos)
        self._set_scale_anchored(target, anchor_scene, anchor_pos)

    def _set_scale_anchored(self, target_scale: float, anchor_scene, anchor_pos_view):
        """Set the absolute view scale, keeping ``anchor_scene`` pinned at
        ``anchor_pos_view`` in view coordinates."""
        cur = self.current_scale()
        f = target_scale / cur
        if abs(f - 1.0) < 1e-6:
            return
        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(f, f)
        after = self.mapToScene(anchor_pos_view)
        delta = after - anchor_scene
        self.translate(delta.x(), delta.y())
        self.setTransformationAnchor(old_anchor)
        self.zoom_changed.emit(self.current_scale())

    def _pan_by_pixels(self, dx: float, dy: float):
        """Scroll the viewport by ``dx, dy`` view-pixels.

        Scrollbars only accept ints, so we accumulate fractional deltas and
        emit whole-pixel steps when they pile up. This keeps high-DPI
        trackpad gestures from stair-stepping when each event reports a
        small pixelDelta.
        """
        if dx:
            self._pan_accum_x += dx
        if dy:
            self._pan_accum_y += dy
        int_dx = int(self._pan_accum_x)
        int_dy = int(self._pan_accum_y)
        self._pan_accum_x -= int_dx
        self._pan_accum_y -= int_dy
        if int_dx:
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - int_dx)
        if int_dy:
            sb = self.verticalScrollBar()
            sb.setValue(sb.value() - int_dy)

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
        # Middle-button, or right-button-on-empty-canvas, drags to pan.
        # Right-click on a node/edge still falls through so context menus
        # (and future right-click actions) keep working.
        if event.button() == Qt.MiddleButton:
            self._begin_pan(event.pos())
            event.accept()
            return
        if event.button() == Qt.RightButton and self.itemAt(event.pos()) is None:
            self._begin_pan(event.pos())
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            node = _closest_live_node(item)
            mods = event.modifiers()

            # Alt+Left-drag = knife: slice through connections to delete.
            # Checked first so it works regardless of what's under the
            # cursor (nodes don't block the knife).
            if mods & Qt.AltModifier:
                self._start_knife(event.pos())
                event.accept()
                return

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
        if self._knife_preview is not None:
            self._update_knife(event.pos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MiddleButton, Qt.RightButton) and self._panning:
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
        if event.button() == Qt.LeftButton and self._knife_preview is not None:
            self._finish_knife()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Only the left mouse button spawns a new node / opens the
        # inspector. Middle- and right-button double-clicks fall through
        # to the base class (right falls back to pan on empty canvas).
        if event.button() != Qt.LeftButton:
            super().mouseDoubleClickEvent(event)
            return
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
            # Shift-drag expresses hierarchy: src is the parent, target the
            # child. Mark directed so the arrow appears without the user
            # toggling it manually.
            conn = Connection(from_id=src.node.id, to_id=target.node.id, directed=True)
            self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
            return

        # Fell onto empty canvas → create a new linked note there.
        pt = self.mapToScene(pos)
        node = Node(id=self.scene().graph.allocate_id(),
                    x=pt.x() - 90, y=pt.y() - 28,
                    text="New note", width=180, height=56)
        conn = Connection(from_id=src.node.id, to_id=node.id, directed=True)
        self.undo_stack.beginMacro("Add linked note")
        self.undo_stack.push(AddNodeCmd(self.scene(), node))
        self.undo_stack.push(AddConnectionCmd(self.scene(), conn))
        self.undo_stack.endMacro()
        self.scene().request_edit(node.id)

    # ---- knife ------------------------------------------------------------
    def _start_knife(self, pos):
        self._knife_points = [self.mapToScene(pos)]
        path = QPainterPath()
        path.moveTo(self._knife_points[0])
        self._knife_preview = QGraphicsPathItem(path)
        pen = QPen(QColor(KNIFE_COLOR), 2.0, Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        self._knife_preview.setPen(pen)
        self._knife_preview.setZValue(1001)
        self._knife_preview.setAcceptedMouseButtons(Qt.NoButton)
        self.scene().addItem(self._knife_preview)
        self.viewport().setCursor(Qt.CrossCursor)

    def _update_knife(self, pos):
        if self._knife_preview is None:
            return
        pt = self.mapToScene(pos)
        # Skip near-duplicate points so the preview path stays cheap on
        # long sweeps — we still get a smooth polyline to intersect with.
        if self._knife_points:
            last = self._knife_points[-1]
            if abs(pt.x() - last.x()) < 0.5 and abs(pt.y() - last.y()) < 0.5:
                return
        self._knife_points.append(pt)
        path = QPainterPath()
        path.moveTo(self._knife_points[0])
        for p in self._knife_points[1:]:
            path.lineTo(p)
        self._knife_preview.setPath(path)

    def _finish_knife(self):
        if self._knife_preview is None:
            return
        pts = self._knife_points
        self.scene().removeItem(self._knife_preview)
        self._knife_preview = None
        self._knife_points = []
        self.viewport().setCursor(Qt.ArrowCursor)

        if len(pts) < 2:
            return

        path = QPainterPath()
        path.moveTo(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        # Stroke the knife path into a thin ribbon so QPainterPath.intersects
        # (which tests filled areas) actually detects crossings with the
        # stroked connection shapes. Width is scale-aware so the knife stays
        # usable when fully zoomed out.
        stroker = QPainterPathStroker()
        stroker.setWidth(max(2.0, 4.0 / max(self.current_scale(), 0.01)))
        knife_area = stroker.createStroke(path)

        to_remove = []
        for ci in list(self.scene().connection_items):
            if knife_area.intersects(ci.shape()):
                to_remove.append(ci.conn)
        if not to_remove:
            return

        if len(to_remove) > 1:
            self.undo_stack.beginMacro(f"Cut {len(to_remove)} connections")
        for conn in to_remove:
            self.undo_stack.push(RemoveConnectionCmd(self.scene(), conn))
        if len(to_remove) > 1:
            self.undo_stack.endMacro()

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
