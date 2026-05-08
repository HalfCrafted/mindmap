"""LiveMainWindow — modern UI with prominent notes, live auto-layout."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QEvent, QSettings, QSize, Qt
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
    QSlider,
    QSplitter,
    QTextEdit,
    QToolButton,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

from .. import io as mio
from ..integrations import dir_link as dirlink
from ..integrations import mac_delegate as macdg
from ..integrations import reminder as reminders
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
        self._sidebar_widget = self._build_sidebar()
        self.splitter.addWidget(self._sidebar_widget)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        # Default split sizes — restored when the sidebar is re-revealed.
        self._sidebar_default_sizes = [1000, 400]
        self.splitter.setSizes(self._sidebar_default_sizes)
        self.splitter.setHandleWidth(1)
        vbox.addWidget(self.splitter, 1)

        # Hide the sidebar by default and create a small "notch" on the
        # right edge of the canvas that reveals it when clicked.
        self._sidebar_widget.hide()
        self._build_sidebar_notch()

        self._build_statusbar()
        self._build_shortcuts()

        # Signals
        self.scene.selectionChanged.connect(self._sync_inspector)
        self.scene.selectionChanged.connect(self._on_selection_for_focus)
        self.scene.edit_requested.connect(self._open_in_inspector)
        self.scene.layout_started.connect(lambda: self._status_label.setText("Arranging…"))
        self.scene.layout_finished.connect(self._refresh_counts)
        self.view.zoom_changed.connect(self._on_zoom_changed)

        self._connected_screen = None
        # ``windowHandle()`` isn't available until after ``show()``, so we
        # wire the screen-change listener in ``showEvent`` instead of here.
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
        icon_btn("Re-arrange", "Re-run auto-layout", lambda: self.scene.schedule_layout(fresh=True), shortcut="Ctrl+L")
        icon_btn("Mac log",
                 "Tail the Mac's reminder log in a terminal "
                 "(SSH'd live — Ctrl+C to close)",
                 self._open_mac_log)

        # Spread / cluster — multiplies the physics repulsion strength.
        # Persisted in QSettings so the user's preference survives restarts.
        sep_spread = QFrame(); sep_spread.setFrameShape(QFrame.VLine); sep_spread.setStyleSheet(f"color:{BORDER};")
        h.addWidget(sep_spread)
        spread_label = QLabel("Spread")
        spread_label.setObjectName("AppSubtitle")
        h.addWidget(spread_label)
        self._spread_slider = QSlider(Qt.Horizontal)
        # Logarithmic feel: slider value 0..200 maps to scale 0.25..4.0 via
        # exp interpolation, so the centre tick is the baseline (1.0) and
        # each end is two octaves out.
        self._spread_slider.setRange(0, 200)
        self._spread_slider.setFixedWidth(140)
        self._spread_slider.setToolTip(
            "Repulsion strength — lower = clustered, higher = spread out"
        )
        settings = QSettings()
        saved_scale = float(settings.value("spread_scale", 1.0))
        self._spread_slider.setValue(self._scale_to_slider(saved_scale))
        self.scene.set_repulsion_scale(saved_scale)
        self._spread_slider.valueChanged.connect(self._on_spread_changed)
        h.addWidget(self._spread_slider)

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

        # Section header: "NODE" + a close-sidebar button on the right.
        header_row = QHBoxLayout()
        header = QLabel("NOTE")
        header.setObjectName("SidebarHeader")
        header_row.addWidget(header)
        header_row.addStretch()
        close_btn = QPushButton("×")
        close_btn.setToolTip("Hide sidebar (click the notch on the canvas to bring it back)")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:{TEXT_DIM}; "
            f"border:1px solid {BORDER}; border-radius:11px; font-weight:600; }} "
            f"QPushButton:hover {{ color:{TEXT}; border-color:{ACCENT}; }}"
        )
        close_btn.clicked.connect(self.hide_sidebar)
        header_row.addWidget(close_btn)
        v.addLayout(header_row)

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

        # Description — short subtext shown directly on the card.
        v.addSpacing(4)
        desc_label = QLabel("DESCRIPTION")
        desc_label.setObjectName("SidebarHeader")
        v.addWidget(desc_label)

        self._desc_edit = QTextEdit()
        self._desc_edit.setObjectName("BodyEditor")
        self._desc_edit.setAcceptRichText(False)
        self._desc_edit.setPlaceholderText("Short blurb shown on the card under the title…")
        self._desc_edit.setMaximumHeight(110)
        self._desc_edit.textChanged.connect(self._schedule_live_description)
        self._desc_edit.focusOutEvent = self._wrap_focus_out(
            self._desc_edit.focusOutEvent, self._commit_description
        )
        v.addWidget(self._desc_edit)

        # Notes — long-form body, inspector-only. Plain text, with the option
        # to import a Markdown file as the starting content.
        v.addSpacing(6)
        notes_header_row = QHBoxLayout()
        notes_label = QLabel("NOTES")
        notes_label.setObjectName("SidebarHeader")
        notes_header_row.addWidget(notes_label)
        notes_header_row.addStretch()
        self._import_md_btn = QPushButton("Import .md")
        self._import_md_btn.setToolTip("Replace notes with the contents of a Markdown file")
        self._import_md_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:{TEXT}; border:1px solid {BORDER}; "
            f"border-radius:6px; padding:2px 8px; }}"
            f"QPushButton:hover {{ border-color:{ACCENT}; }}"
        )
        self._import_md_btn.clicked.connect(self._import_notes_markdown)
        notes_header_row.addWidget(self._import_md_btn)
        v.addLayout(notes_header_row)

        self._body_edit = QTextEdit()
        self._body_edit.setObjectName("BodyEditor")
        self._body_edit.setAcceptRichText(False)
        self._body_edit.setPlaceholderText("Long-form notes (plain text or imported Markdown). "
                                           "These do NOT show on the card.")
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

        v.addSpacing(6)

        # Divider before integrations.
        d_int = QFrame(); d_int.setObjectName("Divider"); d_int.setFrameShape(QFrame.HLine)
        v.addWidget(d_int)

        # Folder shortcut. Per-device paths are stored on the node — the
        # path field shows whichever path is set for *this* device (the
        # Tailscale node name). Other devices keep their own entries on
        # the same dict and round-trip through JSON sync.
        folder_label = QLabel("FOLDER")
        folder_label.setObjectName("SidebarHeader")
        v.addWidget(folder_label)
        self._folder_check = QCheckBox("Folder shortcut")
        self._folder_check.toggled.connect(self._on_folder_toggle)
        v.addWidget(self._folder_check)
        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._folder_path = QLineEdit()
        self._folder_path.setPlaceholderText(
            f"Path on {dirlink.current_device_key()}…"
        )
        self._folder_path.editingFinished.connect(self._commit_folder_path)
        self._folder_open_btn = QPushButton("Open")
        self._folder_open_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:{TEXT}; border:1px solid {BORDER}; "
            f"border-radius:6px; padding:4px 10px; }} "
            f"QPushButton:hover {{ background:{SURFACE_3}; }} "
            f"QPushButton:disabled {{ color:{TEXT_DIM}; }}"
        )
        self._folder_open_btn.clicked.connect(self._open_folder_for_selected)
        path_row.addWidget(self._folder_path, 1)
        path_row.addWidget(self._folder_open_btn)
        v.addLayout(path_row)
        self._folder_hint = QLabel("")
        self._folder_hint.setObjectName("SidebarHint")
        self._folder_hint.setWordWrap(True)
        v.addWidget(self._folder_hint)

        v.addSpacing(8)

        # Reminder. The user types a free-form schedule
        # ("daily at 9am", "in 30 minutes", "every Friday at 5pm");
        # parse_reminder echoes back what it understood. Saving installs a
        # crontab/at job tagged with the node id; toggling off removes it.
        rem_label = QLabel("REMINDER")
        rem_label.setObjectName("SidebarHeader")
        v.addWidget(rem_label)
        self._rem_check = QCheckBox("Schedule reminder")
        self._rem_check.toggled.connect(self._on_reminder_toggle)
        v.addWidget(self._rem_check)
        self._rem_when = QLineEdit()
        self._rem_when.setPlaceholderText('e.g. "daily at 9am" or "in 30 minutes"')
        self._rem_when.textChanged.connect(self._on_reminder_when_changed)
        v.addWidget(self._rem_when)
        self._rem_message = QLineEdit()
        self._rem_message.setPlaceholderText("Notification message (defaults to title)")
        v.addWidget(self._rem_message)
        self._rem_ai_label = QLabel("AI prompt (optional)")
        self._rem_ai_label.setObjectName("SidebarHint")
        v.addWidget(self._rem_ai_label)
        self._rem_ai_prompt = QTextEdit()
        self._rem_ai_prompt.setObjectName("BodyEditor")
        self._rem_ai_prompt.setAcceptRichText(False)
        self._rem_ai_prompt.setFixedHeight(80)
        self._rem_ai_prompt.setPlaceholderText(
            "If set, fires Claude with this prompt + mindmap context "
            "+ access to any linked directories, then emails the response."
        )
        v.addWidget(self._rem_ai_prompt)
        self._rem_mac = QCheckBox("Run on Mac (always-on, fires when this device sleeps)")
        self._rem_mac.setChecked(True)  # default to always-on delivery
        v.addWidget(self._rem_mac)
        rem_btn_row = QHBoxLayout()
        rem_btn_row.setSpacing(6)
        self._rem_save_btn = QPushButton("Save reminder")
        self._rem_save_btn.setStyleSheet(
            f"QPushButton {{ background:{SURFACE_2}; color:{TEXT}; border:1px solid {BORDER}; "
            f"border-radius:6px; padding:4px 10px; }} "
            f"QPushButton:hover {{ background:{SURFACE_3}; }} "
            f"QPushButton:disabled {{ color:{TEXT_DIM}; }}"
        )
        self._rem_save_btn.clicked.connect(self._save_reminder)
        self._rem_clear_btn = QPushButton("Clear")
        self._rem_clear_btn.setStyleSheet(self._rem_save_btn.styleSheet())
        self._rem_clear_btn.clicked.connect(self._clear_reminder)
        rem_btn_row.addWidget(self._rem_save_btn)
        rem_btn_row.addWidget(self._rem_clear_btn)
        rem_btn_row.addStretch()
        v.addLayout(rem_btn_row)
        self._rem_hint = QLabel("")
        self._rem_hint.setObjectName("SidebarHint")
        self._rem_hint.setWordWrap(True)
        v.addWidget(self._rem_hint)

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
            self._title_input, self._desc_edit, self._body_edit, self._import_md_btn,
            self._bold, self._italic, dup_btn, del_btn,
            self._folder_check, self._folder_path, self._folder_open_btn,
            self._rem_check, self._rem_when, self._rem_message, self._rem_ai_prompt,
            self._rem_mac, self._rem_save_btn, self._rem_clear_btn,
        ]
        self._set_sidebar_enabled(False)
        return side

    # ---- sidebar reveal notch ---------------------------------------------
    def _build_sidebar_notch(self):
        """Small handle clipped to the right edge of the canvas.

        Parented to the view itself so it stacks above the QGraphicsScene
        contents — buttons reparented to the QMainWindow ended up behind
        the central widget and never received clicks.
        """
        self._sidebar_notch = QPushButton("‹", self.view)
        self._sidebar_notch.setToolTip("Show inspector sidebar")
        self._sidebar_notch.setCursor(Qt.PointingHandCursor)
        self._sidebar_notch.setFocusPolicy(Qt.NoFocus)
        self._sidebar_notch.setFixedSize(16, 72)
        self._sidebar_notch.setStyleSheet(
            f"QPushButton {{"
            f" background:{SURFACE_2}; color:{TEXT_DIM};"
            f" border:1px solid {BORDER}; border-right:none;"
            f" border-top-left-radius:6px; border-bottom-left-radius:6px;"
            f" font-weight:600;"
            f"}}"
            f"QPushButton:hover {{ background:{SURFACE_3}; color:{TEXT}; }}"
        )
        self._sidebar_notch.clicked.connect(self._toggle_sidebar)
        # Install event filters on the view and the sidebar pane so we
        # see canvas resizes AND sidebar show/hide/resize, which together
        # cover every way the sidebar can disappear.
        self.view.installEventFilter(self)
        self._sidebar_widget.installEventFilter(self)
        # Splitter drag can also collapse the sidebar (width → 0 without
        # hide()), so listen for splitterMoved to keep the notch in sync.
        self.splitter.splitterMoved.connect(lambda *_: self._update_notch_visibility())
        self._sidebar_notch.show()
        self._sidebar_notch.raise_()
        self._reposition_sidebar_notch()

    def _sidebar_is_visible(self) -> bool:
        if not hasattr(self, "_sidebar_widget"):
            return False
        if not self._sidebar_widget.isVisible():
            return False
        sizes = self.splitter.sizes()
        # Splitter index 1 is the sidebar pane.
        return len(sizes) >= 2 and sizes[1] > 4

    def _update_notch_visibility(self):
        """Notch is always visible — it's a toggle, not a reveal-only handle.

        The chevron direction flips so the user can tell at a glance which
        way clicking will move the sidebar: ``‹`` = pull sidebar in, ``›``
        = push it back out.
        """
        notch = getattr(self, "_sidebar_notch", None)
        if notch is None:
            return
        if self._sidebar_is_visible():
            notch.setText("›")
            notch.setToolTip("Hide inspector sidebar")
        else:
            notch.setText("‹")
            notch.setToolTip("Show inspector sidebar")
        notch.show()
        notch.raise_()
        self._reposition_sidebar_notch()

    def _toggle_sidebar(self):
        if self._sidebar_is_visible():
            self.hide_sidebar()
        else:
            self._reveal_sidebar()

    def _reposition_sidebar_notch(self):
        notch = getattr(self, "_sidebar_notch", None)
        if notch is None:
            return
        view = getattr(self, "view", None)
        if view is None:
            return
        x = max(0, view.width() - notch.width())
        y = max(0, (view.height() - notch.height()) // 2)
        notch.move(x, y)
        notch.raise_()

    def _reveal_sidebar(self):
        if not hasattr(self, "_sidebar_widget"):
            return
        # Show the widget (in case it was hide()-ed) AND give it a non-zero
        # split size (in case the user dragged the handle to collapse it).
        if not self._sidebar_widget.isVisible():
            self._sidebar_widget.show()
        self.splitter.setSizes(getattr(self, "_sidebar_default_sizes", [1000, 400]))
        self._update_notch_visibility()

    def hide_sidebar(self):
        if hasattr(self, "_sidebar_widget"):
            self._sidebar_widget.hide()
        self._update_notch_visibility()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_notch_visibility()

    def eventFilter(self, obj, event):
        et = event.type()
        # Resize of the canvas → reposition. Show/Hide of the sidebar pane
        # → keep the notch in sync (covers programmatic and user-driven
        # collapses that don't fire splitterMoved).
        if obj is getattr(self, "view", None) and et == QEvent.Resize:
            self._update_notch_visibility()
        elif obj is getattr(self, "_sidebar_widget", None) and et in (
            QEvent.Show, QEvent.Hide, QEvent.Resize,
        ):
            self._update_notch_visibility()
        return super().eventFilter(obj, event)

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
            # Keyboards without a dedicated Delete key (e.g. compact
            # laptop layouts) get Backspace and X as aliases.
            ("Backspace", self.delete_selected),
            ("X", self.delete_selected),
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
        self._commit_description()
        self._commit_body()

        n = self._selected_single_node()
        if n is None:
            self._set_sidebar_enabled(False)
            self._title_input.blockSignals(True)
            self._title_input.setText("")
            self._title_input.setPlaceholderText("Select or double-click a note")
            self._title_input.blockSignals(False)
            self._desc_edit.blockSignals(True)
            self._desc_edit.setPlainText("")
            self._desc_edit.blockSignals(False)
            self._body_edit.blockSignals(True)
            self._body_edit.setPlainText("")
            self._body_edit.blockSignals(False)
            self._edit_target_id: Optional[int] = None
            self._baseline_text = ""
            self._baseline_description = ""
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
        self._baseline_description = n.description
        self._baseline_body = n.body
        self._title_input.blockSignals(True)
        self._title_input.setText(n.text)
        self._title_input.setPlaceholderText("Title…")
        self._title_input.blockSignals(False)
        self._desc_edit.blockSignals(True)
        self._desc_edit.setPlainText(n.description)
        self._desc_edit.blockSignals(False)
        self._body_edit.blockSignals(True)
        self._body_edit.setPlainText(n.body)
        self._body_edit.blockSignals(False)
        deg = self.scene.degree_of(n.id)
        self._sidebar_hint.setText(f"Node #{n.id} · {deg} connection{'s' if deg != 1 else ''}")
        self._bold.blockSignals(True); self._bold.setChecked(n.bold); self._bold.blockSignals(False)
        self._italic.blockSignals(True); self._italic.setChecked(n.italic); self._italic.blockSignals(False)
        self._sync_folder_inspector(n)
        self._sync_reminder_inspector(n)

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

    def _schedule_live_description(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        n = self.scene.graph.nodes.get(nid)
        if n is None:
            return
        n.description = self._desc_edit.toPlainText()
        item = self.scene.node_items.get(nid)
        if item is not None:
            item.refresh()

    def _commit_description(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        if nid not in self.scene.graph.nodes:
            return
        new_desc = self._desc_edit.toPlainText()
        self._push_attr_edit(nid, "description", new_desc,
                             baseline=getattr(self, "_baseline_description", new_desc),
                             label="Edit description")

    def _import_notes_markdown(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Markdown into notes", "", "Markdown (*.md *.markdown);;All files (*)"
        )
        if not path:
            return
        try:
            text = Path(path).read_text()
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))
            return
        self._body_edit.blockSignals(True)
        self._body_edit.setPlainText(text)
        self._body_edit.blockSignals(False)
        # Push through the schedule/commit pipeline so the change is undoable.
        self._schedule_live_body()
        self._commit_body()

    # ---- folder shortcut --------------------------------------------------
    def _sync_folder_inspector(self, n: Node):
        """Populate the Folder section from the node's ``dir_links`` dict."""
        host = dirlink.current_device_key()
        local_path = n.dir_links.get(host, "")
        has_any = bool(n.dir_links)
        self._folder_check.blockSignals(True)
        self._folder_check.setChecked(has_any)
        self._folder_check.blockSignals(False)
        self._folder_path.blockSignals(True)
        self._folder_path.setText(local_path)
        self._folder_path.setEnabled(has_any)
        self._folder_path.blockSignals(False)
        self._update_folder_hint(n, host, local_path)

    def _update_folder_hint(self, n: Node, host: str, local_path: str):
        # Build hint reflecting (a) where the path resolves, and (b) which
        # other devices already have an entry on this node.
        others = [k for k in n.dir_links.keys() if k != host]
        if local_path:
            exists = dirlink.path_exists(local_path)
            self._folder_open_btn.setEnabled(exists)
            base = ("✓ Path exists on this device" if exists
                    else "⚠ Path doesn't exist on this device yet")
        else:
            self._folder_open_btn.setEnabled(False)
            base = (f"No path set for {host}." if n.dir_links
                    else "Add a folder path. Each device keeps its own.")
        if others:
            base += f"  Also linked on: {', '.join(others)}."
        self._folder_hint.setText(base)

    def _on_folder_toggle(self, checked: bool):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None or nid not in self.scene.graph.nodes:
            return
        n = self.scene.graph.nodes[nid]
        if not checked:
            # Clear all device entries — uncheck means "no folder link".
            if n.dir_links:
                n.dir_links = {}
                self._refresh_node_card(nid)
            self._folder_path.blockSignals(True)
            self._folder_path.setText("")
            self._folder_path.setEnabled(False)
            self._folder_path.blockSignals(False)
        else:
            self._folder_path.setEnabled(True)
            self._folder_path.setFocus()
        host = dirlink.current_device_key()
        self._update_folder_hint(n, host, n.dir_links.get(host, ""))

    def _commit_folder_path(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None or nid not in self.scene.graph.nodes:
            return
        n = self.scene.graph.nodes[nid]
        host = dirlink.current_device_key()
        new_path = self._folder_path.text().strip()
        cur_path = n.dir_links.get(host, "")
        if new_path == cur_path:
            self._update_folder_hint(n, host, new_path)
            return
        new_links = dict(n.dir_links)
        if new_path:
            new_links[host] = new_path
        else:
            new_links.pop(host, None)
        n.dir_links = new_links
        self._refresh_node_card(nid)
        self._update_folder_hint(n, host, new_path)
        # Keep the toggle in sync: emptying the last device's entry
        # un-checks the box.
        self._folder_check.blockSignals(True)
        self._folder_check.setChecked(bool(new_links))
        self._folder_check.blockSignals(False)

    def _open_folder_for_selected(self):
        n = self._selected_single_node()
        if n is None:
            return
        path = dirlink.resolve_path(n.dir_links)
        if path and dirlink.path_exists(path):
            dirlink.open_path(path)

    def _refresh_node_card(self, nid: int):
        item = self.scene.node_items.get(nid)
        if item is not None:
            item.refresh()

    # ---- reminder ---------------------------------------------------------
    def _sync_reminder_inspector(self, n: Node):
        rem = n.reminder or {}
        active = bool(rem)
        self._rem_check.blockSignals(True)
        self._rem_check.setChecked(active)
        self._rem_check.blockSignals(False)
        self._rem_when.blockSignals(True)
        self._rem_when.setText(rem.get("spec", ""))
        self._rem_when.setEnabled(active)
        self._rem_when.blockSignals(False)
        self._rem_message.blockSignals(True)
        self._rem_message.setText(rem.get("message", ""))
        self._rem_message.setEnabled(active)
        self._rem_message.blockSignals(False)
        self._rem_ai_prompt.blockSignals(True)
        self._rem_ai_prompt.setPlainText(rem.get("claude_prompt", ""))
        self._rem_ai_prompt.setEnabled(active)
        self._rem_ai_prompt.blockSignals(False)
        self._rem_mac.blockSignals(True)
        # If a reminder already exists, restore its host. New nodes default
        # to "mac" so the cron fires whether or not this Linux box is on.
        self._rem_mac.setChecked(rem.get("host", "mac") == "mac")
        self._rem_mac.setEnabled(active)
        self._rem_mac.blockSignals(False)
        self._rem_save_btn.setEnabled(active)
        self._rem_clear_btn.setEnabled(bool(rem))
        self._update_reminder_hint()

    def _update_reminder_hint(self):
        spec = self._rem_when.text().strip()
        if not self._rem_check.isChecked():
            self._rem_hint.setText("")
            self._rem_save_btn.setEnabled(False)
            return
        tools = reminders.has_tools()
        missing = [k for k, v in tools.items() if not v]
        if missing:
            self._rem_hint.setText(
                f"⚠ This device is missing: {', '.join(missing)}. "
                "Reminders won't fire here until those are installed."
            )
        if not spec:
            if not missing:
                self._rem_hint.setText("Type when it should fire.")
            self._rem_save_btn.setEnabled(False)
            return
        parsed = reminders.parse_reminder(spec)
        if parsed is None:
            self._rem_hint.setText("⚠ Couldn't parse — try \"daily at 9am\" or \"in 30 minutes\".")
            self._rem_save_btn.setEnabled(False)
            return
        prefix = "" if not missing else self._rem_hint.text() + "  "
        self._rem_hint.setText(prefix + f"→ {parsed.summary}")
        self._rem_save_btn.setEnabled(not missing)

    def _on_reminder_when_changed(self, _text: str):
        self._update_reminder_hint()

    def _on_reminder_toggle(self, checked: bool):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None or nid not in self.scene.graph.nodes:
            return
        n = self.scene.graph.nodes[nid]
        if not checked and n.reminder:
            self._clear_reminder()
            return
        self._rem_when.setEnabled(checked)
        self._rem_message.setEnabled(checked)
        self._rem_save_btn.setEnabled(checked and bool(self._rem_when.text().strip()))
        if checked:
            self._rem_when.setFocus()
        self._update_reminder_hint()

    def _save_reminder(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None or nid not in self.scene.graph.nodes:
            return
        n = self.scene.graph.nodes[nid]
        spec = self._rem_when.text().strip()
        message = self._rem_message.text().strip() or n.text or "Reminder"
        ai_prompt = self._rem_ai_prompt.toPlainText().strip()
        run_on_mac = self._rem_mac.isChecked()
        parsed = reminders.parse_reminder(spec)
        if parsed is None:
            self._rem_hint.setText("⚠ Couldn't parse the schedule.")
            return
        # AI mode requires a saved file: cron needs an on-disk JSON to
        # read the latest node + context at fire time.
        if (ai_prompt or run_on_mac) and self.current_path is None:
            self._rem_hint.setText(
                "⚠ Save the mindmap to a file first — "
                "AI / Mac-delegated reminders need an on-disk JSON."
            )
            return
        ai_json_path = str(self.current_path) if ai_prompt else None

        try:
            if run_on_mac:
                # Always re-save before delegating, so the Mac sees the
                # latest node text / dir_links / connections at fire time.
                self.save_file()
                ok, push_msg = self._push_json_to_mac()
                if not ok:
                    self._rem_hint.setText(f"✗ Mac sync: {push_msg}")
                    return
                ok, boot_msg = macdg.bootstrap()
                if not ok:
                    self._rem_hint.setText(f"✗ Mac setup: {boot_msg}")
                    return
                # Clear any prior local install so we don't double-fire.
                reminders.remove(nid)
                ai_basename = (Path(self.current_path).name
                               if ai_prompt else None)
                macdg.install(nid, parsed, message,
                              ai_json_basename=ai_basename)
                host = "mac"
            else:
                # Clear any prior mac install on best-effort basis (don't
                # fail the save if mac is unreachable).
                try:
                    if macdg.is_reachable():
                        macdg.remove(nid)
                except Exception:
                    pass
                reminders.install(nid, parsed, message,
                                  ai_json_path=ai_json_path)
                host = "local"
        except Exception as exc:
            self._rem_hint.setText(f"✗ Failed: {exc}")
            return

        n.reminder = {"spec": spec, "message": message,
                      "kind": parsed.kind, "schedule": parsed.schedule,
                      "host": host}
        if ai_prompt:
            n.reminder["claude_prompt"] = ai_prompt
        self._refresh_node_card(nid)
        location = "Mac (always-on)" if host == "mac" else "this device"
        suffix = "  (AI)" if ai_prompt else ""
        self._rem_hint.setText(
            f"✓ Installed on {location} — {parsed.summary}{suffix}"
        )
        self._rem_clear_btn.setEnabled(True)

    def _open_mac_log(self):
        """Spawn a terminal that tails the Mac's reminder log over SSH.
        Read-only, Ctrl+C closes it. Uses Ptyxis (the user's preferred
        terminal on Fedora) when available, falling back to xterm or
        x-terminal-emulator."""
        import shutil, subprocess
        cmd = ("ssh -t -o BatchMode=yes -o ConnectTimeout=5 mac "
               "'tail -F ~/.cache/pymindmap-notify.log 2>/dev/null || "
               "echo \"(no log yet — fire a reminder first)\"; sleep 3'")
        for term in ("ptyxis", "gnome-terminal", "xterm"):
            if shutil.which(term):
                if term == "ptyxis":
                    subprocess.Popen([term, "--", "bash", "-c", cmd])
                elif term == "gnome-terminal":
                    subprocess.Popen([term, "--", "bash", "-c", cmd])
                else:
                    subprocess.Popen([term, "-e", "bash", "-c", cmd])
                return
        self._status_label.setText("(no terminal emulator found)")

    def _push_json_to_mac(self) -> tuple[bool, str]:
        """Rsync the current mindmap JSON to the Mac's rendezvous folder.
        The launcher already does this on app close; we replicate it
        here so a freshly-saved reminder can be installed immediately
        without forcing the user to quit first."""
        if self.current_path is None:
            return False, "no file"
        import subprocess
        cmd = ["rsync", "-t", "--update",
               "-e", "ssh -o BatchMode=yes -o ConnectTimeout=8",
               str(self.current_path),
               f"mac:Sync/pymindmap/{self.current_path.name}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, str(exc)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout).strip()[:200]
        return True, "ok"

    def _clear_reminder(self):
        nid = getattr(self, "_edit_target_id", None)
        if nid is None or nid not in self.scene.graph.nodes:
            return
        n = self.scene.graph.nodes[nid]
        # Try both local and mac so an old delegation is cleaned up
        # regardless of where it was installed. Mac removal is best-
        # effort since it might be asleep.
        try:
            reminders.remove(nid)
        except Exception as exc:
            self._rem_hint.setText(f"✗ Failed to remove local: {exc}")
            return
        try:
            if macdg.is_reachable():
                macdg.remove(nid)
        except Exception:
            pass
        n.reminder = None
        self._refresh_node_card(nid)
        self._rem_check.blockSignals(True)
        self._rem_check.setChecked(False)
        self._rem_check.blockSignals(False)
        self._rem_when.blockSignals(True)
        self._rem_when.setText("")
        self._rem_when.setEnabled(False)
        self._rem_when.blockSignals(False)
        self._rem_message.blockSignals(True)
        self._rem_message.setText("")
        self._rem_message.setEnabled(False)
        self._rem_message.blockSignals(False)
        self._rem_ai_prompt.blockSignals(True)
        self._rem_ai_prompt.setPlainText("")
        self._rem_ai_prompt.setEnabled(False)
        self._rem_ai_prompt.blockSignals(False)
        self._rem_mac.blockSignals(True)
        self._rem_mac.setChecked(True)  # default for the next reminder
        self._rem_mac.setEnabled(False)
        self._rem_mac.blockSignals(False)
        self._rem_save_btn.setEnabled(False)
        self._rem_clear_btn.setEnabled(False)
        self._rem_hint.setText("Reminder removed.")

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
        elif attr == "description":
            self._baseline_description = new_val
        # Size-affecting edits → request a layout pass.
        if attr in ("text", "body", "description"):
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
        self._reveal_sidebar()
        self.scene.clearSelection()
        item.setSelected(True)
        # Always focus the TITLE input on double-click — the user wants to
        # rename the node, not edit its description or notes.
        self._title_input.setFocus()
        self._title_input.selectAll()

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

    # ---- spread slider --------------------------------------------------
    def _slider_to_scale(self, value: int) -> float:
        # 0 → 0.25, 100 (centre) → 1.0, 200 → 4.0. Two octaves either side.
        import math
        return 2.0 ** ((value - 100) / 50.0)

    def _scale_to_slider(self, scale: float) -> int:
        import math
        return int(round(100 + 50.0 * math.log2(max(0.05, min(8.0, scale)))))

    def _on_spread_changed(self, value: int):
        scale = self._slider_to_scale(value)
        self.scene.set_repulsion_scale(scale)
        QSettings().setValue("spread_scale", scale)

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
                   if text in n.text.lower() or text in n.body.lower()
                      or text in n.description.lower()]
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
                x=src.x + 30, y=src.y + 30, text=src.text,
                description=src.description, body=src.body,
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
        self._remember_recent(path)
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
        self._commit_description()
        self._commit_body()
        if self.current_path is None:
            self.save_file_as()
            return
        try:
            mio.save_graph(self.scene.graph, self.current_path)
            self.undo_stack.setClean()
            self._remember_recent(self.current_path)
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

    def _remember_recent(self, path: Path) -> None:
        """Persist the given path as the most recently opened file so the
        next launch can reopen it automatically."""
        QSettings().setValue("recent_path", str(path))

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
        self._commit_description()
        self._commit_body()
        if self._confirm_discard():
            e.accept()
        else:
            e.ignore()

    # ---- display-change handling ----------------------------------------
    def showEvent(self, e):
        super().showEvent(e)
        h = self.windowHandle()
        if h is not None and h.screen() is not self._connected_screen:
            if self._connected_screen is not None:
                try:
                    h.screenChanged.disconnect(self._on_screen_changed)
                except (TypeError, RuntimeError):
                    pass
            h.screenChanged.connect(self._on_screen_changed)
            self._connected_screen = h.screen()

    def _on_screen_changed(self, _screen):
        """Rebuild every node's cached metrics when the DPI changes.

        Font metrics are computed against the current paint device, so
        moving between displays with different device-pixel ratios can
        leave node widths stale. Forcing ``_refresh_node_sizes`` picks up
        the new screen's metrics.
        """
        self.scene._refresh_node_sizes()
