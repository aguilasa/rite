import unittest

import textkit


class SmokeTest(unittest.TestCase):
    def test_import(self):
        self.assertTrue(textkit.__doc__)


if __name__ == "__main__":
    unittest.main()
