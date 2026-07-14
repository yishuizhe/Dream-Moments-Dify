import base64
import requests
import logging
import random
from datetime import datetime
import threading
import time
import os
import shutil
from services.database import HistoryStore, Session, ChatMessage, make_identity_key
from config import config
from wechat.adapter import WxAuto4PollingAdapter
import re
import pyautogui
from handlers.emoji import EmojiHandler
from handlers.image import ImageHandler
from handlers.message import MessageHandler
from handlers.voice import VoiceHandler
from plugins.manager import PluginManager
from services.ai.moonshot import MoonShotAI
from utils.cleanup import cleanup_pycache, CleanupUtils
from utils.logger import LoggerConfig
from colorama import init
from utils.console import print_status, print_banner

# 获取项目根目录
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 配置日志
logger_config = LoggerConfig(root_dir)
logger = logger_config.setup_logger('main')
listen_list = config.user.listen_list
queue_lock = threading.Lock()  # 队列访问锁
user_queues = {}  # 用户消息队列管理
chat_contexts = {}  # 存储上下文
# 初始化colorama
init()

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

    def process_user_messages(self, chat_id):
        """Forward a structured debounce batch to MessageHandler."""
        try:
            with self.queue_lock:
                if chat_id not in self.user_queues:
                    return
                user_data = self.user_queues.pop(chat_id)
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
            self.message_handler.add_to_queue(
                chat_id=chat_id,
                content=str(latest.get("content") or ""),
                sender_name=sender_name,
                username=username,
                is_group=is_group,
                message_items=messages,
            )
        except Exception as exc:
            logger.error("处理消息队列失败: %s", str(exc), exc_info=True)

    def handle_wxauto_message(self, msg, chatName, is_group=False):
        try:
            username = msg.sender
            content = getattr(msg, 'content', None) or getattr(msg, 'text', None)

            logger.info(f"收到消息 - 来源: {chatName}, 发送者: {username}, 是否群聊: {is_group}")

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
            self.history_store.remember_user_message(
                identity_key=make_identity_key(chatName, sender_id, is_group),
                chat_id=chatName,
                sender_id=sender_id,
                sender_name=username,
                content=content,
            )

            img_path = None
            is_emoji = False
            
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
                    self.wx.send_text(chatName, plugin_reply)
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
                original_content = content
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
                if f'@{self.robot_name}' in original_content:
                    content = re.sub(rf'@{re.escape(self.robot_name)}\s*', '', content).strip()
                elif re.search(rf'(^|[\s,\uFF0C]){re.escape(self.robot_name)}([\s,\uFF0C]|$)', original_content):
                    content = re.sub(rf'(^|[\s,\uFF0C]){re.escape(self.robot_name)}([\s,\uFF0C]|$)', '', original_content).strip()
                elif is_reply_to_bot:
                    content = original_content.strip()
                else:
                    logger.info("群聊消息未触发机器人，已跳过")
                    return

            # 处理图片消息。
            if content.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp')):
                img_path = content
                is_emoji = False
                content = None

            # 处理动画表情
            if content and "[动画表情]" in content:
                logger.info("检测到动画表情")
                img_path = emoji_handler.capture_and_save_screenshot(chatName)
                logger.info(f"表情截图保存路径: {img_path}")
                is_emoji = True
                content = None

            if img_path:
                logger.info(f"开始处理图片/表情 - 路径: {img_path}, 是否表情: {is_emoji}")
                recognized_text = self.moonshot_ai.recognize_image(img_path, is_emoji)
                logger.info(f"图片/表情识别结果: {recognized_text}")
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
                if chatName not in self.user_queues:
                    self.user_queues[chatName] = {
                        "timer": threading.Timer(5.0, self.process_user_messages, args=[chatName]),
                        "messages": [str(content or "")],
                        "message_items": [queue_item],
                        "is_group": bool(is_group),
                    }
                    self.user_queues[chatName]["timer"].start()
                else:
                    queue = self.user_queues[chatName]
                    queue["timer"].cancel()
                    queue["messages"].append(str(content or ""))
                    queue.setdefault("message_items", []).append(queue_item)
                    queue["is_group"] = bool(is_group)
                    queue["timer"] = threading.Timer(5.0, self.process_user_messages, args=[chatName])
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
emoji_handler = EmojiHandler(root_dir, wechat=wechat_adapter)
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
    temperature=config.media.image_recognition.temperature
)

