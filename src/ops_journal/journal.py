"""Append-only change journal kept in a markdown file inside a git repository.

Why this exists: when several people (or automation) change shared infrastructure, "what changed, where,
how do I undo it" must be written down in one place that cannot be silently edited or poisoned with secrets.

Guarantees (each has a test):
  * entries are only ever appended; the writer never rewrites existing bytes;
  * the timestamp is stamped by the writer in a configured time zone: callers cannot supply or get it wrong;
  * an entry that looks like it contains a credential is refused, not redacted;
  * the file is locked while appending, so concurrent writers cannot interleave entries;
  * if the file lives in a git repository, each entry is committed on its own.
"""
from __future__ import annotations

import fcntl
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# key = value pairs for credential-looking keys, plus well known token shapes.
SECRET_PATTERNS = [
    re.compile(r"(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*[^\s<]{6,}", re.I),
    re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
]
ACTOR_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) (\S+), ([\w.-]+): (.+)$")


class Refused(ValueError):
    """The entry was rejected (bad input or looks like a secret)."""


@dataclass
class Entry:
    date: str
    time: str
    tz: str
    actor: str
    title: str
    bullets: list[str]


def looks_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def normalise_bullets(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        out.append(s if s.startswith("- ") else f"- {s}")     # never alter the content itself
    return out


def _git_commit(path: Path, message: str) -> bool:
    top = subprocess.run(["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0:
        return False
    root = top.stdout.strip()
    subprocess.run(["git", "-C", root, "add", "--", str(path)], check=True, capture_output=True)
    done = subprocess.run(["git", "-C", root, "commit", "-q", "-m", message, "--", str(path)], capture_output=True)
    return done.returncode == 0


def append(path: str | Path, actor: str, title: str, bullets: list[str],
           tz: str = "UTC", now: datetime | None = None, commit: bool = True) -> str:
    """Append one entry. Returns the header line written."""
    path = Path(path)
    if not ACTOR_RE.match(actor):
        raise Refused(f"actor {actor!r} must match {ACTOR_RE.pattern}")
    title = title.strip()
    if not title or "\n" in title or len(title) > 160:
        raise Refused("title must be one line, 1-160 characters")
    body = normalise_bullets(bullets)
    if not body:
        raise Refused("no bullets")
    if len(body) > 40:
        raise Refused("too many bullets (max 40)")
    if looks_secret(title) or looks_secret("\n".join(bullets)) or looks_secret("\n".join(body)):
        raise Refused("entry looks like it contains a secret; refused (describe where it lives instead)")
    zone = ZoneInfo(tz)
    stamp = (now or datetime.now(zone)).astimezone(zone)
    header = f"## {stamp:%Y-%m-%d %H:%M} {stamp.tzname()}, {actor}: {title}"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(f"\n{header}\n" + "\n".join(body) + "\n")
        f.flush()
    if commit:
        _git_commit(path, f"{actor}: {title}")
    return header


def parse(path: str | Path) -> list[Entry]:
    entries: list[Entry] = []
    cur: Entry | None = None
    for line in Path(path).read_text().splitlines():
        m = HEADER_RE.match(line)
        if m:
            cur = Entry(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), [])
            entries.append(cur)
        elif cur and line.startswith("- "):
            cur.bullets.append(line[2:])
    return entries
