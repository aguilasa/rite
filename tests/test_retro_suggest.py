"""`rite retro-suggest`: Keep / Promote / Prune candidates measured across cycles."""

from __future__ import annotations

import json
import unittest

from fixtures import Fixture, add_item, write

PITFALL = """\
### {title}
- tags: {tags}
- paths: {paths}
- proven by: {proof}
- rule: do it the other way
"""


def fix(fix_id: str, origin: str, done_on: str, commit: str, files: str = "[]") -> str:
    return f"""\
---
id: {fix_id}
origin: {origin}
title: "t"
severity: low
status: done
done_on: {done_on}
done_commit: {commit}
files: {files}
---

# {fix_id}
"""


class RetroSuggestTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture("subfolder")
        self.root = self.fx.root

    def tearDown(self):
        self.fx.cleanup()

    def js(self, *args) -> dict:
        code, out, err = self.fx.rite("retro-suggest", *args, "--json")
        self.assertEqual(code, 0, err + out)
        return json.loads(out)

    def two_cycles(self) -> None:
        """alpha finished first: its fix proved a pitfall on src/app.py and its profile had gates. beta
        inherited the pitfalls by copy, kept an entry whose path is gone, and its fix hit src/app.py."""
        profiles = self.root / "docs/rite/profiles"
        sha_a = self.fx.work_commit("src/app.py", "print('a')\n", "fix: a")
        add_item(self.root / "docs/rite/cycles/alpha/FIX-ALP-001.md",
                 fix("FIX-ALP-001", "ALP-TASK-01", "2026-01-10", sha_a))
        entry = PITFALL.format(title="App entry", tags="app", paths="`src/app.py`",
                               proof="FIX-ALP-001 (2026-01-10)")
        write(profiles / "alpha.pitfalls.md", "# Measured pitfalls — alpha\n\n" + entry)
        with (profiles / "alpha.md").open("a", encoding="utf-8") as fh:
            fh.write("\n## Gates\n\n- make test\n")
        gone = PITFALL.format(title="Old tree", tags="old", paths="old/*.py", proof="abc1234 (2025-12-01)")
        write(profiles / "beta.pitfalls.md", "# Measured pitfalls — beta\n\n<!-- format -->\n\n" + entry + "\n" + gone)
        with (profiles / "beta.md").open("a", encoding="utf-8") as fh:
            fh.write("\n## Gates\n\n<!-- commands that must pass -->\n")
        sha_b = self.fx.work_commit("src/app.py", "print('b')\n", "fix: b")
        add_item(self.root / "docs/rite/cycles/beta/FIX-BET-001.md",
                 fix("FIX-BET-001", "BET-TASK-01", "2026-02-01", sha_b))

    def test_candidates_across_two_cycles(self):
        self.two_cycles()
        data = self.js("beta")
        self.assertEqual(data["previous"], "alpha")
        self.assertEqual(data["pitfalls"], ["docs/rite/profiles/beta.pitfalls.md"])
        [keep] = data["keep"]
        self.assertEqual((keep["fix"], keep["paths"], keep["suggest"]),
                         ("FIX-BET-001", ["src/app.py"], "update-existing"))
        self.assertEqual(keep["matches_existing"],
                         [{"title": "App entry", "file": "docs/rite/profiles/beta.pitfalls.md", "by": "paths"}])
        [promote] = data["promote"]
        self.assertEqual((promote["title"], promote["proven_by"], promote["cycles"]),
                         ("App entry", ["FIX-ALP-001", "FIX-BET-001"], ["alpha", "beta"]))
        self.assertEqual([(p["kind"], p["title"]) for p in data["prune"]], [("pitfall-paths-gone", "Old tree")])
        [carry] = data["carry_over"]
        self.assertEqual((carry["section"], carry["from_cycle"], carry["content"]), ("Gates", "alpha", "- make test"))

    def test_a_fix_already_named_by_an_entry_matches_by_proof(self):
        self.two_cycles()
        path = self.root / "docs/rite/profiles/beta.pitfalls.md"
        path.write_text(path.read_text(encoding="utf-8").replace("FIX-ALP-001 (2026-01-10)",
                                                                 "FIX-ALP-001 (2026-01-10), FIX-BET-001 (2026-02-01)"),
                        encoding="utf-8")
        self.assertEqual(self.js("beta")["keep"][0]["matches_existing"][0]["by"], "proven_by")

    def test_previous_can_be_named_and_a_first_cycle_has_none(self):
        data = self.js("alpha")
        self.assertIsNone(data["previous"])
        self.assertEqual((data["keep"], data["promote"], data["prune"], data["carry_over"]), ([], [], [], []))
        self.two_cycles()
        self.assertEqual(self.js("alpha", "--previous", "beta")["previous"], "beta")

    def test_a_profile_over_max_kb_lists_its_sections_by_size(self):
        profile = self.root / "docs/rite/profiles/alpha.md"
        with profile.open("a", encoding="utf-8") as fh:
            fh.write("\n## Hot files\n\n" + "- src/app.py is hot\n" * 800)
        [prune] = self.js("alpha")["prune"]
        self.assertEqual((prune["kind"], prune["max_kb"]), ("profile-over-max-kb", 12))
        self.assertEqual(prune["largest_sections"][0]["title"], "Hot files")

    def test_text_output(self):
        self.two_cycles()
        code, out, _ = self.fx.rite("retro-suggest", "beta")
        self.assertEqual(code, 0)
        self.assertIn("FIX-BET-001: update-existing — App entry", out)
        self.assertIn("Gates (from alpha)", out)


if __name__ == "__main__":
    unittest.main()
