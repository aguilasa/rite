"""What the single-repository and workspace layouts do today, pinned before repositories could live
outside the root. A failure here is a regression of an existing layout, never a test to adjust."""

import json
import subprocess
import sys
import tempfile
import unittest

from fixtures import ROOT, Fixture, fields, git, write

from test_workspace import WorkspaceCase

RESOLVE_KEYS = {"cycle", "path", "prefix", "progress", "fixes", "progress_state", "fixes_state", "profile",
                "profile_exists", "pitfalls", "pitfalls_exists", "plan", "archived", "ticket", "local", "commit",
                "workspace", "repos"}
BEGIN_KEYS = {"cycle", "kind", "reason", "taken", "paths", "prefix", "ticket", "local", "workspace", "repos",
              "item", "commit", "config", "repo_kb", "next_step"}
REFS_KEYS = {"local", "ticket", "repo", "subject_template", "trailers", "co_author_footer"}


class SingleRepoLayout(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def js(self, *args) -> dict:
        code, out, err = self.fx.rite(*args, "--json")
        self.assertEqual(code, 0, f"rite {' '.join(args)} failed: {err}{out}")
        return json.loads(out)

    def test_resolve_cycle_and_begin_report_no_repositories(self):
        res = self.js("resolve-cycle", "alpha")
        self.assertLessEqual(RESOLVE_KEYS, set(res))
        self.assertEqual((res["workspace"], res["local"], res["repos"]), (False, False, []))
        begin = self.js("begin", "task", "--cycle", "alpha")
        self.assertLessEqual(BEGIN_KEYS, set(begin))
        self.assertEqual((begin["workspace"], begin["repos"]), (False, []))
        self.assertLessEqual(REFS_KEYS, set(begin["commit"]))
        self.assertEqual((begin["commit"]["repo"], begin["commit"]["trailers"]), (None, ["Refs: ALP-TASK-01"]))

    def test_commit_refs_keep_the_item_ref(self):
        refs = self.js("commit-refs", "ALP-TASK-01")
        self.assertEqual((refs["local"], refs["repo"], refs["subject_template"], refs["trailers"]),
                         (False, None, "{subject}", ["Refs: ALP-TASK-01"]))

    def test_new_task_and_fix_write_no_repo(self):
        res = self.js("new-task", "--cycle", "alpha", "--title", "Extra", "--type", "feature", "--phase", "1",
                      "--source-of-truth", "/docs/plans/PLAN-alpha.md#1")
        self.assertNotIn("repo", fields(self.root / res["path"]))
        fix = self.js("new-fix", "--cycle", "alpha", "--origin", "ALP-TASK-01", "--title", "late",
                      "--severity", "low")
        self.assertNotIn("repo", fields(self.root / fix["path"]))

    def test_close_logs_plain_git_and_commits_bookkeeping_in_the_root(self):
        sha = self.fx.work_commit("src/a.py", "a\n", "feat: harness")
        res = self.js("close", "ALP-TASK-01")
        self.assertEqual((res["repo"], res["done_commit"]), (None, sha))
        text = (self.root / "docs/rite/cycles/alpha/01-harness.md").read_text(encoding="utf-8")
        self.assertIn("(`git show --name-status", text)
        self.assertNotIn("git -C", text)
        self.assertEqual(self.fx.git("log", "-1", "--format=%s").strip(), "chore(rite): close ALP-TASK-01")

    def test_gates_run_in_the_root(self):
        write(self.root / "marker-only-here", "x\n")
        cfg = self.root / "rite.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + '\n[gates]\nglobal = ["test -f marker-only-here"]\n',
                       encoding="utf-8", newline="\n")
        for extra in ((), ("--id", "ALP-TASK-01")):
            data = self.js("gates", "--cycle", "alpha", *extra)
            if data["shell"] == "system":
                self.skipTest("no bash on this machine")
            self.assertEqual((data["where"], data["passed"]), (".", True), data)

    def test_guard_matches_relative_to_the_root_only(self):
        self.assertEqual(self.fx.rite("guard", "vendor/x.js")[0], 1)
        self.assertEqual(self.fx.rite("guard", str(self.root / "vendor/x.js"))[0], 1)
        with tempfile.TemporaryDirectory() as other:
            code, out, _ = self.fx.rite("guard", f"{other}/vendor/x.js", "--json")
            self.assertEqual((code, json.loads(out)["blocked"]), (0, False))
        state_file = "docs/rite/cycles/alpha/progress.json"
        code, out, _ = self.fx.rite("guard", state_file, "--json")
        self.assertEqual((code, json.loads(out)["kind"]), (1, "state"))

    def test_batch_plan_conflicts_on_a_shared_path(self):
        for n in (1, 2):
            self.js("set", f"ALP-TASK-0{n}", "--files", "src/app.py", "--depends-on", "")
        plan = self.js("batch-plan", "--cycle", "alpha", "2")
        self.assertEqual(plan["waves"], [["ALP-TASK-01"], ["ALP-TASK-02"]])
        self.assertEqual([i["repo"] for i in plan["items"]], [None, None])

    def test_finish_pushes_the_root_once(self):
        with tempfile.TemporaryDirectory() as bare:
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            self.fx.git("remote", "add", "origin", bare)
            self.fx.git("push", "-q", "-u", "origin", "HEAD")
            cfg = self.root / "rite.toml"
            cfg.write_text(cfg.read_text(encoding="utf-8") + '\n[commit]\npush = "after-each-item"\n',
                           encoding="utf-8")
            self.fx.git("commit", "-q", "-am", "chore: push")
            self.fx.work_commit("src/a.py", "a\n", "feat: harness")
            data = self.js("finish", "ALP-TASK-01", "--cycle", "alpha")
            self.assertEqual(data["pushed"], [{"repo": ".", "ok": True, "error": None, "skipped": None}])

    def test_check_is_clean(self):
        code, out, _ = self.fx.rite("check", "--cycle", "alpha", "--json")
        self.assertEqual([f for f in json.loads(out)["findings"] if f["level"] == "error"], [])

    def test_guard_hook_from_a_folder_without_config_is_inert(self):
        env = {k: v for k, v in __import__("os").environ.items() if k != "CLAUDE_PROJECT_DIR"}
        with tempfile.TemporaryDirectory() as tmp:
            ev = {"cwd": tmp, "tool_name": "Write", "tool_input": {"file_path": str(self.root / "vendor/x")}}
            res = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")], input=json.dumps(ev),
                                 capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(res.returncode, 0, res.stderr)


