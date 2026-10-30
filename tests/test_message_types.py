import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from wechat.message_types import is_poke_notice
from wechat.adapter import WxAuto4PollingAdapter

POKE = '<msg><appmsg appid=""><title>"测试成员" 拍了拍 "Claude"</title><type>62</type></appmsg></msg>'


class MessageTypeTests(unittest.TestCase):
    def test_poke_app_message_is_system_even_without_a_system_type_label(self):
        self.assertTrue(is_poke_notice(POKE))
        self.assertTrue(is_poke_notice('<?xml version="1.0"?>' + POKE))
        self.assertTrue(is_poke_notice('wxid_sender:\n' + POKE))
        self.assertTrue(is_poke_notice('<sysmsg type="pat"><patmsg/></sysmsg>'))

    def test_discussing_poking_or_ordinary_links_stays_human_text(self):
        for content in ['Claude 你为什么拍了拍我', '今天我拍了拍他',
                        '<msg><appmsg><title>拍一拍介绍</title><type>5</type></appmsg></msg>',
                        '<msg><appmsg><type>62', '']:
            self.assertFalse(is_poke_notice(content), content)

    def test_poke_with_another_groups_sender_id_is_not_dispatched(self):
        adapter = WxAuto4PollingAdapter([], wechat_factory=lambda: None)
        adapter.get_my_name = lambda: 'Claude'
        raw = SimpleNamespace(content=POKE, sender='外群成员甲', sender_id='wxid_other_group',
                              type='应用消息', attr='friend')
        normalized = adapter._normalize_message('本群', raw, is_group_chat=True,
                                                stable_chat_id='target@chatroom')
        self.assertIsNotNone(normalized)
        self.assertFalse(normalized.incoming_human)


if __name__ == '__main__':
    unittest.main()
