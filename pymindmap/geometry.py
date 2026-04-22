"""Pure-math helpers for routing bezier connections.

Kept Qt-free so it can be unit-tested headlessly.
"""
from __future__ import annotations

from typing import List, Tuple

from .model import Connection, EdgeAnchor, Node, Waypoint


def anchor_point(node: Node, anchor: EdgeAnchor | None, toward: Tuple[float, float]) -> Tuple[float, float, Tuple[float, float]]:
    """Return (px, py, tangent) for a connection endpoint on *node*.

    Auto-anchor behaviour:
      • Pick the side of the bounding box the line from ``node.center()`` to
        ``toward`` exits through.
      • Place the anchor at the **exact exit point** of that line, not the
        midpoint of the side. So diagonal approaches meet the pill near the
        appropriate end of the edge, making the noodle visually land where
        the eye expects — not the center of the nearest face.
      • Clamp the slide to a small inset from the corner so anchors never
        fall onto the rounded portion of the pill.
    """
    cx, cy = node.center()
    w, h = max(1.0, node.width), max(1.0, node.height)
    left, right = node.x, node.x + w
    top, bottom = node.y, node.y + h

    if anchor and anchor.edge != "auto":
        edge = anchor.edge
        off = max(0.0, min(1.0, anchor.offset))
        if edge == "left":
            return left, top + off * h, (-1.0, 0.0)
        if edge == "right":
            return right, top + off * h, (1.0, 0.0)
        if edge == "top":
            return left + off * w, top, (0.0, -1.0)
        return left + off * w, bottom, (0.0, 1.0)

    dx = toward[0] - cx
    dy = toward[1] - cy
    if dx == 0 and dy == 0:
        # No preferred direction — default to right edge midpoint.
        return right, cy, (1.0, 0.0)

    # Intersection parameter t where the ray from (cx, cy) in direction
    # (dx, dy) crosses each side of the bounding box. The side with the
    # smallest positive t is the exit side.
    inf = float("inf")
    t_right = (w * 0.5) / dx if dx > 0 else inf
    t_left = (-w * 0.5) / dx if dx < 0 else inf
    t_bottom = (h * 0.5) / dy if dy > 0 else inf
    t_top = (-h * 0.5) / dy if dy < 0 else inf

    # Keep anchor off the corner arc by at most a small inset measured in
    # the edge's long dimension. 20% on each end ≈ straight edge for the
    # pill geometry the live variant uses.
    inset = 0.18

    if t_right <= t_bottom and t_right <= t_top and t_right <= t_left:
        y = cy + t_right * dy
        y = min(bottom - inset * h, max(top + inset * h, y))
        return right, y, (1.0, 0.0)
    if t_left <= t_bottom and t_left <= t_top:
        y = cy + t_left * dy
        y = min(bottom - inset * h, max(top + inset * h, y))
        return left, y, (-1.0, 0.0)
    if t_bottom <= t_top:
        x = cx + t_bottom * dx
        x = min(right - inset * w, max(left + inset * w, x))
        return x, bottom, (0.0, 1.0)
    x = cx + t_top * dx
    x = min(right - inset * w, max(left + inset * w, x))
    return x, top, (0.0, -1.0)


def route_bezier(conn: Connection, nodes: dict[int, Node]) -> List[Tuple[float, float]]:
    """Compute the list of cubic-bezier control points for *conn*.

    Returns a flat list [(p0), (c1), (c2), (p1), (c1'), (c2'), (p2), ...]
    one cubic per segment. Segments are:
      node-from -> wp0 -> wp1 -> ... -> node-to

    Waypoints use their own handle offsets; if zero, we auto-smooth.
    """
    from_node = nodes[conn.from_id]
    to_node = nodes[conn.to_id]

    # Build sequence of (point, tangent-out, tangent-in) anchors.
    anchors = []  # list of (x, y, tan_out_dx, tan_out_dy, tan_in_dx, tan_in_dy)

    # From-node
    target = (to_node.center() if not conn.waypoints
              else (conn.waypoints[0].x, conn.waypoints[0].y))
    fx, fy, ftan = anchor_point(from_node, conn.from_anchor, target)
    anchors.append((fx, fy, ftan[0], ftan[1], -ftan[0], -ftan[1]))

    # Waypoints
    for i, w in enumerate(conn.waypoints):
        if w.out_dx or w.out_dy or w.in_dx or w.in_dy:
            anchors.append((
                w.x, w.y,
                w.out_dx, w.out_dy,
                w.in_dx, w.in_dy,
            ))
        else:
            # Auto-smooth: tangent = normalized vector from prev to next.
            prev = anchors[-1][:2]
            if i + 1 < len(conn.waypoints):
                nxt = (conn.waypoints[i + 1].x, conn.waypoints[i + 1].y)
            else:
                nxt = to_node.center()
            tx, ty = nxt[0] - prev[0], nxt[1] - prev[1]
            mag = (tx * tx + ty * ty) ** 0.5 or 1.0
            tx, ty = tx / mag, ty / mag
            anchors.append((w.x, w.y, tx, ty, -tx, -ty))

    # To-node — ``source`` is what the to-node's anchor is pointing *back*
    # toward, i.e. the previous node/waypoint on the path.
    source = (from_node.center() if not conn.waypoints
              else (conn.waypoints[-1].x, conn.waypoints[-1].y))
    tx, ty, ttan = anchor_point(to_node, conn.to_anchor, source)
    # For the to-node, we want the tangent pointing *into* the node along its edge,
    # which means the "incoming" tangent should be -ttan.
    anchors.append((tx, ty, ttan[0], ttan[1], -ttan[0], -ttan[1]))

    # Build cubic segments.
    pts: List[Tuple[float, float]] = []
    for i in range(len(anchors) - 1):
        a = anchors[i]
        b = anchors[i + 1]
        p0 = (a[0], a[1])
        p3 = (b[0], b[1])
        dist = ((p3[0] - p0[0]) ** 2 + (p3[1] - p0[1]) ** 2) ** 0.5
        # Handle length scales with distance, capped to avoid wild loops.
        h = max(30.0, min(180.0, dist * 0.5))
        # c1 uses a's out-tangent; c2 uses b's in-tangent.
        c1 = (p0[0] + a[2] * h, p0[1] + a[3] * h)
        c2 = (p3[0] + b[4] * h, p3[1] + b[5] * h)
        if i == 0:
            pts.append(p0)
        pts.extend([c1, c2, p3])
    return pts


def cubic_point(p0, c1, c2, p3, t: float) -> Tuple[float, float]:
    mt = 1.0 - t
    x = (mt ** 3) * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + (t ** 3) * p3[0]
    y = (mt ** 3) * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + (t ** 3) * p3[1]
    return x, y
