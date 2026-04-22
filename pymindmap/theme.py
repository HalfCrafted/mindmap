"""Theme constants. Override via ``pymindmap.theme.THEME.update(...)`` before launch."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Theme:
    # Canvas
    bg: str = "#0a0a0a"
    grid_dot: str = "#1a1a1e"
    grid_spacing: int = 24

    # Nodes
    node_bg: str = "#1a1a1e"
    node_border: str = "#2a2a32"
    node_border_selected: str = "#6366f1"
    node_text: str = "#e6e6ea"
    node_header_default: str = "#6366f1"
    node_radius: int = 8
    node_header_height: int = 6
    node_min_width: int = 80
    node_min_height: int = 44
    node_padding: int = 10

    # Connections
    conn_color: str = "#6366f1"
    conn_selected: str = "#ffb020"
    conn_width: float = 2.0
    waypoint_color: str = "#ffb020"

    # Selection
    marquee_fill: str = "#6366f133"
    marquee_stroke: str = "#6366f1"

    # Default palette for colorizing nodes
    palette: list = field(default_factory=lambda: [
        "#6366f1", "#22c55e", "#ef4444", "#f59e0b",
        "#06b6d4", "#a855f7", "#ec4899", "#10b981",
    ])


THEME = Theme()
