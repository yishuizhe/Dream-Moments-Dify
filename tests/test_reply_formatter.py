from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.reply_formatter import (
    FORMAT_MARKER,
    build_system_prompt,
    normalize_reply_text,
    split_reply_bubbles,
)


class ReplyFormatterTests(unittest.TestCase):
    def test_build_system_prompt_adds_format_rule_once(self):
        prompt = build_system_prompt("system")
        self.assertIn("system", prompt)
        self.assertIn(FORMAT_MARKER, prompt)
        self.assertEqual(build_system_prompt(prompt).count(FORMAT_MARKER), 1)

    def test_repairs_reported_unpunctuated_reply(self):
        sample = (
            "\u591c\u73ed\u8981\u5230\u51e0\u70b9\u5440\u90a3\u73b0\u5728\u5077\u5077\u72af\u56f0"
            "\u8fd8\u662f\u7cbe\u795e\u8fd8\u4e0d\u9519 \u6211\u5e2e\u4f60\u76ef\u7740\u65f6\u95f4\u63d0\u9192\u4f60"
            "\u6d3b\u52a8\u4e00\u4e0b\u597d\u5566\u4e0d\u8fc7\u8bf4\u8d77\u6765 \u4f60\u5de5\u4f5c\u65f6\u4f1a\u559d\u8336"
            "\u8fd8\u662f\u5496\u5561\u63d0\u795e"
        )
        formatted = normalize_reply_text(sample)
        self.assertEqual(
            formatted.splitlines(),
            [
                "\u591c\u73ed\u8981\u5230\u51e0\u70b9\u5440\uff1f",
                "\u90a3\u73b0\u5728\u5077\u5077\u72af\u56f0\u8fd8\u662f\u7cbe\u795e\u8fd8\u4e0d\u9519\uff1f",
                "\u6211\u5e2e\u4f60\u76ef\u7740\u65f6\u95f4\u63d0\u9192\u4f60\u6d3b\u52a8\u4e00\u4e0b\u597d\u5566\u3002",
                "\u4e0d\u8fc7\u8bf4\u8d77\u6765\uff0c\u4f60\u5de5\u4f5c\u65f6\u4f1a\u559d\u8336\u8fd8\u662f\u5496\u5561\u63d0\u795e\uff1f",
            ],
        )
        self.assertEqual(split_reply_bubbles(formatted), formatted.splitlines())

    def test_keeps_normal_punctuation_unchanged(self):
        reply = "\u4eca\u5929\u6709\u70b9\u7d2f\uff0c\u5148\u4f11\u606f\u4e00\u4e0b\u5427\u3002\u665a\u70b9\u518d\u7ee7\u7eed\uff0c\u597d\u5417\uff1f"
        self.assertEqual(normalize_reply_text(reply), reply)

    def test_supports_legacy_backslash_separator(self):
        reply = "\u7b2c\u4e00\u53e5" + "\\" + "\u7b2c\u4e8c\u53e5"
        self.assertEqual(normalize_reply_text(reply).splitlines(), ["\u7b2c\u4e00\u53e5", "\u7b2c\u4e8c\u53e5"])

    def test_does_not_break_windows_path(self):
        reply = r"File: C:\Users\Public\photo.gif"
        self.assertEqual(normalize_reply_text(reply), reply)

    def test_does_not_repair_code_block_or_url(self):
        code = "```python\nprint('hello')\n```"
        url = "https://example.com/very/long/path/without/chinese/punctuation"
        self.assertEqual(normalize_reply_text(code), code)
        self.assertEqual(normalize_reply_text(url), url)
        self.assertEqual(split_reply_bubbles(code), [code])
        self.assertEqual(split_reply_bubbles(url, max_chars=20), [url])

    def test_splits_long_sentence_near_punctuation(self):
        reply = "alpha beta gamma, delta epsilon zeta, eta theta iota."
        bubbles = split_reply_bubbles(reply, max_chars=20)
        self.assertGreater(len(bubbles), 1)
        self.assertTrue(all(len(item) <= 20 for item in bubbles))


if __name__ == "__main__":
    unittest.main()
