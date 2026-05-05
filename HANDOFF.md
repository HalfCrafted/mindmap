# pymindmap — handoff

State of the world after this round of changes. Two big features landed
(directory shortcuts + reminders), with reminders branching into
local-cron, AI-prompt expansion via Claude, and Mac delegation for
always-on firing. Plus several routing/physics tweaks that are still
chasing the user's preferred feel.

## Anatomy

```
pymindmap/
  model.py          ← Node now carries reminder dict + dir_links dict
  io.py             ← round-trip those new fields (JSON-compat for old files)
  geometry.py       ← bezier routing for connections (see "Open work")
  live/
    items.py        ← LiveNodeItem with folder + bell card icons
    scene.py        ← physics simulator (60 Hz), spread slider, branch colours
    mainwindow.py   ← inspector with Folder + Reminder sections, "Mac log" tool
    view.py         ← smooth zoom (instant + chase), AABB collision
  integrations/     ← new package
    dir_link.py     ← Tailscale-name device key, resolve_path, open_path
    reminder.py     ← natural-lang parser → cron/at, local install/remove
    claude_run.py   ← spawns claude with mindmap context for AI reminders
    email_send.py   ← Gmail SMTP via app password
    mac_delegate.py ← bootstrap + remote install on the always-on Mac
```

## Reminders pipeline

A node's `reminder` dict carries:

```python
{ "spec": "daily at 9am",          # original user text
  "kind": "cron" | "at",           # parsed schedule type
  "schedule": "0 9 * * *",         # cron expr or ISO datetime
  "message": "Daily standup",      # email subject + fallback body
  "claude_prompt": "...",          # optional — runs claude w/ context
  "host": "mac" | "local"          # where it's installed
}
```

### Local path
`integrations/reminder.py` parses NL → installs in user crontab (recurring)
or via `at` (one-shot). Each line tagged `# pymindmap:<node_id>` so user-
written entries are untouched. The `pymindmap-notify` wrapper at
`~/.local/bin/` runs notify-send + Gmail SMTP.

### Mac-delegated path
`integrations/mac_delegate.py` does the same install via SSH on the
always-on Mac. Bootstraps Mac on first use (rsync of pymindmap source,
embedded osascript-flavoured wrapper, scp of `email.json` mode-0600).

**Critical knowledge for cron lines on macOS:**

- `~/` is *not* expanded by cron's shell — must use `$HOME`.
- `%` in a cron line is special — anything after the first unescaped
  `%` becomes stdin. `$(date +%Y)` must be written `$(date +\%Y)`. This
  was the bug behind "1-minute timer not firing".
- macOS's `at` daemon (`atrun`) is **disabled by default** and needs
  sudo to enable. We work around by using cron with year/month/day
  guard for one-shots — works without sudo.
- Self-removing a cron line from inside its own fired body is unreliable
  on macOS (cron seems to lock the file). We don't try; the year-guard
  makes leftover lines harmlessly no-op in later years, and reusing the
  same node id rewrites the line on next install.
- `osascript display notification` from cron may need user-granted
  permission — toast may be silent until the user clicks "Allow" once
  on first attempt.

### AI mode
When a reminder has `claude_prompt`, the cron line invokes
`pymindmap-notify --ai <node_id> <json_path> "title" "fallback"`. The
wrapper reads the JSON, calls `python3 -m pymindmap.integrations.claude_run`,
which loads the graph, builds a system prompt (node title/notes,
parent/children/siblings, accessible directories), runs `claude --print`,
returns its response. The wrapper then emails that response and toasts.

## Directory shortcuts

`Node.dir_links: Dict[str, str]` maps **Tailscale node name** (parsed
from `tailscale status --json`'s `Self.DNSName`, first DNS component —
e.g. "fedora-desktop") to a local filesystem path. The card draws a
folder icon (lit if the path resolves on the current device, dim
otherwise). Clicking it shells out to `xdg-open` / `open` / `startfile`.

The inspector "Folder" section auto-shows the path entry for the
current device. Other devices' paths are listed in the hint line ("Also
linked on: thinkpad, mac"). Each device sets its own path; the JSON
syncs between machines via the existing launcher rsync (Mac as
rendezvous) so a folder linked on one device is known to all.

## Physics + routing

The continuous force-directed layout from a previous session is still
in place (`scene.py:_physics_tick`). New tunables in this round:

- `PHYSICS_IDEAL_EDGE` is now scaled per-edge by
  `sqrt(max(weight_a, weight_b)) * 22` — so trunk edges feeding heavy
  subtrees get longer rest lengths to absorb the cumulative inward
  pressure their descendants apply.
- AABB hard-shell + position-correction constraint solver still
  guarantees rectangles never overlap.
- `LiveNodeItem` now has `ItemIsMovable` so the user can drag nodes
  manually; `mousePressEvent` pins the node against the simulator while
  held.

