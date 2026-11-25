# Field notes: a change log shared by two AI coding sessions

`ops-journal` is the cleaned-up form of something I ran for real for about two weeks: a single markdown change
log, kept in a git repository on my workstation, that **two AI coding assistants on two different machines** wrote
to. One ran on a work laptop, the other on the workstation; between them they touched the same servers, the same
private network and the same SSH setup. Neither could see the other's terminal. The log was the only memory
they shared.

## The rules that emerged

The rules started as a short README and were tightened as problems came up:

1. **Read the last 40 lines before you touch a shared host.** A session starts cold; the log is its context.
2. **After changing anything shared, append an entry:** what changed, where, how to undo it, what is still open.
3. **Never edit or delete the other side's entries. Correct them with a new entry.**
4. **No secrets in the log.** Point to where a secret lives.

## Each feature is a scar

| Feature | What actually happened |
|---|---|
| **The writer stamps the time** | Entries were hand-written at first. One came out stamped in UTC while every other was in local time, so the log briefly said a change happened six hours in the future. The fix was not "be more careful", it was taking the timestamp away from the author: the tool computes it in a fixed zone. A later entry (see below) still had to correct the wrong one. |
| **Append-only, corrections as new entries** | A health-check alert was attributed to the wrong machine in one entry. I'd disabled a dead service on the workstation, noted that as the cause of a cleared alert, and then the alert didn't clear: it belonged to two failed report units on a production server I had not touched. The correction went in as a new entry directly under the wrong one. The record of *what I believed and when* is itself useful. |
| **Secret refusal** | The log is read by several agents and copied into backups. Redacting is a promise to clean up later; refusing at write time is a guarantee. The patterns cover `key=value` credentials and the common token shapes. |
| **`flock` while appending** | Both machines could write within seconds of each other (one over ssh). Without a lock, two multi-line entries can interleave into nonsense. A 20-writer test pins that. |
| **One git commit per entry** | `git log` becomes the audit trail and a bad entry can be found by `git blame`, without anyone being allowed to rewrite history. |
| **Health checks that check the habit** | The real log had a ten-point "mesh check" script. The most useful checks weren't "is the host up" but "is the backup fresh" and "is the shared drive actually mounted", because those fail silently. They became the `file_age` and `mount` check types, plus `journal_fresh` for "is anyone still logging?". |

## The bug the tests found while I was extracting it

While generalising the writer I normalised bullets by stripping leading dashes. A test then showed that a line
beginning `-----BEGIN PRIVATE KEY-----` was rewritten to `- BEGIN PRIVATE KEY-----` **before** the secret check
ran, so the refusal never fired. Content is now never altered, and the secret check runs on the raw input as
well as the normalised text. The original shell version had the same ordering and was never exposed to such a
line; it only showed up because a unit test went looking.

## Backing up the journal itself

A log like this is the thing you'd least like to lose, so it had its own backup: a verified `git bundle`,
checksummed, copied to three places on three disks, with a run that **fails if fewer than two copies land**.
That idea is what became `min_copies` in [`repo-fleet`](https://github.com/MC-intel/repo-fleet).

## What I would add next

* Signed entries (so "who wrote this" survives a shared account).
* A reader that renders only entries touching a given host, so a cold session loads kilobytes instead of the
  whole log.
