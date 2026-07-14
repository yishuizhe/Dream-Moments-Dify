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
from services.database import HistoryStore, Session, ChatMessage, make_identity_key
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
        history_store=None,
    ):
        self.root_dir = root_dir
        self.api_key = api_key
        self.max_groups = max_groups
        self.robot_name = robot_name
        self.prompt_content = prompt_content
        self.ai_provider = str(ai_provider or "deepseek").strip().lower()
        self.history_store = history_store or HistoryStore()

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
        """保存兼容旧版本的数据表记录；新历史由 HistoryStore 单独维护。"""
        session = None
        try:
            session = Session()
            chat_message = ChatMessage(
                sender_id=sender_id,
                sender_name=sender_name,
                message=message,
                reply=reply,
            )
            session.add(chat_message)
            session.commit()
        except Exception as e:
            logger.error("保存消息失败: %s", str(e))
            if session is not None:
                session.rollback()
        finally:
            if session is not None:
                session.close()

    def get_api_response(
        self,
        message: str,
        user_id: str,
        *,
        is_group: bool = False,
        sender_name: str = "",
        identity_key: str = "",
    ) -> str:
        """Get a reply with group identity and local per-member memory."""
        context_parts = []
        if is_group:
            context_parts.append(
                f"当前触发者：{sender_name or '未知成员'}。消息前的昵称标签表示不同群成员。"
            )
        memories = self.history_store.get_memory_items(identity_key) if identity_key else []
        if memories:
            memory_lines = "\n".join(f"- {item}" for item in memories[-8:])
            context_parts.append(
                f"关于当前成员的本地记忆（仅作连贯对话参考）：\n{memory_lines}"
            )
        request_message = message
        if getattr(self, "ai_provider", "deepseek") == "dify" and context_parts:
            request_message = "\n\n".join(context_parts + [message])
        return self.ai.get_response(
            request_message,
            user_id,
            build_system_prompt(
                self.prompt_content,
                is_group=is_group,
                extra_context="\n\n".join(context_parts),
            ),
        )

    def generate_summary_response(self, prompt: str, chat_id: str) -> str:
        """Run an isolated summary task without contaminating normal chat context."""
        context_key = f"summary:{chat_id}:{time.time_ns()}"
        try:
            reply = self.ai.get_response(
                prompt,
                context_key,
                build_system_prompt(self.prompt_content, is_group=True, task_type="summary"),
            )
            return normalize_reply_text(reply)
        finally:
            clear = getattr(self.ai, "clear_history", None) or getattr(self.ai, "clear_context", None)
            if callable(clear):
                clear(context_key)

    def _send_text_reply(self, chat_id: str, reply: str) -> None:
        """Split a reply into natural WeChat bubbles with pauses only between bubbles."""
        parts = split_reply_bubbles(reply)
        for index, part in enumerate(parts):
            self.wx.SendMsg(msg=part, who=chat_id)
            if index < len(parts) - 1:
                time.sleep(random.randint(1, 2))

    def _record_assistant_reply(self, chat_id: str, reply: str, is_group: bool) -> None:
        self.history_store.record_message(
            chat_id=chat_id,
            sender_id=self.robot_name or "bot",
            sender_name=self.robot_name or "AI",
            role="assistant",
            content=reply,
            is_group=is_group,
        )

    def process_messages(self, chat_id: str):
        """Process structured queued messages without losing group member identity."""
        with self.queue_lock:
            if chat_id not in self.user_queues:
                return
            user_data = self.user_queues.pop(chat_id)

        raw_items = list(user_data.get("messages") or [])[-5:]
        if not raw_items:
            return
        is_group = bool(user_data.get("is_group", False))
        items = []
        for item in raw_items:
            if isinstance(item, dict):
                items.append(dict(item))
            else:
                items.append({
                    "content": str(item or ""),
                    "sender_name": user_data.get("sender_name", ""),
                    "sender_id": user_data.get("username", ""),
                    "timestamp": datetime.now(),
                    "is_group": is_group,
                })
        latest = items[-1]
        sender_name = str(latest.get("sender_name") or latest.get("sender_id") or "")
        username = str(latest.get("sender_id") or sender_name)
        identity_key = make_identity_key(chat_id, username, is_group)
        conversation_key = f"group:{chat_id}" if is_group else identity_key

        messages = []
        for item in items:
            timestamp = item.get("timestamp")
            if not isinstance(timestamp, datetime):
                timestamp = datetime.now()
            content = str(item.get("content") or "").strip()
            if is_group:
                label = str(item.get("sender_name") or item.get("sender_id") or "未知成员")
                messages.append(f"[{timestamp:%Y-%m-%d %H:%M:%S}] {label}：{content}")
            else:
                messages.append(f"[{timestamp:%Y-%m-%d %H:%M:%S}] {content}")
        merged_message = "\n".join(messages)
        logger.info("Processing %s queued message(s) from %s", len(messages), sender_name)

        latest_content = str(latest.get("content") or "").strip()
        if latest_content == "查看我的记忆":
            memories = self.history_store.get_memory_items(identity_key)
            reply = (
                "我记得你最近说过：\n" + "\n".join(f"- {item}" for item in memories)
                if memories else "我还没有保存你的本地记忆。"
            )
            self._send_text_reply(chat_id, reply)
            self._record_assistant_reply(chat_id, reply, is_group)
            return
        if latest_content == "清除我的记忆":
            self.history_store.clear_memory(identity_key)
            reply = "已清除只属于你的本地记忆。"
            self._send_text_reply(chat_id, reply)
            self._record_assistant_reply(chat_id, reply, is_group)
            return

        try:
            # 检查消息是否包含图片识别结果
            is_image_recognition = any("发送了图片：" in msg or "发送了表情包：" in msg for msg in messages)
            if is_image_recognition:
                logger.info("Detected image-recognition result")

            # 检查是否为语音请求
            if self.voice_handler.is_voice_request(merged_message):
                logger.info("检测到语音请求")
                reply = normalize_reply_text(
                    self.get_api_response(
                        merged_message, conversation_key, is_group=is_group,
                        sender_name=sender_name, identity_key=identity_key
                    )
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

                self._record_assistant_reply(chat_id, reply, is_group)
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
                        reply = "给你找了一张好看的图片。"
                    except Exception as e:
                        logger.error("发送图片失败: %s", str(e))
                        reply = "图片发送失败了，请稍后再试。"
                    finally:
                        try:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                        except Exception as e:
                            logger.error("删除临时图片失败: %s", str(e))
                else:
                    reply = "暂时没有获取到图片，请稍后再试。"

                self.wx.SendMsg(msg=reply, who=chat_id)
                self._record_assistant_reply(chat_id, reply, is_group)
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
                    self._record_assistant_reply(chat_id, reply, is_group)
                    return

                unavailable = self.image_handler.get_unavailable_message()
                self._send_text_reply(chat_id, unavailable)
                self._record_assistant_reply(chat_id, unavailable, is_group)
                return

            # 处理普通文本回复
            else:
                logger.info("处理普通文本回复")
                reply = normalize_reply_text(
                    self.get_api_response(
                        merged_message, conversation_key, is_group=is_group,
                        sender_name=sender_name, identity_key=identity_key
                    )
                )
                logger.info("AI reply generated for chat %s", chat_id)

                # Automatically split by punctuation instead of model backslashes.
                self._send_text_reply(chat_id, reply)
                self._record_assistant_reply(chat_id, reply, is_group)

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


    def add_to_queue(
        self,
        chat_id: str,
        content: str,
        sender_name: str,
        username: str,
        is_group: bool = False,
        *,
        message_items: Optional[List[dict]] = None,
    ):
        """Add structured messages to the debounce queue."""
        entries = [dict(item) for item in (message_items or [])]
        if not entries:
            entries = [{
                "content": str(content or ""),
                "sender_name": sender_name,
                "sender_id": username,
                "timestamp": datetime.now(),
                "is_group": bool(is_group),
            }]
        latest = entries[-1]
        with self.queue_lock:
            if chat_id not in self.user_queues:
                self.user_queues[chat_id] = {
                    "timer": threading.Timer(5.0, self.process_messages, args=[chat_id]),
                    "messages": entries,
                    "sender_name": latest.get("sender_name", sender_name),
                    "username": latest.get("sender_id", username),
                    "is_group": bool(is_group),
                }
                self.user_queues[chat_id]["timer"].start()
            else:
                queue = self.user_queues[chat_id]
                queue["timer"].cancel()
                queue["messages"].extend(entries)
                queue["sender_name"] = latest.get("sender_name", sender_name)
                queue["username"] = latest.get("sender_id", username)
                queue["is_group"] = bool(is_group)
                queue["timer"] = threading.Timer(5.0, self.process_messages, args=[chat_id])
                queue["timer"].start()
