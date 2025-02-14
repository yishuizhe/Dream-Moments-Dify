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
from openai import OpenAI
from wxauto import WeChat
from services.database import Session, ChatMessage
import random
import os
from services.ai.dify import DifyAI

logger = logging.getLogger(__name__)

class MessageHandler:
    def __init__(self, root_dir, api_key, base_url, max_groups, robot_name, prompt_content, image_handler, emoji_handler, voice_handler):
        self.root_dir = root_dir
        self.api_key = api_key
        self.max_groups = max_groups
        self.robot_name = robot_name
        self.prompt_content = prompt_content
        
        # 使用 difyAI 替换直接的 OpenAI 客户端
        self.dify = DifyAI(
            api_key=api_key,
            base_url=base_url,
            max_groups=max_groups
        )
        
        # 消息队列相关
        self.user_queues = {}
        self.queue_lock = threading.Lock()
        self.chat_contexts = {}
        
        # 微信实例
        self.wx = WeChat()

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
            print(f"保存消息失败: {str(e)}")

    def get_api_response(self, message: str, user_id: str) -> str:
        """获取 API 回复"""
        return self.dify.get_response(message, user_id, self.prompt_content)

    def process_messages(self, chat_id: str):
        """处理消息队列中的消息"""
        with self.queue_lock:
            if chat_id not in self.user_queues:
                return
            user_data = self.user_queues.pop(chat_id)
            messages = user_data['messages']
            sender_name = user_data['sender_name']
            username = user_data['username']
            is_group = user_data.get('is_group', False)

        messages = messages[-5:]
        merged_message = ' \\ '.join(messages)
        print(f"处理合并消息 ({sender_name}): {merged_message}")

        try:
            # 检查是否为语音请求
            if self.voice_handler.is_voice_request(merged_message):
                reply = self.get_api_response(merged_message, chat_id)
                if "</think>" in reply:
                    reply = reply.split("</think>", 1)[1].strip()
                
                voice_path = self.voice_handler.generate_voice(reply)
                if voice_path:
                    try:
                        self.wx.SendFiles(filepath=voice_path, who=chat_id)
                    except Exception as e:
                        logger.error(f"发送语音失败: {str(e)}")
                        if is_group:
                            reply = f"@{sender_name} {reply}"
                        self.wx.SendMsg(msg=reply, who=chat_id)
                    finally:
                        try:
                            os.remove(voice_path)
                        except Exception as e:
                            logger.error(f"删除临时语音文件失败: {str(e)}")
                else:
                    if is_group:
                        reply = f"@{sender_name} {reply}"
                    self.wx.SendMsg(msg=reply, who=chat_id)
                
                # 异步保存消息记录
                threading.Thread(target=self.save_message, 
                               args=(username, sender_name, merged_message, reply)).start()
                return

            # 检查是否为随机图片请求
            if self.image_handler.is_random_image_request(merged_message):
                image_path = self.image_handler.get_random_image()
                if image_path:
                    try:
                        self.wx.SendFiles(filepath=image_path, who=chat_id)
                        reply = "给你找了一张好看的图片哦~"
                    except Exception as e:
                        logger.error(f"发送图片失败: {str(e)}")
                        reply = "抱歉，图片发送失败了..."
                    finally:
                        try:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                        except Exception as e:
                            logger.error(f"删除临时图片失败: {str(e)}")
                    
                    if is_group:
                        reply = f"@{sender_name} {reply}"
                    self.wx.SendMsg(msg=reply, who=chat_id)
                    return

            # 检查是否为图像生成请求
            if self.image_handler.is_image_generation_request(merged_message):
                image_path = self.image_handler.generate_image(merged_message)
                if image_path:
                    try:
                        self.wx.SendFiles(filepath=image_path, who=chat_id)
                        reply = "这是按照您的要求生成的图片\\(^o^)/~"
                    except Exception as e:
                        logger.error(f"发送生成图片失败: {str(e)}")
                        reply = "抱歉，图片生成失败了..."
                    finally:
                        try:
                            if os.path.exists(image_path):
                                os.remove(image_path)
                        except Exception as e:
                            logger.error(f"删除临时图片失败: {str(e)}")
                    
                    if is_group:
                        reply = f"@{sender_name} {reply}"
                    self.wx.SendMsg(msg=reply, who=chat_id)
                    return

            # 检查是否需要发送表情包
            if self.emoji_handler.is_emoji_request(merged_message):
                print("表情包请求")
                emoji_path = self.emoji_handler.get_random_emoji()
                if emoji_path:
                    try:
                        self.wx.SendFiles(filepath=emoji_path, who=chat_id)
                        reply = "嘟嘟嘟~~"
                    except Exception as e:
                        logger.error(f"发送表情包失败: {str(e)}")
                        reply = "啦啦啦~"
                    
                    if is_group:
                        reply = f"@{sender_name} {reply}"
                    self.wx.SendMsg(msg=reply, who=chat_id)
                    return

            # 获取普通文本回复
            reply = self.get_api_response(merged_message, chat_id)
            if "</think>" in reply:
                reply = reply.split("</think>", 1)[1].strip()
            print(f"API回复: {reply}")
            if is_group:
                reply = f"@{sender_name} {reply}"

            if '\\' in reply:
                parts = [p.strip() for p in reply.split('\\') if p.strip()]
                for part in parts:
                    self.wx.SendMsg(msg=part, who=chat_id)
                    time.sleep(random.randint(2, 4))
            else:
                self.wx.SendMsg(msg=reply, who=chat_id)

            # 异步保存消息记录
            threading.Thread(target=self.save_message, 
                           args=(username, sender_name, merged_message, reply)).start()

        except Exception as e:
            logger.error(f"处理消息失败: {str(e)}")

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