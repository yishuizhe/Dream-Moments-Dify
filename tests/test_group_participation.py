import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from services.group_participation import GroupParticipation, GroupPolicySettings
from handlers.message import MessageHandler


class ParticipationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.policy = GroupParticipation(
            GroupPolicySettings(enabled=True, sample_probability=0),
            clock=lambda: self.now, rng=lambda: 1,
        )

    def observe(self, text="离谱但确实发生了", sender="a", group="g", **kwargs):
        return self.policy.observe(group, sender, sender, text, **kwargs)

    def test_two_different_members_repeat_once(self):
        self.observe("下班了", "a")
        candidate = self.observe("下班了", "b")
        self.assertEqual(candidate["action"], "repeat")
        self.assertTrue(self.policy.commit("g", candidate, "repeat"))
        self.assertIsNone(self.observe("下班了", "c"))
        self.now += 61
        self.assertIsNone(self.observe("下班了", "d"))

    def test_same_member_cannot_start_repeat_chain(self):
        self.observe("下班了", "a")
        self.assertIsNone(self.observe("下班了", "a"))

    def test_repeat_detection_and_limits_are_scoped_to_group(self):
        self.observe("下班了", "a", "g1")
        self.assertIsNone(self.observe("下班了", "b", "g2"))
        candidate = self.observe("下班了", "b", "g1")
        self.assertTrue(self.policy.commit("g1", candidate, "repeat"))
        self.assertEqual(self.observe("下班了", "a", "g2")["action"], "repeat")

    def test_old_or_nonconsecutive_messages_do_not_trigger_repeat(self):
        self.observe("下班了", "a")
        self.now += 121
        self.assertIsNone(self.observe("下班了", "b"))
        self.observe("回家了", "c")
        self.assertIsNone(self.observe("下班了", "d"))

    def test_explicit_messages_do_not_create_ambient_jobs(self):
        self.assertIsNone(self.observe(explicit=True))

    def test_system_notices_and_sensitive_strings_are_not_repeatable(self):
        for text in ('A拍了拍B', '[图片]', '验证码123456', '电话13800138000',
                     '/status', 'https://example.com', '<sysmsg>test</sysmsg>', '@其他人 你好'):
            with self.subTest(text=text):
                self.assertFalse(self.policy.repeatable(text))

    def test_new_message_or_bot_reply_cancels_pending_decision(self):
        candidate = self.observe()
        self.observe("知道了", "b")
        self.assertFalse(self.policy.commit("g", candidate, "chat"))
        self.now += 21
        candidate = self.observe()
        self.policy.note_bot_reply("g", "我已经回了")
        self.assertFalse(self.policy.commit("g", candidate, "chat"))

    def test_slow_decisions_are_dropped(self):
        candidate = self.observe()
        self.now += 31
        self.assertFalse(self.policy.commit("g", candidate, "chat"))

    def test_hourly_cap_covers_repeat_and_chat(self):
        self.policy.settings.max_per_hour = 1
        candidate = self.observe()
        self.assertTrue(self.policy.commit("g", candidate, "chat"))
        self.now += 61
        self.assertIsNone(self.observe("竟然真的把门拆了换新门"))

    def test_disabled_policy_never_produces_actions(self):
        self.policy.settings.enabled = False
        self.assertIsNone(self.observe())

    def test_model_gate_output_is_strict_and_context_is_cleared(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler.ai = Mock()
        for output, expected in [('{"action":"repeat"}', 'repeat'),
                                 ('{"action":"chat"}', 'chat'),
                                 ('好的，我来聊一句', 'pass'),
                                 ('{"action":"send_to_other_group"}', 'pass')]:
            handler.ai.get_response.return_value = output
            self.assertEqual(handler.decide_group_participation('A：聊天数据', '当前消息'), expected)
        self.assertEqual(handler.ai.clear_history.call_count, 4)

    def test_async_worker_does_not_block_polling_and_rechecks_staleness(self):
        started, finish, ended = threading.Event(), threading.Event(), threading.Event()
        candidate = self.observe()
        called = Mock()
        def decide(*_):
            started.set()
            finish.wait(2)
            ended.set()
            return 'chat'
        self.assertTrue(self.policy.submit('g', candidate, decide, called))
        self.assertTrue(started.wait(1))
        self.assertFalse(self.policy.submit('g', candidate, decide, called))
        self.observe('话题已经变了', 'b')
        finish.set()
        self.assertTrue(ended.wait(1))
        # Synchronize on the worker slot rather than sleep.
        self.assertTrue(self.policy._worker.acquire(timeout=1))
        called.assert_not_called()
        self.policy._worker.release()

    def test_repeat_does_not_wait_for_another_groups_model_request(self):
        self.observe('下班了', 'a')
        candidate = self.observe('下班了', 'b')
        sent = threading.Event()
        self.policy._worker.acquire()
        try:
            self.assertTrue(self.policy.submit('g', candidate, Mock(), lambda _: sent.set()))
            self.assertTrue(sent.wait(1))
        finally:
            self.policy._worker.release()


class ChatBotIntegrationTests(unittest.TestCase):
    def make_bot(self):
        import main
        history = Mock()
        history.register_chat_identity.return_value = 'g@chatroom'
        handler = Mock()
        handler.queue_lock = threading.Lock()
        handler.user_queues = {}
        wx = Mock()
        wx.get_my_name.return_value = 'Claude'
        wx.is_recent_sent_text.return_value = False
        plugins = Mock()
        plugins.handle_group_message.return_value = None
        bot = main.ChatBot(handler, Mock(), wx, plugin_manager=plugins, history_store=history)
        bot.group_participation = GroupParticipation(GroupPolicySettings(enabled=True, sample_probability=0))
        return bot, handler, history, wx

    def message(self, content, sender='wxid_a', **kwargs):
        return SimpleNamespace(sender=sender, sender_id=sender, content=content,
                               chat_id='g@chatroom', is_self=False, type='文本', **kwargs)

    def test_poke_notice_is_not_a_human_message_or_memory(self):
        bot, handler, history, wx = self.make_bot()
        bot.handle_wxauto_message(self.message('“A”拍了拍“B”'), '群名', True)
        history.record_message.assert_not_called()
        history.remember_user_message.assert_not_called()
        wx.send_text.assert_not_called()

    def test_explicit_group_reply_and_memory_keep_stable_group_scope(self):
        bot, handler, history, wx = self.make_bot()
        with patch('main.threading.Timer'):
            bot.handle_wxauto_message(self.message('Claude 你好'), '群名', True)
        queue = next(iter(bot.user_queues.values()))
        self.assertEqual(queue['reply_target'], 'g@chatroom')
        self.assertEqual(history.remember_user_message.call_args.kwargs['identity_key'],
                         'group:g@chatroom:member:wxid_a')

    def test_two_people_repeat_to_originating_group_without_ai_generation(self):
        bot, handler, history, wx = self.make_bot()
        sent = threading.Event()
        wx.send_text.side_effect = lambda *_: sent.set()
        bot.handle_wxauto_message(self.message('下班了', 'a'), '群名', True)
        bot.handle_wxauto_message(self.message('下班了', 'b'), '群名', True)
        self.assertTrue(sent.wait(2))
        wx.send_text.assert_called_once_with('g@chatroom', '下班了')
        handler.decide_group_participation.assert_not_called()

    def test_human_question_about_poking_is_not_a_system_notice(self):
        bot, handler, history, wx = self.make_bot()
        with patch('main.threading.Timer'):
            bot.handle_wxauto_message(self.message('Claude 你刚才为什么拍了拍我'), '群名', True)
        history.record_message.assert_called_once()
        self.assertEqual(len(bot.user_queues), 1)


if __name__ == '__main__':
    unittest.main()
