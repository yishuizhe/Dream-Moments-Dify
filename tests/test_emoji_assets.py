from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.emoji import EmojiHandler


class EmojiAssetTests(unittest.TestCase):
    def test_bundled_emotion_gifs_are_animated(self):
        base = ROOT / "data" / "avatars" / "MONO" / "emojis"
        for emotion in ("happy", "sad", "angry", "neutral"):
            files = sorted((base / emotion).glob("*.gif"))
            self.assertTrue(files, f"missing GIF assets for {emotion}")
            for path in files:
                with Image.open(path) as image:
                    self.assertEqual(image.format, "GIF")
                    self.assertGreater(image.n_frames, 1)

    def test_emotion_handler_selects_matching_directory(self):
        handler = EmojiHandler(str(ROOT))
        self.assertEqual(handler.detect_emotion("今天真开心"), "happy")
        self.assertEqual(handler.detect_emotion("有一点难过"), "sad")
        self.assertEqual(handler.detect_emotion("我生气了"), "angry")
        self.assertEqual(handler.detect_emotion("我是怕吓到你嘛。"), "happy")
        selected = Path(handler.get_emotion_emoji("哈哈，真开心"))
        self.assertEqual(selected.parent.name, "happy")
        self.assertEqual(selected.suffix.lower(), ".gif")

    def test_emotion_emoji_has_per_chat_cooldown(self):
        handler = EmojiHandler(str(ROOT))
        handler.cooldown_seconds = 60
        self.assertIsNotNone(handler.get_emotion_emoji("好耶！", chat_id="group"))
        self.assertIsNone(handler.get_emotion_emoji("哈哈", chat_id="group"))
        self.assertIsNotNone(handler.get_emotion_emoji("哈哈", chat_id="other-group"))


if __name__ == "__main__":
    unittest.main()
