"""The version must agree wherever it is written."""

import json
import re
import unittest

from fixtures import ROOT

from rite_lib import __version__


class VersionTest(unittest.TestCase):
    def test_manifests_and_package_agree(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        listed = [p["version"] for p in market["plugins"] if p["name"] == plugin["name"]]
        self.assertEqual(listed, [plugin["version"]], "marketplace.json lists another version")
        self.assertEqual(plugin["version"], __version__, "rite_lib.__version__ differs from plugin.json")

    def test_changelog_has_the_version(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        headings = re.findall(r"(?m)^## \[([^\]]+)\]", changelog)
        self.assertTrue(headings, "CHANGELOG.md has no version headings")
        released = [h for h in headings if h != "Unreleased"]
        self.assertTrue(released and released[0] == __version__,
                        f"latest released CHANGELOG entry {released[:1]} is not {__version__}")


if __name__ == "__main__":
    unittest.main()
