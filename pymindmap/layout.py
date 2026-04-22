"""Force-directed graph layout (Fruchterman–Reingold).

Pure-math, Qt-free. Given a Graph, returns a dict of new (x, y) for each node.
Keeps existing positions as the starting configuration so the animation is
stable (nodes don't fly in from random starts).
"""
from __future__ import annotations

import math
import random
from typing import Dict, Tuple

from .model import Graph


def fruchterman_reingold(
    graph: Graph,
    *,
    iterations: int = 200,
    ideal_distance: float | None = None,
    seed: int | None = None,
    compactness: float = 1.05,
    center_force: float = 0.9,
) -> Dict[int, Tuple[float, float]]:
    """Return new positions keyed by node id.

    ``ideal_distance`` = natural edge length between *centers*. Defaults to
    ``max(avg_w, avg_h) * compactness`` — a tight packing that still leaves a
    visible gap between connected cards. Pass a larger ``compactness`` for
    more airiness.

    ``center_force`` (0..1) is a light spring pulling every node toward the
    origin each step. Higher values make the layout more compact.
    """
    nodes = list(graph.nodes.values())
    n = len(nodes)
    if n == 0:
        return {}

    rng = random.Random(seed)

    # Positions are node *centers*.
    # We rescale the starting positions into a bounded frame sized to the
    # desired ideal distance, so the final layout is compact instead of
    # inheriting whatever spread the user's current positions have.
    raw: Dict[int, list] = {}
    for node in nodes:
        raw[node.id] = [node.x + node.width / 2, node.y + node.height / 2]

    # Adjacency (undirected for layout).
    adj: Dict[int, set] = {node.id: set() for node in nodes}
    for c in graph.connections:
        if c.from_id in adj and c.to_id in adj:
            adj[c.from_id].add(c.to_id)
            adj[c.to_id].add(c.from_id)

    # Default ideal distance: avg node dimension scaled by ``compactness``.
    # compactness=1.0 → centers avg-node-size apart (cards touching).
    # compactness=1.15 → small visible gap. Higher → airier.
    if ideal_distance is None:
        avg_w = sum(node.width for node in nodes) / n
        avg_h = sum(node.height for node in nodes) / n
        k = max(avg_w, avg_h) * compactness
    else:
        k = float(ideal_distance)

    # Per-node "radius" so big hubs don't overlap small leaves: the effective
    # minimum distance between two nodes is scaled by their sizes.
    radius: Dict[int, float] = {}
    for node in nodes:
        radius[node.id] = max(node.width, node.height) / 2.0

    # Frame size: side length ~ k * sqrt(n). All starting positions are rescaled
    # into this frame so the layout doesn't inherit arbitrary initial spread.
    frame = k * math.sqrt(n + 1)
    pos: Dict[int, list] = {}
    xs = [p[0] for p in raw.values()]
    ys = [p[1] for p in raw.values()]
    x_span = max(max(xs) - min(xs), 1.0)
    y_span = max(max(ys) - min(ys), 1.0)
    scale = frame / max(x_span, y_span)
    x_min, y_min = min(xs), min(ys)
    for nid, (rx, ry) in raw.items():
        # Map into [-frame/2, frame/2] with jitter.
        nx = (rx - x_min) * scale - frame / 2
        ny = (ry - y_min) * scale - frame / 2
        pos[nid] = [nx + rng.uniform(-0.5, 0.5), ny + rng.uniform(-0.5, 0.5)]

    # Starting temperature: a fraction of the frame so we don't fling nodes.
    t = frame / 10.0
    cooling = t / iterations

    k_sq = k * k

    for _step in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in pos}

        # Repulsive: every pair of nodes pushes each other. Nodes that are
        # closer than (radius_a + radius_b + margin) get a hard-shell boost so
        # oversized hubs can't overlap their small neighbors.
        ids = list(pos.keys())
        for i in range(len(ids)):
            a = ids[i]
            pax, pay = pos[a]
            ra = radius[a]
            for j in range(i + 1, len(ids)):
                b = ids[j]
                pbx, pby = pos[b]
                dx = pax - pbx
                dy = pay - pby
                dist_sq = dx * dx + dy * dy
                if dist_sq < 0.01:
                    dx = rng.uniform(-1, 1)
                    dy = rng.uniform(-1, 1)
                    dist_sq = dx * dx + dy * dy
                dist = math.sqrt(dist_sq)
                force = k_sq / dist
                # Small anti-overlap boost when cards would geometrically
                # touch. Kept modest to avoid flinging nodes apart.
                min_gap = ra + radius[b] + 8.0
                if dist < min_gap:
                    force += (min_gap - dist) * k * 0.15
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp[a][0] += fx
                disp[a][1] += fy
                disp[b][0] -= fx
                disp[b][1] -= fy

        # Attractive: each edge pulls its endpoints together.
        seen = set()
        for a, neighbors in adj.items():
            for b in neighbors:
                if (b, a) in seen:
                    continue
                seen.add((a, b))
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = math.sqrt(dx * dx + dy * dy) or 0.01
                force = (dist * dist) / k
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                disp[a][0] -= fx
                disp[a][1] -= fy
                disp[b][0] += fx
                disp[b][1] += fy

        # Centering spring — pulls everything toward the origin, stronger
        # than the classic F-R to prevent leaves from drifting far out.
        for nid, p in pos.items():
            disp[nid][0] -= p[0] * center_force
            disp[nid][1] -= p[1] * center_force

        # Apply displacement capped by temperature.
        for nid, (dx, dy) in disp.items():
            mag = math.sqrt(dx * dx + dy * dy) or 1.0
            step = min(mag, t)
            pos[nid][0] += (dx / mag) * step
            pos[nid][1] += (dy / mag) * step

        t = max(0.01, t - cooling)

    # Convert centers back to top-left, and center whole layout on origin.
    cx_mean = sum(p[0] for p in pos.values()) / n
    cy_mean = sum(p[1] for p in pos.values()) / n
    result: Dict[int, Tuple[float, float]] = {}
    for node in nodes:
        cx, cy = pos[node.id]
        result[node.id] = (cx - cx_mean - node.width / 2,
                           cy - cy_mean - node.height / 2)
    return result
