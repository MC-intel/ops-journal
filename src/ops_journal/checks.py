"""Config-driven health checks. Each check returns (ok, detail) and never raises.

Check types: tcp, http, command, file_age, mount, journal_fresh. A failing check does not stop the
others: you always get the whole picture, then a non-zero exit code if anything failed.
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

Result = tuple[bool, str]


def check_tcp(c: dict) -> Result:
    t0 = time.time()
    try:
        with socket.create_connection((c["host"], int(c["port"])), timeout=float(c.get("timeout", 3))):
            return True, f"connected in {int((time.time() - t0) * 1000)} ms"
    except OSError as e:
        return False, f"{type(e).__name__}: {e}"


def check_http(c: dict) -> Result:
    try:
        with urllib.request.urlopen(c["url"], timeout=float(c.get("timeout", 5))) as r:
            want = int(c.get("status", 200))
            return r.status == want, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code == int(c.get("status", 200)), f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"{type(e).__name__}: {e}"


def check_command(c: dict) -> Result:
    """Run an argv list (never a shell string) and compare the exit code."""
    argv = c["argv"]
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return False, "argv must be a list of strings"
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=float(c.get("timeout", 10)))
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"
    ok = p.returncode == int(c.get("exit", 0))
    return ok, f"exit {p.returncode}" + ("" if ok else f": {(p.stderr or p.stdout).strip()[:120]}")


def check_file_age(c: dict) -> Result:
    """Newest file matching the glob must be younger than max_age_hours (e.g. 'is the backup fresh?')."""
    base = Path(os.path.expanduser(c["dir"]))
    files = list(base.glob(c.get("glob", "*")))
    if not files:
        return False, f"no files match {base}/{c.get('glob', '*')}"
    newest = max(files, key=lambda p: p.stat().st_mtime)
    age_h = (time.time() - newest.stat().st_mtime) / 3600
    return age_h <= float(c["max_age_hours"]), f"{newest.name} is {age_h:.1f} h old (limit {c['max_age_hours']} h)"


def check_mount(c: dict) -> Result:
    ok = os.path.ismount(c["path"])
    return ok, "mounted" if ok else "NOT MOUNTED"


def check_journal_fresh(c: dict) -> Result:
    """The journal must have an entry younger than max_age_days (catches 'nobody is logging changes')."""
    from .journal import parse
    from datetime import date
    try:
        entries = parse(os.path.expanduser(c["path"]))
    except OSError as e:
        return False, str(e)
    if not entries:
        return False, "journal has no entries"
    days = (date.today() - date.fromisoformat(entries[-1].date)).days
    return days <= int(c["max_age_days"]), f"last entry {days} day(s) ago"


CHECKS: dict[str, Callable[[dict], Result]] = {
    "tcp": check_tcp, "http": check_http, "command": check_command,
    "file_age": check_file_age, "mount": check_mount, "journal_fresh": check_journal_fresh,
}


def run_all(config_path: str | Path, out=print) -> int:
    cfg = tomllib.loads(Path(config_path).read_text())
    failed = 0
    items = cfg.get("check", [])
    for c in items:
        fn = CHECKS.get(c.get("type", ""))
        name = c.get("name", c.get("type", "?"))
        if not fn:
            ok, detail = False, f"unknown check type {c.get('type')!r}"
        else:
            try:
                ok, detail = fn(c)
            except Exception as e:                    # a broken check is a failed check, not a crash
                ok, detail = False, f"{type(e).__name__}: {e}"
        failed += not ok
        out(f"{'ok  ' if ok else 'FAIL'} {name:32} {detail}")
    out(f"== {len(items) - failed}/{len(items)} checks passed")
    return failed
