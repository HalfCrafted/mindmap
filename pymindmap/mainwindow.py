"""MainWindow: toolbar, shortcuts, inspector, file IO."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QSize, Qt, QVariantAnimation
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QActionGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QTextEdit,
    QToolBar,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from . import io as mio
from .commands import EditNodeCmd, MoveNodesCmd, RemoveConnectionCmd, RemoveNodesCmd
from .items import ConnectionItem, NodeItem
from .layout import fruchterman_reingold
from .model import Connection, Graph, Node
from .scene import MindMapScene
from .theme import THEME
from .view import MindMapView


class MainWindow(QMainWindow):
    def __init__(self, graph: Optional[Graph] = None, open_path: Optional[Path] = None):
        super().__init__()
        self.setWindowTitle("pymindmap")
        self.resize(1280, 820)

        self.current_path: Optional[Path] = open_path
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(100)

        self.scene = MindMapScene(graph if graph is not None else Graph())
        self.view = MindMapView(self.scene, self.undo_stack)
        self.setCentralWidget(self.view)

        self._build_toolbar()
        self._build_inspector()
        self._build_statusbar()
        self._build_shortcuts()

        self.scene.selectionChanged.connect(self._sync_inspector)
        self.scene.selectionChanged.connect(self._on_selection_for_focus)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.undo_stack.cleanChanged.connect(self._update_title)
        self.undo_stack.indexChanged.connect(lambda _: self._update_title())

        # If nothing loaded, create one starter node.
        if graph is None or not graph.nodes:
            n = Node(id=self.scene.graph.allocate_id(), x=-60, y=-20,
                     text="Welcome to pymindmap", width=200, height=60,
                     color=THEME.node_header_default, font_size=15)
            self.scene.add_node(n)

        self.view.reset_view()

    # ---- UI building ------------------------------------------------------
    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        def act(name, shortcut, slot):
            a = QAction(name, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            tb.addAction(a)
            return a

        act("New", "Ctrl+N", self.new_file)
        act("Open", "Ctrl+O", self.open_file)
        act("Save", "Ctrl+S", self.save_file)
        act("Save As", "Ctrl+Shift+S", self.save_file_as)
        tb.addSeparator()
        act("Undo", "Ctrl+Z", self.undo_stack.undo)
        act("Redo", "Ctrl+Y", self.undo_stack.redo)
        tb.addSeparator()
        act("Add node", "Shift+A", self.add_node_at_center)
        act("Delete", "Delete", self.delete_selected)
        tb.addSeparator()
        act("Fit", ".", self.view.fit_all)
        act("Home", "Home", self.view.reset_view)
        tb.addSeparator()
        act("Auto-layout", "Ctrl+L", self.run_auto_layout)

        # Focus mode — dims unrelated nodes when one is selected.
        self._focus_action = QAction("Focus", self)
        self._focus_action.setCheckable(True)
        self._focus_action.setShortcut(QKeySequence("F"))
        self._focus_action.setToolTip("Focus on selected node's neighborhood (F)")
        self._focus_action.toggled.connect(self._on_focus_toggled)
        tb.addAction(self._focus_action)

        # Depth slider for focus mode (small inline).
        self._focus_depth = 2
        depth_label = QLabel("  Depth ")
        tb.addWidget(depth_label)
        self._focus_depth_combo = QComboBox()
        self._focus_depth_combo.addItems(["1", "2", "3", "4", "∞"])
        self._focus_depth_combo.setCurrentIndex(1)
        self._focus_depth_combo.currentIndexChanged.connect(self._on_depth_changed)
        tb.addWidget(self._focus_depth_combo)

        tb.addSeparator()

        # Search field.
        self._search = QLineEdit()
        self._search.setPlaceholderText("Find (Ctrl+F)…")
        self._search.setMaximumWidth(180)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.returnPressed.connect(self._cycle_search_match)
        self._search_matches: list = []
        self._search_match_index = 0
        # Esc in search clears and returns focus to canvas.
        _orig_keypress = self._search.keyPressEvent
        def _search_keypress(ev):
            if ev.key() == Qt.Key_Escape:
                self._search.clear()
                self.view.setFocus()
                return
            _orig_keypress(ev)
        self._search.keyPressEvent = _search_keypress
        tb.addWidget(self._search)

        find_act = QAction("Find", self)
        find_act.setShortcut(QKeySequence("Ctrl+F"))
        find_act.triggered.connect(self._focus_search)
        self.addAction(find_act)

    def _build_inspector(self):
        dock = QDockWidget("Inspector", self)
        dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._insp_title = QLabel("Select a node")
        self._insp_title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._insp_title)

        # Font size
        fs_row = QHBoxLayout()
        fs_row.addWidget(QLabel("Size"))
        self._font_slider = QSlider(Qt.Horizontal)
        self._font_slider.setRange(8, 72)
        self._font_slider.setValue(14)
        self._font_slider.valueChanged.connect(self._set_font_size)
        fs_row.addWidget(self._font_slider)
        self._font_label = QLabel("14")
        fs_row.addWidget(self._font_label)
        layout.addLayout(fs_row)

        # Align
        align_row = QHBoxLayout()
        align_row.addWidget(QLabel("Align"))
        self._align_combo = QComboBox()
        self._align_combo.addItems(["left", "center", "right"])
        self._align_combo.currentTextChanged.connect(self._set_align)
        align_row.addWidget(self._align_combo)
        layout.addLayout(align_row)

        # Bold / Italic
        bi_row = QHBoxLayout()
        self._bold = QCheckBox("Bold")
        self._italic = QCheckBox("Italic")
        self._bold.toggled.connect(lambda v: self._set_attrs({"bold": v}))
        self._italic.toggled.connect(lambda v: self._set_attrs({"italic": v}))
        bi_row.addWidget(self._bold)
        bi_row.addWidget(self._italic)
        bi_row.addStretch()
        layout.addLayout(bi_row)

        # Color palette + custom
        layout.addWidget(QLabel("Color"))
        pal_row = QHBoxLayout()
        pal_row.setSpacing(4)
        for col in THEME.palette:
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setStyleSheet(f"background:{col}; border-radius:4px; border:1px solid #2a2a32;")
            btn.clicked.connect(lambda _=None, c=col: self._set_attrs({"color": c}))
            pal_row.addWidget(btn)
        # "None" swatch
        none_btn = QPushButton("×")
        none_btn.setFixedSize(22, 22)
        none_btn.setStyleSheet("background:#1a1a1e; color:#aaa; border:1px solid #2a2a32; border-radius:4px;")
        none_btn.clicked.connect(lambda: self._set_attrs({"color": "none"}))
        pal_row.addWidget(none_btn)
        # Custom
        custom_btn = QPushButton("…")
        custom_btn.setFixedSize(22, 22)
        custom_btn.clicked.connect(self._pick_custom_color)
        pal_row.addWidget(custom_btn)
        pal_row.addStretch()
        layout.addLayout(pal_row)

        # Body (long-form note) ------------------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a2a32;")
        layout.addWidget(sep)
        layout.addWidget(QLabel("Notes"))
        self._body_edit = QTextEdit()
        self._body_edit.setPlaceholderText("Long-form notes for this node…")
        self._body_edit.setAcceptRichText(False)
        self._body_edit.setMinimumHeight(140)
        self._body_edit_node_id: Optional[int] = None
        self._body_edit.focusOutEvent = self._wrap_focus_out(
            self._body_edit.focusOutEvent, self._commit_body
        )
        layout.addWidget(self._body_edit, 1)

        dock.setWidget(wrap)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.setMinimumWidth(260)

        # disable initially
        self._set_inspector_enabled(False)

    def _build_statusbar(self):
        bar = self.statusBar()
        self._zoom_label = QLabel("100%")
        self._count_label = QLabel("")
        bar.addPermanentWidget(self._zoom_label)
        bar.addPermanentWidget(self._count_label)
        self._refresh_counts()

    def _build_shortcuts(self):
        # Extra shortcuts not in toolbar
        for seq, slot in [
            ("Tab", self._edit_selected_node),
            ("Escape", self._stop_edit_selected),
            ("Shift+D", self._duplicate_selected),
        ]:
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)

    # ---- inspector sync ---------------------------------------------------
    def _set_inspector_enabled(self, enabled: bool):
        for w in (self._font_slider, self._align_combo, self._bold, self._italic, self._body_edit):
            w.setEnabled(enabled)

    def _selected_single_node(self) -> Optional[Node]:
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        if len(sel) == 1:
            return sel[0].node
        return None

    def _sync_inspector(self):
        # Commit any pending body edit for the previously-selected node first.
        self._commit_body()
        n = self._selected_single_node()
        if n is None:
            self._insp_title.setText("Select a node")
            self._set_inspector_enabled(False)
            self._body_edit.blockSignals(True)
            self._body_edit.setPlainText("")
            self._body_edit.blockSignals(False)
            self._body_edit_node_id = None
            return
        self._insp_title.setText(f"Node #{n.id}")
        self._set_inspector_enabled(True)
        self._font_slider.blockSignals(True)
        self._font_slider.setValue(n.font_size)
        self._font_slider.blockSignals(False)
        self._font_label.setText(str(n.font_size))
        self._align_combo.blockSignals(True)
        self._align_combo.setCurrentText(n.align)
        self._align_combo.blockSignals(False)
        self._bold.blockSignals(True); self._bold.setChecked(n.bold); self._bold.blockSignals(False)
        self._italic.blockSignals(True); self._italic.setChecked(n.italic); self._italic.blockSignals(False)
        self._body_edit.blockSignals(True)
        self._body_edit.setPlainText(n.body)
        self._body_edit.blockSignals(False)
        self._body_edit_node_id = n.id
        self._refresh_counts()

    # ---- body-edit helpers ------------------------------------------------
    def _wrap_focus_out(self, original, commit):
        def handler(event):
            commit()
            return original(event)
        return handler

    def _commit_body(self):
        nid = getattr(self, "_body_edit_node_id", None)
        if nid is None:
            return
        n = self.scene.graph.nodes.get(nid)
        if n is None:
            return
        new_body = self._body_edit.toPlainText()
        if new_body != n.body:
            self.undo_stack.push(EditNodeCmd(self.scene, nid, {"body": new_body}, label="Edit notes"))

    def _set_attrs(self, attrs: dict):
        n = self._selected_single_node()
        if n is None:
            return
        self.undo_stack.push(EditNodeCmd(self.scene, n.id, attrs))
        self._sync_inspector()

    def _set_font_size(self, v: int):
        self._font_label.setText(str(v))
        n = self._selected_single_node()
        if n is None or n.font_size == v:
            return
        self.undo_stack.push(EditNodeCmd(self.scene, n.id, {"font_size": v}))

    def _set_align(self, txt: str):
        self._set_attrs({"align": txt})

    def _pick_custom_color(self):
        n = self._selected_single_node()
        start = QColor(n.color) if (n and n.color != "none") else QColor(THEME.node_header_default)
        col = QColorDialog.getColor(start, self, "Pick node color")
        if col.isValid():
            self._set_attrs({"color": col.name()})

    # ---- actions ----------------------------------------------------------
    def add_node_at_center(self):
        c = self.view.mapToScene(self.view.viewport().rect().center())
        n = Node(id=self.scene.graph.allocate_id(), x=c.x() - 60, y=c.y() - 20,
                 text="New node", width=120, height=60)
        from .commands import AddNodeCmd
        self.undo_stack.push(AddNodeCmd(self.scene, n))
        item = self.scene.node_items[n.id]
        self.scene.clearSelection()
        item.setSelected(True)
        item.start_edit()
        self._refresh_counts()

    def delete_selected(self):
        # Stop any text edit first
        self._stop_edit_selected()
        sel = self.scene.selectedItems()
        node_ids = [it.node.id for it in sel if isinstance(it, NodeItem)]
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

    def _edit_selected_node(self):
        n = self._selected_single_node()
        if n is None:
            return
        item = self.scene.node_items.get(n.id)
        if item is not None:
            item.start_edit()

    def _stop_edit_selected(self):
        for it in self.scene.items():
            if isinstance(it, NodeItem):
                it.stop_edit()

    def _duplicate_selected(self):
        from .commands import AddNodeCmd
        sel = [it for it in self.scene.selectedItems() if isinstance(it, NodeItem)]
        if not sel:
            return
        self.undo_stack.beginMacro("Duplicate")
        new_items = []
        for it in sel:
            src = it.node
            dup = Node(
                id=self.scene.graph.allocate_id(),
                x=src.x + 30, y=src.y + 30, text=src.text,
                width=src.width, height=src.height, color=src.color,
                font_size=src.font_size, align=src.align,
                bold=src.bold, italic=src.italic,
            )
            self.undo_stack.push(AddNodeCmd(self.scene, dup))
            new_items.append(self.scene.node_items[dup.id])
        self.undo_stack.endMacro()
        self.scene.clearSelection()
        for ni in new_items:
            ni.setSelected(True)

    # ---- search -----------------------------------------------------------
    def _focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def _on_search_changed(self, text: str):
        text = text.strip().lower()
        if not text:
            # Cleared — restore focus emphasis if enabled, else clear.
            self._search_matches: list = []
            if self._focus_action.isChecked():
                self._update_focus_emphasis()
            else:
                self.scene.clear_emphasis()
            return
        matches = []
        for nid, n in self.scene.graph.nodes.items():
            if text in n.text.lower() or text in n.body.lower():
                matches.append(nid)
        self._search_matches = matches
        self._search_match_index = 0
        if not matches:
            # No matches: dim everything.
            self.scene.set_emphasis({})
            return
        # Emphasize matches at full opacity, dim others.
        emph = {nid: 1.0 for nid in matches}
        self.scene.set_emphasis(emph)
        self._center_on_node(matches[0])

    def _cycle_search_match(self):
        if not getattr(self, "_search_matches", None):
            return
        self._search_match_index = (self._search_match_index + 1) % len(self._search_matches)
        self._center_on_node(self._search_matches[self._search_match_index])

    def _center_on_node(self, nid: int):
        item = self.scene.node_items.get(nid)
        if item is not None:
            self.view.centerOn(item)

    def _clear_search(self):
        self._search.clear()  # triggers _on_search_changed which clears emphasis

    # ---- focus mode -------------------------------------------------------
    def _on_selection_for_focus(self):
        if self._focus_action.isChecked():
            self._update_focus_emphasis()

    def _on_focus_toggled(self, on: bool):
        if on:
            self._update_focus_emphasis()
        else:
            self.scene.clear_emphasis()

    def _on_depth_changed(self, idx: int):
        mapping = [1, 2, 3, 4, 99]
        self._focus_depth = mapping[idx]
        if self._focus_action.isChecked():
            self._update_focus_emphasis()

    def _update_focus_emphasis(self):
        n = self._selected_single_node()
        if n is None:
            self.scene.clear_emphasis()
            return
        act = self.scene.spreading_activation(n.id, max_depth=self._focus_depth)
        self.scene.set_emphasis(act)

    # ---- auto-layout ------------------------------------------------------
    def run_auto_layout(self):
        g = self.scene.graph
        if len(g.nodes) < 2:
            return
        new_pos = fruchterman_reingold(g)
        starts = {nid: (n.x, n.y) for nid, n in g.nodes.items()}
        # Animate then commit a single undo command.
        self._animate_positions(starts, new_pos, duration_ms=600)

    def _animate_positions(self, starts: dict, ends: dict, *, duration_ms: int = 600):
        # Keep animation object alive as an attribute.
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration_ms)
        anim.setEasingCurve(QEasingCurve.InOutCubic)

        def on_frame(t):
            for nid, end in ends.items():
                s = starts.get(nid)
                if s is None:
                    continue
                nx = s[0] + (end[0] - s[0]) * t
                ny = s[1] + (end[1] - s[1]) * t
                n = self.scene.graph.nodes.get(nid)
                if n is None:
                    continue
                n.x, n.y = nx, ny
                item = self.scene.node_items.get(nid)
                if item is not None:
                    item.setPos(nx, ny)
            # Re-route connections so edges follow the nodes smoothly.
            for ci in self.scene.connection_items:
                ci.rebuild_path()

        def on_finished():
            # Commit as a single undoable MoveNodesCmd.
            moves = [(nid, starts[nid], ends[nid]) for nid in ends if nid in starts]
            # Reset to starts so the command's redo does the actual apply.
            for nid, s in starts.items():
                n = self.scene.graph.nodes.get(nid)
                if n is not None:
                    n.x, n.y = s
                    item = self.scene.node_items.get(nid)
                    if item is not None:
                        item.setPos(s[0], s[1])
            self.undo_stack.push(MoveNodesCmd(self.scene, moves))
            self.view.fit_all()

        anim.valueChanged.connect(on_frame)
        anim.finished.connect(on_finished)
        self._layout_anim = anim  # keep alive
        anim.start()

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
        self.scene.graph = g
        self.scene.rebuild_all()
        self.undo_stack.clear()
        self.current_path = Path(path)
        self._update_title()
        self._refresh_counts()
        self.view.fit_all()

    def save_file(self):
        self._commit_body()
        if self.current_path is None:
            self.save_file_as()
            return
        try:
            mio.save_graph(self.scene.graph, self.current_path)
            self.undo_stack.setClean()
            self.statusBar().showMessage(f"Saved {self.current_path}", 2500)
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
        r = QMessageBox.question(
            self, "Unsaved changes",
            "Discard unsaved changes?",
            QMessageBox.Discard | QMessageBox.Cancel,
        )
        return r == QMessageBox.Discard

    # ---- helpers ----------------------------------------------------------
    def _update_title(self, *_):
        name = self.current_path.name if self.current_path else "untitled"
        dirty = "" if self.undo_stack.isClean() else " •"
        self.setWindowTitle(f"pymindmap — {name}{dirty}")

    def _on_zoom_changed(self, s: float):
        self._zoom_label.setText(f"{int(s * 100)}%")

    def _refresh_counts(self):
        g = self.scene.graph
        self._count_label.setText(f"{len(g.nodes)} nodes · {len(g.connections)} edges")

    def closeEvent(self, e):
        self._commit_body()
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()

    def load_path(self, path: Path):
        try:
            g = mio.load_graph(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.scene.graph = g
        self.scene.rebuild_all()
        self.undo_stack.clear()
        self.current_path = path
        self._update_title()
        self._refresh_counts()
        self.view.fit_all()
