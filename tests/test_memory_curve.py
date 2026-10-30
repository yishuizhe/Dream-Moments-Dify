from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services import memory_curve


class MemoryCurveTests(unittest.TestCase):
    def test_retention_decays_and_reinforcement_slows_it(self):
        entry = memory_curve.new_entry("我喜欢喝绿茶", stability=4.0)
        entry["last_seen"] = "2026-01-01T00:00:00"
        now = memory_curve.parse_time("2026-02-01T00:00:00")
        faded = memory_curve.retention(entry, now)
        self.assertLess(faded, 0.2)
        for _ in range(4):
            memory_curve.reinforce(entry, now)
        self.assertGreater(memory_curve.retention(entry, now), faded)

    def test_rank_drops_fully_forgotten_items(self):
        fresh = memory_curve.new_entry("我喜欢猫")
        old = memory_curve.new_entry("很久以前说过的一句话")
        old["last_seen"] = "2025-01-01T00:00:00"
        now = memory_curve.parse_time("2026-10-24T00:00:00")
        ranked = memory_curve.rank(
            [old, fresh], now, half_life_days=14, min_strength=0.12, limit=8
        )
        self.assertEqual([item["text"] for item in ranked], ["我喜欢猫"])

    def test_legacy_string_memory_is_migrated(self):
        entry = memory_curve.normalize_entry("旧格式的记忆")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["text"], "旧格式的记忆")
        self.assertEqual(entry["hits"], 1)
        self.assertIn("importance", entry)

    def test_prune_respects_max_items(self):
        entries = [memory_curve.new_entry(f"记忆{i}") for i in range(60)]
        kept = memory_curve.prune(entries, max_items=10, min_strength=0.0)
        self.assertEqual(len(kept), 10)


if __name__ == "__main__":
    unittest.main()
