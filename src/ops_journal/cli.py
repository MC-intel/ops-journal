"""``ops-journal append|list|check``."""
from __future__ import annotations

import argparse
import os
import sys

from . import checks, journal


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ops-journal")
    ap.add_argument("--file", default=os.environ.get("OPS_JOURNAL_FILE", "journal.md"))
    ap.add_argument("--tz", default=os.environ.get("OPS_JOURNAL_TZ", "UTC"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append", help="append an entry; bullets are read from stdin")
    a.add_argument("actor")
    a.add_argument("title")
    a.add_argument("--no-commit", action="store_true")
    ls = sub.add_parser("list", help="print entries")
    ls.add_argument("-n", type=int, default=10)
    c = sub.add_parser("check", help="run health checks from a TOML file")
    c.add_argument("config")
    ns = ap.parse_args(argv)
    if ns.cmd == "append":
        try:
            print(journal.append(ns.file, ns.actor, ns.title, sys.stdin.read().splitlines(),
                                 tz=ns.tz, commit=not ns.no_commit))
        except journal.Refused as e:
            print(f"refused: {e}", file=sys.stderr)
            return 3
        return 0
    if ns.cmd == "list":
        for e in journal.parse(ns.file)[-ns.n:]:
            print(f"{e.date} {e.time} {e.actor}: {e.title}")
        return 0
    return 1 if checks.run_all(ns.config) else 0


if __name__ == "__main__":
    sys.exit(main())
