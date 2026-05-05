"""Delegate cron/at-scheduled reminders to the always-on Mac rendezvous.

The Linux machines (desktop, thinkpad) sleep, so reminders installed in
their local crontabs only fire when the user is awake at that machine.
Pushing the reminder to the Mac instead means it fires regardless of
which Linux box is online — same Gmail email arrives at
``aabawi@lji.org``, same AI prompt expansion if one is set, just driven
by the Mac's clock.

The Mac SSH alias used everywhere here is ``mac``. We never assume the
Mac is reachable: ``is_reachable`` is a 3-second probe and every public
function returns ``(ok, detail)`` so the UI can surface clean messages.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

REMOTE_HOST = "mac"
REMOTE_TIMEOUT = 8

# Mac-side paths. Cron on macOS doesn't expand ``~/`` inside the
# command portion of a crontab line — the resulting "no such file"
# silently fails — so we use ``$HOME`` everywhere a cron line will see
# the path. ``~`` works fine for ssh-shell-side use (rsync, scp).
REMOTE_REPO = "~/repos/mindmap"
REMOTE_NOTIFIER_INSTALL = "~/.local/bin/pymindmap-notify"   # for ssh setup
REMOTE_NOTIFIER = "$HOME/.local/bin/pymindmap-notify"        # for cron lines
REMOTE_EMAIL_CFG = "~/.config/pymindmap/email.json"
REMOTE_JSON_DIR = "~/Sync/pymindmap"

TAG_PREFIX = "# pymindmap:"

# Mac-flavoured wrapper. Embedded so bootstrap is a single SSH push and
# we don't have to ship + reference an extra file.
MAC_NOTIFIER_SCRIPT = r"""#!/bin/zsh
# pymindmap notification wrapper (Mac variant)
# Fires a desktop toast (osascript), sends an email, and logs the event.
# In --ai mode, runs claude with the node's prompt + mindmap context and
# uses the response as the body. Errors are silent so the email always
# fires even if the toast or AI step fails.
#
#   pymindmap-notify "<title>" "<body>"
#   pymindmap-notify --ai <node-id> <json-path> "<title>" "<fallback>"

LOG="$HOME/.cache/pymindmap-notify.log"
mkdir -p "$(dirname "$LOG")"
REPO="$HOME/repos/mindmap"
PY=/usr/bin/python3
CLAUDE="$HOME/.local/bin/claude"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

if [ "$1" = "--ai" ]; then
    shift
    NODE_ID="$1"; JSON="$2"; TITLE="${3:-pymindmap reminder}"; FALLBACK="${4:-}"
    BODY=""
    if [ -x "$PY" ] && [ -d "$REPO/pymindmap" ]; then
        BODY="$( PYMINDMAP_CLAUDE_BIN="$CLAUDE" cd "$REPO" && \
            "$PY" -m pymindmap.integrations.claude_run --node-id "$NODE_ID" --json "$JSON" \
            2>>"$LOG" )"
    fi
    [ -z "$BODY" ] && BODY="$FALLBACK"
else
    TITLE="${1:-pymindmap reminder}"
    BODY="${2:-}"
fi

# Mac toast — escape internal double-quotes so AppleScript doesn't choke.
ESCAPED_BODY="${BODY//\"/\\\"}"
ESCAPED_TITLE="${TITLE//\"/\\\"}"
osascript -e "display notification \"${ESCAPED_BODY}\" with title \"${ESCAPED_TITLE}\"" \
    >/dev/null 2>&1

# Email (mac uses the same email_send.py as Linux).
if [ -x "$PY" ] && [ -f "$HOME/.config/pymindmap/email.json" ]; then
    cd "$REPO" && "$PY" -m pymindmap.integrations.email_send "$TITLE" "$BODY" \
        >>"$LOG" 2>&1
fi

# Append a structured event line so `tail -f` is useful.
TS="$(date '+%Y-%m-%d %H:%M:%S')"
printf '%s  %s :: %s\n' "$TS" "$TITLE" "${BODY:0:160}" >> "$LOG"
"""


# ---------------------------------------------------------------------------
# probes / setup
# ---------------------------------------------------------------------------
def _ssh(remote_cmd: str, *, timeout: int = REMOTE_TIMEOUT,
         stdin: Optional[str] = None) -> subprocess.CompletedProcess:
    """Run a single shell command on the Mac. ``remote_cmd`` is passed
    as one argument so ``&&`` / pipes / redirects parse on the remote
    side, not the local one. ssh wraps it in the user's login shell."""
    cmd = ["ssh", "-o", "BatchMode=yes",
           "-o", f"ConnectTimeout={REMOTE_TIMEOUT}", REMOTE_HOST, remote_cmd]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        input=stdin,
    )


