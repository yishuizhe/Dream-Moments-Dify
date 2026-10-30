from __future__ import annotations

import json
import sys
import tempfile
import unittest
from PIL import Image
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
        Image.new("RGB", (256, 256), "orange").save(image)
        other_dir = self.root / "data" / "avatars" / "Test" / "memes" / "deepseek"
        other_dir.mkdir(parents=True)
        other = other_dir / "deepseek-1.png"
        Image.new("RGB", (256, 256), "blue").save(other)
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
        path = self.handler.pick("大肥鱼又在吃白饭", chat_id="c1")
        self.assertIsNotNone(path)
        self.assertIn("deepseek", path)

    def test_explicit_request_can_pick_without_tag_match(self):
        path = self.handler.pick("来个梗图", chat_id="c2", explicit=True)
        self.assertIsNotNone(path)

    def test_cooldown_blocks_second_send(self):
        self.handler.cooldown_seconds = 600
        self.assertIsNotNone(self.handler.pick("封号了", chat_id="c3"))
        self.assertIsNone(self.handler.pick("封号了", chat_id="c3"))

    def test_character_name_alone_never_selects_a_picture(self):
        self.assertIsNone(self.handler.pick("Claude 大肥鱼", chat_id="c"))

    def test_negated_emotion_does_not_match_positive_tag_or_caption(self):
        entry = {'tags': ['开心'], 'caption': '开心'}
        self.assertEqual(self.handler.score(entry, '我不开心'), 0)
        self.assertGreater(self.handler.score(entry, '今天开心'), 0)

    def test_input_topic_cannot_override_unrelated_reply(self):
        self.assertIsNone(self.handler.pick("吃白饭", chat_id="c", reply_text="先把问题处理好"))

    def test_invalid_or_tiny_assets_are_rejected_even_on_explicit_request(self):
        for entry in self.handler.entries:
            Path(entry['path']).write_bytes(b'broken image')
        self.assertIsNone(self.handler.pick("来个梗图", explicit=True))

    def test_picks_in_one_group_do_not_exhaust_other_group(self):
        self.assertIsNotNone(self.handler.pick("封号了", chat_id="g1"))
        self.assertIsNotNone(self.handler.pick("封号了", chat_id="g2"))


if __name__ == "__main__":
    unittest.main()
