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

    # Ray-exit test: which side of the bounding box does a ray from the
    # node centre toward the target cross *first*? This naturally
    # accounts for node aspect — wide pills exit through top/bottom for
    # most off-horizontal angles, narrow pills the opposite. Crucially,
    # it picks the right answer when bounding boxes *overlap* on one
    # axis (a common layout outcome for wide siblings stacked
    # vertically): the geometrically-shorter axis becomes the exit and
    # the resulting tangent points toward the other node, not away from
    # it through an irrelevant face.
    inset = 0.18
    inf = float("inf")
    t_right = (w * 0.5) / dx if dx > 0 else inf
    t_left = (-w * 0.5) / dx if dx < 0 else inf
    t_bottom = (h * 0.5) / dy if dy > 0 else inf
    t_top = (-h * 0.5) / dy if dy < 0 else inf
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


def _node_contains(node: Node, pt: Tuple[float, float]) -> bool:
    """Whether ``pt`` is inside ``node``'s axis-aligned bounding box."""
    return (node.x <= pt[0] <= node.x + node.width
            and node.y <= pt[1] <= node.y + node.height)


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

    # Degenerate case: nodes overlap so heavily that one anchor sits
    # *inside* the other's bounding box. No bezier can stay outside both
    # nodes — any control-point offset would just dive deeper into a
    # node. Fall back to a straight line so the connection at least
    # renders as something visually identifiable.
    if (not conn.waypoints
            and (_node_contains(to_node, (fx, fy))
                 or _node_contains(from_node, (tx, ty)))):
        return [(fx, fy), (fx, fy), (tx, ty), (tx, ty)]
    # c2 should sit on the "coming from" side of p3 — i.e., *outside* the
    # to-node, along the outward normal. The cubic tangent at p3 is
    # (p3 - c2), so offsetting c2 by +ttan*h makes the curve enter p3
    # moving along -ttan (inward into the node). Using -ttan here placed
    # c2 *inside* the node, producing a loop and throwing the midpoint
    # (where the arrowhead sits) off-centre.
    anchors.append((tx, ty, ttan[0], ttan[1], ttan[0], ttan[1]))

    # Build cubic segments.
    pts: List[Tuple[float, float]] = []
    for i in range(len(anchors) - 1):
        a = anchors[i]
        b = anchors[i + 1]
        p0 = (a[0], a[1])
        p3 = (b[0], b[1])
        dist = ((p3[0] - p0[0]) ** 2 + (p3[1] - p0[1]) ** 2) ** 0.5
        # Handle length scales with distance, capped to avoid wild loops.
        # When endpoint tangents point *away* from each other (i.e. the
        # curve would have to turn around to reach p3), we shorten the
        # handles further: long handles in opposite directions cause
        # severe S-curves whose midpoint tangent points the wrong way
        # for the arrowhead to land on. Detected by dotting the from-
        # tangent with the direction toward p3.
        line_dx = p3[0] - p0[0]
        line_dy = p3[1] - p0[1]
        line_mag = (line_dx * line_dx + line_dy * line_dy) ** 0.5 or 1.0
        ux, uy = line_dx / line_mag, line_dy / line_mag
        # +1 = tangent points at p3, -1 = points away.
        a_align = a[2] * ux + a[3] * uy
        b_align = -(b[4] * ux + b[5] * uy)
        # Shrink handles when either endpoint disagrees with the line
        # direction. align in [-1, 1]; map to [0.15, 1.0]. Aggressive
        # shrink at the disagreeing end keeps the curve from looping
        # back through the node it's meant to be leaving.
        a_scale = 0.15 + 0.85 * max(0.0, (a_align + 1.0) * 0.5)
        b_scale = 0.15 + 0.85 * max(0.0, (b_align + 1.0) * 0.5)
        # Also shrink the absolute handle length when the curve is short
        # — short curves with thick lines look most like arrowheads
        # caught in a corkscrew when handles approach the node radius.
        max_h = min(180.0, dist * 0.5)
        h_a = max_h * a_scale
        h_b = max_h * b_scale
        # c1 uses a's out-tangent; c2 uses b's in-tangent. Per-endpoint
        # handle lengths so an aligned end keeps its smooth curve while
        # an opposing end is reined in.
        c1 = (p0[0] + a[2] * h_a, p0[1] + a[3] * h_a)
        c2 = (p3[0] + b[4] * h_b, p3[1] + b[5] * h_b)
        if i == 0:
            pts.append(p0)
        pts.extend([c1, c2, p3])
    return pts


def cubic_point(p0, c1, c2, p3, t: float) -> Tuple[float, float]:
    mt = 1.0 - t
    x = (mt ** 3) * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + (t ** 3) * p3[0]
    y = (mt ** 3) * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + (t ** 3) * p3[1]
    return x, y
