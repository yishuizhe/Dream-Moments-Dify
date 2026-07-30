import random
from datetime import datetime
import threading
import time
import os
from services.database import HistoryStore, Session, ChatMessage, make_identity_key, resolve_identity
from config import config
from wechat.adapter import WxAuto4PollingAdapter
import re
from handlers.emoji import EmojiHandler
from handlers.image import ImageHandler
from handlers.message import MessageHandler
from handlers.voice import VoiceHandler
from handlers.image_recognition import (
    download_wechat_image,
    honest_image_failure_reply,
    is_image_message,
    is_image_placeholder,
    recognition_failed,
)
from plugins.manager import PluginManager
from services.ai.moonshot import MoonShotAI
from utils.cleanup import cleanup_pycache, CleanupUtils
from utils.logger import LoggerConfig
from colorama import init
from utils.console import print_status, print_banner
from utils.reply_formatter import split_summary_bubbles

# 获取项目根目录
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logger_config = LoggerConfig(root_dir)
logger = logger_config.setup_logger('main')
listen_list = config.user.listen_list
queue_lock = threading.Lock()  # 队列访问锁
user_queues = {}  # 用户消息队列管理
chat_contexts = {}  # 存储上下文
known_group_chats = set()  # 已确认的群聊会话名
# 初始化colorama
init()

def is_image_content(content: str | None) -> bool:
    return is_image_placeholder(content)


_IMAGE_REQUEST_MARKERS = (
    "看图",
    "看看图",
    "看一下图",
    "看下图",
    "看图片",
    "看看图片",
    "看一下图片",
    "识图",
    "图片里",
    "图里",
    "这张图",
    "这个图",
    "截图",
    "照片",
)
_IMAGE_REQUEST_TIMEOUT_SECONDS = 90.0


def is_explicit_image_request(content: str | None) -> bool:
    """Return whether the sender explicitly asked the bot to inspect an image."""
    compact = re.sub(r"\s+", "", str(content or "")).lower()
    return bool(compact) and any(marker in compact for marker in _IMAGE_REQUEST_MARKERS)


def is_visual_message(msg, content: str | None) -> bool:
    """Recognize visual message types without downloading or analysing them."""
    text = str(content or "").strip()
    return (
        is_image_message(msg, text)
        or is_image_placeholder(text)
        or "[动画表情]" in text
        or text in {"动画表情", "[动画表情]"}
    )


def strip_group_bot_mention(content: str, robot_name: str) -> tuple[str, bool]:
    """Strip bot mention and report whether the group message should trigger a reply.

    A bot name is an explicit group trigger wherever it occurs in the sentence.
    This accepts @娜娜、娜娜你好、请娜娜看图 and similar natural Chinese forms.
    """
    original = str(content or "")
    name = str(robot_name or "").strip()
    if not name or not original.strip():
        return original, False

    match = re.search(rf"[@＠]?\s*{re.escape(name)}", original)
    if match:
        cleaned = original[:match.start()] + original[match.end():]
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = cleaned.strip(" \t,，、:：;；")
        return cleaned, True

    return original, False



