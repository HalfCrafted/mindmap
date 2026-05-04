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
    warm_start: bool = False,
    initial_positions: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[int, Tuple[float, float]]:
    """Return new positions keyed by node id.

    ``ideal_distance`` = natural edge length between *centers*. Defaults to
    ``max(avg_w, avg_h) * compactness`` — a tight packing that still leaves a
    visible gap between connected cards. Pass a larger ``compactness`` for
    more airiness.

    ``center_force`` (0..1) is a light spring pulling every node toward the
    origin each step. Higher values make the layout more compact.

    ``warm_start`` skips the position rescale + jitter and runs at low
    temperature. New nodes (those still at the origin) are placed near a
    connected neighbor before relaxation. Use this for incremental updates
    so structural mutations only nudge the existing layout.

    ``initial_positions`` (optional) overrides ``node.x/node.y`` as the
    starting layout for every node it contains. Top-left coordinates,
    same convention as the return value. Used by ``organic_tree_layout``
    in cold mode to seed F-R from a deterministic radial-tree baseline
    instead of the user's current positions.
    """
    nodes = list(graph.nodes.values())
    n = len(nodes)
    if n == 0:
        return {}

    rng = random.Random(seed)

    # Positions are node *centers*.
    # ``initial_positions`` overrides node.x/y as the starting layout.
    raw: Dict[int, list] = {}
    for node in nodes:
        if initial_positions is not None and node.id in initial_positions:
            ix, iy = initial_positions[node.id]
            raw[node.id] = [ix + node.width / 2, iy + node.height / 2]
        else:
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

    pos: Dict[int, list] = {}
    if warm_start:
        # Use the graph's existing positions verbatim — no rescale, no jitter.
        # New nodes (those still at the origin with no neighbour-derived hint)
        # get a small offset so they don't sit on top of an existing node.
        for nid, (rx, ry) in raw.items():
            looks_unset = abs(rx) < 1.0 and abs(ry) < 1.0
            if looks_unset:
                # Place near a connected neighbour, if any has been positioned.
                for nb in adj[nid]:
                    nb_x, nb_y = raw[nb]
                    if abs(nb_x) >= 1.0 or abs(nb_y) >= 1.0:
                        ang = (nid * 1.0) % (2 * math.pi)  # deterministic
                        rx = nb_x + math.cos(ang) * k
                        ry = nb_y + math.sin(ang) * k
                        break
            pos[nid] = [rx, ry]
        # Low temperature: only nudge.
        t = k / 12.0
    else:
        # Cold layout: rescale the input positions (which the caller has
        # supplied via ``initial_positions`` for determinism, or are the
        # node's current x/y) into a fresh frame, then jitter slightly so
        # symmetric inputs don't deadlock.
        frame = k * math.sqrt(n + 1)
        xs = [p[0] for p in raw.values()]
        ys = [p[1] for p in raw.values()]
        x_span = max(max(xs) - min(xs), 1.0)
        y_span = max(max(ys) - min(ys), 1.0)
        scale = frame / max(x_span, y_span)
        x_min, y_min = min(xs), min(ys)
        for nid, (rx, ry) in raw.items():
            nx = (rx - x_min) * scale - frame / 2
            ny = (ry - y_min) * scale - frame / 2
            pos[nid] = [nx + rng.uniform(-0.5, 0.5), ny + rng.uniform(-0.5, 0.5)]
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

    # Convert centers back to top-left. Cold layouts re-centre on the origin;
    # warm layouts preserve the existing absolute positions so the user's
    # current view doesn't drift on incremental updates.
    if warm_start:
        cx_mean = 0.0
        cy_mean = 0.0
    else:
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


