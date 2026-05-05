"""Side-channel integrations for pymindmap nodes.

Modules in this package wire individual nodes up to OS-level features:
``dir_link`` opens a file-manager path attached to a node, ``reminder``
schedules a crontab/at job from a natural-language description.

Everything here is best-effort and degrades cleanly: if Tailscale isn't
running, if cron/at aren't installed, if a path doesn't exist on the
current device — the rest of the app keeps working without them.
"""
