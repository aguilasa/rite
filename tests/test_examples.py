"""Every example must be a valid Rite repository and carry a usable e2e manifest (no tokens spent)."""

import json
import re
import shutil
import sys
import unittest
from pathlib import Path

from fixtures import ROOT, rite

sys.path.insert(0, str(ROOT / "tests" / "e2e"))
import _example as example  # noqa: E402

EXAMPLES = ROOT / "examples"
REQUIRED = ("name", "cycle", "prefix", "plan", "gate", "read_only_probe", "defect")
DEFECT_REQUIRED = ("file_glob", "symptom_command", "good_output", "bad_output")


def example_dirs() -> list[Path]:
    return sorted(p for p in EXAMPLES.iterdir() if p.is_dir())


class ExamplesTest(unittest.TestCase):
    def test_there_are_examples(self):
        self.assertTrue(example_dirs(), "examples/ is empty")

    def test_each_example_is_clean_and_self_describing(self):
        for directory in example_dirs():
            with self.subTest(example=directory.name):
                code, out, _ = rite(directory, "check", "--all", "--json")
                data = json.loads(out)
                self.assertEqual(code, 0, f"rite check: {data.get('findings')}")
                self.assertEqual((data["errors"], data["warnings"]), (0, 0), data.get("findings"))

                manifest_path = directory / "e2e.json"
                self.assertTrue(manifest_path.is_file(), "missing e2e.json")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for key in REQUIRED:
                    self.assertIn(key, manifest)
                for key in DEFECT_REQUIRED:
                    self.assertIn(key, manifest["defect"])

                self.assertTrue((directory / manifest["plan"].lstrip("/")).is_file(), manifest["plan"])
                self.assertTrue((directory / manifest["read_only_probe"]).is_file(), manifest["read_only_probe"])
                self.assertTrue(manifest["gate"].strip(), "gate is empty")
                glob = manifest["defect"]["file_glob"]
                self.assertTrue((directory / glob).parent.is_dir(), f"{glob}: parent directory missing")
                edits = manifest["defect"].get("candidates") or [manifest["defect"]]
                for edit in edits:
                    self.assertIn("find", edit)
                    self.assertIn("replace", edit)
                    self.assertNotEqual(edit["find"], edit["replace"])

    def test_manifest_matches_the_shipped_cycle(self):
        for directory in example_dirs():
            with self.subTest(example=directory.name):
                manifest = json.loads((directory / "e2e.json").read_text(encoding="utf-8"))
                code, out, _ = rite(directory, "resolve-cycle", manifest["cycle"], "--json")
                self.assertEqual(code, 0, out)
                info = json.loads(out)
                self.assertEqual(info["prefix"], manifest["prefix"])
                self.assertTrue(info["profile_exists"], info["profile"])
                self.assertEqual(info.get("plan"), "/" + manifest["plan"].lstrip("/"))

    def test_seeding_data_is_complete(self):
        for directory in example_dirs():
            manifest = json.loads((directory / "e2e.json").read_text(encoding="utf-8"))
            if "defects" not in manifest:
                continue
            with self.subTest(example=directory.name):
                solution = manifest["solution"]
                for task in solution["tasks"].values():
                    for rel in task["files"]:
                        source = directory / solution["dir"] / (rel + solution.get("suffix", ""))
                        self.assertTrue(source.is_file(), source)
                touched = []
                for defect in manifest["defects"]:
                    for key in (*DEFECT_REQUIRED, "title", "severity", "origin", "files", "candidates"):
                        self.assertIn(key, defect, defect.get("title"))
                    self.assertIn(defect["origin"], solution["tasks"])
                    touched += defect["files"]
                # one wave: the slope of the experiment must not also count waves
                self.assertEqual(len(touched), len(set(touched)), "two defects share a file")

    @unittest.skipUnless(shutil.which("node") and shutil.which("git"), "needs node and git")
    def test_node_minimal_seeds_open_fixes_without_a_model(self):
        tmp, repo, manifest = example.make_repo("node-minimal", strip=("e2e", "e2e.json"))
        try:
            self.assertFalse((repo / "e2e.json").exists())
            self.assertEqual(example.seed_done(repo, manifest, "node-minimal"),
                             ["SLG-TASK-01", "SLG-TASK-02"])
            defects = example.defect_list(manifest)
            for defect in defects:
                self.assertIsNotNone(example.apply_defect(repo, defect), defect["title"])
            self.assertEqual(len(example.seed_fixes(repo, manifest, defects)), len(defects))
            self.assertEqual(example.open_fixes(repo, manifest["cycle"]), len(defects))
            self.assertEqual(example.rite(repo, "check", "--all")[0], 0)
            plan = example.rite_json(repo, "batch-plan", "all", "--kind", "fix", "--cycle", manifest["cycle"])
            self.assertEqual(len(plan["waves"]), 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_the_residue_defect_prints_past_the_inline_limit(self):
        """Control for the lifecycle's residue step: without a model, the planted fix is over the
        limit a fresh `rite.toml` gets, and the same command prints the good output without the defect."""
        raw = json.loads((EXAMPLES / "python-minimal" / "e2e.json").read_text(encoding="utf-8"))
        for key in (*DEFECT_REQUIRED, "title", "severity", "find", "replace"):
            self.assertIn(key, raw["residue_defect"])
        template = (ROOT / "templates" / "rite.toml").read_text(encoding="utf-8")
        limit_kb = int(re.search(r"(?m)^inline_triage_max_output_kb\s*=\s*(\d+)", template).group(1))
        tmp, repo, manifest = example.make_repo("python-minimal")
        big = manifest["residue_defect"]
        try:
            # the lifecycle's tasks write slugify; a stand-in to the plan's contract does here
            (repo / "textkit" / "__init__.py").write_text(
                "import re\n\n\ndef slugify(text):\n"
                "    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')\n", encoding="utf-8")
            example.sh(repo, "git", "commit", "-qam", "feat: slugify")
            self.assertEqual(example.symptom_of(repo, big), big["good_output"])
            planted = example.apply_defect(repo, big)
            self.assertIsNotNone(planted)
            origin = example.rite_json(repo, "next", "task", "--cycle", manifest["cycle"])["id"]
            fix_id = example.seed_fix(repo, big, origin, planted)
            fix = example.rite_json(repo, "reproduce", fix_id, "--cycle", manifest["cycle"])["fixes"][0]
            self.assertEqual((fix["runnable"], fix["why"]), (True, "ok"))
            self.assertNotEqual(fix["commands"][0]["exit_code"], 0)
            self.assertFalse(fix["commands"][0]["shell_error"])
            self.assertGreater(fix["held_bytes"], limit_kb * 1024)
            self.assertTrue(fix["over_limit"])
            self.assertEqual(example.rite(repo, "check", "--all")[0], 0)
            self.assertEqual(example.sh(repo, "git", "status", "--porcelain").strip(), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_read_only_probe_is_guarded(self):
        for directory in example_dirs():
            with self.subTest(example=directory.name):
                manifest = json.loads((directory / "e2e.json").read_text(encoding="utf-8"))
                code, out, _ = rite(directory, "guard", manifest["read_only_probe"], "--json")
                self.assertEqual(code, 1, f"{manifest['read_only_probe']} is not guarded: {out}")
                self.assertEqual(json.loads(out)["kind"], "read_only")


if __name__ == "__main__":
    unittest.main()
