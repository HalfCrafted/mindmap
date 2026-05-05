"""Send a pymindmap reminder by email.

Designed to be invoked as a CLI from cron / at lines:

    python -m pymindmap.integrations.email_send "<subject>" "<body>"

Reads SMTP config + app password from ``~/.config/pymindmap/email.json``
(mode 0600). If the config file is absent, exits silently with status 0
so a missing config never breaks the desktop ``notify-send`` half of the
notification — email is best-effort, the toast is the source of truth.
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Optional


CONFIG_PATH = Path.home() / ".config" / "pymindmap" / "email.json"


def load_config() -> Optional[dict]:
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def send(subject: str, body: str, *, recipient: Optional[str] = None) -> bool:
    cfg = load_config()
    if cfg is None:
        return False
    to_addr = recipient or cfg.get("default_recipient")
    from_addr = cfg.get("from_email") or cfg.get("username")
    user = cfg.get("username")
    pw = (cfg.get("app_password") or "").replace(" ", "")
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    if not (to_addr and from_addr and user and pw):
        print("email_send: incomplete config", file=sys.stderr)
        return False

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body or "")

    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(user, pw)
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        print(f"email_send: {exc}", file=sys.stderr)
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Send a pymindmap reminder email.")
    p.add_argument("subject", help="email subject line")
    p.add_argument("body", nargs="?", default="", help="email body")
    p.add_argument("--to", help="override the configured default recipient")
    args = p.parse_args(argv)
    ok = send(args.subject, args.body, recipient=args.to)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
