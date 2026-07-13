from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plugins.manager import PluginManager


PLUGIN_SOURCE = """class Plugin:
    name = {name!r}

    def __init__(self):
        self.received = []

    def handle_message(self, message):
        self.received.append(dict(message))
        {body}


def create_plugin(plugin_dir, logger=None):
    return Plugin()
"""


class PluginManagerTests(unittest.TestCase):
    def write_plugin(self, root: Path, directory: str, *, name: str, body: str) -> None:
        plugin_dir = root / directory
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "dream_plugin.py").write_text(
            PLUGIN_SOURCE.format(name=name, body=body), encoding="utf-8"
        )

    def test_all_plugins_observe_message_and_first_reply_wins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_plugin(root, "01-first", name="first", body="return 'first reply'")
            self.write_plugin(root, "02-second", name="second", body="return 'second reply'")
            manager = PluginManager(root)

            reply = manager.handle_group_message(
                chat_id="group",
                sender_id="u1",
                sender_name="user",
                content="hello",
                bot_name="bot",
            )

            self.assertEqual(reply, "first reply")
            self.assertEqual(len(manager.plugins), 2)
            self.assertEqual(len(manager.plugins[0].instance.received), 1)
            self.assertEqual(len(manager.plugins[1].instance.received), 1)
            self.assertTrue(manager.plugins[0].instance.received[0]["is_group"])

    def test_broken_plugin_does_not_block_healthy_plugin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_plugin(root, "01-broken", name="broken", body="raise RuntimeError('boom')")
            self.write_plugin(root, "02-good", name="good", body="return 'ok'")
            logger = logging.getLogger("plugin-manager-test")
            with self.assertLogs(logger, level="ERROR") as captured:
                manager = PluginManager(root, logger=logger)
                reply = manager.handle_group_message(
                    chat_id="group",
                    sender_id="u1",
                    sender_name="user",
                    content="private message body",
                )

            self.assertEqual(reply, "ok")
            joined = "\n".join(captured.output)
            self.assertIn("broken", joined)
            self.assertNotIn("private message body", joined)

    def test_invalid_plugin_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            invalid = root / "invalid"
            invalid.mkdir()
            (invalid / "dream_plugin.py").write_text("value = 1\n", encoding="utf-8")
            manager = PluginManager(root)
            self.assertEqual(manager.plugins, [])


if __name__ == "__main__":
    unittest.main()
