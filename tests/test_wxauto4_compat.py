from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wechat.wxauto4_compat import needs_profile_popover_compat


class WxAuto4CompatibilityTests(unittest.TestCase):
    def test_unknown_version_keeps_upstream_behavior(self):
        self.assertFalse(needs_profile_popover_compat(None))

    def test_wechat_418_keeps_upstream_behavior(self):
        self.assertFalse(needs_profile_popover_compat((4, 1, 8, 107)))

    def test_wechat_411_uses_profile_popover_compatibility(self):
        self.assertTrue(needs_profile_popover_compat((4, 1, 11, 24)))


if __name__ == "__main__":
    unittest.main()