# ---------------------------------------------------------------------------
# Organic tree layout — F-R baseline + tree-aware angular untangling.
# ---------------------------------------------------------------------------
def organic_tree_layout(
    graph: Graph,
    *,
    iterations: int = 200,
    compactness: float = 1.25,
    center_force: float = 0.75,
    seed: Optional[int] = None,
    parent: Optional[Dict[int, Optional[int]]] = None,
    children: Optional[Dict[int, Set[int]]] = None,
    sibling_gap: float = 0.06,
    warm_start: bool = False,
) -> Dict[int, Tuple[float, float]]:
    """Force-directed (neuron-shaped) layout with tree-edge crossings removed.

    Pipeline:
      1. Fruchterman–Reingold lays out the graph for an organic baseline.
      2. The directed connections (or BFS spanning tree) define a tree.
      3. BFS untangle pass: for each parent, if any of its children's subtrees
         occupy overlapping angular wedges around the parent, the colliding
         subtrees are rigidly rotated into non-overlapping wedges. Rotation
         preserves all internal distances and shapes — only the orientation
         of each subtree relative to its parent changes.

    The result keeps F-R's irregular distances and asymmetric branching
    (the "neuron" feel) while guaranteeing tree edges cannot cross.

    ``sibling_gap`` is the minimum angular padding (in radians) inserted
    between adjacent sibling subtrees.
    """
    nodes = graph.nodes
    if not nodes:
        return {}

    # 1. Baseline positions.
    # Cold: full F-R produces an organic spread.
    # Warm: keep the graph's current positions verbatim — only newly-added
    # nodes (still at the origin) get nudged near a connected neighbour.
    # F-R's global relaxation isn't appropriate for incremental updates: it
    # would drag already-settled nodes around.
    if warm_start:
        fr_top_left: Dict[int, Tuple[float, float]] = {}
        adj_pairs: Dict[int, List[int]] = {nid: [] for nid in nodes}
        for c in graph.connections:
            if c.from_id in adj_pairs and c.to_id in adj_pairs:
                adj_pairs[c.from_id].append(c.to_id)
                adj_pairs[c.to_id].append(c.from_id)
        # Two passes so a new node's neighbour gets resolved even if it was
        # added before the neighbour in dict order.
        for _ in range(2):
            for nid, n in nodes.items():
                if nid in fr_top_left:
                    continue
                looks_unset = abs(n.x) < 1.0 and abs(n.y) < 1.0
                if not looks_unset:
                    fr_top_left[nid] = (n.x, n.y)
                    continue
                placed_near = None
                for nb in adj_pairs.get(nid, []):
                    nb_n = nodes.get(nb)
                    if nb_n is None:
                        continue
                    nb_x, nb_y = (
                        fr_top_left[nb] if nb in fr_top_left
                        else (nb_n.x, nb_n.y)
                    )
                    if abs(nb_x) >= 1.0 or abs(nb_y) >= 1.0:
                        placed_near = (nb_x, nb_y)
                        break
                if placed_near is not None:
                    # Place the new node in the *largest empty angular gap*
                    # among the parent's already-positioned neighbours, so
                    # the placement doesn't immediately collide with an
                    # existing sibling. Without this, deterministic-by-id
                    # placement would land roughly 1-in-3 nodes inside an
                    # existing subtree's wedge, triggering an untangle
                    # rotation that doesn't undo on remove → drift.
                    anchor_nid = None
                    for nb in adj_pairs.get(nid, []):
                        nb_n = nodes.get(nb)
                        if nb_n is None:
                            continue
                        nb_pos = (
                            fr_top_left[nb] if nb in fr_top_left
                            else (nb_n.x, nb_n.y)
                        )
                        if nb_pos == placed_near:
                            anchor_nid = nb
                            break
                    occupied: List[float] = []
                    if anchor_nid is not None:
                        for sib in adj_pairs.get(anchor_nid, []):
                            if sib == nid:
                                continue
                            sib_n = nodes.get(sib)
                            if sib_n is None:
                                continue
                            sx, sy = (
                                fr_top_left[sib] if sib in fr_top_left
                                else (sib_n.x, sib_n.y)
                            )
                            if abs(sx) < 1.0 and abs(sy) < 1.0:
                                continue
                            occupied.append(math.atan2(
                                sy - placed_near[1], sx - placed_near[0]))
                    if occupied:
                        occupied.sort()
                        m = len(occupied)
                        biggest_gap = -1.0
                        biggest_idx = 0
                        for i in range(m):
                            j = (i + 1) % m
                            gap = occupied[j] - occupied[i]
                            if j == 0:
                                gap += 2 * math.pi
                            if gap > biggest_gap:
                                biggest_gap = gap
                                biggest_idx = i
                        ang = occupied[biggest_idx] + biggest_gap / 2.0
                    else:
                        ang = (nid * 1.7) % (2 * math.pi)
                    fr_top_left[nid] = (
                        placed_near[0] + math.cos(ang) * (n.width + 40),
                        placed_near[1] + math.sin(ang) * (n.height + 40),
                    )
            if len(fr_top_left) == len(nodes):
                break
        for nid, n in nodes.items():
            fr_top_left.setdefault(nid, (n.x, n.y))
    else:
        # Re-arrange path. Rebuilds positions from scratch is a non-goal —
        # it always feels destructive when a settled layout gets shuffled.
        # Instead, pass the user's current positions through verbatim and
        # let the untangle pass below clean up any sibling crossings. F-R
        # re-equilibration was tried (both cold-from-radial and brief
        # polish) and reliably produced large shifts for users who hadn't
        # asked for them.
        fr_top_left: Dict[int, Tuple[float, float]] = {}
        for nid, n in nodes.items():
            fr_top_left[nid] = (n.x, n.y)
    centers: Dict[int, List[float]] = {
        nid: [fr_top_left[nid][0] + nodes[nid].width / 2,
              fr_top_left[nid][1] + nodes[nid].height / 2]
        for nid in nodes
    }

    # 2. Spanning tree.
    if parent is None or children is None:
        tree = _directed_spanning_tree(graph)
        if tree is None:
            tree = _bfs_spanning_tree(graph)
        parent, children = tree

    # Pre-compute descendants for each node (subtree members, including self)
    # so we can rotate a subtree as a rigid body.
    descendants: Dict[int, List[int]] = {}

    def _collect(nid: int) -> List[int]:
        members = [nid]
        for c in children.get(nid, set()):
            members.extend(_collect(c))
        descendants[nid] = members
        return members

    roots = [nid for nid, p in parent.items() if p is None]
    for r in roots:
        _collect(r)

    # 3. BFS untangle. Repeated up to a few passes because rotations at
    # depth N can change the angular extent of a subtree as seen from depth
    # < N, leaving small residual violations higher up. A second pass cleans
    # those up; convergence is fast (typically 1–2 passes).
    for _untangle_pass in range(4):
        any_rotation_this_pass = False
        queue: deque = deque(roots)
        while queue:
            cur = queue.popleft()
            kids = list(children.get(cur, set()))
            for c in kids:
                queue.append(c)
            if len(kids) <= 1:
                continue

            cx, cy = centers[cur]

            extents: Dict[int, Tuple[float, float, float]] = {}
            for c in kids:
                angles = [
                    math.atan2(centers[d][1] - cy, centers[d][0] - cx)
                    for d in descendants[c]
                ]
                extents[c] = _smallest_arc(angles)

            kids_with_mid = [(c, _wrap_pi(extents[c][2])) for c in kids]
            kids_with_mid.sort(key=lambda x: x[1])
            n_k = len(kids_with_mid)
            sorted_mids = [m for _, m in kids_with_mid]
            sorted_kids = [c for c, _ in kids_with_mid]

            biggest_gap = -1.0
            biggest_idx = n_k - 1
            for i in range(n_k):
                j = (i + 1) % n_k
                gap = sorted_mids[j] - sorted_mids[i]
                if j == 0:
                    gap += 2 * math.pi
                if gap > biggest_gap:
                    biggest_gap = gap
                    biggest_idx = i
            cut = (biggest_idx + 1) % n_k
            if cut == 0:
                mids = list(sorted_mids)
                kids_lin = list(sorted_kids)
            else:
                mids = sorted_mids[cut:] + [m + 2 * math.pi for m in sorted_mids[:cut]]
                kids_lin = sorted_kids[cut:] + sorted_kids[:cut]

            halves = [
                max((extents[c][1] - extents[c][0]) / 2.0, 0.02)
                for c in kids_lin
            ]

            # In warm mode (mutation), skip rotations entirely — every
            # rotation persists across remove and accumulates into permanent
            # layout drift. The Re-arrange button (warm_start=False) runs
            # this same untangle with no tolerance and fixes any genuine
            # tangles. In Re-arrange mode, only suppress FP-noise re-fires.
            if warm_start:
                continue
            violation_tol = 1e-4
            any_violation = False
            for i in range(n_k - 1):
                need = halves[i] + halves[i + 1] + sibling_gap
                if (mids[i + 1] - mids[i]) < need - violation_tol:
                    any_violation = True
                    break
            if not any_violation:
                continue

            new_mids = _resolve_angular_constraints(mids, halves, sibling_gap)

            for c, old_m, new_m in zip(kids_lin, mids, new_mids):
                rotation = new_m - old_m
                if abs(rotation) < 1e-4:
                    continue
                any_rotation_this_pass = True
                cos_r = math.cos(rotation)
                sin_r = math.sin(rotation)
                for d in descendants[c]:
                    dx = centers[d][0] - cx
                    dy = centers[d][1] - cy
                    centers[d][0] = cx + dx * cos_r - dy * sin_r
                    centers[d][1] = cy + dx * sin_r + dy * cos_r
        if not any_rotation_this_pass:
            break

    # 4. Centres → top-left.
    result: Dict[int, Tuple[float, float]] = {}
    for nid in nodes:
        cx, cy = centers[nid]
        n = nodes[nid]
        result[nid] = (cx - n.width / 2, cy - n.height / 2)
    return result


