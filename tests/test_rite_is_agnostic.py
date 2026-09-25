"""The rite (commands, parts, agents) must not name any concrete project, tool or path."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RITE_DIRS = ("commands", "parts", "agents")

# Names that leaked into the original prompts, plus common tool/stack names. Extend when a leak is found.
BLACKLIST = [
    r"we2002", r"newWe2002", r"xvfb", r"\bwine\b", r"\broms?/", r"\bctest\b", r"\bcmake\b",
    r"\bnpm\b", r"\bpnpm\b", r"\byarn\b", r"\bpytest\b", r"\bcargo\b", r"\bgradle\b", r"\bmaven\b",
    r"\bmake test\b", r"\bdocker\b", r"\bingmar\b", r"\bperfil\b", r"\bprogresso\b", r"\bCORR-",
    r"docs/tasks", r"\bDISPLAY=",
]
ABSOLUTE_PATH = re.compile(r"(?<![\w$}])(?:/home/|/Users/|/mnt/|/opt/|[A-Za-z]:[\\/])")


def rite_files():
    for d in RITE_DIRS:
        base = ROOT / d
        if base.is_dir():
            yield from sorted(base.rglob("*.md"))


class AgnosticTest(unittest.TestCase):
    def test_there_is_a_rite(self):
        self.assertTrue(list(rite_files()))

    def test_no_concrete_names(self):
        leaks = []
        for f in rite_files():
            text = f.read_text(encoding="utf-8")
            for pat in BLACKLIST:
                for m in re.finditer(pat, text, flags=re.IGNORECASE):
                    line = text.count("\n", 0, m.start()) + 1
                    leaks.append(f"{f.relative_to(ROOT)}:{line}: {m.group(0)!r}")
            for m in ABSOLUTE_PATH.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                leaks.append(f"{f.relative_to(ROOT)}:{line}: absolute path {m.group(0)!r}")
        self.assertEqual(leaks, [], "rite names concrete things:\n" + "\n".join(leaks))

    def test_command_size(self):
        """A command carries its rules, so the cap is what one turn may load, not what prose wants."""
        # The whole command is read on every invocation: 10 KB is about 2.8k tokens, 0.6k above the
        # first cap of 8 KB, which was a guess and started deciding the wording of rules. It protects
        # the per-invocation cost. A command past it moves prose to a shared part or to
        # docs/CONCEPTS.md; the cap does not go up again.
        big = [f"{f.relative_to(ROOT)}: {f.stat().st_size} B" for f in (ROOT / "commands").glob("*.md")
               if f.stat().st_size > 10 * 1024]
        self.assertEqual(big, [], "commands must stay <= 10 KB; move prose to parts/ or docs/CONCEPTS.md")

    def test_commands_do_not_send_the_reader_to_another_file(self):
        """Fragments read at runtime were a third of an invocation's cost; parts are inlined instead."""
        leaks = [f"{f.relative_to(ROOT)}" for f in (ROOT / "commands").glob("*.md")
                 if "shared/" in f.read_text(encoding="utf-8")]
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
