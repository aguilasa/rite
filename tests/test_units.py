import tempfile
import unittest
from pathlib import Path

import fixtures  # noqa: F401  (puts the plugin root on sys.path)

from rite_lib import config, frontmatter, markdown
from rite_lib.guard import glob_regex
from rite_lib.naming import Naming, slugify
from rite_lib.config import DEFAULTS


class FrontmatterTest(unittest.TestCase):
    DOC = (
        "---\n"
        "id: ALP-TASK-01\n"
        "title: \"Card: diff\"   # quoted because of the colon\n"
        "phase: 3\n"
        "depends_on: [ALP-TASK-02, \"ALP-TASK-03\"]\n"
        "tags:\n"
        "  - a\n"
        "  - b\n"
        "done_on: null\n"
        "empty:\n"
        "flag: true\n"
        "---\n"
        "body\n"
    )

    def test_parse(self):
        data, body = frontmatter.parse(self.DOC)
        self.assertEqual(data["id"], "ALP-TASK-01")
        self.assertEqual(data["title"], "Card: diff")
        self.assertEqual(data["phase"], 3)
        self.assertEqual(data["depends_on"], ["ALP-TASK-02", "ALP-TASK-03"])
        self.assertEqual(data["tags"], ["a", "b"])
        self.assertIsNone(data["done_on"])
        self.assertIsNone(data["empty"])
        self.assertIs(data["flag"], True)
        self.assertEqual(body, "body\n")

    def test_set_fields_is_surgical(self):
        out = frontmatter.set_fields(self.DOC, {"title": "New", "tags": ["c"], "done_on": "2026-01-02",
                                                "added": "x y"})
        data, body = frontmatter.parse(out)
        self.assertEqual(data["title"], "New")
        self.assertEqual(data["tags"], ["c"])
        self.assertEqual(data["done_on"], "2026-01-02")
        self.assertEqual(data["added"], "x y")
        self.assertIn("# quoted because of the colon", out)
        self.assertEqual(body, "body\n")
        self.assertEqual(frontmatter.set_fields(out, {"title": "New"}), out)

    def test_dump_quotes_ambiguous(self):
        self.assertEqual(frontmatter.dump_value("pending"), "pending")
        self.assertEqual(frontmatter.dump_value("true"), '"true"')
        self.assertEqual(frontmatter.dump_value("12"), '"12"')
        self.assertEqual(frontmatter.dump_value("a: b"), '"a: b"')
        self.assertEqual(frontmatter.dump_value("/docs/p.md#2.1"), '"/docs/p.md#2.1"')

    def test_errors(self):
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("---\nid: a\n")
        with self.assertRaises(frontmatter.FrontmatterError):
            frontmatter.parse("---\nid: a\nid: b\n---\n")


class NamingTest(unittest.TestCase):
    def test_default_templates(self):
        n = Naming(DEFAULTS["naming"])
        self.assertEqual(n.task_id("ALP", 5), "ALP-TASK-05")
        self.assertEqual(n.fix_id("ALP", 14), "FIX-ALP-014")
        self.assertEqual(n.task_file("ALP", 5, "card-diff"), "05-card-diff.md")
        self.assertEqual(n.fix_file("ALP", 14, "x"), "FIX-ALP-014.md")
        self.assertEqual(n.parse_id("FIX-ALP-014"), ("fix", {"prefix": "ALP", "n": "014", "pattern": 0}))
        self.assertEqual(n.parse_id("ALP-TASK-05")[0], "task")
        self.assertIsNone(n.parse_id("nope"))
        self.assertEqual(n.match_file("fix", "FIX-ALP-014.md").group("n"), "014")

    def test_list_templates_first_is_canonical(self):
        n = Naming({**DEFAULTS["naming"],
                    "task_id": ["{prefix}-TASK-{n:02}", "{prefix}-{n:03}"],
                    "task_file": ["{n:02}-{slug}.md", "{id}.md"]})
        self.assertEqual(n.task_id("ALP", 5), "ALP-TASK-05")          # creation uses the first
        self.assertEqual(n.task_file("ALP", 5, "x"), "05-x.md")
        self.assertEqual(n.parse_id("OLD-007"), ("task", {"prefix": "OLD", "n": "007", "pattern": 1}))
        self.assertEqual(n.match_file("task", "PAR-TASK-03.md").group("n"), "03")   # read-only shape
        self.assertEqual(n.match_file("task", "OLD-007.md").group("prefix"), "OLD")
        self.assertIsNone(n.match_file("task", "notes.md"))

    def test_slugify(self):
        self.assertEqual(slugify("Extração de Tabelas!"), "extracao-de-tabelas")