class ChatBot:
    def __init__(
        self,
        message_handler,
        moonshot_ai,
        wechat,
        plugin_manager=None,
        history_store=None,
    ):
        self.message_handler = message_handler
        self.moonshot_ai = moonshot_ai
        self.user_queues = {}  # 将user_queues移到类的实例变量
        self.queue_lock = threading.Lock()  # 将queue_lock也移到类的实例变量
        self._pending_visual_requests: dict[str, float] = {}
        
        # 获取机器人的微信名称
        self.wx = wechat
        self.robot_name = self.wx.get_my_name()
        self.plugin_manager = (
            plugin_manager
            if plugin_manager is not None
            else PluginManager(os.path.join(root_dir, "plugins"), logger=logger)
        )
        self.history_store = history_store or HistoryStore()
        logger.info(f"机器人名称: {self.robot_name}")

    def _has_pending_visual_request(self, queue_key: str) -> bool:
        with self.queue_lock:
            expires_at = self._pending_visual_requests.get(queue_key, 0.0)
            if expires_at <= time.monotonic():
                self._pending_visual_requests.pop(queue_key, None)
                return False
            return True

    def _request_visual(self, queue_key: str) -> None:
        with self.queue_lock:
            self._pending_visual_requests[queue_key] = (
                time.monotonic() + _IMAGE_REQUEST_TIMEOUT_SECONDS
            )

    def _consume_visual_request(self, queue_key: str) -> None:
        with self.queue_lock:
            self._pending_visual_requests.pop(queue_key, None)

    def process_user_messages(self, queue_key):
        """Forward a structured debounce batch to MessageHandler and process immediately."""
        try:
            with self.queue_lock:
                if queue_key not in self.user_queues:
                    return
                user_data = self.user_queues.pop(queue_key)
            messages = list(user_data.get("message_items") or [])
            if not messages:
                raw_messages = list(user_data.get("messages") or [])
                messages = [{
                    "content": str(item or ""),
                    "sender_name": user_data.get("sender_name", ""),
                    "sender_id": user_data.get("username", ""),
                    "timestamp": datetime.now(),
                    "is_group": bool(user_data.get("is_group", False)),
                } for item in raw_messages]
            if not messages:
                return
            latest = messages[-1]
            sender_name = str(latest.get("sender_name") or latest.get("sender_id") or "")
            username = str(latest.get("sender_id") or sender_name)
            is_group = bool(user_data.get("is_group", False))
            chat_id = str(user_data.get("chat_id") or str(queue_key).split("::member::", 1)[0])
            handler_key = f"{chat_id}::member::{username}" if is_group else str(chat_id)

            # Already debounced once in ChatBot; process now to avoid a second 5s delay
            # and to make voice/image replies more reliable.
            with self.message_handler.queue_lock:
                existing = self.message_handler.user_queues.get(handler_key)
                if existing and existing.get("timer"):
                    try:
                        existing["timer"].cancel()
                    except Exception:
                        pass
                self.message_handler.user_queues[handler_key] = {
                    "timer": None,
                    "messages": messages,
                    "sender_name": sender_name,
                    "username": username,
                    "is_group": bool(is_group),
                    "chat_id": str(chat_id),
                }
            logger.info(
                "开始处理消息队列 %s（%s条）",
                handler_key,
                len(messages),
            )
            self.message_handler.process_messages(handler_key)
        except Exception as exc:
            logger.error("处理消息队列失败: %s", str(exc), exc_info=True)

    def handle_wxauto_message(self, msg, chatName, is_group=False):
        try:
            username = msg.sender
            content = getattr(msg, 'content', None) or getattr(msg, 'text', None)

            remember_chat_type(chatName, bool(is_group))
            logger.info(f"收到消息 - 来源: {chatName}, 发送者: {username}, 是否群聊: {is_group}, 内容预览: {str(content)[:40] if content else ''}")

            if not content:
                logger.warning("消息内容为空，跳过处理")
                return

            sender_id = str(getattr(msg, "sender_id", None) or username)
            received_at = getattr(msg, "timestamp", None)
            if not isinstance(received_at, datetime):
                received_at = datetime.now()
            self.history_store.record_message(
                chat_id=chatName,
                sender_id=sender_id,
                sender_name=username,
                role="user",
                content=content,
                is_group=is_group,
                created_at=received_at,
            )
            identity_key, _ = resolve_identity(
                chatName,
                sender_id,
                username,
                is_group,
                config.behavior.context.identity_aliases,
            )
            self.history_store.remember_user_message(
                identity_key=identity_key,
                chat_id=chatName,
                sender_id=sender_id,
                sender_name=username,
                content=content,
            )

            img_path = None
            is_emoji = False
            original_content = str(content or "")
            visual_message = is_visual_message(msg, original_content)
            mention_triggered = False
            visual_requested = False
            queue_key = (
                f"{chatName}::member::{sender_id}"
                if is_group
                else str(chatName)
            )
            pending_visual_request = self._has_pending_visual_request(queue_key)

            # 处理群聊消息
            if is_group:
                # 外部插件需要观察白名单群的每条文本消息，用于统计和命令处理。
                plugin_reply = self.plugin_manager.handle_group_message(
                    chat_id=chatName,
                    sender_id=sender_id,
                    sender_name=username,
                    content=content,
                    bot_name=self.robot_name or "",
                    timestamp=getattr(msg, 'timestamp', None),
                    is_self=bool(getattr(msg, 'is_self', False)),
                )
                if plugin_reply:
                    bubbles = split_summary_bubbles(plugin_reply)
                    if not bubbles:
                        bubbles = [plugin_reply]
                    for index, bubble in enumerate(bubbles):
                        self.wx.send_text(chatName, bubble)
                        if index < len(bubbles) - 1:
                            time.sleep(random.uniform(0.35, 0.9))
                    self.history_store.record_message(
                        chat_id=chatName,
                        sender_id=self.robot_name or "bot",
                        sender_name=self.robot_name or "AI",
                        role="assistant",
                        content=plugin_reply,
                        is_group=True,
                    )
                    return

                # 群聊触发需要机器人昵称；引用消息还可通过最近发送文本兼容群昵称。
                if not self.robot_name:
                    logger.warning("未取得机器人昵称，已跳过群聊消息")
                    return
                quoted_sender = re.sub(
                    r"^[\s@]+|[\s:\uFF1A]+$",
                    "",
                    str(getattr(msg, 'quoted_sender', '') or ''),
                )
                quoted_content = str(getattr(msg, 'quoted_content', '') or '')
                recent_text_checker = getattr(self.wx, 'is_recent_sent_text', None)
                quote_matches_recent_reply = bool(
                    quoted_content
                    and callable(recent_text_checker)
                    and recent_text_checker(chatName, quoted_content)
                )
                is_reply_to_bot = bool(
                    getattr(msg, 'is_quote', False)
                    and (quoted_sender == self.robot_name or quote_matches_recent_reply)
                )
                cleaned, mentioned = strip_group_bot_mention(original_content, self.robot_name)
                if mentioned:
                    mention_triggered = True
                    content = cleaned
                elif is_reply_to_bot:
                    mention_triggered = True
                    content = original_content.strip()
                elif visual_message and pending_visual_request:
                    # A picture may follow "娜娜，看图" as a separate WeChat message.
                    content = original_content.strip()
                    visual_requested = True
                else:
                    logger.info("群聊消息未显式触发机器人，已跳过")
                    return

                if mention_triggered and visual_message:
                    visual_requested = is_explicit_image_request(original_content)
                    if not visual_requested:
                        logger.info("群聊图片未明确请求识别，已跳过")
                        return
                elif mention_triggered:
                    visual_requested = is_explicit_image_request(original_content)
            elif visual_message:
                # Private images also need a preceding explicit "看图" request.
                if not pending_visual_request:
                    logger.info("私聊图片未明确请求识别，已跳过")
                    return
                visual_requested = True
            else:
                visual_requested = is_explicit_image_request(original_content)

            if visual_requested and not visual_message:
                self._request_visual(queue_key)
                logger.info(
                    "已记录识图请求，等待 %s 秒内的下一张图片",
                    int(_IMAGE_REQUEST_TIMEOUT_SECONDS),
                )
                return

            # Visual content is downloaded only after an explicit request. Do not
            # use a screen-capture fallback: it steals the foreground and is less
            # reliable than wxauto4's native image download.
            content_text = str(content or "").strip()
            is_emoji = "[动画表情]" in content_text or content_text in {"动画表情", "[动画表情]"}
            if visual_message and visual_requested:
                self._consume_visual_request(queue_key)
                if content_text.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')) and os.path.exists(content_text):
                    img_path = content_text
                else:
                    logger.info("收到明确识图请求，尝试下载原图")
                    save_dir = os.path.join(root_dir, "data", "images", "incoming")
                    img_path = download_wechat_image(msg, save_dir)
                if not img_path:
                    logger.warning("图片原图下载失败，已跳过前台截图兜底")
                    content = "IMAGE_RECOGNITION_FAILED: 未能下载图片原图"
                else:
                    content = None
            elif visual_message:
                logger.info("图片未满足明确识别条件，已跳过")
                return
            elif content_text.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp')) and os.path.exists(content_text):
                # Kept for callers that pass an ordinary text path instead of a
                # wxauto image message; it still requires an explicit request.
                if not visual_requested:
                    return
                logger.info("检测到图片消息，尝试下载原图")
                img_path = content_text
                content = None

            if img_path:
                logger.info("开始处理图片/表情 - 路径: %s, 是否表情: %s", img_path, is_emoji)
                if not img_path or not os.path.exists(str(img_path)):
                    recognized_text = "IMAGE_RECOGNITION_FAILED: 未能获取图片文件"
                else:
                    recognized_text = self.moonshot_ai.recognize_image(str(img_path), is_emoji)
                logger.info("图片/表情识别结果: %s", str(recognized_text)[:200])
                if recognition_failed(recognized_text):
                    # 明确失败标记，后续不让模型瞎编图片内容。
                    detail = str(getattr(self.moonshot_ai, "last_error", "") or recognized_text)
                    content = f"IMAGE_RECOGNITION_FAILED: {detail}"
                else:
                    content = recognized_text if content is None else f"{content} {recognized_text}"

            sender_name = username
            queue_item = {
                "content": str(content or ""),
                "sender_name": sender_name,
                "sender_id": sender_id,
                "timestamp": received_at,
                "is_group": bool(is_group),
            }
            with self.queue_lock:
                if queue_key not in self.user_queues:
                    self.user_queues[queue_key] = {
                        "timer": threading.Timer(5.0, self.process_user_messages, args=[queue_key]),
                        "messages": [str(content or "")],
                        "message_items": [queue_item],
                        "is_group": bool(is_group),
                        "chat_id": str(chatName),
                        "sender_name": sender_name,
                        "username": str(sender_id),
                    }
                    self.user_queues[queue_key]["timer"].start()
                else:
                    queue = self.user_queues[queue_key]
                    queue["timer"].cancel()
                    queue["messages"].append(str(content or ""))
                    queue.setdefault("message_items", []).append(queue_item)
                    queue["is_group"] = bool(is_group)
                    queue["chat_id"] = str(chatName)
                    queue["sender_name"] = sender_name
                    queue["username"] = str(sender_id)
                    queue["timer"] = threading.Timer(5.0, self.process_user_messages, args=[queue_key])
                    queue["timer"].start()

        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}", exc_info=True)
