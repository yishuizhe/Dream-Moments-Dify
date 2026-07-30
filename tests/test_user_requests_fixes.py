import sys, unittest
from pathlib import Path
sys.path.insert(0, "src")
sys.path.insert(0, "plugins/ChatSummary")

code = Path("src/main.py").read_text(encoding="utf-8")
start = code.find("def is_image_content")
if start < 0:
    start = code.find("def strip_group_bot_mention")
end = code.find("class ChatBot")
ns = {
    "re": __import__("re"),
    "os": __import__("os"),
    "is_image_placeholder": __import__(
        "handlers.image_recognition", fromlist=["is_image_placeholder"]
    ).is_image_placeholder,
}
exec(code[start:end], ns)
strip = ns["strip_group_bot_mention"]
is_img = ns["is_image_content"]
is_image_request = ns["is_explicit_image_request"]
from dream_plugin import DreamChatSummaryPlugin as P
from services.web_search import is_search_request, extract_search_query
from handlers.voice import VoiceHandler
from handlers.image_recognition import honest_image_failure_reply, recognition_failed

class T(unittest.TestCase):
    def test_startswith_no_space(self):
        cleaned, ok = strip("娜娜你好呀", "娜娜")
        self.assertTrue(ok)
        self.assertEqual(cleaned, "你好呀")
    def test_at(self):
        cleaned, ok = strip("@娜娜 总结一下", "娜娜")
        self.assertTrue(ok)
        self.assertIn("总结", cleaned)
    def test_alone(self):
        cleaned, ok = strip("娜娜", "娜娜")
        self.assertTrue(ok)
        self.assertEqual(cleaned, "")
    def test_name_anywhere_in_sentence_triggers(self):
        cleaned, ok = strip("麻烦娜娜看一下图", "娜娜")
        self.assertTrue(ok)
        self.assertEqual(cleaned, "麻烦看一下图")
    def test_no_trigger(self):
        _, ok = strip("大家好", "娜娜")
        self.assertFalse(ok)
    def test_image_placeholder(self):
        self.assertTrue(is_img("图片"))
        self.assertTrue(is_img("[图片]"))
        self.assertFalse(is_img("今天天气"))
    def test_explicit_image_request(self):
        self.assertTrue(is_image_request("娜娜，看图"))
        self.assertTrue(is_image_request("请你看看这张图片"))
        self.assertFalse(is_image_request("今天群里好多图片"))
    def test_recognition_failed_marker(self):
        self.assertTrue(recognition_failed("IMAGE_RECOGNITION_FAILED: bad"))
        self.assertFalse(recognition_failed("发送了图片：一只橘猫"))
        self.assertFalse(recognition_failed(""))
    def test_image_failure_reply_does_not_expose_configuration(self):
        reply = honest_image_failure_reply("图片识别 API Key 无效")
        self.assertNotIn("API Key", reply)
        self.assertNotIn("sk-", reply)
    def test_group_default(self):
        r = P._parse_command("总结群聊", "娜娜")
        self.assertEqual(r["kind"], "group")
        self.assertGreaterEqual(r["limit"], 100)
    def test_days(self):
        r = P._parse_command("总结最近3天", "娜娜")
        self.assertEqual(r["kind"], "days")
        self.assertEqual(r["days"], 3)
    def test_today(self):
        r = P._parse_command("总结今天", "娜娜")
        self.assertEqual(r["kind"], "today")
    def test_search(self):
        self.assertTrue(is_search_request("联网搜索今天油价"))
        self.assertEqual(extract_search_query("搜索：OpenAI"), "OpenAI")
    def test_voice_clean(self):
        vh = VoiceHandler(root_dir=".", tts_api_url="")
        self.assertTrue(vh.is_voice_request("发语音说晚安"))
        self.assertEqual(vh.clean_voice_prompt("请用语音回复今天天气怎么样"), "今天天气怎么样")

if __name__ == "__main__":
    unittest.main(verbosity=2)
