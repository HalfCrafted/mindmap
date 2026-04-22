"""LiveMainWindow — modern UI with prominent notes, live auto-layout."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QToolButton,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from .. import io as mio
from ..commands import (
    EditNodeCmd,
    RemoveConnectionCmd,
    RemoveNodesCmd,
    SwapConnectionDirectionCmd,
    ToggleConnectionDirectionCmd,
)
from ..items import ConnectionItem
from ..model import Graph, Node

from .items import LiveNodeItem
from .scene import LiveMindMapScene
from .view import LiveMindMapView


# Modern palette
ACCENT = "#7c7cf5"
TEXT = "#e9e9ef"
TEXT_DIM = "#9a9ab0"
SURFACE_0 = "#0b0b10"
SURFACE_1 = "#12121a"
SURFACE_2 = "#17171f"
SURFACE_3 = "#1e1e28"
BORDER = "#26262f"
SWATCHES = ["#7c7cf5", "#22c55e", "#ef4444", "#f59e0b",
            "#06b6d4", "#a855f7", "#ec4899", "#10b981"]


APP_QSS = f"""
QMainWindow, QWidget#Sidebar, QWidget#TopBar {{
    background: {SURFACE_0};
    color: {TEXT};
}}

/* Top bar */
QWidget#TopBar {{
    border-bottom: 1px solid {BORDER};
}}
QLabel#AppTitle {{
    color: {TEXT};
    font-size: 14px;
    font-weight: 600;
    padding-left: 4px;
}}
QLabel#AppSubtitle {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

/* Icon buttons on top bar */
QToolButton {{
    background: transparent;
    color: {TEXT};
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}}
QToolButton:hover {{
    background: {SURFACE_2};
}}
QToolButton:checked {{
    background: {ACCENT};
    color: white;
}}
QToolButton:pressed {{
    background: {SURFACE_3};
}}

/* Sidebar */
QWidget#Sidebar {{
    border-left: 1px solid {BORDER};
}}
QLabel#SidebarHeader {{
    color: {TEXT_DIM};
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding-top: 4px;
    padding-bottom: 2px;
}}
QLabel#SidebarTitle {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 600;
}}
QLabel#SidebarHint {{
    color: {TEXT_DIM};
    font-size: 12px;
}}

/* Fields */
QLineEdit, QTextEdit, QComboBox {{
    background: {SURFACE_1};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit#TitleInput {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
    color: {TEXT};
    font-size: 18px;
    font-weight: 600;
    padding: 6px 0;
}}
QLineEdit#TitleInput:focus {{
    border-bottom: 1px solid {ACCENT};
}}
QTextEdit#BodyEditor {{
    font-size: 13px;
    line-height: 140%;
    padding: 10px 12px;
}}
QLineEdit#SearchField {{
    background: {SURFACE_1};
    min-width: 180px;
}}

/* Pill checkbox-like */
QCheckBox {{
    color: {TEXT};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {SURFACE_1};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}

/* Divider */
QFrame#Divider {{
    color: {BORDER};
    background: {BORDER};
    max-height: 1px;
    min-height: 1px;
}}

/* Status bar */
QStatusBar {{
    background: {SURFACE_0};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
}}

/* ComboBox arrow */
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}

/* Scrollbars - slim */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {SURFACE_3};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