class MarkdownTest(unittest.TestCase):
    TEXT = "# T\n\n## 2.1 Card diff\n\n```\n## not a heading\n[x](nope.md)\n```\n\n[ok](/a.md) `[no](b.md)`\n"

    def test_headings_and_links_skip_code(self):
        self.assertEqual([h for _, h in markdown.headings(self.TEXT)], ["T", "2.1 Card diff"])
        self.assertEqual([t for _, t in markdown.links(self.TEXT)], ["/a.md"])
        self.assertEqual(markdown.github_slug("2.1 Card diff"), "21-card-diff")

    def test_section_and_append(self):
        text = "# A\n\n## Log\n\n- one\n\n## Next\n\nx\n"
        self.assertEqual(markdown.section(text, "log").strip(), "- one")
        out = markdown.append_to_section(text, "Log", "- two")
        self.assertIn("- one\n- two\n\n## Next", out)
        out2 = markdown.append_to_section("# A\n", "Log", "- first")
        self.assertTrue(out2.endswith("## Log\n\n- first\n"))
        out3 = markdown.append_to_section("# A\n\n## Log\n", "Log", "- first")
        self.assertEqual(out3, "# A\n\n## Log\n\n- first\n")

    def test_first_section_and_append_to_a_list_of_titles(self):
        text = "# A\n\n## Evidência\n\nx\n\n## Log de Execução\n\n- one\n"
        self.assertEqual(markdown.first_section(text, ["Evidence", "Evidência"]), ("Evidência", "\nx\n"))
        self.assertIsNone(markdown.first_section(text, ["Evidence"]))
        out = markdown.append_to_section(text, ["Execution Log", "Log de Execução"], "- two")
        self.assertTrue(out.endswith("## Log de Execução\n\n- one\n- two\n"))
        out2 = markdown.append_to_section("# A\n", ["Execution Log", "Log de Execução"], "- first")
        self.assertTrue(out2.endswith("## Execution Log\n\n- first\n"))

    def test_an_exact_title_wins_over_a_suffixed_one(self):
        text = "## Log — 2026-08-30\n\nold\n\n## Log\n\nnew\n"
        self.assertEqual(markdown.first_section(text, ["Log"]), ("Log", "\nnew"))
        self.assertEqual(markdown.first_section("## Log *(filled after)*\n\n- a\n", ["Log"])[0],
                         "Log *(filled after)*")
        out = markdown.append_to_section("## Log *(filled after)*\n\n- a\n", ["Log"], "- b")
        self.assertEqual(out, "## Log *(filled after)*\n\n- a\n- b\n")
        self.assertIsNone(markdown.first_section("## Logbook\n\nx\n", ["Log"]))
        self.assertEqual(markdown.near_headings("## Log of the harness\n", ["Log"]), ["Log of the harness"])


class SectionsConfigTest(unittest.TestCase):
    def test_title_or_list(self):
        cfg = config.parse(Path("."), '[sections]\nevidence = ["Evidence", "Evidência"]\nfiles = "Arquivos"\n')
        self.assertEqual(cfg["sections"]["evidence"], ["Evidence", "Evidência"])
        self.assertEqual(cfg["sections"]["files"], "Arquivos")
        self.assertEqual(cfg["sections"]["gates"], "Gates")

    def test_empty_title_is_an_error(self):
        for bad in ('evidence = []', 'gates = ""', 'scope = ["Scope", 3]'):
            with self.assertRaisesRegex(config.ConfigError, r"\[sections\]\.\w+ must be a title"):
                config.parse(Path("."), "[sections]\n" + bad + "\n")


class SectionParsersTest(unittest.TestCase):
    def test_bare_paths_count_only_when_they_exist(self):
        from rite_lib.batch import _section_paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools/layout.py").write_text("", encoding="utf-8")
            text = ("## Arquivos\n\n- tools/layout.py (linhas ~2050)\n- tools/gone.py\n"
                    "- nada muda aqui.\n- `src/x.py` também\n")
            self.assertEqual(_section_paths(text, ["Arquivos"], root), ["src/x.py", "tools/layout.py"])
            self.assertEqual(_section_paths(text, ["Arquivos"]), ["src/x.py"])

    def test_gates_are_bullets_never_a_table(self):
        from rite_lib.compose import gate_commands
        body = ("- `make test` must pass\n\n| target | how |\n| --- | --- |\n"
                "| `selftest` | `python tools/selftest.py` |\n")
        self.assertEqual(gate_commands(body), ["make test"])
        prose = "- `make test`\n\n**But `ctest` is reachable** with the toolchain.\n*Only `CTestTestfile.cmake`.*\n"
        self.assertEqual(gate_commands(prose), ["make test"], "bold or italic prose is not a bullet")


class GlobTest(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(glob_regex("roms/**").match("roms/a/b.bin"))
        self.assertTrue(glob_regex("**/*.gen.ts").match("src/x/y.gen.ts"))
        self.assertTrue(glob_regex("**/*.gen.ts").match("y.gen.ts"))
        self.assertFalse(glob_regex("src/*.py").match("src/a/b.py"))
        self.assertTrue(glob_regex("vendor/").match("vendor/lib.js"))


if __name__ == "__main__":
    unittest.main()
