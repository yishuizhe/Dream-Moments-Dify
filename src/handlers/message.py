"""
消息处理模块
负责处理聊天消息，包括:
- 消息队列管理
- 消息分发处理
- API响应处理
- 多媒体消息处理
"""

import logging
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional
from services.database import Session, ChatMessage
import random
import os
from services.ai.dify import DifyAI
from services.ai.deepseek import DeepSeekAI
from utils.reply_formatter import build_system_prompt, normalize_reply_text, split_reply_bubbles

logger = logging.getLogger(__name__)

class MessageHandler:
    def __init__(
        self,
        root_dir,
        api_key,
        base_url,
        max_groups,
        robot_name,
        prompt_content,
        image_handler,
        emoji_handler,
        voice_handler,
        dify_api_key,
        dify_base_url,
        wechat,
        ai_provider="deepseek",
        model="deepseek-chat",
        max_tokens=2000,
        temperature=1.0,
    ):
        self.root_dir = root_dir
        self.api_key = api_key
        self.max_groups = max_groups
        self.robot_name = robot_name
        self.prompt_content = prompt_content
        self.ai_provider = str(ai_provider or "deepseek").strip().lower()

        if self.ai_provider == "dify":
            if not str(dify_api_key or "").strip():
                raise ValueError("AI_PROVIDER=dify 时必须配置 DIFY_API_KEY")
            self.ai = DifyAI(
                dify_api_key=dify_api_key,
                dify_base_url=dify_base_url,
                max_groups=max_groups,
            )
        elif self.ai_provider == "deepseek":
            if not str(api_key or "").strip():
                raise ValueError("AI_PROVIDER=deepseek 时必须配置 DEEPSEEK_API_KEY")
            if not str(base_url or "").strip():
                raise ValueError("AI_PROVIDER=deepseek 时必须配置 DEEPSEEK_BASE_URL")
            self.ai = DeepSeekAI(
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_token=int(max_tokens),
                temperature=float(temperature),
                max_groups=max_groups,
            )
        else:
            raise ValueError(
                f"不支持的 AI_PROVIDER: {self.ai_provider}; 可选 deepseek 或 dify"
            )

        logger.info("聊天 AI 提供方: %s", self.ai_provider)

        # 消息队列相关
        self.user_queues = {}
        self.queue_lock = threading.Lock()
        self.chat_contexts = {}

        # Shared adapter serializes polling and send operations.
        self.wx = wechat

        # 添加 handlers
        self.image_handler = image_handler
        self.emoji_handler = emoji_handler
        self.voice_handler = voice_handler

    def save_message(self, sender_id: str, sender_name: str, message: str, reply: str):
        """保存聊天记录到数据库"""
        try:
            session = Session()
            chat_message = ChatMessage(
                sender_id=sender_id,
                sender_name=sender_name,
                message=message,
                reply=reply
            )
            session.add(chat_message)
            session.commit()
            session.close()
        except Exception as e:
            logger.error(f"保存消息失败: {str(e)}")

    def get_api_response(self, message: str, user_id: str) -> str:
        """从当前配置的 AI 提供方获取回复。"""
        return self.ai.get_response(
            message,
            user_id,
            build_system_prompt(self.prompt_content),
        )

    def _send_text_reply(self, chat_id: str, reply: str) -> None:
        """Split a reply into natural WeChat bubbles with pauses only between bubbles."""
        parts = split_reply_bubbles(reply)
        for index, part in enumerate(parts):
            self.wx.SendMsg(msg=part, who=chat_id)
            if index < len(parts) - 1:
                time.sleep(random.randint(1, 2))

    def process_messages(self, chat_id: str):
        """处理消息队列中的消息"""
        with self.queue_lock:
            if chat_id not in self.user_queues:
                return
            user_data = self.user_queues.pop(chat_id)
            messages = user_data['messages']
            sender_name = user_data['sender_name']
            username = user_data['username']

        messages = messages[-5:]
        merged_message = ' \\ '.join(messages)
        logger.info("Processing queued message from %s", sender_name)

        try:
            # 检查消息是否包含图片识别结果
            is_image_recognition = any("发送了图片：" in msg or "发送了表情包：" in msg for msg in messages)
            if is_image_recognition:
                logger.info("Detected image-recognition result")

            # 检查是否为语音请求
            if self.voice_handler.is_voice_request(merged_message):
                logger.info("检测到语音请求")
                reply = normalize_reply_text(
                    self.get_api_response(merged_message, chat_id)
                )

                voice_path = self.voice_handler.generate_voice(reply)
                if voice_path:
                    try:
                        self.wx.SendFiles(filepath=voice_path, who=chat_id)
                    except Exception as e:
                        logger.error(f"发送语音失败: {str(e)}")
                        self._send_text_reply(chat_id, reply)
                    finally:
                        try:
                            os.remove(voice_path)
                        except Exception as e:
                            logger.error(f"删除临时语音文件失败: {str(e)}")
                else:
                    self._send_text_reply(chat_id, reply)

                # 异步保存消息记录
                threading.Thread(target=self.save_message,
                            args=(username, sender_name, merged_message, reply)).start()
                return

            # 检查是否为随机图片请求
            elif self.image_handler.is_random_image_request(merged_message):
                logger.info("检测到随机图片请求")
                image_path = self.image_handler.get_random_image()
                if image_path:
                    try:
                        self.wx.SendFiles(filepath=image_path, who=chat_id)
                        reply = "给主人你找了一张好看的图片哦~"
                    except Exception as e:
                        logger.error(f"发送图片失败: {str(e)}")
                        reply = "抱歉主人，图片发送失败了..."
                    finally:
                        try:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                        except Exception as e:
                            logger.error(f"删除临时图片失败: {str(e)}")

                    self.wx.SendMsg(msg=reply, who=chat_id)
                    return

            # 检查是否为图像生成请求，但跳过图片识别结果
            elif not is_image_recognition and self.image_handler.is_image_generation_request(merged_message):
                logger.info("检测到画图请求")
                image_path = self.image_handler.generate_image(merged_message)
                if image_path:
                    try:
                        self.wx.SendFiles(filepath=image_path, who=chat_id)
                        reply = "这是按照主人您的要求生成的图片\\(^o^)/~"
                    except Exception as e:
                        logger.error(f"发送生成图片失败: {str(e)}")
                        reply = "抱歉主人，图片生成失败了..."
                    finally:
                        try:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                        except Exception as e:
                            logger.error(f"删除临时图片失败: {str(e)}")

                    self.wx.SendMsg(msg=reply, who=chat_id)
                    return

            # 处理普通文本回复
            else:
                logger.info("处理普通文本回复")
                reply = normalize_reply_text(
                    self.get_api_response(merged_message, chat_id)
                )
                logger.info("AI reply generated for chat %s", chat_id)

                # Automatically split by punctuation instead of model backslashes.
                self._send_text_reply(chat_id, reply)

                # 检查回复中是否包含情感关键词并发送表情包
                logger.info("开始检查AI回复的情感关键词")
                emotion_detected = False

                try:
                    if not hasattr(self.emoji_handler, 'emotion_map'):
                        logger.error("emoji_handler 缺少 emotion_map 属性")
                        return

                    for emotion, keywords in self.emoji_handler.emotion_map.items():
                        if not keywords:  # 跳过空的关键词列表（如 neutral）
                            continue

                        if any(keyword in reply for keyword in keywords):
                            emotion_detected = True
                            logger.info(f"在回复中检测到情感: {emotion}")

                            emoji_path = self.emoji_handler.get_emotion_emoji(reply)
                            if emoji_path:
                                try:
                                    self.wx.SendFiles(filepath=emoji_path, who=chat_id)
                                    logger.info(f"已发送情感表情包: {emoji_path}")
                                except Exception as e:
                                    logger.error(f"发送表情包失败: {str(e)}")
                            else:
                                logger.warning(f"未找到对应情感 {emotion} 的表情包")
                            break

                    if not emotion_detected:
                        logger.info("未在回复中检测到明显情感")

                except Exception as e:
                    logger.error(f"情感检测过程发生错误: {str(e)}")

                # 异步保存消息记录
                threading.Thread(target=self.save_message,
                            args=(username, sender_name, merged_message, reply)).start()

        except Exception as e:
            logger.error(f"处理消息失败: {str(e)}", exc_info=True)


    def add_to_queue(self, chat_id: str, content: str, sender_name: str,
                    username: str, is_group: bool = False):
        """添加消息到队列"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        time_aware_content = f"[{current_time}] {content}"

        with self.queue_lock:
            if chat_id not in self.user_queues:
                self.user_queues[chat_id] = {
                    'timer': threading.Timer(5.0, self.process_messages, args=[chat_id]),
                    'messages': [time_aware_content],
                    'sender_name': sender_name,
                    'username': username,
                    'is_group': is_group
                }
                self.user_queues[chat_id]['timer'].start()
            else:
                self.user_queues[chat_id]['timer'].cancel()
                self.user_queues[chat_id]['messages'].append(time_aware_content)
                self.user_queues[chat_id]['timer'] = threading.Timer(5.0, self.process_messages, args=[chat_id])
                self.user_queues[chat_id]['timer'].start()
