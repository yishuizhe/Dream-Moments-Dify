import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from handlers.message import MessageHandler
from services.dialogue_memory import DialogueMemory, turn_kind
from services.group_participation import GroupParticipation, GroupPolicySettings
from wechat.adapter import WxAuto4PollingAdapter
from wechat.message_types import conversation_text, quote_metadata
from services.database import HistoryStore


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.policy = GroupParticipation(GroupPolicySettings(enabled=True, sample_probability=0),
                                         clock=lambda: self.now, rng=lambda: 1)
        self.policy.note_bot_reply('g', '手动刮胡刀也行', sender_id='a')
        self.now += 5

    def message(self, text='怎么用', sender='a', group='g', **kwargs):
        return self.policy.observe(group, sender, sender, text, **kwargs)

    def test_short_followup_bypasses_ambient_cooldown_and_minimum_length(self):
        candidate = self.message()
        self.assertEqual(candidate['mode'], 'followup')
        self.assertTrue(self.policy.commit('g', candidate, 'chat'))
        self.assertEqual(len(self.policy._state('g')['sent']), 0)
        self.assertEqual(len(self.policy._state('g')['continuations']), 1)

    def test_exhausted_ambient_budget_does_not_end_an_active_conversation(self):
        self.policy.settings.max_per_hour = 0
        self.assertEqual(self.message('然后呢')['mode'], 'followup')

    def test_immediate_and_detailed_feedback_is_not_filtered_as_a_repeat(self):
        self.now = 1000.1
        candidate = self.message('你理解错了，' + '我说的是手动的那种。' * 20)
        self.assertEqual(candidate['mode'], 'followup')
        self.assertTrue(self.policy.commit('g', candidate, 'chat'))

    def test_reply_to_another_person_does_not_enter_our_thread(self):
        self.assertIsNone(self.message('怎么用', reply_to_other=True))
        self.assertIsNone(self.message('@别人 怎么用'))

    def test_other_group_or_uninvolved_member_is_not_a_followup(self):
        self.assertIsNone(self.message('怎么用', group='other'))
        self.assertIsNone(self.message('明天八点开会', sender='b'))

    def test_mere_acknowledgement_does_not_force_a_reply(self):
        for text in ('嗯嗯', '好', '哈哈哈'):
            self.assertIsNone(self.message(text))

    def test_continuation_window_expires(self):
        self.now += 181
        self.assertIsNone(self.message('然后呢'))

    def test_followup_budget_prevents_a_fast_unbounded_loop(self):
        self.policy.settings.followup_max_per_minute = 2
        for _ in range(2):
            candidate = self.message('为什么')
            self.assertTrue(self.policy.commit('g', candidate, 'chat'))
            self.policy.note_bot_reply('g', '新的解释', sender_id='a')
            self.now += 4
        self.assertIsNone(self.message('然后呢'))

    def test_automated_repeat_does_not_open_a_conversation_thread(self):
        self.policy.note_bot_reply('g', '同文跟读', sender_id='a', kind='repeat')
        self.now += 5
        self.assertIsNone(self.message('然后呢'))

    def test_followup_gate_cannot_turn_into_an_extra_repeat_rule(self):
        candidate = self.message()
        self.assertFalse(self.policy.commit('g', candidate, 'repeat'))

    def test_inflight_followup_keeps_latest_short_message_instead_of_losing_it(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        sent = []
        first = self.message('手动刮怎么样')
        def gate(_context, text):
            if text == '手动刮怎么样':
                started.set()
                release.wait(3)
            return 'chat'
        self.policy.submit('g', first, gate, lambda _: sent.append(first['text']))
        self.assertTrue(started.wait(2))
        self.now += 1
        latest = self.message('怎么用')
        def send_latest(_):
            sent.append(latest['text'])
            finished.set()
        self.policy.submit('g', latest, gate, send_latest)
        release.set()
        self.assertTrue(finished.wait(3))
        self.assertEqual(sent, ['怎么用'])

    def test_explicit_trigger_supersedes_pending_followup(self):
        candidate = self.message()
        self.message('Claude 重新说一下', explicit=True)
        self.assertFalse(self.policy.commit('g', candidate, 'chat'))


class InteractionProgressTests(unittest.TestCase):
    def test_closing_feedback_is_scoped_to_member_and_group_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'notes.json'
            memory = DialogueMemory(path)
            memory.observe('g', 'a', '你非得揪着那个咒语不放了？')
            memory = DialogueMemory(path)
            self.assertIn('咒语', memory.context('g', 'a', '下班啦'))
            self.assertNotIn('咒语', memory.context('g', 'b', '下班啦'))
            self.assertNotIn('咒语', memory.context('other', 'a', '下班啦'))
            self.assertIn('不要把之前的斗嘴', memory.context('g', 'a', '下班啦'))

    def test_current_explicit_topic_can_be_reopened(self):
        memory = DialogueMemory()
        memory.observe('g', 'a', '别再提奶茶了')
        self.assertIn('奶茶', memory.context('g', 'a', '你好'))
        self.assertNotIn('以前表示不想', memory.context('g', 'a', '奶茶到底怎么点'))

    def test_completed_progress_is_remembered_without_resentment(self):
        memory = DialogueMemory()
        memory.observe('g', 'a', '那个问题已经解决了')
        self.assertIn('已经解决了', memory.context('g', 'a', '今天挺累'))
        self.assertNotIn('已经解决了', memory.context('other', 'a', '今天挺累'))
        memory.observe('g', 'a', '你怎么又乱说')
        self.assertNotIn('你怎么又乱说', json.dumps(memory._notes, ensure_ascii=False))

    def test_repeated_persona_motif_is_toned_down_without_banning_requested_topic(self):
        memory = DialogueMemory()
        memory.note_bot_reply('g', '是不是要借奶茶钱')
        memory.note_bot_reply('g', '夸我也不能抵奶茶钱')
        self.assertIn('最近已反复用过', memory.context('g', 'a', '你好聪明'))
        self.assertNotIn('最近已反复用过', memory.context('g', 'a', '奶茶好喝吗'))

    def test_feedback_and_ordinary_greetings_have_different_intents(self):
        self.assertEqual(turn_kind('下班啦。'), 'greeting')
        self.assertEqual(turn_kind('你理解错了'), 'correction')
        self.assertEqual(turn_kind('行了换个话题'), 'close_topic')


class QuoteAndSceneTests(unittest.TestCase):
    QUOTE = ('a123456789:\n<?xml version="1.0"?><msg><appmsg><title>然后呢</title><type>57</type>'
             '<refermsg><chatusr>wxid_bot</chatusr><displayname>群内小克</displayname>'
             '<content>手动刮也行</content></refermsg></appmsg></msg>')

    def test_legacy_account_prefix_and_xml_quote_are_parsed_as_a_reply(self):
        quote = quote_metadata(self.QUOTE)
        self.assertEqual(quote['reply'], '然后呢')
        self.assertEqual(quote['sender_id'], 'wxid_bot')
        adapter = WxAuto4PollingAdapter([], wechat_factory=lambda: None)
        adapter.get_my_name = lambda: 'Claude'
        raw = SimpleNamespace(sender='成员', sender_id='wxid_a', content=self.QUOTE,
                              type='应用消息', attr='friend')
        message = adapter._normalize_message('本群', raw, is_group_chat=True).message
        self.assertEqual(message.sender_id, 'wxid_a')
        self.assertEqual(message.content, '然后呢')
        self.assertTrue(message.is_quote)
        self.assertEqual(message.quoted_sender_id, 'wxid_bot')

    def test_media_transport_is_not_invented_image_understanding(self):
        self.assertEqual(conversation_text('<msg><img aeskey="private"/></msg>'), '[图片，未识别内容]')
        self.assertEqual(conversation_text('a123456789:\n你这个AI'), '你这个AI')
        self.assertIn('引用群内小克', conversation_text(self.QUOTE))

    def test_transcript_keeps_actual_bot_name_and_strips_transport_details(self):
        store = SimpleNamespace(get_recent_messages=lambda chat, limit: [
            {'role': 'assistant', 'sender_name': 'Claude', 'content': '接着说'},
            {'role': 'user', 'sender_name': 'A', 'content': self.QUOTE}])
        transcript = HistoryStore.format_recent_transcript(store, 'g', within_hours=None)
        self.assertIn('Claude：接着说', transcript)
        self.assertNotIn('娜娜', transcript)
        self.assertNotIn('<msg>', transcript)
        self.assertIn('A：然后呢（引用群内小克', transcript)

    def test_addressed_correction_is_acknowledged_even_if_model_would_pass(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler.ai = Mock()
        self.assertEqual(handler.decide_group_followup('机器人：继续这个梗', '别再提这个了'), 'chat')
        handler.ai.get_response.assert_not_called()

    def test_shared_group_scene_has_separate_person_memory_and_no_other_group(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler.ai_provider = 'openai_compatible'
        handler.prompt_content = 'persona'
        handler.ai = Mock()
        handler.ai.get_response.return_value = '回复'
        handler.history_store = Mock()
        handler.history_store.get_memory_items.return_value = []
        handler.history_store.format_recent_transcript.return_value = 'A：前一句\nB：接着前一句'
        for group, person in [('g', 'a'), ('g', 'b'), ('other', 'a')]:
            handler.get_api_response('当前消息', person, is_group=True, chat_id=group,
                                     sender_id=person, sender_name=person)
        calls = handler.ai.get_response.call_args_list
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertNotEqual(calls[0].args[1], calls[2].args[1])
        identities = [call.args[0] for call in handler.history_store.get_memory_items.call_args_list]
        self.assertEqual(identities, ['group:g:member:a', 'group:g:member:b', 'group:other:member:a'])

    def test_followup_does_not_hit_ordinary_eight_second_reply_suppression(self):
        handler = MessageHandler.__new__(MessageHandler)
        handler._reply_lock = threading.Lock()
        handler._last_reply_at, handler._last_reply_text = {}, {}
        handler.reply_cooldown_seconds, handler.duplicate_window_seconds = 8, 120
        self.assertFalse(handler._should_suppress_reply('g:a', '前一条'))
        self.assertFalse(handler._should_suppress_reply('g:a', '接着解释', allow_continuation=True))
        self.assertTrue(handler._should_suppress_reply('g:a', '接着解释', allow_continuation=True))


if __name__ == '__main__':
    unittest.main()
