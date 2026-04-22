# pymindmap

A modular Python port of the ScatterMind node-based mindmap tool
(`mindmap.html`). Built on PyQt5's `QGraphicsScene`/`QGraphicsView`.

Two entry points:

- **`pymindmap.app`** — faithful port: manual drag-to-arrange, inspector on
  the right, optional auto-layout via `Ctrl+L`.
- **`pymindmap.live`** — always-on auto-layout, card-style nodes with inline
  body previews, degree-based sizing, modern UI. Best for note-heavy thought
  processing.

## Install & run

```bash
# PyQt5 is the only runtime dependency.
python3 -m pip install PyQt5

# Faithful port
python3 -m pymindmap.app [path.json]

# Live auto-layout variant — the newer, opinionated UI
python3 -m pymindmap.live [path.json]
```

## Controls

| Input                         | Action                                      |
|-------------------------------|---------------------------------------------|
| **Double-click empty space**  | Create node (and immediately edit)          |
| **Double-click node**         | Edit node text                              |
| **Shift + drag from node**    | Draw a connection to another node           |
| **Shift + drag to empty**     | Create a new node and connect to it         |
| **Double-click connection**   | Insert a waypoint at the click              |
| **Double-click waypoint**     | Delete waypoint                             |
| **Drag waypoint**             | Curve the connection                        |
| **Left drag on empty space**  | Box-select (Shift = additive)               |
| **Middle drag**               | Pan                                         |
| **Wheel**                     | Zoom (0.1× – 5×)                            |
| **Drag node corner**          | Resize                                      |
| **Tab**                       | Edit selected node                          |
| **Esc**                       | Stop editing                                |
| **Shift+A**                   | Add node at viewport center                 |
| **Shift+D**                   | Duplicate selection                         |
| **Delete**                    | Delete selected nodes & connections         |
| **Ctrl+Z / Ctrl+Y**           | Undo / Redo                                 |
| **Ctrl+S / Ctrl+Shift+S**     | Save / Save As                              |
| **Ctrl+O**                    | Open JSON                                   |
| **.**                         | Fit all to view                             |
| **Home**                      | Reset view                                  |
| **Ctrl+L**                    | Auto-layout (force-directed)                |
| **F**                         | Toggle Focus mode                           |
| **Ctrl+F**                    | Focus search field                          |
| **Enter** (in search)         | Cycle to next match                         |
| **Esc** (in search)           | Clear search                                |

The right-hand **Inspector** sets per-node color, font size, alignment, bold,
and italic for the currently-selected node, and holds a **Notes** text area
for long-form body content (indicated by a small dot on the node).

### Thought-processing features

- **Focus mode** (toolbar `Focus` toggle or `F`) dims unrelated nodes so you
  can see a selected node's neighborhood. The `Depth` combo controls how far
  the "spreading activation" reaches (1–4 hops, or ∞). Opacity falls off with
  graph distance — closer neighbors stay bright, far ones fade.
- **Auto-layout** (toolbar `Auto-layout` or `Ctrl+L`) runs Fruchterman–Reingold
  force simulation on the graph and animates nodes to their new positions in
  one undoable step. Useful after dumping a lot of nodes to let the graph
  self-organize.
- **Search** (`Ctrl+F`) highlights every node whose title or body contains the
  query; `Enter` jumps the view to the next match.
- **Node body / notes** — expand on a node's idea in the Inspector's *Notes*
  pane without growing the node visually. Search finds matches in bodies too.

## Architecture

```
pymindmap/
├── model.py       # Node, Connection, Waypoint, Graph — Qt-free dataclasses
├── io.py          # JSON load/save, compatible with ScatterMind format
├── geometry.py    # Bezier routing (anchor_point, route_bezier)
├── theme.py       # Colors/sizes dataclass — mutate THEME to restyle
├── items.py       # NodeItem, ConnectionItem, WaypointItem (QGraphicsItems)
├── scene.py       # MindMapScene — owns the Graph; spreading-activation/emphasis
├── view.py        # MindMapView — pan, zoom, marquee, drag-to-connect
├── layout.py      # Fruchterman–Reingold force-directed layout (pure math)
├── commands.py    # QUndoCommand subclasses (all mutations go through these)
├── mainwindow.py  # Toolbar, inspector, shortcuts, search, file IO
├── app.py         # Entry point + dark palette
└── live/          # Live-layout variant (separate UI, reuses model/io/layout)
    ├── app.py
    ├── scene.py   # LiveMindMapScene — auto-layout on every mutation
    ├── items.py   # LiveNodeItem — card-style, degree-sized, body preview
    ├── view.py    # Pan/zoom tuned for the card UI
    └── mainwindow.py
```

Modules below `items.py` have **no Qt dependency** and can be used in tests,
batch-processing scripts, or headless conversion pipelines.

## Differences from the HTML original

**Kept**
- Full node/connection/waypoint data model
- Bezier-curved connections with edge-aware anchors
- Pan/zoom, marquee select, multi-select, Shift-drag-to-connect
- Undo/redo (now via `QUndoStack` — 100 levels, coalesces macros)
- Node resize, color, font-size, alignment, bold/italic
- Round-trip JSON compatibility with existing ScatterMind exports

**Simplified / improved**
- **Command pattern** for every mutation (replaces 50-state snapshot stack)
- **Decoupled model** — `model.py`, `io.py`, `geometry.py` don't touch Qt
- **Theming** via a single `Theme` dataclass in `theme.py`
- Dropped the custom minimap (Qt's `fitInView` covers the use case)
- Dropped the (unused) 3D tilt effect — easy to re-add as an optional
  `QGraphicsEffect` if ever needed
- Dropped localStorage auto-save; file I/O is explicit

## The `live` variant

`python -m pymindmap.live` is a re-imagined front-end sharing the same model
layer. What's different:

- **Always-on auto-layout.** Adding a node, creating a connection, deleting
  anything, or editing a title/body triggers a debounced Fruchterman–Reingold
  pass (~80 iters, 120 ms debounce, 350 ms animation). User drags pin nodes
  for ~2.5 s so the layout doesn't fight the user.
- **Cards, not boxes.** Nodes render as notecards with a title row and an
  inline body preview (up to 4 wrapped lines with ellipsis). Body content
  is visible *on the canvas*, not just in a panel.
- **Degree drives size.** Each node's width/height grow with `√degree`, so
  hubs stand out automatically and rare-link nodes stay compact. A small
  degree badge in the corner shows the exact count.
- **Prominent notes panel.** The sidebar's *NOTES* editor takes the majority
  of the vertical space — it's the obvious place to expand on an idea.
  Double-click any card to open it here.
- **Modernized look.** Custom QSS: slim scrollbars, pill buttons, icon
  toolbar, single-accent color scheme, better typography.

## Extending

Because mutations go through `QUndoCommand` subclasses, adding a feature is
typically:

1. Add a field to `Node`/`Connection` in `model.py` (and its IO in `io.py`).
2. Render it in the corresponding `QGraphicsItem.paint()`.
3. Add a new `QUndoCommand` subclass in `commands.py` if users can edit it.
4. Wire a control in `mainwindow.py`'s inspector.

Auto-layout, graph algorithms, CSV import, and so on can live in new modules
without touching the UI layer.
