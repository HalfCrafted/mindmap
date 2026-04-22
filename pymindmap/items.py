"""QGraphicsItem subclasses: NodeItem, ConnectionItem, WaypointItem."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QTextOption,
)
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from .geometry import route_bezier
from .model import Connection, Node, Waypoint
from .theme import THEME

if TYPE_CHECKING:
    from .scene import MindMapScene


# ---------------------------------------------------------------------------
# NodeItem
# ---------------------------------------------------------------------------
class NodeItem(QGraphicsObject):
    """Renders a single Node. Position is the node's top-left in scene coords."""

    HANDLE_SIZE = 10  # resize grip size

    def __init__(self, node: Node, scene: "MindMapScene"):
        super().__init__()
        self.node = node
        self._scene = scene
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(node.x, node.y)

        # Inline text editor (child item, not focus by default).
        self._text_item = QGraphicsTextItem(node.text, self)
        self._text_item.setDefaultTextColor(QColor(THEME.node_text))
        self._text_item.setTextInteractionFlags(Qt.NoTextInteraction)
        self._apply_font()
        self._layout_text()

        self._resizing = False
        self._resize_start: Optional[QPointF] = None
        self._size_at_resize = (node.width, node.height)

    # ---- geometry ---------------------------------------------------------
    def boundingRect(self) -> QRectF:
        # Include a small margin for the resize handle.
        return QRectF(0, 0, self.node.width, self.node.height).adjusted(-1, -1, self.HANDLE_SIZE, self.HANDLE_SIZE)

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(0, 0, self.node.width, self.node.height, THEME.node_radius, THEME.node_radius)
        return p

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.Antialiasing)

        # Body
        rect = QRectF(0, 0, self.node.width, self.node.height)
        painter.setBrush(QBrush(QColor(THEME.node_bg)))
        border = THEME.node_border_selected if self.isSelected() else THEME.node_border
        painter.setPen(QPen(QColor(border), 1.5))
        painter.drawRoundedRect(rect, THEME.node_radius, THEME.node_radius)

        # Header bar (colored)
        if self.node.color and self.node.color != "none":
            header = QRectF(0, 0, self.node.width, THEME.node_header_height)
            clip = QPainterPath()
            clip.addRoundedRect(rect, THEME.node_radius, THEME.node_radius)
            painter.save()
            painter.setClipPath(clip)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(self.node.color)))
            painter.drawRect(header)
            painter.restore()

        # Note indicator: small dot top-right when node has body text.
        if self.node.body:
            r = 3.0
            cx = self.node.width - 8
            cy = THEME.node_header_height + 8
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor("#9ca3af")))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Resize handle (subtle corner square when hovered/selected).
        if self.isSelected():
            hs = self.HANDLE_SIZE
            hx = self.node.width - hs
            hy = self.node.height - hs
            painter.setPen(QPen(QColor(THEME.node_border_selected), 1))
            painter.setBrush(QBrush(QColor(THEME.node_border_selected)))
            painter.drawRect(QRectF(hx, hy, hs, hs))

    # ---- helpers ----------------------------------------------------------
    def _apply_font(self):
        f = QFont()
        f.setPointSize(max(6, self.node.font_size - 2))
        f.setBold(self.node.bold)
        f.setItalic(self.node.italic)
        self._text_item.setFont(f)

    def _layout_text(self):
        doc = self._text_item.document()

        # Word-wrap only at whitespace — never split a word across lines.
        opt = doc.defaultTextOption()
        align_map = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}
        opt.setAlignment(align_map.get(self.node.align, Qt.AlignHCenter))
        opt.setWrapMode(QTextOption.WordWrap)
        doc.setDefaultTextOption(opt)

        # Grow node width if the longest word doesn't fit. Otherwise Qt would
        # either break it mid-word or overflow the node box.
        fm = QFontMetricsF(self._text_item.font())
        longest_word_w = 0.0
        for line in self.node.text.split("\n"):
            for word in line.split():
                w = fm.horizontalAdvance(word)
                if w > longest_word_w:
                    longest_word_w = w
        required_w = longest_word_w + 2 * THEME.node_padding + 2  # +2 safety
        size_changed = False
        if self.node.width < required_w:
            self.node.width = required_w
            size_changed = True

        doc.setTextWidth(self.node.width - 2 * THEME.node_padding)

        # Grow height if wrapped text is taller than the node.
        text_h = doc.size().height()
        required_h = text_h + 2 * THEME.node_padding
        required_h = max(required_h, THEME.node_min_height)
        if self.node.height < required_h:
            self.node.height = required_h
            size_changed = True

        if size_changed:
            self.prepareGeometryChange()
            self.notify_connections()

        # Center vertically (account for header).
        self._text_item.setPos(
            THEME.node_padding,
            max(THEME.node_header_height, (self.node.height - text_h) / 2),
        )

    def refresh(self):
        """Call after mutating the underlying Node."""
        self.prepareGeometryChange()
        self.setPos(self.node.x, self.node.y)
        self._text_item.setPlainText(self.node.text)
        self._apply_font()
        self._layout_text()
        self.update()
        self.notify_connections()

    def notify_connections(self):
        if self._scene is not None:
            self._scene.refresh_connections_for(self.node.id)

    # ---- events -----------------------------------------------------------
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            self.notify_connections()
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        # Start resize if click is in handle corner.
        if event.button() == Qt.LeftButton:
            hs = self.HANDLE_SIZE
            hx = self.node.width - hs
            hy = self.node.height - hs
            if event.pos().x() >= hx and event.pos().y() >= hy:
                self._resizing = True
                self._resize_start = event.scenePos()
                self._size_at_resize = (self.node.width, self.node.height)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_start is not None:
            delta = event.scenePos() - self._resize_start
            new_w = max(THEME.node_min_width, self._size_at_resize[0] + delta.x())
            new_h = max(THEME.node_min_height, self._size_at_resize[1] + delta.y())
            self.prepareGeometryChange()
            self.node.width = new_w
            self.node.height = new_h
            self._layout_text()
            self.notify_connections()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.start_edit()
        event.accept()

    def start_edit(self):
        self._text_item.setTextInteractionFlags(Qt.TextEditorInteraction)
        self._text_item.setFocus(Qt.MouseFocusReason)
        cursor = self._text_item.textCursor()
        cursor.select(cursor.Document)
        self._text_item.setTextCursor(cursor)

    def stop_edit(self):
        self._text_item.setTextInteractionFlags(Qt.NoTextInteraction)
        self.node.text = self._text_item.toPlainText()
        self._layout_text()


