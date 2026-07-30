from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from handlers.image import ImageHandler


class ImageGenerationTests(unittest.TestCase):
    def test_disabled_provider_never_calls_deepseek_image_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("handlers.image.requests.post") as post:
            handler = ImageHandler(
                temp_dir,
                api_key="text-key",
                base_url="https://api.deepseek.com/v1",
                text_model="deepseek-v4-pro",
                image_enabled=False,
            )
            self.assertIsNone(handler.generate_image("\u753b\u4e00\u53ea\u732b"))
            post.assert_not_called()
            self.assertIn("\u72ec\u7acb\u56fe\u50cf\u751f\u6210 API", handler.get_unavailable_message())

    @patch("handlers.image.DeepSeekAI")
    def test_prompt_optimizer_uses_configured_text_model(self, deepseek_cls):
        with tempfile.TemporaryDirectory() as temp_dir:
            handler = ImageHandler(
                temp_dir,
                api_key="text-key",
                base_url="https://api.deepseek.com/v1",
                text_model="deepseek-v4-pro",
            )
            handler._get_text_ai()
            self.assertEqual(deepseek_cls.call_args.kwargs["model"], "deepseek-v4-pro")

    def test_base64_image_response_is_saved(self):
        image_bytes = b"fake-png"
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "handlers.image.requests.post", return_value=response
        ) as post:
            handler = ImageHandler(
                temp_dir,
                image_enabled=True,
                image_api_key="image-key",
                image_base_url="https://images.example/v1",
                image_model="image-model",
            )
            handler._expand_prompt = lambda prompt: prompt
            handler._optimize_prompt = lambda prompt: (prompt, "raw")
            handler._build_final_negatives = lambda prompt: ""
            path = handler.generate_image("cat")
            self.assertIsNotNone(path)
            self.assertEqual(Path(path).read_bytes(), image_bytes)
            self.assertEqual(post.call_args.args[0], "https://images.example/v1/images/generations")


if __name__ == "__main__":
    unittest.main()