def _wrap_pi(a: float) -> float:
    """Normalise an angle to [-π, π]."""
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _resolve_angular_constraints(
    mids: List[float],
    halves: List[float],
    gap: float,
    *,
    max_iter: int = 200,
) -> List[float]:
    """Project ``mids`` onto the feasible region where every adjacent pair is
    at least ``halves[i] + halves[i+1] + gap`` apart. Pairwise pushes are
    symmetric (each sibling moves half the violation), iterated until stable.
    Approximates the minimum-displacement solution; non-conflicting siblings
    don't move at all.
    """
    n = len(mids)
    if n <= 1:
        return list(mids)
    theta = list(mids)
    for _ in range(max_iter):
        max_viol = 0.0
        for i in range(n - 1):
            min_dist = halves[i] + halves[i + 1] + gap
            actual = theta[i + 1] - theta[i]
            if actual < min_dist:
                viol = min_dist - actual
                push = viol / 2.0
                theta[i] -= push
                theta[i + 1] += push
                if viol > max_viol:
                    max_viol = viol
        for i in range(n - 2, -1, -1):
            min_dist = halves[i] + halves[i + 1] + gap
            actual = theta[i + 1] - theta[i]
            if actual < min_dist:
                viol = min_dist - actual
                push = viol / 2.0
                theta[i] -= push
                theta[i + 1] += push
                if viol > max_viol:
                    max_viol = viol
        if max_viol < 1e-5:
            break
    return theta


