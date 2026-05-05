"""Run a Claude Code instance with a mindmap node as context.

Used by AI-mode reminders: when a node's reminder has a ``claude_prompt``,
the cron wrapper invokes this module instead of emailing the static
message. Builds a system-prompt that describes the node, its immediate
relatives, and any directories the node has linked on the current device,
then runs ``claude --print`` and prints the response to stdout. The
notification wrapper captures stdout and emails it as the reminder body.

Designed to be invoked as a CLI from cron lines:

    python -m pymindmap.integrations.claude_run \\
        --node-id N --json /path/to/mindmap.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .. import io as mio
from ..model import Graph, Node
from . import dir_link as dirlink


CLAUDE_TIMEOUT_S = 240
CLAUDE_DEFAULT_PATH = Path.home() / ".local" / "bin" / "claude"


def _find_relatives(graph: Graph, node_id: int):
    """Return (parent, children, siblings) — *Node* instances. Uses
    directed edges for hierarchy where they exist; falls back to
    undirected adjacency otherwise."""
    parent: Optional[Node] = None
    children: List[Node] = []
    for c in graph.connections:
        if c.directed and c.to_id == node_id:
            parent = graph.nodes.get(c.from_id) or parent
        if c.directed and c.from_id == node_id:
            child = graph.nodes.get(c.to_id)
            if child is not None:
                children.append(child)
    siblings: List[Node] = []
    if parent is not None:
        for c in graph.connections:
            if c.directed and c.from_id == parent.id and c.to_id != node_id:
                sib = graph.nodes.get(c.to_id)
                if sib is not None:
                    siblings.append(sib)
    return parent, children, siblings


def build_system_prompt(graph: Graph, node_id: int) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return "You are running as a scheduled mindmap reminder, but the target node could not be located."
    parent, children, siblings = _find_relatives(graph, node_id)
    host = dirlink.current_device_key()

    lines: List[str] = []
    lines.append(
        "You are running as a scheduled task fired from a personal mind-map "
        "node (the user's pymindmap app). Your job is to read the prompt "
        "below, gather any necessary information from the linked directories "
        "or other tools, and produce a concise plain-text response suitable "
        "for delivery as the body of an email reminder."
    )
    lines.append("")
    lines.append("=== Mind-map context ===")
    lines.append(f"Current device: {host}")
    lines.append("")
    lines.append(f"NODE: {node.text or '(untitled)'}")
    if node.body.strip():
        lines.append("NOTES:")
        for ln in node.body.splitlines():
            lines.append(f"  {ln}")
    if parent is not None:
        lines.append(f"PARENT: {parent.text or '(untitled)'}")
    if children:
        lines.append("CHILDREN:")
        for c in children:
            lines.append(f"  - {c.text or '(untitled)'}")
    if siblings:
        lines.append("SIBLINGS:")
        for s in siblings:
            lines.append(f"  - {s.text or '(untitled)'}")

    # Directories linked on this device, for the node and any of its
    # immediate relatives — those are the most likely useful sources.
    related_paths: List[tuple[str, str]] = []
    for n in [node] + ([parent] if parent else []) + children + siblings:
        if n is None:
            continue
        path = dirlink.resolve_path(n.dir_links)
        if path and dirlink.path_exists(path):
            related_paths.append((n.text or f"node #{n.id}", path))
    if related_paths:
        lines.append("")
        lines.append("LINKED DIRECTORIES (you can Read/Bash these):")
        for label, p in related_paths:
            lines.append(f"  - [{label}] {p}")

    lines.append("")
    lines.append(
        "Output a concise plain-text body (no markdown headers, no preamble "
        "like 'Here is …'). Do what the prompt asks, then return the result."
    )
    return "\n".join(lines)


def run_claude(prompt: str, system_prompt: str, *,
               extra_dirs: Optional[List[str]] = None,
               claude_bin: Optional[str] = None,
               timeout: int = CLAUDE_TIMEOUT_S) -> str:
    """Spawn ``claude --print`` with the given prompt + appended system
    prompt. Returns the stdout (stripped) on success or a short error
    string on failure — never raises, since the cron wrapper would have
    no way to surface a Python traceback."""
    binary = claude_bin or os.environ.get("PYMINDMAP_CLAUDE_BIN") or str(CLAUDE_DEFAULT_PATH)
    cmd = [binary, "--print", "--output-format", "text",
           "--append-system-prompt", system_prompt]
    if extra_dirs:
        cmd.extend(["--add-dir", *extra_dirs])
    cmd.append(prompt)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return f"[claude binary not found at {binary}]"
    except subprocess.TimeoutExpired:
        return f"[claude timed out after {timeout}s]"
    out = (result.stdout or "").strip()
    # Filter known-noisy lines (e.g. SessionEnd hook chatter) — keep
    # everything up to those if they appear at the very end of stdout.
    out = "\n".join(
        ln for ln in out.splitlines()
        if "SessionEnd hook" not in ln
    ).strip()
    if not out and result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        return f"[claude failed (rc={result.returncode}): {' / '.join(err[-3:])[:300]}]"
    return out or "(empty response)"


def run(node_id: int, json_path: str) -> str:
    """Top-level: load the graph, build context for the node, run claude,
    return the response text."""
    p = Path(os.path.expanduser(json_path))
    if not p.exists():
        return f"[mindmap json not found: {p}]"
    try:
        graph = mio.load_graph(p)
    except Exception as exc:
        return f"[failed to read mindmap: {exc}]"
    node = graph.nodes.get(node_id)
    if node is None:
        return f"[node #{node_id} not found in mindmap]"
    if not node.reminder:
        return "(no reminder configured)"
    user_prompt = node.reminder.get("claude_prompt", "").strip()
    if not user_prompt:
        # Fall back to the static message — caller should normally have
        # detected this and skipped invoking us, but be defensive.
        return node.reminder.get("message", node.text or "")
    system_prompt = build_system_prompt(graph, node_id)
    # Surface every linked directory (any device) as an --add-dir so
    # claude has explicit access even when the node didn't store the
    # path under the current device key. We only include paths that
    # actually exist locally.
    extra_dirs: List[str] = []
    for n in graph.nodes.values():
        for path in n.dir_links.values():
            expanded = os.path.expanduser(path)
            if os.path.isdir(expanded) and expanded not in extra_dirs:
                extra_dirs.append(expanded)
    return run_claude(user_prompt, system_prompt, extra_dirs=extra_dirs)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run claude on a mindmap node.")
    p.add_argument("--node-id", type=int, required=True)
    p.add_argument("--json", required=True, help="path to mindmap json")
    args = p.parse_args(argv)
    sys.stdout.write(run(args.node_id, args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
