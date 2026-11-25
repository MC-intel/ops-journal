import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ops_journal import checks, journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.tmp)]))
        self.f = self.tmp / "journal.md"

    def test_stamps_in_configured_zone_and_parses_back(self):
        now = datetime(2026, 7, 4, 15, 30, tzinfo=ZoneInfo("UTC"))
        h = journal.append(self.f, "alice", "Rotate cache nodes", ["drained node 2", "- restarted"], tz="America/Chicago", now=now, commit=False)
        self.assertTrue(h.startswith("## 2026-07-04 10:30 CDT, alice: Rotate cache nodes"))
        e = journal.parse(self.f)[0]
        self.assertEqual((e.actor, e.time, e.tz, e.bullets), ("alice", "10:30", "CDT", ["drained node 2", "restarted"]))

    def test_existing_bytes_never_change(self):
        journal.append(self.f, "a", "one", ["x"], commit=False)
        before = self.f.read_bytes()
        journal.append(self.f, "b", "two", ["y"], commit=False)
        self.assertTrue(self.f.read_bytes().startswith(before))

    def test_refuses_secrets(self):
        for bullet in ("password: hunter2hunter2", "token=abcdef123456", "key ghp_" + "a" * 30,
                       "AKIA" + "A" * 16, "-----BEGIN RSA PRIVATE KEY-----", "api_key = 'abcdefghij'"):
            with self.assertRaises(journal.Refused, msg=bullet):
                journal.append(self.f, "a", "t", [bullet], commit=False)
        self.assertFalse(self.f.exists())

    def test_refuses_secret_in_title_too(self):
        with self.assertRaises(journal.Refused):
            journal.append(self.f, "a", "set password=supersecret1", ["ok"], commit=False)

    def test_allows_describing_where_a_secret_lives(self):
        journal.append(self.f, "a", "Rotated key", ["new token stored in the vault under ops/db; none written here"], commit=False)
        self.assertTrue(self.f.exists())

    def test_input_validation(self):
        for actor, title, bullets in (("Bad Actor", "t", ["x"]), ("a", "", ["x"]), ("a", "multi\nline", ["x"]),
                                      ("a", "t", []), ("a", "t", ["", "  "]), ("a", "x" * 161, ["x"])):
            with self.assertRaises(journal.Refused, msg=(actor, title, bullets)):
                journal.append(self.f, actor, title, bullets, commit=False)

    def test_commits_each_entry_in_a_git_repo(self):
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
            subprocess.run(["git", "-C", str(self.tmp), "config", k, v], check=True)
        journal.append(self.f, "a", "first", ["x"])
        journal.append(self.f, "a", "second", ["y"])
        log = subprocess.run(["git", "-C", str(self.tmp), "log", "--format=%s"], capture_output=True, text=True).stdout.split("\n")
        self.assertEqual(log[:2], ["a: second", "a: first"])

    def test_concurrent_writers_do_not_interleave(self):
        def w(i):
            journal.append(self.f, f"w{i}", f"entry {i}", [f"line a {i}", f"line b {i}"], commit=False)
        ts = [threading.Thread(target=w, args=(i,)) for i in range(20)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        es = journal.parse(self.f)
        self.assertEqual(len(es), 20)
        for e in es:
            n = e.actor[1:]
            self.assertEqual(e.bullets, [f"line a {n}", f"line b {n}"])


class CheckTests(unittest.TestCase):
    def test_tcp_ok_and_closed_port(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        self.assertTrue(checks.check_tcp({"host": "127.0.0.1", "port": port})[0])
        s.close()
        self.assertFalse(checks.check_tcp({"host": "127.0.0.1", "port": port, "timeout": 1})[0])

    def test_command_uses_argv_not_a_shell(self):
        self.assertTrue(checks.check_command({"argv": ["true"]})[0])
        self.assertFalse(checks.check_command({"argv": ["false"]})[0])
        ok, detail = checks.check_command({"argv": "true; rm -rf /"})
        self.assertFalse(ok)
        self.assertIn("argv must be a list", detail)
        self.assertFalse(checks.check_command({"argv": ["definitely-not-a-command"]})[0])

    def test_file_age(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(d)]))
        self.assertFalse(checks.check_file_age({"dir": str(d), "max_age_hours": 1})[0])
        f = d / "a.bundle"
        f.write_text("x")
        self.assertTrue(checks.check_file_age({"dir": str(d), "glob": "*.bundle", "max_age_hours": 1})[0])
        old = time.time() - 5 * 3600
        os.utime(f, (old, old))
        self.assertFalse(checks.check_file_age({"dir": str(d), "glob": "*.bundle", "max_age_hours": 1})[0])

    def test_runner_reports_everything_and_survives_bad_checks(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(d)]))
        cfg = d / "c.toml"
        cfg.write_text('[[check]]\nname="good"\ntype="command"\nargv=["true"]\n'
                       '[[check]]\nname="bad"\ntype="command"\nargv=["false"]\n'
                       '[[check]]\nname="typo"\ntype="nope"\n'
                       '[[check]]\nname="missing key"\ntype="tcp"\n')
        out = []
        self.assertEqual(checks.run_all(cfg, out=out.append), 3)
        self.assertEqual(len(out), 5)
        self.assertTrue(out[0].startswith("ok"))
        self.assertIn("1/4 checks passed", out[-1])


if __name__ == "__main__":
    unittest.main()