# 读取提示文件
avatar_dir = os.path.join(root_dir, config.behavior.context.avatar_dir)
prompt_path = os.path.join(avatar_dir, "avatar.md")
with open(prompt_path, "r", encoding="utf-8") as file:
    prompt_content = file.read()

# 创建全局实例
# Free wxauto4 polling adapter. It only relies on public foreground APIs.
wechat_adapter = WxAuto4PollingAdapter(
    contacts=listen_list,
    poll_interval=config.wechat.poll_interval,
    history_size=config.wechat.history_size,
    state_path=os.path.join(root_dir, config.wechat.state_file),
    process_existing_on_start=config.wechat.process_existing_on_start,
    exact_match=config.wechat.exact_match,
)
# ``WxAuto4PollingAdapter`` is lazy. Do not connect to WeChat during import,
# otherwise tests and the config web UI fail whenever WeChat is not running.
ROBOT_WX_NAME = ""

# Services that do not require a logged-in WeChat client.
emoji_handler = EmojiHandler(root_dir)
image_handler = ImageHandler(
    root_dir=root_dir,
    api_key=config.llm.api_key,
    base_url=config.llm.base_url,
    text_model=config.llm.model,
    image_enabled=config.media.image_generation.enabled,
    image_api_key=config.media.image_generation.api_key,
    image_base_url=config.media.image_generation.base_url,
    image_model=config.media.image_generation.model,
    temp_dir=config.media.image_generation.temp_dir,
)
voice_handler = VoiceHandler(
    root_dir=root_dir,
    tts_api_url=config.media.text_to_speech.tts_api_url
)
moonshot_ai = MoonShotAI(
    api_key=config.media.image_recognition.api_key,
    base_url=config.media.image_recognition.base_url,
    temperature=config.media.image_recognition.temperature,
    model=config.media.image_recognition.model
)
_vision_ok, _vision_msg = moonshot_ai.validate_credentials()
if _vision_ok:
    logger.info("图片识别服务可用")
