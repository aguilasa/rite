"""Local cycles (documents kept out of git) and a per-cycle ticket in commit messages."""

import json
import unittest

from fixtures import write

from test_cli import FixtureCase, fields


def set_progress_field(case: FixtureCase, cycle: str, line: str) -> None:
    """Add a frontmatter line to a fixture cycle's progress file and commit it."""
    path = case.root / f"docs/rite/cycles/{cycle}/progress.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("---\n", f"---\n{line}\n", 1), encoding="utf-8", newline="\n")
    case.fx.git("add", str(path.relative_to(case.root)))
    case.fx.git("commit", "-q", "-m", f"docs: {line}")


def body(case: FixtureCase, rev: str = "HEAD") -> str:
    return case.fx.git("show", "-s", "--format=%B", rev).strip()


def warnings(case: FixtureCase, *args: str) -> list[str]:
    _, out, _ = case.fx.rite("check", "--json", *args)
    return [f"{f['path']}: {f['message']}" for f in json.loads(out)["findings"] if f["level"] == "warn"]


class LocalCycleTest(FixtureCase):
    def make_local(self) -> None:
        write(self.root / ".gitignore", "docs/rite/cycles/gamma/\ndocs/rite/profiles/gamma*\n")
        self.fx.git("add", ".gitignore")
        self.fx.git("commit", "-q", "-m", "chore: ignore gamma")
        res = self.js("new-cycle", "gamma", "--prefix", "GAM", "--local", "--ticket", "PROJ-7", "--commit")
        self.assertEqual((res["local"], res["ticket"], res["commit"]), (True, "PROJ-7", None))
        self.assertTrue(all(res["ignored"].values()), res["ignored"])
        self.js("new-task", "--cycle", "gamma", "--title", "First", "--type", "feature", "--phase", "1",
                "--source-of-truth", "/docs/plans/PLAN-alpha.md#1")

    def test_local_loop_writes_state_without_bookkeeping_commits(self):
        self.make_local()
        refs = self.js("commit-refs", "GAM-TASK-01")
        self.assertEqual(refs["trailers"], ["Refs: PROJ-7"])  # no Refs to an item that is not in git
        work = self.fx.work_commit("src/gamma.py", "g = 1\n", "feat: gamma\n\nRefs: PROJ-7")
        before = self.log()
        res = self.js("close", "GAM-TASK-01")
        self.assertEqual((res["commit"], res["local"]), (None, True))
        self.assertEqual(self.log(), before)  # nothing committed
        meta = fields(self.root / "docs/rite/cycles/gamma/01-first.md")
        self.assertEqual((meta["status"], meta["done_commit"], meta["reviewed_on"]), ("done", work, "pending"))
        # the state on disk drives selection exactly as in a tracked cycle
        self.assertEqual(self.js("next", "review", "--cycle", "gamma")["id"], "GAM-TASK-01")
        self.assertIsNone(self.js("mark-reviewed", "GAM-TASK-01")["commit"])
        self.assertEqual(self.log(), before)
        self.assertEqual(self.fx.git("status", "--porcelain"), "")  # ignored files leave the tree clean
        # only the skeleton profile's missing phase entry, as in any new cycle
        self.assertEqual([e for e in self.check_errors("--cycle", "gamma") if "phase 1" not in e], [])

        res = self.js("archive", "gamma")
        self.assertEqual((res["commit"], res["local"]), (None, True))
        self.assertTrue((self.root / "docs/rite/cycles/archive/gamma/01-first.md").is_file())
        self.assertEqual(self.log(), before)

    def test_check_warns_when_local_and_ignore_disagree(self):
        self.js("new-cycle", "gamma", "--prefix", "GAM", "--local")
        code, out, _ = self.fx.rite("check", "--cycle", "gamma", "--json")
        warns = [f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"]
        self.assertTrue(any("git does not ignore" in w for w in warns), warns)

        write(self.root / ".gitignore", "docs/rite/cycles/delta/\n")
        self.js("new-cycle", "delta", "--prefix", "DEL")
        code, out, _ = self.fx.rite("check", "--cycle", "delta", "--json")
        warns = [f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"]
        self.assertTrue(any("not 'local: true'" in w for w in warns), warns)

    def test_publish_makes_the_cycle_tracked_in_one_commit(self):
        self.make_local()
        code, _, err = self.fx.rite("publish", "gamma")
        self.assertEqual(code, 1)
        self.assertIn("still ignored", err)
        write(self.root / ".gitignore", "")
        res = self.js("publish", "gamma")
        self.assertEqual(self.log(1), ["chore(rite): publish cycle gamma"])
        self.assertIn("Refs: PROJ-7", body(self))
        self.assertIn("docs/rite/cycles/gamma", res["files"])
        self.assertIs(fields(self.root / "docs/rite/cycles/gamma/progress.md")["local"], False)
        tracked = self.fx.git("ls-files", "docs/rite/cycles/gamma", "docs/rite/profiles").split()
        self.assertIn("docs/rite/cycles/gamma/01-first.md", tracked)
        self.assertIn("docs/rite/profiles/gamma.md", tracked)
        self.assertEqual(self.js("commit-refs", "GAM-TASK-01")["trailers"], ["Refs: GAM-TASK-01", "Refs: PROJ-7"])


class TicketTest(FixtureCase):
    def test_ticket_as_trailer_on_bookkeeping_commits(self):
        set_progress_field(self, "alpha", "ticket: PROJ-123")
        self.assertEqual(self.js("resolve-cycle", "alpha")["ticket"], "PROJ-123")
        refs = self.js("commit-refs", "ALP-TASK-01")
        self.assertEqual(refs["trailers"], ["Refs: ALP-TASK-01", "Refs: PROJ-123"])
        self.assertEqual(refs["subject_template"], "{subject}")
        self.fx.work_commit("src/a.py", "a\n", "feat: a")
        self.ok("close", "ALP-TASK-01")
        self.assertEqual(self.log(1), ["chore(rite): close ALP-TASK-01"])
        self.assertTrue(body(self).endswith("Refs: PROJ-123"), body(self))

    def test_ticket_in_subject_and_close_still_spots_bookkeeping(self):
        path = self.root / "rite.toml"
        path.write_text(path.read_text(encoding="utf-8") + '\n[commit]\nticket_format = "{ticket} {subject}"\n',
                        encoding="utf-8", newline="\n")
        self.fx.git("add", "rite.toml")
        self.fx.git("commit", "-q", "-m", "chore: ticket in subject")
        set_progress_field(self, "alpha", "ticket: PROJ-9")
        refs = self.js("commit-refs", "ALP-TASK-01")
        self.assertEqual((refs["subject_template"], refs["trailers"]), ("PROJ-9 {subject}", ["Refs: ALP-TASK-01"]))
        self.fx.work_commit("src/a.py", "a\n", "PROJ-9 feat: a")
        self.ok("close", "ALP-TASK-01")
        self.assertEqual(self.log(1), ["PROJ-9 chore(rite): close ALP-TASK-01"])
        # HEAD is now a bookkeeping commit: closing against it is refused even with the ticket in front
        code, _, err = self.fx.rite("close", "ALP-TASK-02")
        self.assertEqual(code, 1)
        self.assertIn("bookkeeping commit", err)

    def test_no_ticket_leaves_messages_unchanged(self):
        self.assertEqual(self.js("commit-refs", "ALP-TASK-01")["trailers"], ["Refs: ALP-TASK-01"])
        self.fx.work_commit("src/a.py", "a\n", "feat: a")
        self.ok("close", "ALP-TASK-01")
        self.assertEqual(body(self), "chore(rite): close ALP-TASK-01")

    def test_ticket_format_needs_the_placeholder(self):
        path = self.root / "rite.toml"
        path.write_text(path.read_text(encoding="utf-8") + '\n[commit]\nticket_format = "Refs: JIRA"\n',
                        encoding="utf-8", newline="\n")
        code, _, err = self.fx.rite("status")
        self.assertEqual(code, 1)
        self.assertIn("ticket_format", err)


class RebindTest(FixtureCase):
    def test_rebind_after_squash(self):
        self.fx.work_commit("src/a.py", "a\n", "feat: a (part 1)")
        self.fx.work_commit("src/b.py", "b\n", "feat: a (part 2)")
        old = self.js("close", "ALP-TASK-01")["done_commit"]
        self.ok("mark-reviewed", "ALP-TASK-01")
        # squash the two work commits and replay the bookkeeping on top, as a rebase would
        self.fx.git("reset", "-q", "--hard", "HEAD~4")
        self.fx.git("merge", "-q", "--squash", "ORIG_HEAD")
        self.fx.git("commit", "-q", "-m", "feat: a")
        squashed = self.fx.git("rev-parse", "--short", "HEAD").strip()
        self.assertEqual(self.check_errors("--cycle", "alpha"), [])
        warns = warnings(self, "--cycle", "alpha")
        self.assertTrue(any(f"done_commit {old}" in w and "rebind ALP-TASK-01" in w for w in warns), warns)

        res = self.js("rebind", "ALP-TASK-01", "--sha", squashed)
        self.assertEqual((res["old_commit"], res["done_commit"]), (old, squashed))
        self.assertEqual(self.log(1), ["chore(rite): rebind ALP-TASK-01"])
        meta = fields(self.root / "docs/rite/cycles/alpha/01-harness.md")
        self.assertEqual((meta["status"], meta["done_commit"]), ("done", squashed))
        self.assertRegex(str(meta["reviewed_on"]), r"^\d{4}-\d{2}-\d{2}$")  # review kept
        self.assertEqual(self.check_errors("--cycle", "alpha"), [])
        self.assertFalse([w for w in warnings(self, "--cycle", "alpha") if "done_commit" in w])

    def test_rebind_refusals(self):
        code, _, err = self.fx.rite("rebind", "ALP-TASK-01", "--sha", "HEAD")
        self.assertEqual(code, 1)
        self.assertIn("rebind is for done or stale items", err)


if __name__ == "__main__":
    unittest.main()
