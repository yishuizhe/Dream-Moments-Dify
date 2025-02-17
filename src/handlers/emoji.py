"""
表情包处理模块
负责处理表情包相关功能，包括:
- 表情包请求识别
- 表情包选择
- 表情包截图
- 文件管理
"""

import os
import random
import logging
import re
from datetime import datetime
import pyautogui
import time
from wxauto import WeChat
from typing import Tuple, Optional
from config import config

logger = logging.getLogger(__name__)

class EmojiHandler:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.emoji_dir = os.path.join(root_dir, config.behavior.context.avatar_dir, "emojis")
        self.screenshot_dir = os.path.join(root_dir, 'screenshot')
        
        # 情感分类映射（情感目录名: 关键词列表）
        self.emotion_map = {
            'happy': ['开心', '高兴', '哈哈', '笑', '嘻嘻', '可爱', '乐'],
            'sad': ['难过', '伤心', '哭', '委屈', '泪', '呜呜', '悲'],
            'angry': ['生气', '怒', '哼', '啊啊', '呵呵'],
            'neutral': []  # 默认中性分类
        }
        
        # 确保目录存在
        os.makedirs(self.emoji_dir, exist_ok=True)
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def is_emoji_request(self, text: str) -> bool:
        """判断是否为表情包请求"""
        emoji_keywords = ["来个表情包", "斗图", "gif", "动图"]
        return any(keyword in text.lower() for keyword in emoji_keywords)

    def detect_emotion(self, text: str) -> str:
        """从文本中检测情感分类"""
        for emotion, keywords in self.emotion_map.items():
            if emotion == 'neutral':
                continue
            if any(keyword in text for keyword in keywords):
                return emotion
        return 'neutral'

    def get_emotion_emoji(self, text: str) -> Optional[str]:
        """根据AI回复内容的情感获取对应表情包"""
        try:
            # 检测情感分类
            emotion = self.detect_emotion(text)
            target_dir = os.path.join(self.emoji_dir, emotion)
            
            # 回退机制处理
            if not os.path.exists(target_dir):
                if os.path.exists(self.emoji_dir):
                    logger.warning(f"情感目录 {emotion} 不存在，使用根目录")
                    target_dir = self.emoji_dir
                else:
                    logger.error(f"表情包根目录不存在: {self.emoji_dir}")
                    return None

            # 获取有效表情包文件
            emoji_files = [f for f in os.listdir(target_dir)
                          if f.lower().endswith(('.gif', '.jpg', '.png', '.jpeg'))]
            
            if not emoji_files:
                logger.warning(f"目录中未找到表情包: {target_dir}")
                return None
                
            # 随机选择并返回路径
            selected = random.choice(emoji_files)
            logger.info(f"已选择 {emotion} 表情包: {selected}")
            return os.path.join(target_dir, selected)
        except Exception as e:
            logger.error(f"获取表情包失败: {str(e)}", exc_info=True)
            return None

    def capture_and_save_screenshot(self, who: str) -> str:
        """捕获并保存聊天窗口截图"""
        try:
            # 确保截图目录存在
            os.makedirs(self.screenshot_dir, exist_ok=True)
            
            screenshot_path = os.path.join(
                self.screenshot_dir, 
                f'{who}_{datetime.now().strftime("%Y%m%d%H%M%S")}.png'
            )
            
            try:
                # 激活并定位微信聊天窗口
                wx_chat = WeChat()
                wx_chat.ChatWith(who)
                chat_window = pyautogui.getWindowsWithTitle(who)[0]
                
                # 确保窗口被前置和激活
                if not chat_window.isActive:
                    chat_window.activate()
                if not chat_window.isMaximized:
                    chat_window.maximize()
                
                # 获取窗口的坐标和大小
                x, y, width, height = chat_window.left, chat_window.top, chat_window.width, chat_window.height

                time.sleep(1)  # 短暂等待确保窗口已激活

                # 截取指定窗口区域的屏幕
                screenshot = pyautogui.screenshot(region=(x, y, width, height))
                screenshot.save(screenshot_path)
                logger.info(f'已保存截图: {screenshot_path}')
                return screenshot_path
                
            except Exception as e:
                logger.error(f'截取或保存截图失败: {str(e)}')
                return None
                
        except Exception as e:
            logger.error(f'创建截图目录失败: {str(e)}')
            return None

    def cleanup_screenshot_dir(self):
        """清理截图目录"""
        try:
            if os.path.exists(self.screenshot_dir):
                for file in os.listdir(self.screenshot_dir):
                    file_path = os.path.join(self.screenshot_dir, file)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        logger.error(f"删除截图失败 {file_path}: {str(e)}")
        except Exception as e:
            logger.error(f"清理截图目录失败: {str(e)}") 