else:
    logger.warning("图片识别服务不可用: %s", _vision_msg)

history_store = HistoryStore()
message_handler = None
chat_bot = None
_daily_briefing_date = None



def seed_known_group_chats() -> None:
    """用历史消息和当前监听列表预热群聊识别结果。"""
    for name in listen_list:
        try:
            recent = history_store.get_recent_messages(str(name), 20)
        except Exception:
            continue
        if any(bool(item.get("is_group")) for item in recent):
            known_group_chats.add(str(name))
    if known_group_chats:
        logger.info("已预热群聊识别: %s", "、".join(sorted(known_group_chats)))

def build_runtime() -> None:
    """Build services that depend on a logged-in WeChat client."""

    global ROBOT_WX_NAME, message_handler, chat_bot
    ROBOT_WX_NAME = wechat_adapter.get_my_name()
    if not ROBOT_WX_NAME:
        ROBOT_WX_NAME = os.environ.get("DREAM_ROBOT_NAME", "").strip()
    if not ROBOT_WX_NAME:
        logger.warning("wxauto4 未返回当前微信昵称")
    else:
        logger.info("微信机器人昵称: %s", ROBOT_WX_NAME)

    message_handler = MessageHandler(
        root_dir=root_dir,
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        dify_api_key=config.llm.dify_api_key,
        dify_base_url=config.llm.dify_base_url,
        ai_provider=config.llm.provider,
        model=config.llm.model,
        max_tokens=config.llm.max_tokens,
        temperature=config.llm.temperature,
        max_groups=config.behavior.context.max_groups,
        robot_name=ROBOT_WX_NAME,
        prompt_content=prompt_content,
        image_handler=image_handler,
        emoji_handler=emoji_handler,
        voice_handler=voice_handler,
        wechat=wechat_adapter,
        history_store=history_store,
        identity_aliases=config.behavior.context.identity_aliases,
    )
    plugin_manager = PluginManager(os.path.join(root_dir, "plugins"), logger=logger)
    plugin_manager.configure_services(
        history_store=history_store,
        ai_responder=message_handler.generate_summary_response,
    )
    chat_bot = ChatBot(
        message_handler,
        moonshot_ai,
        wechat_adapter,
        plugin_manager=plugin_manager,
        history_store=history_store,
    )
    seed_known_group_chats()
    try:
        private_first = [n for n in listen_list if n not in known_group_chats]
        group_later = [n for n in listen_list if n in known_group_chats]
        ordered = private_first + group_later
        wechat_adapter.contacts = ordered
        wechat_adapter.always_poll = list(private_first)
        logger.info("轮询顺序(私聊优先): %s", " | ".join(ordered))
        logger.info("私聊保底轮询: %s", " | ".join(private_first) or "无")
    except Exception as exc:
        logger.debug("调整轮询顺序失败: %s", exc)