# ---------------------------------------------------------------------------
# ConnectionItem
# ---------------------------------------------------------------------------
class ConnectionItem(QGraphicsObject):
    def __init__(self, conn: Connection, scene: "MindMapScene"):
        super().__init__()
        self.conn = conn
        self._scene = scene
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(-1)  # render behind nodes
        self._path = QPainterPath()
        self._bbox = QRectF()
        self.rebuild_path()

    def rebuild_path(self):
        self.prepareGeometryChange()
        nodes = self._scene.graph.nodes
        if self.conn.from_id not in nodes or self.conn.to_id not in nodes:
            self._path = QPainterPath()
            self._bbox = QRectF()
            return
        pts = route_bezier(self.conn, nodes)
        path = QPainterPath()
        if pts:
            path.moveTo(pts[0][0], pts[0][1])
            i = 1
            while i + 2 < len(pts):
                c1 = pts[i]
                c2 = pts[i + 1]
                p = pts[i + 2]
                path.cubicTo(c1[0], c1[1], c2[0], c2[1], p[0], p[1])
                i += 3
        self._path = path
        self._bbox = path.boundingRect().adjusted(-6, -6, 6, 6)
        self.update()

    def boundingRect(self) -> QRectF:
        return self._bbox

    def shape(self) -> QPainterPath:
        stroker = _stroker(12.0)
        return stroker.createStroke(self._path)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.Antialiasing)
        col = THEME.conn_selected if self.isSelected() else THEME.conn_color
        pen = QPen(QColor(col), THEME.conn_width + (1 if self.isSelected() else 0))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(self._path)


def _stroker(width: float):
    from PyQt5.QtGui import QPainterPathStroker
    s = QPainterPathStroker()
    s.setWidth(width)
    return s


# ---------------------------------------------------------------------------
# WaypointItem (small draggable handles on a selected connection)
# ---------------------------------------------------------------------------
class WaypointItem(QGraphicsObject):
    RADIUS = 5.0

    def __init__(self, conn_item: ConnectionItem, index: int):
        super().__init__()
        self.conn_item = conn_item
        self.index = index
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(10)
        w = conn_item.conn.waypoints[index]
        self.setPos(w.x, w.y)

    def boundingRect(self) -> QRectF:
        r = self.RADIUS + 2
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#0a0a0a"), 1.5))
        painter.setBrush(QBrush(QColor(THEME.waypoint_color)))
        painter.drawEllipse(QPointF(0, 0), self.RADIUS, self.RADIUS)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            w = self.conn_item.conn.waypoints[self.index]
            w.x = self.pos().x()
            w.y = self.pos().y()
            self.conn_item.rebuild_path()
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event):
        # Remove waypoint on double-click
        conn = self.conn_item.conn
        if 0 <= self.index < len(conn.waypoints):
            del conn.waypoints[self.index]
            self.conn_item._scene.rebuild_waypoint_handles(self.conn_item)
            self.conn_item.rebuild_path()
        event.accept()
