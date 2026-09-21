"""Workspace mode: rite.toml in a plain folder whose sub-folders are git repositories."""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from fixtures import PLAN, git, rite, write

from test_cli import fields


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-workspace-")
        self.root = Path(self._tmp.name).resolve()
        write(self.root / "rite.toml", '[project]\nname = "workspace"\n')
        write(self.root / "docs/plans/plan-name.md", PLAN)
        for repo in ("api", "web"):
            path = self.root / repo
            path.mkdir()
            git(path, "init", "-q")
            git(path, "config", "user.name", "Rite Test")
            git(path, "config", "user.email", "rite@example.invalid")
            git(path, "config", "commit.gpgsign", "false")
            self.commit(repo, "README.md", f"# {repo}\n", "chore: init")

    def tearDown(self):
        with contextlib.suppress(PermissionError):
            self._tmp.cleanup()

    def rite(self, *args: str) -> tuple[int, str, str]:
        return rite(self.root, *args)

    def js(self, *args: str) -> dict:
        code, out, err = self.rite(*args, "--json")
        self.assertEqual(code, 0, f"rite {' '.join(args)} failed: {err}{out}")
        return json.loads(out)

    def commit(self, repo: str, rel: str, content: str, message: str) -> str:
        write(self.root / repo / rel, content)
        git(self.root / repo, "add", "--", rel)
        git(self.root / repo, "commit", "-q", "-m", message)
        return git(self.root / repo, "rev-parse", "--short", "HEAD").strip()

    def log(self, repo: str) -> list[str]:
        return git(self.root / repo, "log", "--format=%s").splitlines()

    def new_cycle(self) -> None:
        res = self.js("new-cycle", "demo", "--prefix", "DEMO", "--plan", "docs/plans/plan-name.md",
                      "--ticket", "PROJ-1", "--commit")
        self.assertEqual((res["local"], res["commit"]), (True, None))  # no repository to commit to
        for n, repo in ((1, "api"), (2, "web")):
            self.js("new-task", "--cycle", "demo", "--title", f"Task {n}", "--type", "feature", "--phase", "1",
                    "--source-of-truth", "/docs/plans/plan-name.md#1", "--repo", repo)

    def check(self) -> tuple[list[str], list[str]]:
        _, out, _ = self.rite("check", "--cycle", "demo", "--json")
        data = json.loads(out)
        pick = lambda lvl: [f"{f['path']}: {f['message']}" for f in data["findings"] if f["level"] == lvl]  # noqa
        return pick("error"), pick("warn")


class WorkspaceTest(WorkspaceCase):
    def test_resolve_cycle_reports_the_workspace(self):
        self.new_cycle()
        res = self.js("resolve-cycle", "demo")
        self.assertEqual((res["workspace"], res["local"], res["repos"]), (True, True, ["api", "web"]))
        refs = self.js("commit-refs", "DEMO-TASK-02")
        self.assertEqual((refs["repo"], refs["trailers"]), ("web", ["Refs: PROJ-1"]))

    def test_loop_reads_each_task_commit_in_its_own_repository(self):
        self.new_cycle()
        before = {r: self.log(r) for r in ("api", "web")}
        api_sha = self.commit("api", "src/a.py", "a\n", "feat: api side")
        web_sha = self.commit("web", "src/w.ts", "w\n", "feat: web side")

        res = self.js("close", "DEMO-TASK-01")
        self.assertEqual((res["repo"], res["done_commit"], res["commit"]), ("api", api_sha, None))
        self.js("close", "DEMO-TASK-02")
        t1 = self.root / "docs/rite/cycles/demo/01-task-1.md"
        self.assertEqual(fields(t1)["done_commit"], api_sha)
        self.assertEqual(fields(self.root / "docs/rite/cycles/demo/02-task-2.md")["done_commit"], web_sha)
        self.assertIn("git -C api show --name-status", t1.read_text(encoding="utf-8"))
        # the repositories got the work commits only
        self.assertEqual(self.log("api"), ["feat: api side", *before["api"]])
        self.assertEqual(self.log("web"), ["feat: web side", *before["web"]])

        review = self.js("mark-reviewed", "DEMO-TASK-01")
        self.assertEqual(review["review_commit"], api_sha)  # HEAD of the task's repository
        errors, warns = self.check()
        self.assertEqual([e for e in errors if "phase" not in e], [])

        fix = self.js("new-fix", "--cycle", "demo", "--origin", "DEMO-TASK-01", "--title", "late",
                      "--severity", "low")
        self.assertEqual(fields(self.root / fix["path"])["repo"], "api")  # inherited from the origin

    def test_refusals_and_check(self):
        self.js("new-cycle", "demo", "--prefix", "DEMO")
        code, _, err = self.rite("new-task", "--cycle", "demo", "--title", "X", "--type", "feature",
                                 "--phase", "1", "--source-of-truth", "/docs/plans/plan-name.md#1")
        self.assertEqual(code, 1)
        self.assertIn("pass --repo", err)
        self.assertIn("api, web", err)
        code, _, err = self.rite("new-task", "--cycle", "demo", "--title", "X", "--type", "feature",
                                 "--phase", "1", "--source-of-truth", "/docs/plans/plan-name.md#1", "--repo", "docs")
        self.assertEqual(code, 1)
        self.assertIn("not a git repository", err)
        code, _, err = self.rite("publish", "demo")
        self.assertEqual(code, 1)
        self.assertIn("no repository to publish", err)

        # a hand-written task without repo: check names the repositories to choose from
        path = self.root / "docs/rite/cycles/demo/01-manual.md"
        write(path, "---\nid: DEMO-TASK-01\ntitle: Manual\ntype: feature\nphase: 1\ndepends_on: []\n"
                    "source_of_truth: /docs/plans/plan-name.md#1\nstatus: pending\ndone_on: null\n"
                    "done_commit: null\nreviewed_on: null\n---\n\n# DEMO-TASK-01 — Manual\n")
        self.rite("sync", "--cycle", "demo")
        errors, _ = self.check()
        self.assertTrue(any("has no 'repo:'" in e and "api, web" in e for e in errors), errors)

    def test_batch_plan_ignores_same_paths_in_different_repositories(self):
        self.new_cycle()
        for n in (1, 2):
            path = next((self.root / "docs/rite/cycles/demo").glob(f"0{n}-*.md"))
            text = path.read_text(encoding="utf-8").replace("files: []", "files: [src/main.py]")
            path.write_text(text, encoding="utf-8", newline="\n")
        plan = self.js("batch-plan", "--cycle", "demo", "2")
        self.assertEqual(plan["waves"], [["DEMO-TASK-01", "DEMO-TASK-02"]])
        self.assertEqual([i["repo"] for i in plan["items"]], ["api", "web"])


if __name__ == "__main__":
    unittest.main()
