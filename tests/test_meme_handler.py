from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.meme import MemeHandler


class MemeHandlerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        meme_dir = self.root / "data" / "avatars" / "Test" / "memes" / "claude"
        meme_dir.mkdir(parents=True)
        image = meme_dir / "claude-1.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        other_dir = self.root / "data" / "avatars" / "Test" / "memes" / "deepseek"
        other_dir.mkdir(parents=True)
        other = other_dir / "deepseek-1.png"
        other.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        index = self.root / "data" / "avatars" / "Test" / "memes" / "index.json"
        index.write_text(json.dumps({"entries": [
            {"file": "memes/claude/claude-1.png", "family": "claude",
             "tags": ["封号", "欠债"], "caption": "又封号了"},
            {"file": "memes/deepseek/deepseek-1.png", "family": "deepseek",
             "tags": ["白饭", "大肥鱼"], "caption": "开心大米饭"},
        ]}), encoding="utf-8")
        self.handler = MemeHandler(
            self.root, "data/avatars/Test", cooldown_seconds=0, max_per_hour=10, probability=1.0
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_picks_meme_by_conversation_tag(self):
        path = self.handler.pick("大肥鱼又在吃开心大米饭", chat_id="c1")
        self.assertIsNotNone(path)
        self.assertIn("deepseek", path)

    def test_explicit_request_can_pick_without_tag_match(self):
        path = self.handler.pick("来个梗图", chat_id="c2", explicit=True)
        self.assertIsNotNone(path)

    def test_cooldown_blocks_second_send(self):
        self.handler.cooldown_seconds = 600
        self.assertIsNotNone(self.handler.pick("封号了", chat_id="c3"))
        self.assertIsNone(self.handler.pick("封号了", chat_id="c3"))


if __name__ == "__main__":
    unittest.main()