def is_reachable() -> bool:
    try:
        proc = _ssh("echo ok", timeout=REMOTE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and "ok" in (proc.stdout or "")


def bootstrap() -> Tuple[bool, str]:
    """Idempotently install the Mac-side bits needed to run reminders.

    Each step is safe to repeat: rsync only transfers changed files,
    crontab edits use ``# pymindmap:<id>`` tags so existing user
    entries are untouched, and the email config is mode-0600 chmod'd
    after copy."""
    if not is_reachable():
        return False, "Mac not reachable (ssh)"

    # 0. Make sure the destination tree exists. rsync won't auto-create
    #    parents two levels up.
    mkdir = _ssh("mkdir -p $HOME/repos/mindmap/pymindmap "
                 "$HOME/.local/bin "
                 "$HOME/.config/pymindmap "
                 "$HOME/Sync/pymindmap",
                 timeout=10)
    if mkdir.returncode != 0:
        return False, f"mkdir: {mkdir.stderr.strip()[:200]}"

    # 1. pymindmap source
    repo_root = Path(__file__).resolve().parent.parent.parent
    src_pkg = repo_root / "pymindmap"
    rsync = subprocess.run(
        ["rsync", "-az", "--delete", "--exclude=__pycache__",
         "-e", f"ssh -o BatchMode=yes -o ConnectTimeout={REMOTE_TIMEOUT}",
         str(src_pkg) + "/",
         f"{REMOTE_HOST}:repos/mindmap/pymindmap/"],
        capture_output=True, text=True, timeout=60,
    )
    if rsync.returncode != 0:
        return False, f"rsync pymindmap: {rsync.stderr.strip()[:200]}"

    # 2. wrapper script — write via stdin so we don't need a temp file
    #    and so a future edit to the embedded script propagates.
    proc = _ssh(
        f"cat > {REMOTE_NOTIFIER_INSTALL} && chmod +x {REMOTE_NOTIFIER_INSTALL}",
        stdin=MAC_NOTIFIER_SCRIPT, timeout=15,
    )
    if proc.returncode != 0:
        return False, f"install wrapper: {proc.stderr.strip()[:200]}"

    # 3. email config — only push if we have one locally.
    local_cfg = Path.home() / ".config" / "pymindmap" / "email.json"
    if local_cfg.exists():
        scp = subprocess.run(
            ["scp", "-q",
             "-o", "BatchMode=yes",
             "-o", f"ConnectTimeout={REMOTE_TIMEOUT}",
             str(local_cfg),
             f"{REMOTE_HOST}:.config/pymindmap/email.json"],
            capture_output=True, text=True, timeout=15,
        )
        if scp.returncode != 0:
            return False, f"scp email.json: {scp.stderr.strip()[:200]}"
        chmod = _ssh("chmod 600 $HOME/.config/pymindmap/email.json", timeout=5)
        if chmod.returncode != 0:
            return False, f"chmod email.json: {chmod.stderr.strip()[:200]}"

    return True, "ok"


# ---------------------------------------------------------------------------
# crontab + at on Mac
# ---------------------------------------------------------------------------
def _read_crontab() -> str:
    proc = _ssh("crontab -l", timeout=10)
    if proc.returncode == 0:
        return proc.stdout
    if "no crontab" in (proc.stderr or "").lower():
        return ""
    raise RuntimeError(f"mac crontab -l: {proc.stderr.strip()}")


def _write_crontab(content: str) -> None:
    if content and not content.endswith("\n"):
        content += "\n"
    proc = _ssh("crontab -", timeout=10, stdin=content)
    if proc.returncode != 0:
        raise RuntimeError(f"mac crontab install: {proc.stderr.strip()}")


def _build_command(node_id: int, message: str,
                   ai_json_path: Optional[str]) -> str:
    """The command portion of the Mac cron / at line."""
    title = "pymindmap reminder"
    if ai_json_path:
        return (
            f"{REMOTE_NOTIFIER} --ai "
            f"{shlex.quote(str(node_id))} {shlex.quote(ai_json_path)} "
            f"{shlex.quote(title)} {shlex.quote(message or '')}"
        )
    return f"{REMOTE_NOTIFIER} {shlex.quote(title)} {shlex.quote(message or '')}"


def install_cron(node_id: int, cron_expr: str, message: str, *,
                 ai_json_path: Optional[str] = None) -> None:
    tag = f"{TAG_PREFIX}{node_id}"
    cmd = _build_command(node_id, message, ai_json_path)
    line = f"{cron_expr} {cmd} {tag}"
    existing = _read_crontab().splitlines()
    kept = [l for l in existing if not l.rstrip().endswith(tag)]
    kept.append(line)
    _write_crontab("\n".join(kept))


def install_at(node_id: int, when_iso: str, message: str, *,
               ai_json_path: Optional[str] = None) -> None:
    """Schedule a one-shot reminder on Mac via cron + a self-removing
    guard. Avoids macOS's ``at`` daemon (``atrun``), which is disabled
    out of the box and requires sudo to enable. The cron line:

        * fires at ``M H D Mon *`` (cron has no year field)
        * checks ``date +%Y`` matches the target year before doing
          anything — no-op on years the schedule wouldn't apply
        * runs the notification command, then rewrites the user's
          crontab without this line so it can't fire again

    For schedules less than ~70 seconds out, cron's 1-minute
    granularity may miss this fire window — caller should clamp.
    """
    from datetime import datetime
    when = datetime.fromisoformat(when_iso)
    tag = f"{TAG_PREFIX}{node_id}"
    cmd = _build_command(node_id, message, ai_json_path)
    cron_expr = f"{when.minute} {when.hour} {when.day} {when.month} *"
    year_str = str(when.year)
    # ``%`` is special to cron — anything after an unescaped percent in
    # the command field becomes stdin to the command, so ``$(date +%Y)``
    # mangles to ``$(date +`` and the year check explodes silently. We
    # escape every literal ``%`` we want preserved.
    #
    # We don't try to self-remove the line after firing (cron's locked
    # context made that unreliable on macOS); the year-guard means a
    # leftover line just no-ops every year after the target. Reusing the
    # same node id rewrites the line on next install, so accumulation is
    # bounded by the number of unique reminding nodes.
    body = f'[ "$(date +\\%Y)" = "{year_str}" ] && {cmd}'
    line = f"{cron_expr} {body} {tag}"
    existing = _read_crontab().splitlines()
    kept = [l for l in existing if not l.rstrip().endswith(tag)]
    kept.append(line)
    _write_crontab("\n".join(kept))


def remove(node_id: int) -> bool:
    """Remove any Mac-side reminder for this node id."""
    tag = f"{TAG_PREFIX}{node_id}"
    try:
        existing = _read_crontab().splitlines()
    except RuntimeError:
        return False
    kept = [l for l in existing if not l.rstrip().endswith(tag)]
    if len(kept) == len(existing):
        return False
    _write_crontab("\n".join(kept))
    return True


# ---------------------------------------------------------------------------
# unified install — same shape as integrations.reminder.install but
# remote-targeted. Caller passes the same ParsedReminder.
# ---------------------------------------------------------------------------
def install(node_id: int, parsed, message: str, *,
            ai_json_basename: Optional[str] = None) -> None:
    """Install a reminder on the Mac. ``ai_json_basename`` is just the
    filename of the mindmap JSON — we always look for it under the
    Mac's ``~/Sync/pymindmap/`` rendezvous directory because that's
    where the launcher's pre-open rsync drops it."""
    ai_path = (f"$HOME/Sync/pymindmap/{ai_json_basename}"
               if ai_json_basename else None)
    if parsed.kind == "cron":
        # Clean any stale 'at' entry for this node first so a cron→at→cron
        # toggle doesn't leave orphaned at jobs.
        remove(node_id)
        install_cron(node_id, parsed.schedule, message, ai_json_path=ai_path)
    elif parsed.kind == "at":
        remove(node_id)
        install_at(node_id, parsed.schedule, message, ai_json_path=ai_path)
    else:
        raise ValueError(f"unknown reminder kind: {parsed.kind}")
