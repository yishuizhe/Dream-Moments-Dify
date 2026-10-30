from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wechat.replica_compat import (
    _room_member_display_names,
    ReplicaWeChatClient,
    _merge_search_ocr_rows,
    _ocr_name_similarity,
    _safe_ocr_name_matches,
    _search_result_click_point,
    _select_search_result,
    _search_ocr_name_matches,
    _title_ocr_name_matches,
    _uia_chat_title,
)


class ReplicaCompatibilityTests(unittest.TestCase):
    def test_group_nicknames_are_read_from_room_specific_protobuf(self):
        member = b"\x0a\x06wxid_a\x12\x06" + "群名".encode("utf-8") + b"\x18\x01"
        blob = b"\x0a" + bytes([len(member)]) + member
        self.assertEqual(_room_member_display_names(blob), {"wxid_a": "群名"})
        self.assertEqual(_room_member_display_names(blob[:-1]), {})
        self.assertEqual(_room_member_display_names(b"\x0a\xff"), {})

    def setUp(self):
        # Unit tests must not consume the real account's persisted write budget.
        gate = patch("wechatauto.rhythm.gate")
        self.gate = gate.start()
        self.addCleanup(gate.stop)

    def make_client(self):
        db = MagicMock()
        db.get_self_info.return_value = {
            "username": "wxid_self",
            "nick_name": "娜娜",
            "remark": "",
        }
        with patch("wechatauto.WeChatDB", return_value=db):
            client = ReplicaWeChatClient()
        return client, db

    def test_poke_appmsg_does_not_reuse_another_groups_contact_as_human(self):
        client, db = self.make_client()
        client._current_username = 'target@chatroom'
        client._current_name = '本群'
        db.get_nickname.return_value = '外群成员甲'
        message = client._convert_message({
            'sender_id': 17, 'sender_username': 'wxid_other_group', 'type': '应用消息',
            'content': '<msg><appmsg><title>"A" 拍了拍 "B"</title><type>62</type></appmsg></msg>',
        })
        self.assertEqual(message.attr, 'system')

    def test_group_poke_never_selects_a_random_members_avatar(self):
        client, db = self.make_client()
        client._name_to_username['测试群'] = 'g@chatroom'
        client._uia_sender = MagicMock()
        self.assertFalse(client.Poke('测试群'))
        client._uia_sender.open_chat.assert_not_called()

    def test_same_title_different_group_ids_abort_before_ui(self):
        client, db = self.make_client()
        db.get_sessions.return_value = [{'username': 'g1@chatroom'}, {'username': 'g2@chatroom'}]
        db.get_nickname.return_value = '同名群'
        client._uia_sender = MagicMock()
        with self.assertRaisesRegex(RuntimeError, '同名会话'):
            client._open_send_target('同名群', 'g1@chatroom')
        client._uia_sender.open_chat.assert_not_called()

    def test_stable_group_id_is_preserved_while_display_name_changes(self):
        client, db = self.make_client()
        client._name_to_username['旧群名'] = 'g@chatroom'
        client._username_to_name['g@chatroom'] = '旧群名'
        db.get_nickname.return_value = '新群名'
        db.get_sessions.return_value = [{'username': 'g@chatroom'}]
        db.search_contact.return_value = []
        sender = MagicMock()
        sender.open_chat.return_value = True
        sender._chat_is_open.return_value = True
        sender.right_pane_left, sender.render_h, sender.render_w = 200, 800, 1000
        client._uia_sender = sender
        with patch('wechat.replica_compat.time.sleep'):
            self.assertTrue(client.SendMsg('你好', 'g@chatroom'))
        sender.open_chat.assert_called_once_with('新群名', exact=True, expected_group=True)

    def test_similar_chat_titles_never_confirm_sending(self):
        for observed in ['小明的群', '小明', '测试二群', '测试群聊']:
            self.assertFalse(_title_ocr_name_matches(observed, '测试群'))
        self.assertTrue(_title_ocr_name_matches('测试群 (42)', '测试群'))

    def test_reads_database_messages_in_chronological_order(self):
        client, db = self.make_client()
        db.search_contact.return_value = [
            {"username": "friend-id", "nick_name": "小明", "remark": ""}
        ]
        db.get_nickname.return_value = "小明"
        db.get_messages.return_value = [
            {"local_id": 2, "sort_seq": 20, "sender_id": 7, "type": "文本", "content": "后"},
            {"local_id": 1, "sort_seq": 10, "sender_id": 7, "type": "文本", "content": "前"},
        ]

        self.assertEqual(client.ChatWith("小明"), "小明")
        messages = client.GetAllMessage()
        self.assertEqual([item.content for item in messages], ["前", "后"])
        self.assertEqual(messages[0].sender, "小明")

    def test_persisted_id_follows_a_group_rename(self):
        client, db = self.make_client()
        client.BindContactId("旧群名", "room@chatroom")
        db.get_nickname.return_value = "新群名"

        self.assertEqual(client.ChatWith("旧群名"), "新群名")
        self.assertEqual(client.ChatInfo()["chat_id"], "room@chatroom")
        self.assertEqual(client.ChatInfo()["chat_name"], "新群名")

    def test_private_message_direction_matches_wechat_4_1_12_database(self):
        client, db = self.make_client()
        db.search_contact.return_value = [
            {"username": "friend-id", "nick_name": "小明", "remark": ""}
        ]
        db.get_nickname.return_value = "小明"
        db.get_messages.return_value = [
            {"local_id": 2, "sort_seq": 20, "sender_id": 1, "type": "文本", "content": "我发的"},
            {"local_id": 1, "sort_seq": 10, "sender_id": 2, "type": "文本", "content": "对方发的"},
        ]

        client.ChatWith("小明")
        incoming, outgoing = client.GetAllMessage()

        self.assertEqual(incoming.attr, "friend")
        self.assertEqual(outgoing.attr, "self")

    def test_group_sender_prefix_is_removed_and_resolved(self):
        client, db = self.make_client()
        db.search_contact.side_effect = lambda name: (
            [{"username": "room@chatroom", "nick_name": "测试群", "remark": ""}]
            if name == "测试群"
            else []
        )
        db.get_nickname.return_value = "小红"
        db.get_messages.return_value = [
            {
                "local_id": 3,
                "sort_seq": 30,
                "sender_id": 8,
                "sender_username": "wxid_red",
                "type": "文本",
                "content": "wxid_red:\n娜娜在吗",
            }
        ]

        client.ChatWith("测试群")
        message = client.GetAllMessage()[0]
        self.assertEqual(message.content, "娜娜在吗")
        self.assertEqual(message.sender, "小红")
        self.assertEqual(client.ChatInfo()["chat_type"], "group")

    def test_group_sender_prefix_overrides_stale_numeric_sender_mapping(self):
        client, db = self.make_client()
        client.BindContactId("测试群", "room@chatroom")
        db.get_nickname.side_effect = lambda username: {
            "wxid_stale": "错误昵称",
            "wxid_actual": "真实昵称",
            "room@chatroom": "测试群",
        }.get(username, username)
        db.get_messages.return_value = [
            {
                "local_id": 6,
                "sort_seq": 60,
                "sender_id": 19,
                "sender_username": "wxid_stale",
                "type": "文本",
                "content": "wxid_actual:\n娜娜",
            }
        ]

        client.ChatWith("测试群")
        message = client.GetAllMessage()[0]

        self.assertEqual(message.sender_id, "wxid_actual")
        self.assertEqual(message.sender, "真实昵称")
        self.assertEqual(message.content, "娜娜")

    def test_group_sender_prefix_overrides_ambiguous_self_direction(self):
        client, db = self.make_client()
        client.BindContactId("测试群", "room@chatroom")
        db.get_nickname.side_effect = lambda username: (
            "成员" if username == "wxid_member" else "测试群"
        )
        db.get_messages.return_value = [
            {
                "local_id": 4,
                "sort_seq": 40,
                "sender_id": 2,
                "sender_username": "",
                "type": "文本",
                "content": "wxid_member:\n娜娜，出来吧",
            }
        ]

        client.ChatWith("测试群")
        message = client.GetAllMessage()[0]

        self.assertEqual(message.attr, "friend")
        self.assertEqual(message.sender, "成员")
        self.assertEqual(message.content, "娜娜，出来吧")

    def test_group_sender_id_one_is_local_account(self):
        client, db = self.make_client()
        client.BindContactId("测试群", "room@chatroom")
        db.get_nickname.return_value = "测试群"
        db.get_messages.return_value = [
            {
                "local_id": 5,
                "sort_seq": 50,
                "sender_id": 1,
                "type": "文本",
                "content": "我在群里发的",
            }
        ]

        client.ChatWith("测试群")
        self.assertEqual(client.GetAllMessage()[0].attr, "self")

    def test_resolved_member_id_one_is_not_the_local_account(self):
        client, _db = self.make_client()
        client._current_username = "room@chatroom"
        message = client._convert_message({
            "sender_id": 1, "sender_username": "wxid_member",
            "type": "图片", "content": "[图片]",
        })
        self.assertEqual(message.attr, "friend")
        self.assertEqual(message.sender_id, "wxid_member")

    def test_missing_sender_two_is_resolved_from_actual_database_index(self):
        client, db = self.make_client()
        client._current_username = "room@chatroom"
        db._sender_id_index.return_value = {2: "wxid_member", 17: "wxid_self"}
        for message_type in ("图片", "语音", "文件", "动画表情"):
            with self.subTest(message_type=message_type):
                message = client._convert_message({
                    "sender_id": 2, "sender_username": "",
                    "type": message_type, "content": "[媒体]",
                })
                self.assertEqual(message.attr, "friend")
                self.assertEqual(message.sender_id, "wxid_member")
        outgoing = client._convert_message({"sender_id": 17, "content": "我发的"})
        self.assertEqual(outgoing.attr, "self")
        self.assertEqual(outgoing.sender_id, "wxid_self")

    def test_resolved_private_sender_overrides_numeric_direction(self):
        client, _db = self.make_client()
        client._current_username = "wxid_friend"
        incoming = client._convert_message({
            "sender_id": 1, "sender_username": "wxid_friend", "content": "你好",
        })
        outgoing = client._convert_message({
            "sender_id": 19, "sender_username": "wxid_self", "content": "你好",
        })
        self.assertEqual(incoming.attr, "friend")
        self.assertEqual(outgoing.attr, "self")

    def test_self_group_prefix_is_stripped_and_does_not_trigger_a_reply(self):
        client, _db = self.make_client()
        client._current_username = "room@chatroom"
        message = client._convert_message({
            "sender_id": 19, "sender_username": "wxid_stale",
            "content": "wxid_self:\n我在群里发的",
        })
        self.assertEqual(message.attr, "self")
        self.assertEqual(message.content, "我在群里发的")

    def make_gui(self):
        client, _db = self.make_client()
        with patch("wechatauto.guia.WeChatGUI.__init__", return_value=None):
            return client._sender

    def test_send_confirmation_reads_header_after_input_name_becomes_draft(self):
        gui = self.make_gui()
        driver = MagicMock()
        driver.current_chat.return_value = '这段是待发送的回复，不是聊天名'
        gui._get_uia = MagicMock(return_value=driver)
        gui.ocr_zoomed = MagicMock()
        with patch('wechat.replica_compat._uia_chat_title', return_value='测试联系人'):
            self.assertTrue(gui._chat_is_open('测试联系人'))
        driver.current_chat.assert_not_called()
        gui.ocr_zoomed.assert_not_called()

    def test_wrong_header_cannot_be_overridden_by_input_or_ocr(self):
        gui = self.make_gui()
        gui._get_uia = MagicMock(return_value=MagicMock())
        gui.ocr_zoomed = MagicMock()
        with patch('wechat.replica_compat._uia_chat_title', return_value='其他人'):
            self.assertFalse(gui._chat_is_open('测试联系人'))
        gui.ocr_zoomed.assert_not_called()

    def test_header_reader_uses_exact_title_anchor(self):
        driver = MagicMock()
        header = MagicMock()
        header.Name = '测试群'
        with patch('wechatauto.uia_driver._find_by', return_value=header) as find:
            self.assertEqual(_uia_chat_title(driver), '测试群')
        predicate = find.call_args.args[1]
        self.assertTrue(predicate(type('C', (), {'AutomationId': 'content.title.current_chat_name_label'})()))
        self.assertFalse(predicate(type('C', (), {'AutomationId': 'chat_input_field'})()))

    def test_uia_refresh_is_forwarded_to_upstream(self):
        gui = self.make_gui()
        with patch("wechatauto.guia.WeChatGUI._get_uia", return_value="driver") as getter:
            self.assertEqual(gui._get_uia(refresh=True), "driver")
        getter.assert_called_once_with(refresh=True)

    def test_uia_accepts_english_main_window_title(self):
        from wechatauto import uia_driver

        gui = self.make_gui()
        with patch.object(uia_driver, "MAIN_NAMES", ("微信", "Weixin")), \
             patch.object(uia_driver, "MAIN_NAME_HINTS", ("微信", "Weixin")), \
             patch("wechatauto.guia.WeChatGUI._get_uia", return_value=None):
            gui._get_uia()
            self.assertTrue(uia_driver._title_is_main("WeChat"))
            self.assertTrue(uia_driver._title_is_main("WeChat (1)"))
            self.assertFalse(uia_driver._title_is_main("Unrelated window"))

    def test_desktop_probe_handles_removed_upstream_method_and_black_screen(self):
        from PIL import Image

        gui = self.make_gui()
        gui.is_alive = MagicMock(return_value=True)
        gui.render_rect = (0, 0, 32, 32)
        gui._grab_screen = MagicMock(return_value=Image.new("RGB", (32, 32), "white"))
        self.assertTrue(gui.desktop_available())
        gui._grab_screen.return_value = Image.new("RGB", (32, 32), "black")
        self.assertFalse(gui.desktop_available())
        gui._grab_screen.side_effect = OSError("desktop locked")
        self.assertFalse(gui.desktop_available())

    def test_collapsed_search_uses_uia_and_aborts_if_paste_lands_in_chat(self):
        gui = self.make_gui()
        gui.render_h = 800
        gui._update_render_rect = MagicMock()
        uia = MagicMock()
        gui._get_uia = MagicMock(return_value=uia)
        gui._input = MagicMock()
        gui.set_clipboard = MagicMock()
        gui._typed_into_chat_input = MagicMock(return_value=True)
        gui.ocr_zoomed = MagicMock()
        with patch("wechat.replica_compat.time.sleep"):
            self.assertFalse(gui._search_chat("测试群", expected_group=True))
        uia.back_to_chat_tab.assert_called_once()
        uia._search_box.assert_called_once_with(uia._win, expand=True)
        uia._click_ctrl.assert_called_once()
        gui.ocr_zoomed.assert_not_called()
        self.assertNotIn(0x46, [call.args[0] for call in gui._input.key.call_args_list])

    def test_session_fields_match_polling_adapter(self):
        client, db = self.make_client()
        db.get_nickname.return_value = "小明"
        db.get_sessions.return_value = [
            {"username": "friend-id", "summary": "你好", "last_time": 123, "unread": 2}
        ]
        self.assertEqual(
            client.GetSession()[0],
            {
                "name": "小明",
                "username": "friend-id",
                "content": "你好",
                "time": 123,
                "unread_count": 2,
            },
        )

    def test_sidebar_ocr_accepts_one_clipped_group_name_edge(self):
        self.assertTrue(
            _safe_ocr_name_matches("以开心摸鱼小分", "开心摸鱼小分队")
        )
        self.assertFalse(_safe_ocr_name_matches("小明", "开心摸鱼小分队"))

    def test_search_ocr_accepts_one_wrong_character_but_not_another_chat(self):
        self.assertTrue(_search_ocr_name_matches("开芯摸鱼小分队", "开心摸鱼小分队"))
        self.assertFalse(_search_ocr_name_matches("小明", "开心摸鱼小分队"))

    def test_best_search_match_tolerates_multiple_long_name_ocr_errors(self):
        target = "开心摸鱼小分队"
        self.assertGreater(_ocr_name_similarity("开芯摸鱼小分対", target), 0.55)
        self.assertLess(_ocr_name_similarity("完全不同的群聊", target), 0.55)

    def test_search_ocr_scales_keep_clearer_text_and_missing_headings(self):
        merged = _merge_search_ocr_rows(
            [
                [("能@0赤霄安", 87, 129, 32, 10)],
                [
                    ("赤霄安", 88, 129, 12, 12),
                    ("群聊", 84, 275, 11, 10),
                ],
            ],
            "赤霄安全实验室",
        )

        self.assertEqual(merged[0][0], "赤霄安")
        self.assertIn(("群聊", 84, 275, 11, 10), merged)

    def test_title_match_rejects_one_glyph_error_in_send_confirmation(self):
        self.assertFalse(_title_ocr_name_matches("开芯摸鱼小分队（8）", "开心摸鱼小分队"))
        self.assertTrue(_title_ocr_name_matches("开心摸鱼小分队（8）", "开心摸鱼小分队"))
        self.assertFalse(_title_ocr_name_matches("完全不同的群聊", "开心摸鱼小分队"))

    def test_same_name_search_selects_group_from_member_preview(self):
        rows = [
            ("张小明", 128, 117, 14, 12),
            ("包含：张小明〔企业：赤霄安全", 128, 142, 12, 11),
            ("@赤霄安全实验室", 177, 215, 23, 11),
            ("企业：赤霄安全实验室", 128, 238, 12, 11),
            ("群聊", 84, 275, 12, 11),
            ("能@0赤霄安", 87, 321, 32, 10),
            ("搜索网络结果", 85, 372, 14, 10),
        ]

        selected = _select_search_result(
            rows,
            "赤霄安全实验室",
            sidebar_right=261,
            render_h=815,
            expected_group=True,
        )
        self.assertEqual(selected, rows[5])

    def test_same_name_search_prefers_unique_group_in_most_used_section(self):
        rows = [
            ("最常便用", 84, 83, 12, 11),
            ("赤霄安", 128, 129, 12, 12),
            ("包含：张小明〔企业：", 128, 205, 12, 11),
            ("@赤霄安全实验室", 177, 278, 23, 11),
            ("企业：赤霄安全实验室", 128, 301, 12, 11),
            ("搜索网络结果", 84, 340, 14, 10),
        ]

        selected = _select_search_result(
            rows,
            "赤霄安全实验室",
            sidebar_right=221,
            render_h=815,
            expected_group=True,
        )

        self.assertEqual(selected, rows[1])

    def test_same_name_search_accepts_runtime_group_row_at_x_87(self):
        rows = [
            ("最常便用", 84, 83, 12, 11),
            ("生@0赤霄安全实验室", 87, 129, 32, 10),
            ("张小明0", 127, 181, 14, 12),
            ("包含：张小明〔企业：赤霄安全实验室", 128, 206, 12, 11),
            ("@赤霄安全实验室", 177, 279, 23, 11),
            ("企业：赤霄安全实验室", 128, 302, 12, 11),
        ]

        selected = _select_search_result(
            rows,
            "赤霄安全实验室",
            sidebar_right=300,
            render_h=815,
            expected_group=True,
        )

        self.assertEqual(selected, rows[1])

    def test_most_used_section_does_not_expand_to_distant_contains_marker(self):
        rows = [
            ("最常便用", 84, 83, 12, 11),
            ("生@0赤霄安全实验室", 87, 129, 32, 10),
            ("张小明", 128, 213, 14, 12),
            ("@赤霄安全实验室", 177, 215, 23, 11),
            ("企业：赤霄安全实验室", 128, 238, 12, 11),
            ("群聊", 84, 275, 11, 10),
            ("包含：张小明〔企业：赤霄安全实验室", 128, 334, 12, 11),
        ]

        selected = _select_search_result(
            rows,
            "赤霄安全实验室",
            sidebar_right=300,
            render_h=815,
            expected_group=True,
        )

        self.assertEqual(selected, rows[1])

    def test_search_result_click_uses_text_area_not_avatar(self):
        row = ("生@0赤霄安全实验室", 87, 129, 32, 10)

        self.assertEqual(_search_result_click_point(row, 300), (165, 134))

    def test_filehelper_search_ignores_identical_web_result(self):
        rows = [
            ("搜索网络结果", 85, 84, 14, 10),
            ("文件传输助手", 86, 113, 12, 12),
            ("功能", 84, 149, 11, 11),
            ("功能", 84, 150, 11, 11),
            ("文件传输助手", 128, 196, 14, 12),
        ]
        self.assertEqual(_select_search_result(
            rows, "文件传输助手", sidebar_right=300,
            render_h=815, expected_group=False,
        ), rows[4])
        self.assertIsNone(_select_search_result(
            rows[:2], "文件传输助手", sidebar_right=300,
            render_h=815, expected_group=False,
        ))

    def test_same_name_search_selects_non_group_contact(self):
        rows = [
            ("@赤霄安全实验室", 177, 215, 23, 11),
            ("企业：赤霄安全实验室", 128, 238, 12, 11),
            ("群聊", 84, 275, 12, 11),
            ("赤霄安全实验室", 128, 321, 12, 12),
        ]

        selected = _select_search_result(
            rows,
            "赤霄安全实验室",
            sidebar_right=261,
            render_h=815,
            expected_group=False,
        )
        self.assertEqual(selected, rows[1])

    def test_multiple_same_name_groups_are_rejected(self):
        rows = [
            ("群聊", 84, 80, 40, 12),
            ("同名群聊", 100, 120, 40, 12),
            ("同名群聊", 100, 180, 40, 12),
            ("搜索网络结果", 84, 230, 40, 12),
        ]

        self.assertIsNone(
            _select_search_result(
                rows,
                "同名群聊",
                sidebar_right=261,
                render_h=815,
                expected_group=True,
            )
        )

    def test_text_send_requires_target_and_starts_database_audit(self):
        client, _db = self.make_client()
        sender = MagicMock()
        sender.open_chat.return_value = True
        sender._chat_is_open.return_value = True
        sender.right_pane_left = 200
        sender.render_h = 800
        sender.render_w = 1000
        sender.focus_input.return_value = True
        client._uia_sender = sender
        client._resolve_username = MagicMock(return_value="room@chatroom")

        self.assertTrue(client.SendMsg("你好", "测试群"))

        sender.open_chat.assert_called_once_with(
            "测试群", exact=True, expected_group=True
        )
        self.assertEqual(sender._chat_is_open.call_count, 3)
        self.gate.assert_called_once_with("send")

    def test_file_send_uses_upstream_write_gate_before_opening_target(self):
        client, _db = self.make_client()
        client._resolve_username = MagicMock(return_value="room@chatroom")
        client._open_send_target = MagicMock(side_effect=RuntimeError("stop before input"))
        with self.assertRaisesRegex(RuntimeError, "stop before input"):
            client.SendFiles(str(ROOT / "README.md"), "测试群")
        self.gate.assert_called_once_with("send-file")

    def test_text_send_aborts_if_target_changes_before_enter(self):
        client, _db = self.make_client()
        sender = MagicMock()
        sender.open_chat.return_value = True
        sender._chat_is_open.side_effect = [True, True, False]
        sender.right_pane_left = 200
        sender.render_h = 800
        sender.render_w = 1000
        sender.focus_input.return_value = True
        client._uia_sender = sender
        client._resolve_username = MagicMock(return_value="room@chatroom")

        with self.assertRaisesRegex(RuntimeError, "输入过程中发生变化"):
            client.SendMsg("不能发错", "测试群")

        keys = sender._input.key.call_args_list
        self.assertGreaterEqual(len(keys), 5)
        self.assertNotIn(13, [call.args[0] for call in keys])

if __name__ == "__main__":
    unittest.main()