Bezier routing (`geometry.py`):

- Anchor side picked by ray-exit (geometric, accounts for node aspect).
- Per-endpoint handle length scales with how aligned each tangent is
  with the line direction (range 0.15× to 1.0×).
- Arrowhead direction: chord through `t=0.42 → t=0.58`, not local
  cubic tangent (more stable).
- **Degenerate fallback**: if either anchor sits inside the other
  node's bounding box (overlapping nodes), the routing returns a
  straight line instead of a corkscrewing bezier.

## Open work / known issues

### Connection arrows still occasionally bend ugly
Despite the routing fixes, certain combinations of close + slightly-
overlapping nodes still produce L-curves where the arrowhead sits at
an awkward position. Diagnosis: when one node's anchor is on a
horizontal face and the other's is on a vertical face (perpendicular
tangents), the bezier is an L whose midpoint lies near the corner —
the arrowhead at the midpoint can sit very close to one of the nodes.
The current `~/repos/mindmap/scattermind-2025-12-25(1).json` shows
this on Armature Deform → AccuRig and a few other places. Possible
fixes worth trying:

1. Position the arrowhead at e.g. `t=0.6` rather than `t=0.5` so it
   sits in the longer leg of the L away from corners.
2. Detect perpendicular tangents and either route the corner more
   sharply (smaller h_a/h_b) or fall back to a polyline.
3. Strengthen the position-correction so node bboxes never get this
   close to begin with.

### Mac TCC / notification permission
The first time `osascript display notification` runs from cron on a
fresh Mac, macOS may silently block it pending a permission grant the
user has to click in System Settings → Privacy → Notifications. Email
delivery isn't affected. Worth surfacing this in the UI ("first Mac
delegation may suppress toast until you allow it once") or just in
documentation.

### Spread slider drift on extreme values
Repulsion scale 4× pushes nodes hundreds of pixels apart and the
centre force takes a while to pull the system back to the visible
viewport. Not a bug, but a "Fit" press is useful after big spread
changes — could be auto-triggered.

### Reminders fire window is 1 minute
Cron's resolution is 1 minute, so "in 30 seconds" rounds to the next
minute — the user may experience a 30-90 second delay vs the typed
text. For sub-minute reminders the cleanest path would be a launchd
LaunchAgent (`~/Library/LaunchAgents/`) with a `StartCalendarInterval`
or `StartInterval`, but that's a non-trivial rewrite of `mac_delegate`.

### Self-removal of fired one-shot lines
The year-guard means stale lines don't fire again, but they do
accumulate in crontab over time. A periodic cleanup task (or a
"Sweep stale reminders" toolbar action) would be tidy. Could also be
done at app-launch time: SSH in, parse the crontab, drop any
pymindmap-tagged line whose target date is in the past.

### "Mac log" terminal button
Currently spawns Ptyxis with `ssh -t mac tail -F ~/.cache/pymindmap-notify.log`
— works but the spawned terminal is unstyled. Wiring it to inherit
the user's normal Ptyxis profile would be a polish.

## Quick recipes

**Add a reminder that runs Claude on a node every weekday at 9 am,
emails the result, fires from the Mac:**
1. Click the node, open inspector.
2. "Schedule reminder" ✓
3. When: `weekdays at 9am`
4. Message: `Daily review`  *(used as email subject)*
5. AI prompt: `Summarise activity in @linked-dirs over the last 24 h.`
6. "Run on Mac" ✓ (default)
7. Save reminder.

**Set a directory shortcut on this device:**
1. Click node, "Folder shortcut" ✓
2. Enter `/path/to/folder` → click anywhere to commit
3. Card now has a folder icon; clicking it opens the path

**Watch reminders fire in real time:**
- Toolbar → "Mac log" → spawns a terminal tailing
  `~/.cache/pymindmap-notify.log` over SSH

## Files of note

- `~/.config/pymindmap/email.json` — Gmail app password (mode 0600,
  not in repo, never committed).
- `~/.local/bin/pymindmap-notify` — local wrapper.
- On Mac: `~/.local/bin/pymindmap-notify`, `~/.config/pymindmap/email.json`,
  `~/repos/mindmap/pymindmap/` (synced source).
- `~/.cache/pymindmap-notify.log` — fire log (both local and Mac).
- `~/.cache/pymindmap-sync.log` — JSON sync events (launcher).

## Tests / sanity checks

- `python3 -c "from pymindmap.integrations import mac_delegate as m; print(m.is_reachable())"`
  — quick Mac SSH probe.
- `python3 -m pymindmap.integrations.email_send "test" "body"`
  — exercises Gmail SMTP path independently.
- `~/.local/bin/pymindmap-notify "test" "body"` — local toast + email.
- `ssh mac '~/.local/bin/pymindmap-notify "test" "body"'` — mac path.
- `ssh mac 'crontab -l | grep pymindmap'` — what's queued.
