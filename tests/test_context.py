"""`rite context`: what one item needs read, sliced instead of opened whole."""

import json
import unittest

from fixtures import write

from test_cli import FixtureCase

BIG_PLAN = """\
# Plan — alpha

## 1. Context

Background prose.

## 2. Harness

Intro of the harness.

### 2.1 Card diff

{filler}

#### 2.1.1 Detail

A sub-subsection that belongs to 2.1.

### 2.2 Report

Nothing to do with 2.1.

## 3. Closing
"""


class ContextTest(FixtureCase):
    def context(self, item_id: str) -> dict:
        return self.js("context", item_id)

    def test_slices_the_anchored_section_with_its_subsections(self):
        write(self.root / "docs/plans/PLAN-alpha.md", BIG_PLAN.format(filler="The diff itself.\n"))
        data = self.context("ALP-TASK-01")  # source_of_truth: /docs/plans/PLAN-alpha.md#2.1
        plan = next(p for p in data["parts"] if "PLAN-alpha.md" in p["name"])
        self.assertIn("### 2.1 Card diff", plan["text"])
        self.assertIn("#### 2.1.1 Detail", plan["text"])  # subsections come along
        self.assertNotIn("2.2 Report", plan["text"])      # the next sibling does not
        self.assertNotIn("Background prose", plan["text"])
        first, last = plan["lines"]
        self.assertIn(f"sed -n '{first},{last}p'", plan["note"])

    def test_slug_anchor_and_missing_anchor(self):
        data = self.context("ALP-TASK-02")  # anchor #22-report, a github slug
        plan = next(p for p in data["parts"] if "PLAN-alpha.md" in p["name"])
        self.assertIn("2.2 Report", plan["text"])

        path = self.root / "docs/rite/cycles/alpha/01-harness.md"
        text = path.read_text(encoding="utf-8").replace("#2.1", "#nowhere")
        path.write_text(text, encoding="utf-8", newline="\n")
        plan = next(p for p in self.context("ALP-TASK-01")["parts"] if "PLAN-alpha.md" in p["name"])
        self.assertIn("not found", plan["note"])
        self.assertIn("sed -n", plan["note"])  # says how to read the rest

    def test_truncates_at_the_budget_and_says_what_was_cut(self):
        write(self.root / "docs/plans/PLAN-alpha.md", BIG_PLAN.format(filler="x " * 40000))
        path = self.root / "rite.toml"
        path.write_text(path.read_text(encoding="utf-8") + "\n[output]\ncontext_kb = 4\n",
                        encoding="utf-8", newline="\n")
        data = self.context("ALP-TASK-01")
        self.assertLessEqual(data["bytes"], 4 * 1024)
        self.assertTrue(data["truncated"])
        cut = data["truncated"][0]
        self.assertGreater(cut["bytes"], 0)
        self.assertIn("sed -n", cut["command"])
        self.assertIn("bytes cut", self.ok("context", "ALP-TASK-01"))

    def test_the_biggest_part_absorbs_the_cut(self):
        """Measured on a real repository: a 26 KB item file ate the whole budget and left the plan
        section and the profile rules at zero bytes."""
        write(self.root / "docs/plans/PLAN-alpha.md", BIG_PLAN.format(filler="plan line\n" * 200))
        path = self.root / "docs/rite/cycles/alpha/01-harness.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nfiller line\n" * 4000,
                        encoding="utf-8", newline="\n")
        cfg = self.root / "rite.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[output]\ncontext_kb = 8\n",
                       encoding="utf-8", newline="\n")
        data = self.context("ALP-TASK-01")
        sizes = {p["name"]: len(p["text"].encode("utf-8")) for p in data["parts"]}
        plan = next(v for k, v in sizes.items() if "PLAN-alpha" in k)
        self.assertGreater(plan, 1000)                     # the small part is served whole
        self.assertLessEqual(data["bytes"], 8 * 1024)
        self.assertEqual([t["part"] for t in data["truncated"]],
                         [p["name"] for p in data["parts"] if "01-harness" in p["name"]])

    def test_profile_rules_phase_checks_and_matching_pitfalls_only(self):
        write(self.root / "docs/rite/profiles/alpha.md", """
            # Profile — alpha

            ## Confirmed decisions

            - decided: one harness

            ## Gates

            - `python -m unittest discover -s tests`

            ## Phase-specific checks

            ### Phase 1 — build
            - run the harness

            ### Phase 2 — close
            - recount the numbers
            """)
        write(self.root / "docs/rite/profiles/alpha.pitfalls.md", """
            # Pitfalls — alpha

            ### src/app.py is generated
            Regenerate it; never edit by hand.

            ### unrelated corner
            Nothing to do with this item.
            """)
        path = self.root / "docs/rite/cycles/alpha/01-harness.md"
        text = path.read_text(encoding="utf-8").replace("status: pending", "files: [src/app.py]\nstatus: pending")
        path.write_text(text, encoding="utf-8", newline="\n")

        names = {p["name"]: p["text"] for p in self.context("ALP-TASK-01")["parts"]}
        gates = next(v for k, v in names.items() if k.endswith("§ Gates"))
        self.assertIn("unittest", gates)
        checks = next(v for k, v in names.items() if "Phase-specific checks" in k)
        self.assertIn("Phase 1", checks)
        self.assertNotIn("Phase 2", checks)  # only the item's phase
        pitfalls = next(v for k, v in names.items() if "pitfalls" in k)
        self.assertIn("src/app.py is generated", pitfalls)
        self.assertNotIn("unrelated corner", pitfalls)

    def test_is_deterministic_and_survives_a_missing_profile(self):
        first = json.dumps(self.context("ALP-TASK-01"), sort_keys=True)
        self.assertEqual(first, json.dumps(self.context("ALP-TASK-01"), sort_keys=True))
        (self.root / "docs/rite/profiles/alpha.md").unlink()
        data = self.context("ALP-TASK-01")
        self.assertTrue(data["parts"][0]["text"])  # the item itself is still there
        self.assertFalse([p for p in data["parts"] if "profiles/alpha.md" in p["name"]])

    def test_item_without_files_gets_no_pitfalls_noise(self):
        write(self.root / "docs/rite/profiles/alpha.pitfalls.md",
              "# Pitfalls\n\n### something\nUnrelated to this item.\n")
        data = self.context("ALP-TASK-03")
        self.assertFalse([p for p in data["parts"] if "pitfalls" in p["name"]])


if __name__ == "__main__":
    unittest.main()