class LiveMainWindow(QMainWindow):
    def __init__(self, graph: Optional[Graph] = None):
        super().__init__()
        self.setWindowTitle("pymindmap · live")
        self.resize(1400, 880)
        self.setStyleSheet(APP_QSS)

        self.current_path: Optional[Path] = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(200)

        self.scene = LiveMindMapScene(graph if graph is not None else Graph())
        self.view = LiveMindMapView(self.scene, self.undo_stack)

        # Layout: central = top bar + splitter(view | sidebar)
        root = QWidget()
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        vbox.addWidget(self._build_top_bar())
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self._build_sidebar())
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([1000, 400])
        self.splitter.setHandleWidth(1)
        vbox.addWidget(self.splitter, 1)

        self._build_statusbar()
        self._build_shortcuts()

        # Signals
        self.scene.selectionChanged.connect(self._sync_inspector)
        self.scene.selectionChanged.connect(self._on_selection_for_focus)
        self.scene.edit_requested.connect(self._open_in_inspector)
        self.scene.layout_started.connect(lambda: self._status_label.setText("Arranging…"))
        self.scene.layout_finished.connect(self._refresh_counts)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.undo_stack.cleanChanged.connect(self._update_title)
        self.undo_stack.indexChanged.connect(lambda *_: self._update_title())

        # Starter node if empty.
        if graph is None or not graph.nodes:
            n = Node(id=self.scene.graph.allocate_id(), x=-90, y=-28,
                     text="Start here", body="Double-click the canvas to create a note.\n\n"
                                              "Shift+drag from a node to link to another node "
                                              "(or to empty space to create a new linked note).",
                     width=180, height=56)
            self.scene.add_node(n)

        self._sync_inspector()
        self.view.reset_view()

    # ---- top bar ----------------------------------------------------------
    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(14, 8, 12, 8)
        h.setSpacing(6)

        title = QLabel("pymindmap")
        title.setObjectName("AppTitle")
        h.addWidget(title)
        subtitle = QLabel("· live")
        subtitle.setObjectName("AppSubtitle")
        h.addWidget(subtitle)

        h.addSpacing(12)

        def icon_btn(label: str, tip: str, slot, *, checkable: bool = False, shortcut: str | None = None):
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip + (f"  ({shortcut})" if shortcut else ""))
            b.setCheckable(checkable)
            if shortcut:
                a = QAction(self)
                a.setShortcut(QKeySequence(shortcut))
                a.triggered.connect(slot if not checkable else lambda: b.toggle())
                self.addAction(a)
            b.clicked.connect(slot if not checkable else (lambda *_: None))
            if checkable:
                b.toggled.connect(slot)
            h.addWidget(b)
            return b

        icon_btn("New", "New map", self.new_file, shortcut="Ctrl+N")
        icon_btn("Open", "Open map", self.open_file, shortcut="Ctrl+O")
        icon_btn("Save", "Save map", self.save_file, shortcut="Ctrl+S")

        sep = QFrame(); sep.setFrameShape(QFrame.VLine); sep.setStyleSheet(f"color:{BORDER};")
        h.addWidget(sep)

        icon_btn("Undo", "Undo", self.undo_stack.undo, shortcut="Ctrl+Z")
        icon_btn("Redo", "Redo", self.undo_stack.redo, shortcut="Ctrl+Y")

        sep2 = QFrame(); sep2.setFrameShape(QFrame.VLine); sep2.setStyleSheet(f"color:{BORDER};")
        h.addWidget(sep2)

        icon_btn("Add note", "Add note at center", self.add_note_at_center, shortcut="Shift+A")
        icon_btn("Fit", "Fit all to view", self.view.fit_all, shortcut=".")
        icon_btn("Re-arrange", "Re-run auto-layout", self.scene.schedule_layout, shortcut="Ctrl+L")

        h.addStretch(1)

        # Focus toggle
        self._focus_btn = icon_btn("Focus", "Dim non-neighbors of selected node", self._on_focus_toggled,
                                   checkable=True, shortcut="F")

        # Depth selector
        self._focus_depth_combo = QComboBox()
        self._focus_depth_combo.addItems(["1", "2", "3", "4", "∞"])
        self._focus_depth_combo.setCurrentIndex(1)
        self._focus_depth_combo.setFixedWidth(56)
        self._focus_depth_combo.currentIndexChanged.connect(self._on_depth_changed)
        self._focus_depth = 2
        h.addWidget(QLabel("  "))
        h.addWidget(self._focus_depth_combo)

        h.addSpacing(10)

        # Search
        self._search = QLineEdit()
        self._search.setObjectName("SearchField")
        self._search.setPlaceholderText("Find  (Ctrl+F)")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.returnPressed.connect(self._cycle_search_match)
        self._search_matches: list = []
        self._search_match_index = 0
        orig_keypress = self._search.keyPressEvent
        def _search_kp(ev):
            if ev.key() == Qt.Key_Escape:
                self._search.clear()
                self.view.setFocus()
                return
            orig_keypress(ev)
        self._search.keyPressEvent = _search_kp
        h.addWidget(self._search)

        find_act = QAction(self)
        find_act.setShortcut(QKeySequence("Ctrl+F"))
        find_act.triggered.connect(lambda: (self._search.setFocus(), self._search.selectAll()))
        self.addAction(find_act)

        return bar

    # ---- sidebar ----------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setMinimumWidth(320)
        side.setMaximumWidth(560)
        v = QVBoxLayout(side)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        # Section header: "NODE"
        header = QLabel("NOTE")
        header.setObjectName("SidebarHeader")
        v.addWidget(header)

        # Title input (big)
        self._title_input = QLineEdit()
        self._title_input.setObjectName("TitleInput")
        self._title_input.setPlaceholderText("Title…")
        self._title_input.editingFinished.connect(self._commit_title)
        self._title_input.textChanged.connect(self._schedule_live_title)
        v.addWidget(self._title_input)

        # Hint under title
        self._sidebar_hint = QLabel("")
        self._sidebar_hint.setObjectName("SidebarHint")
        v.addWidget(self._sidebar_hint)

        # Body editor — prominent, takes most of the sidebar
        v.addSpacing(4)
        body_label = QLabel("NOTES")
        body_label.setObjectName("SidebarHeader")
        v.addWidget(body_label)

        self._body_edit = QTextEdit()
        self._body_edit.setObjectName("BodyEditor")
        self._body_edit.setAcceptRichText(False)
        self._body_edit.setPlaceholderText("Write expanded thoughts here. "
                                           "Previews show on the card.")
        self._body_edit.textChanged.connect(self._schedule_live_body)
        self._body_edit.focusOutEvent = self._wrap_focus_out(
            self._body_edit.focusOutEvent, self._commit_body
        )
        v.addWidget(self._body_edit, 1)

        # Divider
        d = QFrame(); d.setObjectName("Divider"); d.setFrameShape(QFrame.HLine)
        v.addWidget(d)

        # Style row: color swatches + bold/italic
        style_label = QLabel("STYLE")
        style_label.setObjectName("SidebarHeader")
        v.addWidget(style_label)

        sw_row = QHBoxLayout()
        sw_row.setSpacing(5)
        for col in SWATCHES:
            btn = QPushButton()
            btn.setFixedSize(20, 20)
            btn.setStyleSheet(
                f"QPushButton {{ background:{col}; border:1px solid {BORDER}; border-radius:10px; }}"
                f"QPushButton:hover {{ border:1px solid {TEXT}; }}"
            )
            btn.clicked.connect(lambda _=False, c=col: self._set_attrs({"color": c}))
            sw_row.addWidget(btn)
        none_btn = QPushButton("·")
        none_btn.setFixedSize(20, 20)
        none_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_1}; color:{TEXT_DIM}; "
            f"border:1px solid {BORDER}; border-radius:10px; }}"
        )
        none_btn.clicked.connect(lambda: self._set_attrs({"color": "none"}))
        sw_row.addWidget(none_btn)
        custom_btn = QPushButton("…")
        custom_btn.setFixedSize(20, 20)
        custom_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_1}; color:{TEXT_DIM}; "
            f"border:1px solid {BORDER}; border-radius:10px; }}"
        )
        custom_btn.clicked.connect(self._pick_custom_color)
        sw_row.addWidget(custom_btn)
        sw_row.addStretch()
        v.addLayout(sw_row)

        bi_row = QHBoxLayout()
        bi_row.setSpacing(14)
        self._bold = QCheckBox("Bold")
        self._italic = QCheckBox("Italic")
        self._bold.toggled.connect(lambda v_: self._set_attrs({"bold": v_}))
        self._italic.toggled.connect(lambda v_: self._set_attrs({"italic": v_}))
        bi_row.addWidget(self._bold)
        bi_row.addWidget(self._italic)
        bi_row.addStretch()
        v.addLayout(bi_row)

        v.addSpacing(2)

        # Delete / Duplicate (danger zone at the bottom)
        row = QHBoxLayout()
        dup_btn = QPushButton("Duplicate")
        dup_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:{TEXT}; border:1px solid {BORDER}; "
            f"border-radius:6px; padding:6px 12px; }} "
            f"QPushButton:hover {{ background:{SURFACE_3}; }}"
        )
        dup_btn.clicked.connect(self._duplicate_selected)
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:#ff6b7a; border:1px solid {BORDER}; "
            f"border-radius:6px; padding:6px 12px; }} "
            f"QPushButton:hover {{ background:#2a1a20; }}"
        )
        del_btn.clicked.connect(self.delete_selected)
        row.addWidget(dup_btn)
        row.addWidget(del_btn)
        row.addStretch()
        v.addLayout(row)

        self._sidebar_widgets_for_disable = [
            self._title_input, self._body_edit, self._bold, self._italic, dup_btn, del_btn,
        ]
        self._set_sidebar_enabled(False)
        return side

    # ---- status bar -------------------------------------------------------
    def _build_statusbar(self):
        bar = self.statusBar()
        self._status_label = QLabel("")
        self._zoom_label = QLabel("100%")
        self._count_label = QLabel("")
        bar.addWidget(self._status_label)
        bar.addPermanentWidget(self._count_label)
        bar.addPermanentWidget(self._zoom_label)
        self._refresh_counts()

    def _build_shortcuts(self):
        # Delete/Esc/Duplicate/Direction toggles.
        for seq, slot in [
            ("Delete", self.delete_selected),
            ("Shift+D", self._duplicate_selected),
            ("D", self._toggle_selected_direction),
            ("R", self._reverse_selected_direction),
        ]:
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)

    def _toggle_selected_direction(self):
        """Flip each selected connection between directed and bidirectional."""
        from ..items import ConnectionItem as _CI
        conns = [it.conn for it in self.scene.selectedItems() if isinstance(it, _CI)]
        if not conns:
            return
        if len(conns) > 1:
            self.undo_stack.beginMacro("Toggle direction")
        for c in conns:
            self.undo_stack.push(ToggleConnectionDirectionCmd(self.scene, c))
        if len(conns) > 1:
            self.undo_stack.endMacro()

    def _reverse_selected_direction(self):
        """Flip from/to on each selected directed connection."""
        from ..items import ConnectionItem as _CI
        conns = [it.conn for it in self.scene.selectedItems()
                 if isinstance(it, _CI) and it.conn.directed]
        if not conns:
            return
        if len(conns) > 1:
            self.undo_stack.beginMacro("Reverse direction")
        for c in conns:
            self.undo_stack.push(SwapConnectionDirectionCmd(self.scene, c))
        if len(conns) > 1:
            self.undo_stack.endMacro()

    # ---- inspector sync & edits ------------------------------------------
    def _selected_single_node(self) -> Optional[Node]:
        sel = [it for it in self.scene.selectedItems() if isinstance(it, LiveNodeItem)]
        if len(sel) == 1:
            return sel[0].node
        return None

    def _set_sidebar_enabled(self, enabled: bool):
        for w in self._sidebar_widgets_for_disable:
            w.setEnabled(enabled)

    def _sync_inspector(self):
        # Commit pending edits on the previously-selected node, then swap target.
        self._commit_title()
        self._commit_body()

        n = self._selected_single_node()
        if n is None:
            self._set_sidebar_enabled(False)
            self._title_input.blockSignals(True)
            self._title_input.setText("")
            self._title_input.setPlaceholderText("Select or double-click a note")
            self._title_input.blockSignals(False)
            self._body_edit.blockSignals(True)
            self._body_edit.setPlainText("")
            self._body_edit.blockSignals(False)
            self._edit_target_id: Optional[int] = None
            self._baseline_text = ""
            self._baseline_body = ""
            self._sidebar_hint.setText("")
            self._bold.blockSignals(True); self._bold.setChecked(False); self._bold.blockSignals(False)
            self._italic.blockSignals(True); self._italic.setChecked(False); self._italic.blockSignals(False)
            return

        self._set_sidebar_enabled(True)
        self._edit_target_id = n.id
        # Baseline = values at the moment this node was selected. Used on
        # commit to detect real edits and to build a reversible EditNodeCmd.
        self._baseline_text = n.text
        self._baseline_body = n.body
        self._title_input.blockSignals(True)
        self._title_input.setText(n.text)
        self._title_input.setPlaceholderText("Title…")
        self._title_input.blockSignals(False)
        self._body_edit.blockSignals(True)
        self._body_edit.setPlainText(n.body)
        self._body_edit.blockSignals(False)
        deg = self.scene.degree_of(n.id)
        self._sidebar_hint.setText(f"Node #{n.id} · {deg} connection{'s' if deg != 1 else ''}")
        self._bold.blockSignals(True); self._bold.setChecked(n.bold); self._bold.blockSignals(False)
        self._italic.blockSignals(True); self._italic.setChecked(n.italic); self._italic.blockSignals(False)

    def _wrap_focus_out(self, original, commit):
        def h(ev):
            commit()
            return original(ev)
        return h

    def _schedule_live_title(self, _text: str):
        # Live-update the node card as user types; commit only on editingFinished.
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        n = self.scene.graph.nodes.get(nid)
        if n is None:
            return
        n.text = self._title_input.text()
        item = self.scene.node_items.get(nid)
        if item is not None:
            item.refresh()

    def _commit_title(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        if nid not in self.scene.graph.nodes:
            return
        new_text = self._title_input.text()
        self._push_attr_edit(nid, "text", new_text,
                             baseline=getattr(self, "_baseline_text", new_text),
                             label="Edit title")

    def _schedule_live_body(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        n = self.scene.graph.nodes.get(nid)
        if n is None:
            return
        n.body = self._body_edit.toPlainText()
        item = self.scene.node_items.get(nid)
        if item is not None:
            item.refresh()

    def _commit_body(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        if nid not in self.scene.graph.nodes:
            return
        new_body = self._body_edit.toPlainText()
        self._push_attr_edit(nid, "body", new_body,
                             baseline=getattr(self, "_baseline_body", new_body),
                             label="Edit notes")

    def _push_attr_edit(self, nid: int, attr: str, new_val, *, baseline, label: str):
        """Commit a live-edited attr as a reversible EditNodeCmd.

        ``baseline`` is the value at the moment the node became the edit
        target (i.e. before any live-preview mutation). If the current value
        differs from baseline, we roll the attr back to baseline, push the
        command (which redoes to new_val), then update baseline so a second
        commit on the same node doesn't re-emit the same edit.
        """
        if new_val == baseline:
            return
        setattr(self.scene.graph.nodes[nid], attr, baseline)
        self.undo_stack.push(EditNodeCmd(self.scene, nid, {attr: new_val}, label=label))
        if attr == "text":
            self._baseline_text = new_val
        elif attr == "body":
            self._baseline_body = new_val
        # Size-affecting edits → request a layout pass.
        if attr in ("text", "body"):
            self.scene.schedule_layout()

    def _set_attrs(self, attrs: dict):
        n = self._selected_single_node()
        if n is None:
            return
        self.undo_stack.push(EditNodeCmd(self.scene, n.id, attrs))
        self._sync_inspector()

    def _pick_custom_color(self):
        n = self._selected_single_node()
        start = QColor(n.color) if (n and n.color != "none") else QColor(ACCENT)
        col = QColorDialog.getColor(start, self, "Pick node color")
        if col.isValid():
            self._set_attrs({"color": col.name()})

    def _open_in_inspector(self, nid: int):
        item = self.scene.node_items.get(nid)
        if item is None:
            return
        self.scene.clearSelection()
        item.setSelected(True)
        # Focus the body editor (or title if blank).
        if not item.node.text or item.node.text.strip().lower() in ("", "new note"):
            self._title_input.setFocus()
            self._title_input.selectAll()
        else:
            self._body_edit.setFocus()

    # ---- focus mode -------------------------------------------------------
    def _on_selection_for_focus(self):
        if self._focus_btn.isChecked():
            self._update_focus_emphasis()

    def _on_focus_toggled(self, on: bool):
        if on:
            self._update_focus_emphasis()
        else:
            self.scene.clear_emphasis()

    def _on_depth_changed(self, idx: int):
        mapping = [1, 2, 3, 4, 99]
        self._focus_depth = mapping[idx]
        if self._focus_btn.isChecked():
            self._update_focus_emphasis()

    def _update_focus_emphasis(self):
        n = self._selected_single_node()
        if n is None:
            self.scene.clear_emphasis()
            return
        self.scene.set_emphasis(self.scene.spreading_activation(n.id, max_depth=self._focus_depth))

    # ---- search -----------------------------------------------------------
    def _on_search_changed(self, text: str):
        text = text.strip().lower()
        if not text:
            self._search_matches = []
            if self._focus_btn.isChecked():
                self._update_focus_emphasis()
            else:
                self.scene.clear_emphasis()
            return
        matches = [nid for nid, n in self.scene.graph.nodes.items()
                   if text in n.text.lower() or text in n.body.lower()]
        self._search_matches = matches
        self._search_match_index = 0
        if not matches:
            self.scene.set_emphasis({})
            return
        self.scene.set_emphasis({nid: 1.0 for nid in matches})
        self._center_on_node(matches[0])

    def _cycle_search_match(self):
        if not self._search_matches:
            return
        self._search_match_index = (self._search_match_index + 1) % len(self._search_matches)
        self._center_on_node(self._search_matches[self._search_match_index])

    def _center_on_node(self, nid: int):
        it = self.scene.node_items.get(nid)
        if it is not None:
            self.view.centerOn(it)

    # ---- actions ----------------------------------------------------------
    def add_note_at_center(self):
        c = self.view.mapToScene(self.view.viewport().rect().center())
        n = Node(id=self.scene.graph.allocate_id(), x=c.x() - 90, y=c.y() - 28,
                 text="New note", width=180, height=56)
        from ..commands import AddNodeCmd
        self.undo_stack.push(AddNodeCmd(self.scene, n))
        item = self.scene.node_items.get(n.id)
        if item is not None:
            self.scene.clearSelection()
            item.setSelected(True)
        self._open_in_inspector(n.id)
        self._refresh_counts()

    def delete_selected(self):
        sel = self.scene.selectedItems()
        node_ids = [it.node.id for it in sel if isinstance(it, LiveNodeItem)]
        conns = [it.conn for it in sel if isinstance(it, ConnectionItem)]
        if not node_ids and not conns:
            return
        self.undo_stack.beginMacro("Delete selection")
        if node_ids:
            self.undo_stack.push(RemoveNodesCmd(self.scene, node_ids))
        for c in conns:
            if c in self.scene.graph.connections:
                self.undo_stack.push(RemoveConnectionCmd(self.scene, c))
        self.undo_stack.endMacro()
        self._refresh_counts()

    def _duplicate_selected(self):
        from ..commands import AddNodeCmd
        sel = [it for it in self.scene.selectedItems() if isinstance(it, LiveNodeItem)]
        if not sel:
            return
        self.undo_stack.beginMacro("Duplicate")
        new_items = []
        for it in sel:
            src = it.node
            dup = Node(
                id=self.scene.graph.allocate_id(),
                x=src.x + 30, y=src.y + 30, text=src.text, body=src.body,
                width=src.width, height=src.height, color=src.color,
                font_size=src.font_size, align=src.align,
                bold=src.bold, italic=src.italic,
            )
            self.undo_stack.push(AddNodeCmd(self.scene, dup))
            new_items.append(self.scene.node_items.get(dup.id))
        self.undo_stack.endMacro()
        self.scene.clearSelection()
        for ni in new_items:
            if ni is not None:
                ni.setSelected(True)

    # ---- file IO ----------------------------------------------------------
    def new_file(self):
        if not self._confirm_discard():
            return
        self.scene.graph = Graph()
        self.scene.rebuild_all()
        self.undo_stack.clear()
        self.current_path = None
        self._update_title()
        self._refresh_counts()
        self._sync_inspector()

    def open_file(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open mindmap", "", "JSON (*.json)")
        if not path:
            return
        try:
            g = mio.load_graph(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return
        self.load_path(Path(path), graph=g)

    def load_path(self, path: Path, graph: Optional[Graph] = None):
        if graph is None:
            try:
                graph = mio.load_graph(path)
            except Exception as exc:
                QMessageBox.critical(self, "Open failed", str(exc))
                return
        self.scene.graph = graph
        self.scene.rebuild_all()
        self.undo_stack.clear()
        self.current_path = path
        self._update_title()
        self._refresh_counts()
        self._sync_inspector()
        # Run layout first, then fit the view to the settled result. We use a
        # one-shot signal connection so fit_all fires exactly once after this
        # initial pass (not on every subsequent structural change).
        def _fit_once():
            self.view.fit_all()
            try:
                self.scene.layout_finished.disconnect(_fit_once)
            except TypeError:
                pass
        self.scene.layout_finished.connect(_fit_once)
        self.scene.schedule_layout()

    def save_file(self):
        self._commit_title()
        self._commit_body()
        if self.current_path is None:
            self.save_file_as()
            return
        try:
            mio.save_graph(self.scene.graph, self.current_path)
            self.undo_stack.setClean()
            self._status_label.setText(f"Saved {self.current_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def save_file_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save mindmap", "", "JSON (*.json)")
        if not path:
            return
        self.current_path = Path(path)
        self.save_file()
        self._update_title()

    def _confirm_discard(self) -> bool:
        if self.undo_stack.isClean():
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Discard unsaved changes?",
                                 QMessageBox.Discard | QMessageBox.Cancel)
        return r == QMessageBox.Discard

    # ---- status ----------------------------------------------------------
    def _update_title(self, *_):
        name = self.current_path.name if self.current_path else "untitled"
        dirty = "" if self.undo_stack.isClean() else " •"
        self.setWindowTitle(f"pymindmap · live — {name}{dirty}")

    def _on_zoom_changed(self, s: float):
        self._zoom_label.setText(f"{int(s * 100)}%")

    def _refresh_counts(self):
        g = self.scene.graph
        self._count_label.setText(f"{len(g.nodes)} nodes · {len(g.connections)} edges")
        self._status_label.setText("")

    def closeEvent(self, e):
        self._commit_title()
        self._commit_body()
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()
