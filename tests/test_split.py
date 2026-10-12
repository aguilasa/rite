"""Split layout: rite.toml and Rite's documents in their own git repository, the work in repositories
outside it named in `[repos]`."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fixtures import PLAN, ROOT, add_item, fields, git, rite, write

from rite_lib import config, guard

TOML = '''
[project]
name = "split"
[paths]
default_repo = "code"
[repos]
code = "../code"
[guards]
read_only = ["vendor/**"]
'''


def init(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "user.name", "Rite Test")
    git(path, "config", "user.email", "rite@example.invalid")
    git(path, "config", "commit.gpgsign", "false")


class SplitCase(unittest.TestCase):
    toml = TOML

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="rite-split-")
        self.base = Path(self._tmp.name).resolve()
        self.docs, self.code = self.base / "docs", self.base / "code"
        init(self.docs)
        write(self.docs / "rite.toml", self.toml)
        write(self.docs / "docs/plans/plan-name.md", PLAN)
        git(self.docs, "add", "-A")
        git(self.docs, "commit", "-q", "-m", "chore: init docs")
        init(self.code)
        self.commit("README.md", "# code\n", "chore: init code")

    def tearDown(self):
        with contextlib.suppress(PermissionError):
            self._tmp.cleanup()

    def rite(self, *args: str) -> tuple[int, str, str]:
        return rite(self.docs, *args)

    def js(self, *args: str) -> dict:
        code, out, err = self.rite(*args, "--json")
        self.assertEqual(code, 0, f"rite {' '.join(args)} failed: {err}{out}")
        return json.loads(out)

    def commit(self, rel: str, content: str, message: str, repo: Path | None = None) -> str:
        repo = repo or self.code
        write(repo / rel, content)
        git(repo, "add", "--", rel)
        git(repo, "commit", "-q", "-m", message)
        return git(repo, "rev-parse", "--short", "HEAD").strip()

    def log(self, repo: Path) -> list[str]:
        return git(repo, "log", "--format=%s").splitlines()

    def new_cycle(self, *extra: str) -> None:
        self.js("new-cycle", "demo", "--prefix", "DEMO", "--plan", "docs/plans/plan-name.md", "--commit", *extra)
        self.js("new-task", "--cycle", "demo", "--title", "Code task", "--type", "feature", "--phase", "1",
                "--source-of-truth", "/docs/plans/plan-name.md#1")
        self.js("new-task", "--cycle", "demo", "--title", "Docs task", "--type", "feature", "--phase", "1",
                "--source-of-truth", "/docs/plans/plan-name.md#1", "--repo", ".")
        git(self.docs, "add", "-A")
        git(self.docs, "commit", "-q", "-m", "chore(rite): tasks")

    def findings(self, level: str) -> list[str]:
        _, out, _ = self.rite("check", "--cycle", "demo", "--json")
        return [f"{f['path']}: {f['message']}" for f in json.loads(out)["findings"] if f["level"] == level]

    def task_file(self, n: int) -> Path:
        return next((self.docs / "docs/rite/cycles/demo").glob(f"0{n}-*.md"))


class SplitTest(SplitCase):
    def test_resolve_cycle_reports_the_layout(self):
        self.new_cycle()
        res = self.js("resolve-cycle", "demo")
        self.assertEqual((res["workspace"], res["local"], res["split"], res["repos"], res["default_repo"]),
                         (False, False, True, ["code"], "code"))
        self.assertEqual(res["repo_dirs"], {"code": self.code.as_posix()})
        begin = self.js("begin", "task", "--cycle", "demo", "--id", "DEMO-TASK-01")
        self.assertEqual(begin["item"]["repo_dir"], self.code.as_posix())
        self.assertEqual(begin["commit"]["repo_dir"], self.code.as_posix())

    def test_new_cycle_commits_in_the_docs_repository_only(self):
        before = self.log(self.code)
        res = self.js("new-cycle", "demo", "--prefix", "DEMO", "--commit")
        self.assertEqual(res["local"], False)
        self.assertTrue(res["commit"])
        self.assertTrue(self.log(self.docs)[0].startswith("chore(rite):"))
        self.assertEqual(self.log(self.code), before)

    def test_new_items_record_their_repository(self):
        self.new_cycle()
        self.assertEqual(fields(self.task_file(1))["repo"], "code")
        self.assertEqual(fields(self.task_file(2))["repo"], ".")
        fix = self.js("new-fix", "--cycle", "demo", "--origin", "DEMO-TASK-02", "--title", "late",
                      "--severity", "low")
        self.assertEqual(fields(self.docs / fix["path"])["repo"], ".")  # inherited from the origin
        code, _, err = self.rite("new-task", "--cycle", "demo", "--title", "X", "--type", "feature", "--phase",
                                 "1", "--source-of-truth", "/docs/plans/plan-name.md#1", "--repo", "nope")
        self.assertEqual(code, 1)
        self.assertIn("not a git repository", err)

    def test_commit_refs_leave_the_item_id_out_of_external_repositories(self):
        self.new_cycle("--ticket", "PROJ-9")
        refs = self.js("commit-refs", "DEMO-TASK-01")
        self.assertEqual((refs["repo"], refs["external"], refs["trailers"]), ("code", True, ["Refs: PROJ-9"]))
        refs = self.js("commit-refs", "DEMO-TASK-02")
        self.assertEqual((refs["external"], refs["trailers"]), (False, ["Refs: DEMO-TASK-02", "Refs: PROJ-9"]))
        _, out, _ = self.rite("commit-refs", "DEMO-TASK-01")
        self.assertIn("no Refs to the item", out)

    def test_close_reads_the_code_commit_and_books_in_docs(self):
        self.new_cycle()
        sha = self.commit("src/a.py", "a\n", "feat: code side")
        code_log = self.log(self.code)
        data = self.js("finish", "DEMO-TASK-01", "--cycle", "demo")
        self.assertEqual((data["closed"]["repo"], data["closed"]["done_commit"]), ("code", sha))
        self.assertEqual(self.log(self.docs)[0], "chore(rite): close DEMO-TASK-01")
        self.assertEqual(self.log(self.code), code_log)  # nothing of Rite's landed in the product
        self.assertIn("git -C ../code show --name-status", self.task_file(1).read_text(encoding="utf-8"))
        self.assertEqual(git(self.code, "status", "--porcelain"), "")
        self.assertEqual(data["check"]["errors"], [])
        self.assertEqual(self.js("mark-reviewed", "DEMO-TASK-01")["review_commit"], sha)
        self.assertEqual([e for e in self.findings("error") if "phase" not in e], [])

    def test_docs_task_closes_on_a_docs_commit(self):
        self.new_cycle()
        sha = self.commit("docs/notes.md", "n\n", "docs: notes", repo=self.docs)
        data = self.js("close", "DEMO-TASK-02")
        self.assertEqual((data["repo"], data["done_commit"]), (".", sha))
        self.assertNotIn("git -C", self.task_file(2).read_text(encoding="utf-8"))

    def test_gates_and_reproduce_run_in_the_code_repository(self):
        self.new_cycle()
        self.commit("marker-only-here", "x\n", "chore: marker")
        write(self.docs / "rite.toml", self.toml + '[gates]\nglobal = ["test -f marker-only-here"]\n')
        for extra in ((), ("--id", "DEMO-TASK-01")):
            data = self.js("gates", "--cycle", "demo", *extra)
            if data["shell"] == "system":
                self.skipTest("no bash on this machine")
            self.assertEqual((data["where"], data["passed"]), (self.code.as_posix(), True), data)
        fix = self.js("new-fix", "--cycle", "demo", "--origin", "DEMO-TASK-01", "--title", "broken",
                      "--severity", "low")
        path = self.docs / fix["path"]
        text = path.read_text(encoding="utf-8")
        evidence = "## Evidence\n\n```text\n$ test -f marker-only-here && echo present\npresent\n```\n"
        path.write_text(text.replace("## Evidence", evidence, 1) if "## Evidence" in text else text + evidence,
                        encoding="utf-8")
        for extra in ((), ("--scratch",)):
            data = self.js("reproduce", fix["id"], *extra)
            [result] = data["fixes"]
            [run] = result["commands"]
            self.assertEqual((run["exit_code"], run["output"]), (0, "present"), result)

    def test_push_after_each_item_pushes_both_repositories(self):
        self.new_cycle()
        with tempfile.TemporaryDirectory() as bare_docs, tempfile.TemporaryDirectory() as bare_code:
            for repo, bare in ((self.docs, bare_docs), (self.code, bare_code)):
                subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
                git(repo, "remote", "add", "origin", bare)
                git(repo, "push", "-q", "-u", "origin", "HEAD")
            write(self.docs / "rite.toml", self.toml + '[commit]\npush = "after-each-item"\n')
            git(self.docs, "commit", "-q", "-am", "chore: push")
            self.commit("src/a.py", "a\n", "feat: code side")
            data = self.js("finish", "DEMO-TASK-01", "--cycle", "demo")
            self.assertEqual([p["ok"] for p in data["pushed"]], [True, True])
            self.assertEqual(len(data["pushed"]), 2)

    def test_batch_plan_compares_resolved_repositories(self):
        self.new_cycle()
        self.js("new-task", "--cycle", "demo", "--title", "Third", "--type", "feature", "--phase", "1",
                "--source-of-truth", "/docs/plans/plan-name.md#1")
        for n in (1, 2, 3):
            self.js("set", f"DEMO-TASK-0{n}", "--files", "src/main.py")
        # an item written before default_repo existed names no repo: it is the default one all the same
        from fixtures import set_fields
        entry = fields(self.task_file(3))
        set_fields(self.task_file(3), {**entry, "repo": None})
        plan = self.js("batch-plan", "--cycle", "demo", "3")
        waves = plan["waves"]
        wave_of = {i: n for n, w in enumerate(waves) for i in w}
        self.assertNotEqual(wave_of["DEMO-TASK-01"], wave_of["DEMO-TASK-03"])  # same file, same repository
        self.assertEqual(wave_of["DEMO-TASK-01"], wave_of["DEMO-TASK-02"])  # same path, other repository

    def test_check_reports_bad_repositories(self):
        self.new_cycle()
        self.assertEqual([e for e in self.findings("error") if "phase" not in e], [])
        write(self.docs / "rite.toml", TOML.replace('code = "../code"', 'code = "../code"\nghost = "../ghost"\n'
                                                     'plain = "../plain"'))
        (self.base / "plain").mkdir()
        errors = self.findings("error")
        self.assertTrue(any("[repos].ghost" in e and "does not exist" in e for e in errors), errors)
        self.assertTrue(any("[repos].plain" in e and "not a git repository" in e for e in errors), errors)
        write(self.docs / "rite.toml", TOML.replace('default_repo = "code"', 'default_repo = "nope"'))
        self.assertTrue(any("default_repo" in e for e in self.findings("error")))

    def test_check_flags_a_bad_done_commit_in_the_code_repository(self):
        self.new_cycle()
        self.commit("src/a.py", "a\n", "feat: code side")
        self.js("close", "DEMO-TASK-01")
        from fixtures import set_fields
        set_fields(self.task_file(1), {"done_commit": "abcdef1"})
        self.assertTrue(any("abcdef1" in e and "code" in e for e in self.findings("error")))

    def test_check_warns_when_the_docs_sit_inside_the_code_repository(self):
        nested = self.code / "rite-docs"
        shutil.copytree(self.docs, nested)
        write(nested / "rite.toml", TOML.replace('"../code"', '".."'))
        git(self.code, "add", "-A")
        git(self.code, "commit", "-q", "-m", "chore: docs inside")
        _, out, _ = rite(nested, "check", "--json")
        warns = [f["message"] for f in json.loads(out)["findings"] if f["level"] == "warn"]
        self.assertTrue(any("tracks Rite's documents" in w for w in warns), warns)

    def test_guard_matches_paths_inside_the_code_repository(self):
        cfg = config.load(self.docs)
        verdict = guard.classify(cfg, self.code / "vendor/lib.js")
        self.assertEqual((verdict["blocked"], verdict["path"]), (True, "code:vendor/lib.js"))
        self.assertFalse(guard.classify(cfg, self.code / "src/app.py")["blocked"])
        self.assertFalse(guard.classify(cfg, self.base / "elsewhere/vendor/x")["blocked"])
        self.assertTrue(guard.classify(cfg, self.docs / "vendor/x")["blocked"])
        self.js("new-cycle", "demo", "--prefix", "DEMO")
        self.assertEqual(guard.classify(cfg, self.docs / "docs/rite/cycles/demo/progress.json")["kind"], "state")
        self.assertIsNone(guard.classify(cfg, self.code / "docs/rite/cycles/demo/progress.json")["kind"])

    def test_guard_hook_follows_the_session_into_the_code_repository(self):
        ev = {"cwd": str(self.code), "tool_name": "Write", "tool_input": {"file_path": "vendor/lib.js"}}
        hook = [sys.executable, str(ROOT / "hooks" / "guard.py")]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        res = subprocess.run(hook, input=json.dumps(ev), capture_output=True, text=True, env=env)
        self.assertEqual(res.returncode, 0)  # no rite.toml from the code repository, no project folder
        res = subprocess.run(hook, input=json.dumps(ev), capture_output=True, text=True,
                             env={**env, "CLAUDE_PROJECT_DIR": str(self.docs)})
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("code:vendor/lib.js", res.stderr)


class SplitConfigTest(unittest.TestCase):
    def bad(self, text: str) -> str:
        with self.assertRaises(config.ConfigError) as ctx:
            config.parse(Path("/tmp/x"), text)
        return str(ctx.exception)

    def test_invalid_repos(self):
        self.assertIn("[repos] must be a table", self.bad('repos = "x"'))
        self.assertIn("[repos].code must be the path", self.bad("[repos]\ncode = 3"))
        self.assertIn("[repos].code must be the path", self.bad('[repos]\ncode = ""'))
        self.assertIn("[repos]..", self.bad('[repos]\n"." = "../x"'))
        self.assertIn("[repos].a/b", self.bad('[repos]\n"a/b" = "../x"'))
        self.assertIn("default_repo", self.bad("[paths]\ndefault_repo = 3"))
        self.assertIn("unknown key", self.bad("[paths]\ndefault_repos = 'x'"))

    def test_repo_paths(self):
        cfg = config.parse(Path("/a/b"), '[repos]\nrel = "../c"\nabs = "/d/e"\nhome = "~/f"\n')
        self.assertEqual(cfg.repo_paths(), {"rel": Path("/a/c"), "abs": Path("/d/e"),
                                            "home": (Path.home() / "f").resolve()})
        self.assertEqual(config.parse(Path("/a"), "").repo_paths(), {})


class WorkspaceWithReposTest(unittest.TestCase):
    def test_an_external_repository_in_a_workspace(self):
        with tempfile.TemporaryDirectory(prefix="rite-ws-repos-") as tmp:
            base = Path(tmp).resolve()
            ws, ext = base / "ws", base / "ext"
            write(ws / "rite.toml", '[repos]\next = "../ext"\n')
            init(ws / "api")
            for repo in (ws / "api", ext):
                init(repo)
                write(repo / "README.md", "x\n")
                git(repo, "add", "-A")
                git(repo, "commit", "-q", "-m", "chore: init")
            code, out, err = rite(ws, "new-cycle", "demo", "--prefix", "DEMO", "--json")
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["local"])
            code, out, err = rite(ws, "new-task", "--cycle", "demo", "--title", "T", "--type", "feature",
                                  "--phase", "1", "--source-of-truth", "/x.md#1", "--repo", "ext", "--json")
            self.assertEqual(code, 0, err)
            res = json.loads(rite(ws, "resolve-cycle", "demo", "--json")[1])
            self.assertEqual((res["workspace"], res["split"], res["repos"]), (True, False, ["ext", "api"]))
            write(ext / "src/a.py", "a\n")
            git(ext, "add", "-A")
            git(ext, "commit", "-q", "-m", "feat: ext")
            code, out, err = rite(ws, "close", "DEMO-TASK-01", "--json")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["commit"], None)  # a workspace's cycle stays local
            refs = json.loads(rite(ws, "commit-refs", "DEMO-TASK-01", "--json")[1])
            self.assertEqual(refs["trailers"], [])


if __name__ == "__main__":
    unittest.main()