def _smallest_arc(angles: List[float]) -> Tuple[float, float, float]:
    """Smallest arc containing every angle. Returns (start, end, mid) with
    end >= start (end may exceed π when the arc wraps past ±π)."""
    if not angles:
        return (0.0, 0.0, 0.0)
    if len(angles) == 1:
        a = angles[0]
        return (a, a, a)
    sorted_a = sorted(angles)
    n = len(sorted_a)
    biggest_gap = -1.0
    biggest_idx = -1
    for i in range(n - 1):
        g = sorted_a[i + 1] - sorted_a[i]
        if g > biggest_gap:
            biggest_gap = g
            biggest_idx = i
    wrap_gap = 2 * math.pi - (sorted_a[-1] - sorted_a[0])
    if wrap_gap > biggest_gap:
        # No wrap needed; arc is from min to max.
        s, e = sorted_a[0], sorted_a[-1]
        return (s, e, (s + e) / 2.0)
    # Wrap: cut at the biggest non-wrap gap; arc goes from the next angle
    # forward through ±π to the angle just before the gap.
    start = sorted_a[biggest_idx + 1]
    end = sorted_a[biggest_idx] + 2 * math.pi
    return (start, end, (start + end) / 2.0)


# ---------------------------------------------------------------------------
# Hierarchical (Reingold–Tilford / Walker / Buchheim) tidy tree layout
# ---------------------------------------------------------------------------
def hierarchical_tree_layout(
    graph: Graph,
    *,
    parent: Optional[Dict[int, Optional[int]]] = None,
    children: Optional[Dict[int, Set[int]]] = None,
    level_gap: Optional[float] = None,
    subtree_gap: Optional[float] = None,
    component_gap: Optional[float] = None,
    direction: str = "down",
    existing: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[int, Tuple[float, float]]:
    """Tidy-tree layout (Reingold–Tilford style) — root at top, kids below.

    Each subtree carries a left/right contour; siblings are pushed apart by
    the minimum amount that keeps their contours from clashing, and parents
    sit at the midpoint of their extreme children. Tree edges cannot cross
    by construction. Any non-tree edges (cycles in the graph) are laid out
    on top of this skeleton and may cross — that's unavoidable.

    ``direction``: ``"down"`` (default) = root at top, children below;
    ``"up"`` flips the y-axis; ``"right"`` = root on the left, children
    fanning rightward; ``"left"`` = root on the right.
    """
    nodes = graph.nodes
    if not nodes:
        return {}

    if parent is None or children is None:
        tree = _directed_spanning_tree(graph)
        if tree is None:
            tree = _bfs_spanning_tree(graph)
        parent, children = tree

    # Deterministic child order: by leaf count descending then id, so larger
    # subtrees sit on the outside and the tree visually balances.
    roots = [nid for nid, p in parent.items() if p is None]
    leaves = _count_leaves(roots, children)
    ordered_children: Dict[int, List[int]] = {}
    for nid in nodes:
        kids = list(children.get(nid, set()))
        kids.sort(key=lambda c: (-leaves.get(c, 1), c))
        # Alternate big/small around the centre so wide subtrees don't all
        # cluster on one side.
        left, right = [], []
        for i, c in enumerate(kids):
            (left if i % 2 == 0 else right).append(c)
        ordered_children[nid] = left + list(reversed(right))

    widths = {nid: max(n.width, 1.0) for nid, n in nodes.items()}
    heights = {nid: max(n.height, 1.0) for nid, n in nodes.items()}
    mean_w = sum(widths.values()) / len(widths)
    mean_h = sum(heights.values()) / len(heights)
    if level_gap is None:
        level_gap = mean_h + 60.0
    if subtree_gap is None:
        subtree_gap = mean_w * 0.4 + 16.0
    if component_gap is None:
        component_gap = mean_w + 60.0

    def layout(nid: int):
        """Post-order: returns (xs, lc, rc).
        xs: dict[node_id -> x relative to this subtree's root].
        lc/rc: list of leftmost/rightmost edge x at each relative depth
        (index 0 = this subtree's root row).
        """
        kids = ordered_children.get(nid, [])
        w = widths[nid]
        if not kids:
            return ({nid: 0.0}, [-w / 2], [w / 2])

        results = [layout(c) for c in kids]

        # Place children left-to-right, computing minimum push per child.
        shifts = [0.0]
        merged_lc = list(results[0][1])
        merged_rc = list(results[0][2])

        for i in range(1, len(results)):
            child_lc = results[i][1]
            child_rc = results[i][2]
            push = -float("inf")
            depth = min(len(child_lc), len(merged_rc))
            for d in range(depth):
                gap = merged_rc[d] + subtree_gap - child_lc[d]
                if gap > push:
                    push = gap
            if push == -float("inf"):
                push = 0.0
            shifts.append(push)
            for d in range(len(child_lc)):
                shifted_l = child_lc[d] + push
                shifted_r = child_rc[d] + push
                if d < len(merged_rc):
                    if shifted_l < merged_lc[d]:
                        merged_lc[d] = shifted_l
                    if shifted_r > merged_rc[d]:
                        merged_rc[d] = shifted_r
                else:
                    merged_lc.append(shifted_l)
                    merged_rc.append(shifted_r)

        # Centre this node between its leftmost and rightmost child centres.
        center_x = (shifts[0] + shifts[-1]) / 2.0

        xs: Dict[int, float] = {nid: 0.0}
        for i, (cx, _, _) in enumerate(results):
            for n_, x_ in cx.items():
                xs[n_] = x_ + shifts[i] - center_x

        # Prepend this node's contour at depth 0; children's contours shifted.
        lc_out = [-w / 2] + [x - center_x for x in merged_lc]
        rc_out = [w / 2] + [x - center_x for x in merged_rc]
        return xs, lc_out, rc_out

    # Build per-component layouts.
    components: List[Tuple[int, Dict[int, float], List[float], List[float]]] = []
    for r in roots:
        xs, lc, rc = layout(r)
        components.append((r, xs, lc, rc))

    # Place components left-to-right, biggest first.
    def comp_width(c):
        _, _, lc, rc = c
        if not lc:
            return 0.0
        return max(rc) - min(lc)
    components.sort(key=lambda c: -comp_width(c))

    # Depth lookup for y assignment.
    depth: Dict[int, int] = {}
    for r in roots:
        depth[r] = 0
        stack = [r]
        while stack:
            cur = stack.pop()
            for c in ordered_children.get(cur, []):
                depth[c] = depth[cur] + 1
                stack.append(c)

    raw: Dict[int, Tuple[float, float]] = {}
    cursor_x = 0.0
    for root, xs, lc, rc in components:
        left_extent = min(lc) if lc else 0.0
        right_extent = max(rc) if rc else 0.0
        offset = cursor_x - left_extent
        for nid, x in xs.items():
            raw[nid] = (x + offset, depth.get(nid, 0) * level_gap)
        cursor_x += (right_extent - left_extent) + component_gap

    # Place any orphaned nodes (not in spanning tree) below the trees.
    orphans = [nid for nid in nodes if nid not in parent and nid not in raw]
    if orphans:
        cell = mean_w + 24.0
        cols = max(1, int(math.ceil(math.sqrt(len(orphans)))))
        for i, nid in enumerate(orphans):
            r, c = divmod(i, cols)
            raw[nid] = (c * cell, (max(depth.values(), default=0) + 2 + r) * level_gap)

    # Direction transform.
    if direction == "up":
        raw = {nid: (x, -y) for nid, (x, y) in raw.items()}
    elif direction == "right":
        raw = {nid: (y, x) for nid, (x, y) in raw.items()}
    elif direction == "left":
        raw = {nid: (-y, x) for nid, (x, y) in raw.items()}
    # "down" is the natural orientation; no-op.

    # Centre on origin and convert centres → top-left (LiveNodeItem expects
    # the card's top-left at node.x/y).
    if not raw:
        return {}
    xs_all = [p[0] for p in raw.values()]
    ys_all = [p[1] for p in raw.values()]
    cx = (min(xs_all) + max(xs_all)) / 2
    cy = (min(ys_all) + max(ys_all)) / 2
    result: Dict[int, Tuple[float, float]] = {}
    for nid, (x, y) in raw.items():
        n = nodes[nid]
        result[nid] = (x - cx - n.width / 2, y - cy - n.height / 2)
    return result


def _directed_spanning_tree(graph: Graph):
    """Build a forest from directed edges. Returns (parent, children) or
    None if the graph has no directed edges.

    Nodes with no incoming directed edge are roots. BFS forward from each
    root assigns parents along directed edges. Any remaining unreachable
    nodes (cycles, or undirected-only components) get a BFS spanning-tree
    treatment so we always cover every node.
    """
    has_directed = any(getattr(c, "directed", False) for c in graph.connections)
    if not has_directed:
        return None

    forward: Dict[int, List[int]] = defaultdict(list)
    in_count: Dict[int, int] = defaultdict(int)
    for c in graph.connections:
        if getattr(c, "directed", False):
            forward[c.from_id].append(c.to_id)
            in_count[c.to_id] += 1

    all_ids = set(graph.nodes.keys())
    parent: Dict[int, Optional[int]] = {}
    children: Dict[int, Set[int]] = defaultdict(set)
    seen: Set[int] = set()

    roots = sorted(nid for nid in all_ids if in_count.get(nid, 0) == 0)
    q: deque = deque()
    for r in roots:
        parent[r] = None
        seen.add(r)
        q.append(r)
    while q:
        cur = q.popleft()
        for nb in forward.get(cur, []):
            if nb in seen or nb not in all_ids:
                continue
            parent[nb] = cur
            children[cur].add(nb)
            seen.add(nb)
            q.append(nb)

    # Any nodes still unseen (pure cycles, or nodes only reachable by
    # undirected edges): add them via undirected BFS so the layout still
    # covers everything.
    if len(seen) < len(all_ids):
        adj: Dict[int, Set[int]] = defaultdict(set)
        for c in graph.connections:
            adj[c.from_id].add(c.to_id)
            adj[c.to_id].add(c.from_id)
        unseen = all_ids - seen
        while unseen:
            r = max(unseen, key=lambda n: (len(adj[n]), -n))
            parent[r] = None
            seen.add(r)
            unseen.discard(r)
            q.append(r)
            while q:
                cur = q.popleft()
                for nb in adj[cur]:
                    if nb in unseen:
                        parent[nb] = cur
                        children[cur].add(nb)
                        seen.add(nb)
                        unseen.discard(nb)
                        q.append(nb)

    return parent, dict(children)


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
