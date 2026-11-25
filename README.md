# ops-journal

Two small tools for people who run shared systems:

1. **An append-only change journal** (`ops-journal append`) that humans and automation write to, so
   "what changed, where, and how do I undo it" lives in one reviewable, git-versioned file.
2. **A health-check runner** (`ops-journal check`) that reads a TOML file, runs every check, reports all of
   them, and exits non-zero if any failed.

Standard library only. Python >= 3.11.

## Where this came from

I ran this for real: one change log shared by two AI coding assistants on two machines, which could not see each
other's terminals. Every feature below is a scar from that: a wrong-timezone stamp, an alert attributed to the
wrong machine, a log that must never hold a credential. See [docs/FIELD-NOTES.md](docs/FIELD-NOTES.md).

## The journal

```sh
$ ops-journal --file journal.md --tz America/Chicago append alice "Rotate cache nodes" <<'EOF'
drained node 2, restarted with the new image
undo: redeploy tag v41
open: node 3 still on the old image
EOF
## 2026-07-04 10:30 CDT, alice: Rotate cache nodes
```

Resulting file (each entry is also its own git commit):

```markdown
## 2026-07-04 10:30 CDT, alice: Rotate cache nodes
- drained node 2, restarted with the new image
- undo: redeploy tag v41
- open: node 3 still on the old image
```

### Guarantees (all tested)

| Guarantee | Why it matters |
|---|---|
| Append-only: existing bytes are never rewritten | The log is evidence; "tidying" it destroys that |
| **The writer stamps the time**, in a configured zone | Hand-typed timestamps are wrong often enough to make a log untrustworthy |
| Entries that look like credentials are **refused** (key=value pairs, GitHub/AWS/Slack/OpenAI token shapes, PEM headers) | A shared log is read by many people and copied to many places; refusing beats redacting |
| `flock` while appending | 20 concurrent writers produce 20 intact entries, none interleaved |
| Input validation: actor slug, one-line title of at most 160 characters, 1 to 40 bullets | Keeps the file machine-parseable (`journal.parse`) |
| One git commit per entry when the file is in a repository | `git log` and `git blame` become the audit trail |

A bug the tests caught during development: normalising bullets by stripping leading dashes also mangled
`-----BEGIN PRIVATE KEY-----` into `- BEGIN ...`, which slipped past the secret check. Content is now never
altered, and the check runs on the raw input as well as the normalised text.

## Health checks

```sh
$ ops-journal check examples/checks.toml
ok   backup is fresh                  nightly-2026-07-04.bundle is 6.2 h old (limit 30 h)
FAIL backup disk mounted              NOT MOUNTED
ok   api answers                      HTTP 200
ok   database port                    connected in 1 ms
ok   service unit active              exit 0
ok   somebody is logging changes      last entry 2 day(s) ago
== 5/6 checks passed
```

Check types: `tcp`, `http`, `command`, `file_age`, `mount`, `journal_fresh`.

Design choices worth noting:

* **Checks that check the backups.** `file_age` and `journal_fresh` turn "we have backups" and "we log changes"
  into things that alert you when they silently stop being true.
* **`command` takes an argv list, never a shell string**, so a config file cannot inject shell syntax.
* **One broken check never hides the others.** Exceptions become `FAIL` lines; the runner always finishes.
* The exit status is 0 or 1, ready for cron, systemd `OnFailure=`, or CI.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests     # 12 tests
```