history_store = HistoryStore()
message_handler = None
chat_bot = None


def build_runtime() -> None:
    """Build services that depend on a logged-in WeChat client."""

    global ROBOT_WX_NAME, message_handler, chat_bot
    ROBOT_WX_NAME = wechat_adapter.get_my_name()
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


wait = wechat_adapter.poll_interval

# 全局变量
last_chat_time = None
countdown_timer = None
is_countdown_running = False

# 创建全局实例
cleanup_utils = CleanupUtils(root_dir)

def update_last_chat_time():
    """更新最后一次聊天时间"""
    global last_chat_time
    last_chat_time = datetime.now()
    logger.info(f"更新最后聊天时间: {last_chat_time}")

def is_quiet_time() -> bool:
    """检查当前是否在安静时间段内"""
    try:
        current_time = datetime.now().time()
        quiet_start = datetime.strptime(config.behavior.quiet_time.start, "%H:%M").time()
        quiet_end = datetime.strptime(config.behavior.quiet_time.end, "%H:%M").time()
        
        if quiet_start <= quiet_end:
            # 如果安静时间不跨天
            return quiet_start <= current_time <= quiet_end
        else:
            # 如果安静时间跨天（比如22:00到次日08:00）
            return current_time >= quiet_start or current_time <= quiet_end
    except Exception as e:
        logger.error(f"检查安静时间出错: {str(e)}")
        return False  # 出错时默认不在安静时间

def get_random_countdown_time():
    """获取随机倒计时时间"""
    min_seconds = int(float(config.behavior.auto_message.min_hours) * 3600)
    max_seconds = int(float(config.behavior.auto_message.max_hours) * 3600)
    if min_seconds > max_seconds:
        min_seconds, max_seconds = max_seconds, min_seconds
    return random.randint(min_seconds, max_seconds)

def auto_send_message():
    """自动发送消息"""
    if is_quiet_time():
        logger.info("当前处于安静时间，跳过自动发送消息")
        start_countdown()
        return
        
    if listen_list:
        user_id = random.choice(listen_list)
        logger.info(f"自动发送消息到 {user_id}: {config.behavior.auto_message.content}")
        try:
            message_handler.add_to_queue(
                chat_id=user_id,
                content=config.behavior.auto_message.content,
                sender_name="System",
                username="System",
                is_group=False
            )
            start_countdown()
        except Exception as e:
            logger.error(f"自动发送消息失败: {str(e)}")
            start_countdown()
    else:
        logger.error("没有可用的聊天对象")
        start_countdown()

def start_countdown():
    """开始新的倒计时"""
    global countdown_timer, is_countdown_running
    
    if countdown_timer:
        countdown_timer.cancel()
    
    countdown_seconds = get_random_countdown_time()
    logger.info(f"开始新的倒计时: {countdown_seconds/3600:.2f}小时")
    
    countdown_timer = threading.Timer(countdown_seconds, auto_send_message)
    countdown_timer.daemon = True  # 设置为守护线程
    countdown_timer.start()
    is_countdown_running = True

def message_listener():
    """使用免费 wxauto4 前台 API 轮询消息。"""
    while True:
        try:
            for msg in wechat_adapter.poll_once():
                if msg.is_self or not msg.content:
                    continue
                chat_bot.handle_wxauto_message(
                    msg,
                    msg.chat_name,
                    is_group=msg.is_group,
                )
        except Exception as exc:
            logger.error(f"微信轮询失败: {str(exc)}", exc_info=True)
            wechat_adapter.reconnect()
        time.sleep(wait)

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
        start_countdown()
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
        if countdown_timer:
            countdown_timer.cancel()
        
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
