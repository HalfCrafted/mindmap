"""Per-device directory shortcuts attached to mind-map nodes.

A node can carry a ``dir_links`` dict mapping each device's *Tailscale
hostname* to the local filesystem path that node represents on that
device. We use the Tailscale name (e.g. "fedora-desktop", "thinkpad",
"01-5498-spanda") rather than ``socket.gethostname()`` because hostnames
on Linux/macOS are inconsistent and sometimes user-mutable, while the
Tailscale node name is stable and matches the SSH aliases the user is
already familiar with.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

# Cached so we don't shell out to `tailscale` on every node-paint.
_device_key_cache: Optional[str] = None


def current_device_key() -> str:
    """Return a stable identifier for the current machine.

    Prefers the Tailscale node name (``Self.HostName`` from
    ``tailscale status --json``). Falls back to the short OS hostname
    lowercased. Cached for the lifetime of the process.
    """
    global _device_key_cache
    if _device_key_cache is not None:
        return _device_key_cache
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            self_data = data.get("Self", {})
            # ``DNSName`` is e.g. "fedora-desktop.taila17814.ts.net." —
            # the leading component matches the SSH alias the user already
            # types. ``HostName`` is the short OS hostname (e.g. "fedora")
            # which doesn't always match the Tailscale node name.
            dns = self_data.get("DNSName")
            if isinstance(dns, str) and "." in dns:
                first = dns.split(".", 1)[0].strip()
                if first:
                    _device_key_cache = first
                    return first
            name = self_data.get("HostName")
            if isinstance(name, str) and name:
                _device_key_cache = name
                return name
    except (FileNotFoundError, subprocess.TimeoutExpired,
            json.JSONDecodeError, OSError):
        pass
    _device_key_cache = socket.gethostname().split(".")[0].lower()
    return _device_key_cache


def resolve_path(dir_links: Dict[str, str]) -> Optional[str]:
    """Return the path entry for the current device, or None if there
    isn't one. The returned path is *not* validated to exist — that's
    the caller's job (so a missing path can be surfaced in the UI as
    "this directory doesn't exist on this device" rather than silently
    treated like an unconfigured shortcut).
    """
    if not dir_links:
        return None
    return dir_links.get(current_device_key())


def path_exists(path: Optional[str]) -> bool:
    if not path:
        return False
    try:
        return Path(os.path.expanduser(path)).exists()
    except OSError:
        return False


def open_path(path: str) -> bool:
    """Open ``path`` in the platform's file manager. Returns True if the
    open command was dispatched successfully — not whether the file
    manager actually opened anything (that's async)."""
    if not path:
        return False
    expanded = os.path.expanduser(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", expanded],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            os.startfile(expanded)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["xdg-open", expanded],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except (FileNotFoundError, OSError):
        return False