wait = wechat_adapter.poll_interval

# 创建全局实例
cleanup_utils = CleanupUtils(root_dir)

def remember_chat_type(chat_name: str, is_group: bool) -> None:
    """记录会话类型，供主动消息与后续处理复用。"""
    name = str(chat_name or "").strip()
    if not name:
        return
    if is_group:
        known_group_chats.add(name)
    elif name in known_group_chats:
        # 仅在明确为私聊时移出；未知类型不删除已有群标记
        pass


def is_group_target(chat_name: str) -> bool:
    """判断监听对象是否为群聊。

    优先使用运行时已确认的群聊标记，其次查本地历史消息。
    用于区分主动消息该走群聊语气还是私聊语气。
    """
    name = str(chat_name or "").strip()
    if not name:
        return False
    if name in known_group_chats:
        return True
    try:
        recent = history_store.get_recent_messages(name, 20)
        if any(bool(item.get("is_group")) for item in recent):
            known_group_chats.add(name)
            return True
    except Exception as exc:
        logger.debug("读取会话历史以判断群聊失败: %s", exc)
    return False


def message_listener():
    """使用免费 wxauto4 前台 API 轮询消息。"""
    while True:
        try:
            for msg in wechat_adapter.poll_once():
                if msg.is_self or not msg.content:
                    continue
                remember_chat_type(msg.chat_name, bool(msg.is_group))
                chat_bot.handle_wxauto_message(
                    msg,
                    msg.chat_name,
                    is_group=msg.is_group,
                )
        except Exception as exc:
            logger.error(f"微信轮询失败: {str(exc)}", exc_info=True)
            wechat_adapter.reconnect()
        time.sleep(wait)

