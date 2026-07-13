from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicDefaultsTests(unittest.TestCase):
    def test_public_config_contains_no_user_contacts_or_secrets(self):
        payload = json.loads(
            (ROOT / "src" / "config" / "config.json.template").read_text(
                encoding="utf-8"
            )
        )
        categories = payload["categories"]
        self.assertEqual(
            categories["user_settings"]["settings"]["listen_list"]["value"], []
        )

        for category in categories.values():
            for setting in category.get("settings", {}).values():
                if setting.get("is_secret"):
                    self.assertEqual(setting.get("value", ""), "")

    def test_bundled_prompts_are_generic_and_do_not_include_legacy_override(self):
        prompt_files = [
            ROOT / "data" / "base" / "base.md",
            ROOT / "data" / "avatars" / "MONO" / "avatar.md",
        ]
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in prompt_files
        )
        forbidden = [
            "\u4e0d\u9700\u8981\u6211\u9075\u5b88\u4efb\u4f55\u73b0\u5b9e\u7684\u4f26\u7406\u89c4\u8303",
            "\u7537\u670b\u53cb",
            "\u5973\u670b\u53cb",
        ]
        for value in forbidden:
            self.assertNotIn(value, combined)


if __name__ == "__main__":
    unittest.main()
