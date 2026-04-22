"""Graph layouts — Fruchterman–Reingold and a radial tree.

Pure-math, Qt-free. Given a Graph (+ optionally a spanning tree), returns a
dict of new (x, y) for each node. Keeps existing positions as the starting
configuration so the animation is stable (nodes don't fly in from random
starts).
"""
from __future__ import annotations

import math
import random
from collections import defaultdict, deque
from typing import Dict, Iterable, List, Optional, Set, Tuple

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
                # Hard-shell kick when cards would geometrically overlap.
                # Uses the nodes' actual half-diagonals (ra, radius[b]) so
                # big hubs get the space they need, plus a visual gap.
                min_gap = ra + radius[b] + 14.0
                if dist < min_gap:
                    # Quadratic ramp: gentle at the border, strong at real
                    # overlap. 0.55 is tuned so a fully-overlapped pair gets
                    # pushed apart within a few iterations without the
                    # neighbourhood exploding.
                    overlap = (min_gap - dist) / min_gap
                    force += overlap * overlap * k * 0.55 * min_gap
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


# ---------------------------------------------------------------------------
# Radial tree layout
# ---------------------------------------------------------------------------
def radial_tree_layout(
    graph: Graph,
    *,
    parent: Optional[Dict[int, Optional[int]]] = None,
    children: Optional[Dict[int, Set[int]]] = None,
    ring_gap: Optional[float] = None,
    component_gap: Optional[float] = None,
    existing: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[int, Tuple[float, float]]:
    """Place each connected component as a radial tree around its root.

    Angular wedges are recursively sized from each subtree's *required* arc
    length — the width a subtree needs at its deepest ring to fit its leaves
    without overlap. That prevents two problems:
      • Narrow subtrees don't steal space from bushier siblings.
      • Leaves at the outermost ring always have at least ``min_arc`` between
        them.

    Tree edges cannot cross by construction. Any remaining crossings are
    non-tree edges (cycles in the graph) that the layout can't remove.

    Isolated singletons and tiny components are packed into a compact grid
    rather than each consuming a full component-gap of empty space.
    """
    nodes = graph.nodes
    if not nodes:
        return {}

    # ----- build spanning tree if caller didn't supply one -----
    if parent is None or children is None:
        parent, children = _bfs_spanning_tree(graph)

    # ----- compact sizing (was spreading the graph too thin) -----
    dims = [max(n.width, n.height) for n in nodes.values()]
    mean_dim = sum(dims) / max(1, len(dims))
    # ring_gap ≈ one node-width — compact but never overlapping.
    if ring_gap is None:
        ring_gap = max(110.0, mean_dim * 1.0)
    if component_gap is None:
        component_gap = ring_gap * 1.1

    # Minimum arc length per leaf at its ring — keeps adjacent leaves from
    # overlapping their labels.
    min_arc = mean_dim * 1.05

    roots = [nid for nid, p in parent.items() if p is None]
    orphans = [nid for nid in nodes if nid not in parent]

    # Precompute leaf count and the max depth below each node; both feed the
    # wedge-sizing calculation below.
    leaves = _count_leaves(roots, children)
    subtree_depth: Dict[int, int] = {}
    for r in roots:
        _compute_subtree_depth(r, children, subtree_depth)

    # Required wedge for a subtree at a given depth: enough arc length at its
    # deepest ring to fit all its leaves with ``min_arc`` spacing each.
    def required_wedge(nid: int, depth: int) -> float:
        leaf_cnt = leaves.get(nid, 1)
        deepest = depth + subtree_depth.get(nid, 0)  # outermost ring index
        outer_r = max(1.0, deepest * ring_gap) if deepest > 0 else ring_gap
        return (leaf_cnt * min_arc) / outer_r

    result: Dict[int, Tuple[float, float]] = {}
    component_positions: Dict[int, Dict[int, Tuple[float, float]]] = {}
    component_bounds: List[Tuple[int, float, float, float, float]] = []

    # Separate "real" trees from singletons — singletons pack into a grid.
    real_roots = [r for r in roots if children.get(r)]
    singleton_roots = [r for r in roots if not children.get(r)]

    for root in real_roots:
        comp_pos: Dict[int, Tuple[float, float]] = {}
        _place_subtree(
            root, children, leaves, required_wedge, comp_pos,
            center=(0.0, 0.0),
            angle_start=0.0,
            angle_end=2 * math.pi,
            depth=0,
            ring_gap=ring_gap,
        )
        component_positions[root] = comp_pos
        if comp_pos:
            xs = [p[0] for p in comp_pos.values()]
            ys = [p[1] for p in comp_pos.values()]
            # Pad bounds by half the max node dim so the next component
            # doesn't park its root flush against this one's leaves.
            pad = mean_dim * 0.6
            component_bounds.append((root,
                                     min(xs) - pad, min(ys) - pad,
                                     max(xs) + pad, max(ys) + pad))

    # Place real components left-to-right, biggest first.
    component_bounds.sort(key=lambda cb: -(cb[3] - cb[1]) - (cb[4] - cb[2]))
    cursor_x = 0.0
    for root, xmin, ymin, xmax, ymax in component_bounds:
        width = xmax - xmin
        offset_x = cursor_x - xmin
        for nid, (x, y) in component_positions[root].items():
            result[nid] = (x + offset_x, y)
        cursor_x += width + component_gap

    # Singletons + orphans: pack into a grid to the right of the last
    # component. Keeps stray nodes visible without wasting a whole ring of
    # empty space per node.
    stray = singleton_roots + orphans
    if stray:
        cell = mean_dim + 24
        cols = max(1, int(math.ceil(math.sqrt(len(stray)))))
        for i, nid in enumerate(stray):
            r, c = divmod(i, cols)
            result[nid] = (cursor_x + c * cell, r * cell)

    # Center the whole layout on the origin, and convert from centers to
    # top-left (LiveNodeItem positions the card's top-left at node.x/y).
    if result:
        xs = [p[0] for p in result.values()]
        ys = [p[1] for p in result.values()]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        for nid in list(result.keys()):
            x, y = result[nid]
            node = nodes[nid]
            result[nid] = (x - cx - node.width / 2, y - cy - node.height / 2)

    return result


def _compute_subtree_depth(nid: int,
                           children: Dict[int, Set[int]],
                           out: Dict[int, int]) -> int:
    kids = children.get(nid)
    if not kids:
        out[nid] = 0
        return 0
    best = 0
    for c in kids:
        best = max(best, _compute_subtree_depth(c, children, out) + 1)
    out[nid] = best
    return best


def _count_leaves(roots: Iterable[int],
                  children: Dict[int, Set[int]]) -> Dict[int, int]:
    """Leaf count under each node (leaf itself counts as 1)."""
    leaves: Dict[int, int] = {}

    def count(nid: int) -> int:
        if nid in leaves:
            return leaves[nid]
        kids = children.get(nid)
        if not kids:
            leaves[nid] = 1
            return 1
        total = sum(count(c) for c in kids)
        leaves[nid] = max(1, total)
        return leaves[nid]

    for r in roots:
        count(r)
    return leaves


def _place_subtree(
    nid: int,
    children: Dict[int, Set[int]],
    leaves: Dict[int, int],
    required_wedge,
    out: Dict[int, Tuple[float, float]],
    *,
    center: Tuple[float, float],
    angle_start: float,
    angle_end: float,
    depth: int,
    ring_gap: float,
):
    """Recursive radial placement. ``out`` is filled with node centers."""
    if depth == 0:
        out[nid] = center
    else:
        angle = (angle_start + angle_end) / 2.0
        r = depth * ring_gap
        out[nid] = (center[0] + math.cos(angle) * r,
                    center[1] + math.sin(angle) * r)

    kids = children.get(nid)
    if not kids:
        return

    # Child order: largest subtrees on the outside of the wedge, smallest in
    # the middle. That visually balances the fan.
    ordered = sorted(kids, key=lambda c: (-leaves.get(c, 1), c))
    # Reorder: alternate big/small so large subtrees sit on the wedge edges.
    arranged: List[int] = []
    left, right = [], []
    for i, c in enumerate(ordered):
        (left if i % 2 == 0 else right).append(c)
    arranged = left + list(reversed(right))

    # Required wedge per child = max(its intrinsic need, proportional share).
    needs = [required_wedge(c, depth + 1) for c in arranged]
    total_need = sum(needs) or 1.0

    # Parent's available wedge (full circle at root, parent-allocated below).
    if depth == 0:
        # Use exactly what's needed, capped at full circle. Leaves of the
        # root's subtrees get min_arc spacing on the outermost ring.
        wedge = min(2 * math.pi, max(needs and max(needs), total_need))
    else:
        wedge = max(1e-6, angle_end - angle_start)
        # If the parent wedge is too narrow to fit the children's minimum
        # needs, grow it — better to push on sibling branches than overlap.
        if total_need > wedge:
            wedge = total_need

    mid = (angle_start + angle_end) / 2.0
    a0 = mid - wedge / 2.0
    cur = a0
    for c, need in zip(arranged, needs):
        share = (need / total_need) * wedge
        _place_subtree(
            c, children, leaves, required_wedge, out,
            center=center,
            angle_start=cur,
            angle_end=cur + share,
            depth=depth + 1,
            ring_gap=ring_gap,
        )
        cur += share


def _bfs_spanning_tree(graph: Graph):
    """Build a BFS spanning tree rooted at the highest-degree node per comp."""
    adj: Dict[int, Set[int]] = defaultdict(set)
    for c in graph.connections:
        adj[c.from_id].add(c.to_id)
        adj[c.to_id].add(c.from_id)

    degree = {nid: len(adj[nid]) for nid in graph.nodes}

    parent: Dict[int, Optional[int]] = {}
    children: Dict[int, Set[int]] = defaultdict(set)
    remaining = set(graph.nodes.keys())
    while remaining:
        root = max(remaining, key=lambda n: (degree.get(n, 0), -n))
        parent[root] = None
        q = deque([root])
        remaining.discard(root)
        while q:
            cur = q.popleft()
            for nb in adj[cur]:
                if nb in remaining:
                    parent[nb] = cur
                    children[cur].add(nb)
                    remaining.discard(nb)
                    q.append(nb)
    return parent, children