def daily_briefing_loop(stop_event: threading.Event) -> None:
    """Send one AI-generated morning brief per configured group each day."""
    global _daily_briefing_date
    enabled = os.environ.get("DREAM_DAILY_BRIEFING_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
    briefing_time = os.environ.get("DREAM_DAILY_BRIEFING_TIME", "08:00").strip()
    targets = [item.strip() for item in os.environ.get("DREAM_DAILY_BRIEFING_TARGETS", "").split(",") if item.strip()]
    if not enabled:
        return
    while not stop_event.is_set():
        now = datetime.now()
        if now.strftime("%H:%M") == briefing_time and _daily_briefing_date != now.date():
            for chat_name in (targets or sorted(known_group_chats)):
                if not is_group_target(chat_name) or message_handler is None:
                    continue
                try:
                    transcript = history_store.format_recent_transcript(chat_name, 30, within_hours=24.0)
                    if not transcript:
                        continue
                    prompt = ("请根据下面过去24小时的群聊记录生成一份简短中文早报，只总结事实、待办和有趣话题，"
                              "不要编造，不要提及你是AI，控制在8条以内。\n群聊记录：\n" + transcript)
                    reply = message_handler.generate_summary_response(prompt, chat_name)
                    if reply:
                        wechat_adapter.send_text(chat_name, "【每日早报】\n" + reply)
                        logger.info("Daily briefing sent to %s", chat_name)
                except Exception:
                    logger.exception("Daily briefing failed for %s", chat_name)
            _daily_briefing_date = now.date()
        stop_event.wait(20)

def initialize_wx_listener():
    """初始化免费 wxauto4 并验证配置的会话。"""
    max_retries = 3
    retry_delay = 2

    for attempt in range(max_retries):
        try:
            if not wechat_adapter.is_online():
                raise RuntimeError("未检测到已登录的微信 4 窗口")

            # Build chat baselines in the listener thread instead of opening every chat twice at startup.
            return wechat_adapter
        except Exception as exc:
            logger.error(
                "微信初始化失败 (%s/%s): %s",
                attempt + 1,
                max_retries,
                exc,
            )
            wechat_adapter.reconnect()
            if attempt < max_retries - 1:
                time.sleep(retry_delay)

    return None

def main():
    briefing_stop = threading.Event()
    listener_thread = None  # 在函数开始时定义线程变量
    try:
        print_status("系统启动中...", "info", "🚀")

        # 清理运行缓存并确保目录存在；详细信息写入日志，不刷屏。
        cleanup_pycache()
        logger_config.cleanup_old_logs()
        cleanup_utils.cleanup_all()
        image_handler.cleanup_temp_dir()
        voice_handler.cleanup_voice_dir()
        for dir_name in ("data", "logs", "src/config"):
            os.makedirs(os.path.join(root_dir, dir_name), exist_ok=True)

        print_status("初始化微信监听...", "info", "🤖")
        wx = initialize_wx_listener()
        if not wx:
            print_status("微信初始化失败，请确保微信已登录并保持在前台运行!", "error", "❌")
            return

        build_runtime()
        listener_thread = threading.Thread(target=message_listener, daemon=True)
        listener_thread.start()
        threading.Thread(target=daily_briefing_loop, args=(briefing_stop,), daemon=True).start()
        print_status("机器人已启动，正在等待新消息", "success", "✅")

        # 主循环
        while True:
            time.sleep(1)
            if not listener_thread.is_alive():
                print_status("监听线程已断开，尝试重新连接...", "warning", "🔄")
                try:
                    wechat_adapter.reconnect()
                    wx = initialize_wx_listener()
                    if wx:
                        listener_thread = threading.Thread(target=message_listener)
                        listener_thread.daemon = True
                        listener_thread.start()
                        print_status("重新连接成功", "success", "✅")
                except Exception as e:
                    print_status(f"重新连接失败: {str(e)}", "error", "❌")
                    time.sleep(5)

    except Exception as e:
        print_status(f"主程序异常: {str(e)}", "error", "💥")
        logger.error(f"主程序异常: {str(e)}", exc_info=True)  # 添加详细日志记录
    finally:
        # 清理资源
        # 关闭监听线程
        if listener_thread and listener_thread.is_alive():
            print_status("正在关闭监听线程...", "info", "🔄")
            listener_thread.join(timeout=2)
            if listener_thread.is_alive():
                print_status("监听线程未能正常关闭", "warning", "⚠️")
        
        print_status("正在关闭系统...", "warning", "🛑")
        print_status("系统已退出", "info", "👋")
        print("\n")

if __name__ == '__main__':
    try:
        print_banner()
        main()
    except KeyboardInterrupt:
        print("\n")
        print_status("用户终止程序", "warning", "🛑")
        print_status("感谢使用，再见！", "info", "👋")
        print("\n")
    except Exception as e:
        print_status(f"程序异常退出: {str(e)}", "error", "💥")
