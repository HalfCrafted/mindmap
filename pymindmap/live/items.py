"""Card-style node item for the live-layout variant.

A ``LiveNodeItem`` is rendered like a note card:

  ┌──────────────────────────────┐
  │ ▎Title                  [ 3 ]│   title row (accent bar + degree badge)
  ├──────────────────────────────┤
  │ First lines of the body      │   body preview (dim text)
  │ note, clipped with ellipsis  │
  └──────────────────────────────┘

Width/height are computed from title length, body preview, and connection
degree — so well-connected "hub" nodes are visibly larger, and nodes with
notes are taller than titles-only nodes.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QTextOption,
)
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QStyleOptionGraphicsItem,
    QWidget,
)

from ..model import Node

if TYPE_CHECKING:
    from .scene import LiveMindMapScene


# Card layout constants — leaves at the base size; hubs scale EXPONENTIALLY.
# Each additional connection multiplies the card's linear dimensions (and title
# font) by ``SCALE_BASE``. After ``SCALE_CAP`` is reached we stop growing to
# avoid pathological cases. Rationale: in a neural-network-like mind map, an
# idea linked to 6 others should look *dramatically* more prominent than one
# with 1 or 2 links — not just 30% bigger.
# Cards are sized to their CONTENT — width = text + symmetric gutters, no fixed
# minimum. Gutters scale with degree so hubs get more breathing room; leaves
# hug their text tightly.
PADDING_X = 14        # base horizontal padding (scales with degree)
PADDING_Y = 10        # base vertical padding
TITLE_SIZE = 12       # base title point size (degree 0)
BODY_SIZE = 10
BODY_MAX_LINES = 4
MIN_H = 44            # pill aesthetic floor

SCALE_BASE = 1.20     # per-connection linear multiplier
SCALE_CAP = 3.4       # cap reached near degree 7
MAX_TITLE_PT = 40
MAX_BODY_PT = 18
SAFETY_MAX_W = 820    # safety net for pathological titles

# Colors
CARD_BG = "#16161f"
CARD_BG_HOVER = "#1b1b26"
CARD_BG_SEL = "#20202c"
CARD_BORDER = "#26262f"
CARD_BORDER_SEL = "#7c7cf5"
CARD_TITLE = "#eaeaf2"
CARD_BODY = "#9a9ab0"
CARD_ACCENT = "#7c7cf5"
BADGE_BG = "#2a2a38"
BADGE_FG = "#c7c7d8"


class LiveNodeItem(QGraphicsObject):
    def __init__(self, node: Node, scene: "LiveMindMapScene"):
        super().__init__()
        self.node = node
        self._scene = scene
        self._hover = False

        # Positions are controlled by auto-layout — nodes are NOT user-movable.
        # Selection is still allowed (for inspecting / connecting).
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setPos(node.x, node.y)
        self.recompute_size()

    # ---- sizing -----------------------------------------------------------
    def degree(self) -> int:
        return self._scene.degree_of(self.node.id)

    def degree_scale(self) -> float:
        """Exponential multiplicative scale from degree. 1.20^degree, capped.

        Values: deg 0→1.00, 1→1.20, 2→1.44, 3→1.73, 4→2.07, 5→2.49, 6→2.99,
        7→3.40 (cap), 8+→3.40. Each connection boosts linear size by 20%
        (area by ~44%), so well-linked hubs are visually dominant.
        """
        return min(SCALE_CAP, SCALE_BASE ** self.degree())

    def _title_font(self) -> QFont:
        scale = self.degree_scale()
        size = min(MAX_TITLE_PT, max(TITLE_SIZE, int(round(TITLE_SIZE * scale))))
        f = QFont()
        f.setPointSize(size)
        # Weight also steps up with scale.
        if scale >= 2.0:
            f.setWeight(QFont.Bold)
        elif scale >= 1.3:
            f.setWeight(QFont.DemiBold)
        else:
            f.setWeight(QFont.Medium)
        return f

    def _body_font(self) -> QFont:
        # Body grows gently (sqrt of title scale) so it stays readable
        # rather than exploding alongside the title.
        scale = math.sqrt(self.degree_scale())
        size = min(MAX_BODY_PT, max(BODY_SIZE, int(round(BODY_SIZE * scale))))
        f = QFont()
        f.setPointSize(size)
        return f

    def recompute_size(self):
        """Size the card from its content with consistent, symmetric margins.

        The card hugs its text: width = ``text_w + 2 * gutter`` where ``gutter``
        is the larger of (button reservation, badge reservation, padding). No
        fixed minimum width — a single-word leaf gets a small pill, a hub with
        long text gets a wider pill, but both use the same margin rules.
        """
        deg = self.degree()
        scale = self.degree_scale()

        # Padding scales gently with degree — hubs get more breathing room.
        pad_scale = 0.75 + 0.25 * scale   # scale 1.0→1.00, 2.0→1.25, 3.0→1.50
        pad_x = PADDING_X * pad_scale
        pad_y = PADDING_Y * pad_scale

        title_font = self._title_font()
        title_fm = QFontMetricsF(title_font)
        title_text = self.node.text or "Untitled"

        # Natural text measurements.
        oneline_text = title_text.replace("\n", " ")
        oneline_w = title_fm.horizontalAdvance(oneline_text)
        longest_word_w = max(
            (title_fm.horizontalAdvance(w) for w in oneline_text.split() if w),
            default=oneline_w,
        )

        # Degree badge (top-right) — pill-shaped.
        badge_pt = min(18, max(9, int(round(10 * math.sqrt(scale)))))
        badge_font = QFont()
        badge_font.setPointSize(badge_pt)
        badge_font.setWeight(QFont.Bold)
        badge_fm = QFontMetricsF(badge_font)
        badge_w = max(24.0, badge_fm.horizontalAdvance(str(deg)) + 14.0) if deg > 0 else 0.0
        badge_h = max(20.0, badge_pt + 10)

        # Collapse chevron (top-left) — same pill as the badge.
        has_children = (self._scene is not None
                        and self._scene.has_descendants(self.node.id))
        button_w = badge_h if has_children else 0.0
        button_h = badge_h

        # Gutter = symmetric reserved space, sized to fit whichever side has
        # the larger icon. Ensures centered title sits visually centered no
        # matter which icons are shown.
        icon_inset = 8.0
        icon_gap = 10.0
        left_need = (icon_inset + button_w + icon_gap) if has_children else pad_x
        right_need = (icon_inset + badge_w + icon_gap) if deg > 0 else pad_x
        gutter = max(left_need, right_need, pad_x)

        # Wrap threshold scales with degree — hubs can fit longer single-line
        # titles before we break them. Leaves wrap sooner to stay compact.
        wrap_threshold = 220 + 140 * max(0.0, scale - 1.0)

        if oneline_w <= wrap_threshold:
            title_lines = [oneline_text if oneline_text else "Untitled"]
            text_w = oneline_w
        else:
            wrap_w = max(longest_word_w, wrap_threshold * 0.75)
            title_lines = _wrapped_lines(title_text, wrap_w, title_fm)
            text_w = max(
                (title_fm.horizontalAdvance(line) for line in title_lines),
                default=longest_word_w,
            )

        # Target width: text + symmetric gutters, never narrower than what
        # the longest word needs.
        target_w = text_w + 2 * gutter
        target_w = max(target_w, longest_word_w + 2 * gutter + 4)
        target_w = min(target_w, SAFETY_MAX_W)

        title_h = title_fm.lineSpacing() * len(title_lines)

        # Body lines (if any) — left-aligned inside pad_x on both sides.
        body_lines: list[str] = []
        body_h = 0.0
        body_fm = None
        body_left = pad_x
        if self.node.body.strip():
            body_font = self._body_font()
            body_fm = QFontMetricsF(body_font)
            body_content_w = target_w - 2 * pad_x
            body_lines = _wrapped_lines(self.node.body, body_content_w, body_fm,
                                        max_lines=BODY_MAX_LINES)
            body_h = body_fm.lineSpacing() * len(body_lines) + max(4.0, pad_y * 0.4)

        total_h = pad_y * 2 + title_h + body_h
        total_h = max(total_h, MIN_H)

        self.node.width = target_w
        self.node.height = total_h

        # Cache everything the painter needs.
        self._cached_title_font = title_font
        self._cached_title_fm = title_fm
        self._cached_title_lines = title_lines
        self._cached_title_h = title_h
        self._cached_title_gutter = gutter
        self._cached_title_content_w = target_w - 2 * gutter
        self._cached_title_y = pad_y
        self._cached_body_font = body_fm
        self._cached_body_lines = body_lines
        self._cached_body_left = body_left
        self._cached_badge_w = badge_w
        self._cached_badge_h = badge_h
        self._cached_badge_font = badge_font
        self._cached_has_children = has_children
        self._cached_button_w = button_w
        self._cached_button_h = button_h
        self._cached_pad_x = pad_x
        self._cached_pad_y = pad_y

    # ---- geometry ---------------------------------------------------------
    def boundingRect(self) -> QRectF:
        return QRectF(-2, -2, self.node.width + 4, self.node.height + 6)  # +shadow room

    def shape(self) -> QPainterPath:
        p = QPainterPath()
        p.addRoundedRect(0, 0, self.node.width, self.node.height, 10, 10)
        return p

    # ---- paint ------------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.node.width, self.node.height
        radius = min(w, h) / 2.0        # true pill shape — fully rounded ends
        card_rect = QRectF(0.0, 0.0, w, h)

        # ---- Drop shadow ----------------------------------------------------
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 95)))
        painter.drawRoundedRect(QRectF(0.0, 3.5, w, h), radius, radius)

        # ---- Bubbly gradient fill ------------------------------------------
        if self.isSelected():
            base = QColor(CARD_BG_SEL)
        elif self._hover:
            base = QColor(CARD_BG_HOVER)
        else:
            base = QColor(CARD_BG)
        top_col = _shift(base, 22)
        bot_col = _shift(base, -14)
        body_grad = QLinearGradient(0.0, 0.0, 0.0, h)
        body_grad.setColorAt(0.0, top_col)
        body_grad.setColorAt(1.0, bot_col)
        painter.setBrush(QBrush(body_grad))
        border_col = CARD_BORDER_SEL if self.isSelected() else CARD_BORDER
        painter.setPen(QPen(QColor(border_col), 1.3))
        painter.drawRoundedRect(card_rect, radius, radius)

        # ---- Inner glass highlight (bevel) ---------------------------------
        hl_grad = QLinearGradient(0.0, 0.0, 0.0, h * 0.55)
        hl_grad.setColorAt(0.0, QColor(255, 255, 255, 55))
        hl_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(hl_grad))
        painter.setPen(Qt.NoPen)
        inset = 1.4
        inner_rect = QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
        inner_r = max(1.0, radius - inset)
        painter.drawRoundedRect(inner_rect, inner_r, inner_r)

        # ---- Accent cap (left rounded end, only if node has a color) ------
        if self.node.color and self.node.color != "none":
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(card_rect, radius, radius)
            painter.setClipPath(clip)
            painter.setPen(Qt.NoPen)
            accent_grad = QLinearGradient(0.0, 0.0, 0.0, h)
            painter.setBrush(QBrush(_shift(QColor(self.node.color), 20)))
            # Thin strip that runs vertically at the very left; clipped to pill.
            painter.drawRect(QRectF(0.0, 0.0, 5.0, h))
            painter.restore()

        # ---- Icon row (badge + collapse chevron) ---------------------------
        # Align with the vertical center of the FIRST title line so icons
        # don't drift down when titles wrap to multiple lines.
        first_line_center_y = (self._cached_title_y
                               + self._cached_title_fm.lineSpacing() / 2.0)

        deg = self.degree()
        if deg > 0:
            bw = self._cached_badge_w
            bh = self._cached_badge_h
            bx = w - bw - 8.0
            by = first_line_center_y - bh / 2.0
            painter.setFont(self._cached_badge_font)
            painter.setBrush(QBrush(QColor(BADGE_BG)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(bx, by, bw, bh), bh / 2.0, bh / 2.0)
            painter.setPen(QPen(QColor(BADGE_FG)))
            painter.drawText(QRectF(bx, by, bw, bh), Qt.AlignCenter, str(deg))

        if self._cached_has_children:
            bw = self._cached_button_w
            bh = self._cached_button_h
            bx = 8.0
            by = first_line_center_y - bh / 2.0
            self._button_rect = QRectF(bx, by, bw, bh)
            painter.setBrush(QBrush(QColor(BADGE_BG)))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(self._button_rect, bh / 2.0, bh / 2.0)
            # Chevron: ▼ expanded, ▶ collapsed.
            painter.setPen(QPen(QColor(BADGE_FG), 1.8))
            cx = bx + bw / 2.0
            cy = by + bh / 2.0
            s = min(bw, bh) * 0.28
            path = QPainterPath()
            if self.node.collapsed:
                path.moveTo(cx - s * 0.5, cy - s)
                path.lineTo(cx + s * 0.7, cy)
                path.lineTo(cx - s * 0.5, cy + s)
            else:
                path.moveTo(cx - s, cy - s * 0.5)
                path.lineTo(cx, cy + s * 0.7)
                path.lineTo(cx + s, cy - s * 0.5)
            painter.drawPath(path)
        else:
            self._button_rect = None

        # ---- Title (centered) ----------------------------------------------
        painter.setFont(self._cached_title_font)
        painter.setPen(QPen(QColor(CARD_TITLE)))
        title_rect = QRectF(
            self._cached_title_gutter,
            self._cached_title_y,
            self._cached_title_content_w,
            self._cached_title_h + 2,
        )
        opt = QTextOption()
        opt.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        opt.setWrapMode(QTextOption.WordWrap)
        painter.drawText(title_rect, self.node.text or "Untitled", opt)

        # ---- Body (left-aligned for readability) ---------------------------
        if self._cached_body_lines:
            body_font = self._body_font()
            painter.setFont(body_font)
            painter.setPen(QPen(QColor(CARD_BODY)))
            body_fm = QFontMetricsF(body_font)
            by = self._cached_title_y + self._cached_title_h + 6.0
            for i, line in enumerate(self._cached_body_lines):
                if i == BODY_MAX_LINES - 1 and len(self._cached_body_lines) == BODY_MAX_LINES:
                    line = _elide(line, w - 2 * self._cached_body_left, body_fm)
                painter.drawText(QPointF(self._cached_body_left, by + body_fm.ascent()), line)
                by += body_fm.lineSpacing()

    # ---- events -----------------------------------------------------------
    def hoverEnterEvent(self, e):
        self._hover = True
        self.update()
    def hoverLeaveEvent(self, e):
        self._hover = False
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Layout/animation updates node.x/y directly; keep them in sync
            # on any programmatic move.
            self.node.x = self.pos().x()
            self.node.y = self.pos().y()
            if self._scene is not None:
                self._scene.refresh_connections_for(self.node.id)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        # Intercept clicks on the collapse chevron before selection happens.
        btn = getattr(self, "_button_rect", None)
        if (btn is not None and event.button() == Qt.LeftButton
                and self._cached_has_children and btn.contains(event.pos())):
            if self._scene is not None:
                self._scene.toggle_collapse(self.node.id)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Don't open the editor when double-clicking the chevron.
        btn = getattr(self, "_button_rect", None)
        if btn is not None and self._cached_has_children and btn.contains(event.pos()):
            event.accept()
            return
        if self._scene is not None:
            self._scene.request_edit(self.node.id)
        event.accept()

    def refresh(self):
        self.prepareGeometryChange()
        self.recompute_size()
        self.setPos(self.node.x, self.node.y)
        self.update()
        if self._scene is not None:
            self._scene.refresh_connections_for(self.node.id)

    def notify_connections(self):
        """Compatibility shim for commands.MoveNodesCmd."""
        if self._scene is not None:
            self._scene.refresh_connections_for(self.node.id)


# ---------------------------------------------------------------------------
# text layout helpers
# ---------------------------------------------------------------------------
def _wrapped_lines(text: str, max_width: float, fm: QFontMetricsF,
                   max_lines: int | None = None) -> list[str]:
    """Wrap at whitespace; never split words. Honors explicit \\n in input."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip() and paragraph == "":
            lines.append("")
            continue
        words = paragraph.split(" ")
        cur = ""
        for w in words:
            candidate = (cur + " " + w).strip() if cur else w
            if fm.horizontalAdvance(candidate) <= max_width or not cur:
                cur = candidate
            else:
                lines.append(cur)
                cur = w
                if max_lines and len(lines) >= max_lines:
                    return lines[:max_lines]
        if cur:
            lines.append(cur)
            if max_lines and len(lines) >= max_lines:
                return lines[:max_lines]
    return lines


def _elide(text: str, max_width: float, fm: QFontMetricsF) -> str:
    if fm.horizontalAdvance(text) <= max_width:
        return text
    ell = "…"
    while text and fm.horizontalAdvance(text + ell) > max_width:
        text = text[:-1]
    return text + ell


def _shift(color: QColor, delta: int) -> QColor:
    """Return *color* with each RGB channel brightened (+) or darkened (-)."""
    r = max(0, min(255, color.red() + delta))
    g = max(0, min(255, color.green() + delta))
    b = max(0, min(255, color.blue() + delta))
    out = QColor(r, g, b)
    out.setAlpha(color.alpha())
    return out