class WorkspaceLayout(WorkspaceCase):
    def test_resolve_cycle_shape(self):
        self.new_cycle()
        res = self.js("resolve-cycle", "demo")
        self.assertLessEqual(RESOLVE_KEYS, set(res))
        self.assertEqual(res["repos"], ["api", "web"])
        begin = self.js("begin", "task", "--cycle", "demo")
        self.assertEqual((begin["workspace"], begin["local"], begin["repos"]), (True, True, ["api", "web"]))
        self.assertEqual((begin["commit"]["repo"], begin["commit"]["trailers"]), ("api", ["Refs: PROJ-1"]))

    def test_gates_run_in_the_item_repository(self):
        self.new_cycle()
        self.commit("api", "marker-only-here", "x\n", "chore: marker")
        write(self.root / "rite.toml", '[project]\nname = "workspace"\n[gates]\nglobal = ["test -f marker-only-here"]\n')
        data = self.js("gates", "--cycle", "demo", "--id", "DEMO-TASK-01")
        if data["shell"] == "system":
            self.skipTest("no bash on this machine")
        self.assertEqual((data["where"], data["passed"]), ("api", True), data)
        code, out, _ = self.rite("gates", "--cycle", "demo", "--id", "DEMO-TASK-02", "--json")
        self.assertEqual((code, json.loads(out)["where"]), (1, "web"))

    def test_finish_of_a_local_cycle_pushes_nothing(self):
        self.new_cycle()
        with tempfile.TemporaryDirectory() as bare:
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
            git(self.root / "api", "remote", "add", "origin", bare)
            git(self.root / "api", "push", "-q", "-u", "origin", "HEAD")
            write(self.root / "rite.toml", '[project]\nname = "workspace"\n[commit]\npush = "after-each-item"\n')
            self.commit("api", "src/a.py", "a\n", "feat: api side")
            data = self.js("finish", "DEMO-TASK-01", "--cycle", "demo")
            # a push follows a bookkeeping commit, and a local cycle makes none
            self.assertEqual((data["closed"]["commit"], data["pushed"]), (None, []))

    def test_check_without_repositories_is_bare(self):
        for repo in ("api", "web"):
            __import__("shutil").rmtree(self.root / repo)
        self.js("new-cycle", "demo", "--prefix", "DEMO")
        _, out, _ = self.rite("check", "--cycle", "demo", "--json")
        self.assertEqual([f for f in json.loads(out)["findings"] if f["level"] == "error"], [])
        self.assertEqual(self.js("resolve-cycle", "demo")["repos"], [])


if __name__ == "__main__":
    unittest.main()
