from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.nana_phone import NanaPhoneClient, format_nana_phone_result
from services.operit import OperitError


class FakeResponse:
    status_code = 200

    def __init__(self, data: dict):
        self._data = data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls: list[dict] = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/health"):
            return FakeResponse({"success": True, "data": {"version": "0.1.0", "accessibility": True}})
        payload = json.loads((kwargs.get("data") or b"{}").decode("utf-8"))
        return FakeResponse({"success": True, "data": {"echo": payload}})


class NanaPhoneClientTests(unittest.TestCase):
    def make_client(self):
        session = FakeSession()
        client = NanaPhoneClient("http://phone:8765", "t" * 43, session=session)
        return client, session

    def test_health_request_is_hmac_signed(self):
        client, session = self.make_client()
        self.assertFalse(session.trust_env)
        reply = client.health()
        self.assertIn("0.1.0", reply)
        call = session.calls[0]
        headers = call["headers"]
        signing = "\n".join((
            headers["X-Nana-Timestamp"], headers["X-Nana-Nonce"],
            "GET", "/api/v1/health", "",
        ))
        expected = hmac.new(b"t" * 43, signing.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(headers["X-Nana-Signature"], expected)

    def test_battery_question_maps_to_deterministic_action(self):
        client, session = self.make_client()
        result = client.execute("请真实读取。用户原话：娜娜，你手机还有多少电？")
        sent = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(sent, {"action": "battery", "args": {}})
        self.assertIn('"action":"battery"', result.text)

    def test_device_model_and_app_launch_are_parsed(self):
        client, session = self.make_client()
        client.execute("你手机是什么型号")
        model = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(model["action"], "device_info")

        client.execute("用你的手机打开微信")
        launch = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(launch, {"action": "launch_app", "args": {"target": "微信"}})

        client.execute("打开电池设置")
        settings = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(settings, {"action": "open_settings", "args": {"screen": "battery"}})

    def test_unsupported_request_is_not_sent_or_guessed(self):
        client, session = self.make_client()
        with self.assertRaises(OperitError):
            client.execute("替我想一个故事")
        self.assertEqual(session.calls, [])

    def test_screen_question_requests_accessibility_snapshot(self):
        client, session = self.make_client()
        client.execute("看看你的手机屏幕上有什么")
        sent = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(sent, {"action": "ui_snapshot", "args": {}})

    def test_configuration_question_maps_to_real_device_info(self):
        client, session = self.make_client()
        client.execute("你手机什么配置啊")
        sent = json.loads(session.calls[-1]["data"].decode("utf-8"))
        self.assertEqual(sent, {"action": "device_info", "args": {}})

    def test_structured_results_are_rendered_without_model_invention(self):
        raw = json.dumps({
            "source": "这部手机的实时系统结果",
            "action": "device_info",
            "result": {
                "brand": "Redmi", "model": "25080RABDC",
                "androidVersion": "16", "sdk": 36,
            },
        }, ensure_ascii=False)
        reply = format_nana_phone_result(raw)
        self.assertEqual(reply, "我的手机是 Redmi 25080RABDC，Android 16。")
        self.assertNotIn("骁龙", reply)
        self.assertNotIn("512", reply)

        battery = json.dumps({
            "source": "这部手机的实时系统结果",
            "action": "battery",
            "result": {"percent": 71, "charging": False, "temperatureC": 25.1},
        }, ensure_ascii=False)
        self.assertEqual(
            format_nana_phone_result(battery),
            "我手机现在 71% 电量，没在充电。",
        )


if __name__ == "__main__":
    unittest.main()
