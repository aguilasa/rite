"""Every example must be a valid Rite repository and carry a usable e2e manifest (no tokens spent)."""

import json
import unittest
from pathlib import Path

from fixtures import ROOT, rite

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

    def test_read_only_probe_is_guarded(self):
        for directory in example_dirs():
            with self.subTest(example=directory.name):
                manifest = json.loads((directory / "e2e.json").read_text(encoding="utf-8"))
                code, out, _ = rite(directory, "guard", manifest["read_only_probe"], "--json")
                self.assertEqual(code, 1, f"{manifest['read_only_probe']} is not guarded: {out}")
                self.assertEqual(json.loads(out)["kind"], "read_only")


if __name__ == "__main__":
    unittest.main()
