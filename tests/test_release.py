"""The release tool must find the version in every place it is written, and they must agree."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import release  # noqa: E402


class ReleaseTest(unittest.TestCase):
    def test_every_version_site_matches_once_and_agrees(self):
        version = release.current()
        for name, pattern in release.VERSION_SITES:
            text = (ROOT / name).read_text(encoding="utf-8")
            found = [m.group(1) for m in re.finditer(pattern, text, re.M)]
            self.assertEqual(found, [version], name)

    def test_next_version(self):
        self.assertEqual(release.next_version("0.17.3", "patch"), "0.17.4")
        self.assertEqual(release.next_version("0.17.3", "minor"), "0.18.0")
        self.assertEqual(release.next_version("0.17.3", "major"), "1.0.0")
        self.assertEqual(release.next_version("0.17.3", "0.20.0"), "0.20.0")
        for bad in ("0.17.3", "0.9.9", "next", "1.0"):
            with self.assertRaises(SystemExit, msg=bad):
                release.next_version("0.17.3", bad)

    def test_section_stops_at_the_next_heading(self):
        text = "# Changelog\n\n## [Unreleased]\n\n- a\n\n## [1.0.0] — 2026-01-01\n\n- b\n"
        self.assertEqual(release.section(text, "Unreleased").strip(), "- a")
        self.assertEqual(release.section(text, "1.0.0").strip(), "- b")
        self.assertIsNone(release.section(text, "2.0.0"))

    def test_the_current_version_has_notes(self):
        body = release.section(release.CHANGELOG.read_text(encoding="utf-8"), release.current())
        self.assertTrue(body and body.strip())


if __name__ == "__main__":
    unittest.main()
