"""Reminders: parse natural-language schedules into cron / at jobs.

Each pymindmap-managed line in the user's crontab is tagged with
``# pymindmap:<node_id>`` so we can find/replace/remove just our entries
without disturbing the user's hand-written ones. One-shot reminders are
queued via ``at`` and tracked in a small sidecar JSON keyed by node id,
since ``at`` jobs are referenced by numeric job-ID rather than tag.

The parser is intentionally narrow: it accepts the common phrasings the
user is likely to type, and returns ``None`` for anything else so the UI
can prompt for clarification rather than guess.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional


TAG_PREFIX = "# pymindmap:"
JOBS_FILE = Path.home() / ".config" / "pymindmap" / "at_jobs.json"

WEEKDAY_NAMES = {
    "mon": 1, "monday": 1,
    "tue": 2, "tues": 2, "tuesday": 2,
    "wed": 3, "weds": 3, "wednesday": 3,
    "thu": 4, "thur": 4, "thurs": 4, "thursday": 4,
    "fri": 5, "friday": 5,
    "sat": 6, "saturday": 6,
    "sun": 0, "sunday": 0,
}


@dataclass
class ParsedReminder:
    """A successfully-parsed reminder schedule.

    ``kind`` is "cron" (recurring) or "at" (one-shot). ``schedule`` is
    either a 5-field cron expression or an ISO datetime string suitable
    for handing to ``at``. ``summary`` is a short human echo of what we
    understood, e.g. "every day at 09:00" or "once on 2025-12-26 at 09:00".
    """
    kind: str
    schedule: str
    summary: str


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def _parse_time(text: str) -> Optional[tuple[int, int]]:
    """Accept "9am", "9 am", "9:30am", "09:30", "noon", "midnight"."""
    s = text.strip().lower()
    if s in {"noon", "midday"}:
        return (12, 0)
    if s == "midnight":
        return (0, 0)
    m = re.fullmatch(
        r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", s
    )
    if not m:
        return None
    h = int(m.group(1))
    minute = int(m.group(2) or 0)
    suffix = m.group(3)
    if suffix == "am":
        if h == 12: h = 0
    elif suffix == "pm":
        if h != 12: h += 12
    if not (0 <= h < 24 and 0 <= minute < 60):
        return None
    return (h, minute)


def parse_reminder(text: str, *, now: Optional[datetime] = None) -> Optional[ParsedReminder]:
    """Parse a free-form reminder description. Returns ``None`` if the
    text doesn't match any known pattern."""
    if not text:
        return None
    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None
    now = now or datetime.now().replace(microsecond=0)

    # ---- one-shot patterns (use `at`) ------------------------------------
    # "in N minutes/hours/days"
    m = re.fullmatch(r"in\s+(\d+)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b\.?", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith(("min", "m") if unit != "h" else ()) or unit in ("min", "mins", "minute", "minutes"):
            delta = timedelta(minutes=n)
        elif unit in ("h", "hr", "hrs", "hour", "hours"):
            delta = timedelta(hours=n)
        else:
            delta = timedelta(days=n)
        when = now + delta
        return ParsedReminder(
            kind="at",
            schedule=when.strftime("%Y-%m-%dT%H:%M"),
            summary=f"once at {when.strftime('%Y-%m-%d %H:%M')}",
        )

    # "tomorrow at HH" / "today at HH"
    m = re.fullmatch(r"(today|tomorrow)\s+at\s+(.+)", s)
    if m:
        which, time_part = m.group(1), m.group(2)
        t = _parse_time(time_part)
        if t is not None:
            base = now if which == "today" else now + timedelta(days=1)
            when = base.replace(hour=t[0], minute=t[1], second=0, microsecond=0)
            if which == "today" and when <= now:
                # Already passed — bump to the same time tomorrow.
                when += timedelta(days=1)
            return ParsedReminder(
                kind="at",
                schedule=when.strftime("%Y-%m-%dT%H:%M"),
                summary=f"once at {when.strftime('%Y-%m-%d %H:%M')}",
            )

    # "on YYYY-MM-DD at HH:MM"
    m = re.fullmatch(r"(?:on\s+)?(\d{4}-\d{2}-\d{2})(?:\s+at\s+(.+))?", s)
    if m:
        try:
            d = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            return None
        t = _parse_time(m.group(2)) if m.group(2) else (9, 0)
        if t is None:
            return None
        when = d.replace(hour=t[0], minute=t[1])
        return ParsedReminder(
            kind="at",
            schedule=when.strftime("%Y-%m-%dT%H:%M"),
            summary=f"once at {when.strftime('%Y-%m-%d %H:%M')}",
        )

    # ---- recurring patterns (use cron) -----------------------------------
    # "every N minutes/hours"
    m = re.fullmatch(r"every\s+(\d+)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("min") or unit == "minute" or unit == "minutes":
            if not (1 <= n <= 59):
                return None
            return ParsedReminder("cron", f"*/{n} * * * *", f"every {n} minute{'s' if n != 1 else ''}")
        else:
            if not (1 <= n <= 23):
                return None
            return ParsedReminder("cron", f"0 */{n} * * *", f"every {n} hour{'s' if n != 1 else ''}")

    # "every hour" / "hourly"
    if s in ("every hour", "hourly"):
        return ParsedReminder("cron", "0 * * * *", "every hour")

    # "every day at HH" / "daily at HH"
    m = re.fullmatch(r"(?:every day|daily|each day)\s+at\s+(.+)", s)
    if m:
        t = _parse_time(m.group(1))
        if t is not None:
            return ParsedReminder("cron", f"{t[1]} {t[0]} * * *",
                                  f"every day at {t[0]:02d}:{t[1]:02d}")

    # "weekdays at HH" / "every weekday at HH"
    m = re.fullmatch(r"(?:every\s+)?weekdays?\s+at\s+(.+)", s)
    if m:
        t = _parse_time(m.group(1))
        if t is not None:
            return ParsedReminder("cron", f"{t[1]} {t[0]} * * 1-5",
                                  f"every weekday at {t[0]:02d}:{t[1]:02d}")

    # "weekends at HH" / "every weekend at HH"
    m = re.fullmatch(r"(?:every\s+)?weekends?\s+at\s+(.+)", s)
    if m:
        t = _parse_time(m.group(1))
        if t is not None:
            return ParsedReminder("cron", f"{t[1]} {t[0]} * * 0,6",
                                  f"every weekend at {t[0]:02d}:{t[1]:02d}")

    # "every monday at HH" / "mondays at HH" (single weekday)
    m = re.fullmatch(r"(?:every\s+)?(mon(?:day)?s?|tue(?:s(?:day)?)?s?|wed(?:s|nesday)?s?|thu(?:r|rs|rsday)?s?|fri(?:day)?s?|sat(?:urday)?s?|sun(?:day)?s?)\s+at\s+(.+)", s)
    if m:
        day_word = m.group(1).rstrip("s")
        if day_word in ("mons",):
            day_word = "mon"
        # Normalise: strip trailing 's' once more for plurals like "mondays"
        if day_word.endswith("s") and day_word.rstrip("s") in WEEKDAY_NAMES:
            day_word = day_word.rstrip("s")
        # Find longest matching key.
        dow = None
        for key, val in WEEKDAY_NAMES.items():
            if day_word.startswith(key):
                dow = val
                break
        if dow is None:
            return None
        t = _parse_time(m.group(2))
        if t is None:
            return None
        day_name = max(
            (k for k, v in WEEKDAY_NAMES.items() if v == dow),
            key=len,
        ).capitalize()
        return ParsedReminder("cron", f"{t[1]} {t[0]} * * {dow}",
                              f"every {day_name} at {t[0]:02d}:{t[1]:02d}")

    return None


# ---------------------------------------------------------------------------
# crontab management
# ---------------------------------------------------------------------------
def _read_crontab() -> str:
    proc = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    if proc.returncode == 0:
        return proc.stdout
    if "no crontab" in (proc.stderr or "").lower():
        return ""
    raise RuntimeError(f"crontab -l failed: {proc.stderr.strip()}")


def _write_crontab(content: str) -> None:
    if content and not content.endswith("\n"):
        content += "\n"
    proc = subprocess.run(
        ["crontab", "-"], input=content, text=True, capture_output=True
    )
    if proc.returncode != 0:
        raise RuntimeError(f"crontab install failed: {proc.stderr.strip()}")


def _notify_command(message: str, *,
                    node_id: Optional[int] = None,
                    json_path: Optional[str] = None) -> str:
    """Build the shell command that fires the notification.

    Delegates to ``~/.local/bin/pymindmap-notify``, which sets the
    session-bus environment for ``notify-send`` and (if the SMTP config
    exists) also dispatches the email half of the notification. When
    ``node_id`` and ``json_path`` are both provided, the wrapper runs in
    ``--ai`` mode: it shells out to claude with the node's stored
    ``claude_prompt`` plus mind-map context, and the AI's response
    becomes the notification body. ``message`` is passed as a fallback
    in case claude fails or isn't reachable.
    """
    title = "pymindmap reminder"
    wrapper = str(Path.home() / ".local" / "bin" / "pymindmap-notify")
    if node_id is not None and json_path:
        return (
            f"{shlex.quote(wrapper)} --ai "
            f"{shlex.quote(str(node_id))} {shlex.quote(json_path)} "
            f"{shlex.quote(title)} {shlex.quote(message or '')}"
        )
    return f"{shlex.quote(wrapper)} {shlex.quote(title)} {shlex.quote(message or '')}"


def install_cron(node_id: int, cron_expr: str, message: str, *,
                 ai_json_path: Optional[str] = None) -> None:
    """Add (or replace) the user's crontab entry for this node. If
    ``ai_json_path`` is provided, the line will run in AI mode (Claude
    Code reads the node + mindmap context and the response becomes the
    notification body)."""
    tag = f"{TAG_PREFIX}{node_id}"
    cmd = _notify_command(message, node_id=node_id if ai_json_path else None,
                          json_path=ai_json_path)
    line = f"{cron_expr} {cmd} {tag}"
    existing = _read_crontab().splitlines()
    kept = [l for l in existing if not l.rstrip().endswith(tag)]
    kept.append(line)
    _write_crontab("\n".join(kept))


def remove_cron(node_id: int) -> bool:
    tag = f"{TAG_PREFIX}{node_id}"
    existing = _read_crontab().splitlines()
    kept = [l for l in existing if not l.rstrip().endswith(tag)]
    if len(kept) == len(existing):
        return False
    _write_crontab("\n".join(kept))
    return True


# ---------------------------------------------------------------------------
# at-job management
# ---------------------------------------------------------------------------
def _read_jobs() -> Dict[int, int]:
    if not JOBS_FILE.exists():
        return {}
    try:
        raw = json.loads(JOBS_FILE.read_text())
        return {int(k): int(v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError, KeyError, TypeError):
        return {}


def _write_jobs(jobs: Dict[int, int]) -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    JOBS_FILE.write_text(json.dumps(
        {str(k): v for k, v in jobs.items()}, indent=2
    ))


def install_at(node_id: int, when_iso: str, message: str, *,
               ai_json_path: Optional[str] = None) -> None:
    """Queue a one-shot ``at`` job for this node, replacing any prior one."""
    when = datetime.fromisoformat(when_iso)
    body = _notify_command(message, node_id=node_id if ai_json_path else None,
                           json_path=ai_json_path)
    proc = subprocess.run(
        ["at", when.strftime("%H:%M"), when.strftime("%Y-%m-%d")],
        input=body, text=True, capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"at failed: {proc.stderr.strip()}")
    m = re.search(r"job\s+(\d+)\s+at", proc.stderr or proc.stdout)
    if not m:
        raise RuntimeError(f"could not parse at job id from: {proc.stderr or proc.stdout}")
    job_id = int(m.group(1))
    jobs = _read_jobs()
    if node_id in jobs and jobs[node_id] != job_id:
        subprocess.run(["atrm", str(jobs[node_id])], capture_output=True)
    jobs[node_id] = job_id
    _write_jobs(jobs)


def remove_at(node_id: int) -> bool:
    jobs = _read_jobs()
    if node_id not in jobs:
        return False
    job_id = jobs.pop(node_id)
    subprocess.run(["atrm", str(job_id)], capture_output=True)
    _write_jobs(jobs)
    return True


# ---------------------------------------------------------------------------
# unified install / remove
# ---------------------------------------------------------------------------
def install(node_id: int, parsed: ParsedReminder, message: str, *,
            ai_json_path: Optional[str] = None) -> None:
    """Install a parsed reminder. Removes any prior reminder of the
    *other* kind (so converting cron→at or at→cron is a clean swap).

    ``ai_json_path``, if provided, switches the cron/at line to AI mode:
    when the reminder fires, the wrapper invokes claude with the node's
    ``claude_prompt`` plus mindmap context and uses the response as the
    notification body. The wrapper falls back to ``message`` if the AI
    step fails so a notification always reaches the user.
    """
    if parsed.kind == "cron":
        remove_at(node_id)
        install_cron(node_id, parsed.schedule, message,
                     ai_json_path=ai_json_path)
    elif parsed.kind == "at":
        remove_cron(node_id)
        install_at(node_id, parsed.schedule, message,
                   ai_json_path=ai_json_path)
    else:
        raise ValueError(f"unknown reminder kind: {parsed.kind}")


def remove(node_id: int) -> bool:
    a = remove_cron(node_id)
    b = remove_at(node_id)
    return a or b


def has_tools() -> Dict[str, bool]:
    """Probe whether the OS-side tools needed to install reminders are
    actually available. The UI uses this to disable the test/save
    buttons (and explain why) on a host that's missing them."""
    return {
        "crontab": _has_executable("crontab"),
        "at": _has_executable("at"),
        "notify-send": _has_executable("notify-send"),
    }


def _has_executable(name: str) -> bool:
    from shutil import which
    return which(name) is not None
