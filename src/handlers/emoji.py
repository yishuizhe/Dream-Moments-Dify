"""
表情包处理模块
负责处理表情包选择和文件管理。
"""

import os
import random
import logging
import time
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

class EmojiHandler:
    def __init__(self, root_dir):
        self.root_dir = root_dir
        self.emoji_dir = os.path.join(root_dir, config.behavior.context.avatar_dir, "emojis")
        
        # 情感分类映射（情感目录名: 关键词列表）
        self.emotion_map = {
            'happy': ['开心', '高兴', '哈哈', '嘿嘿', '笑', '嘻嘻', '可爱', '好耶', '喜欢', '爱你', '呀', '啦', '嘛', '～'],
            'sad': ['难过', '伤心', '哭', '委屈', '泪', '呜呜', '悲'],
            'angry': ['生气', '怒', '哼', '啊啊', '呵呵', '讨厌', '气死', '才不要', '不理你'],
            'neutral': []  # 默认中性分类
        }
        self.emotion_map['sad'].extend(['心疼', '抱抱', '可怜'])
        self._last_sent_at: dict[str, float] = {}
        self.cooldown_seconds = 75.0
        
        # 确保目录存在
        os.makedirs(self.emoji_dir, exist_ok=True)

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

    def get_emotion_emoji(self, text: str, chat_id: str = "") -> Optional[str]:
        """根据AI回复内容的情感获取对应表情包"""
        try:
            # 检测情感分类
            emotion = self.detect_emotion(text)
            if emotion == 'neutral':
                return None
            key = str(chat_id or "").strip()
            now = time.monotonic()
            if key and now - self._last_sent_at.get(key, 0.0) < self.cooldown_seconds:
                logger.info("表情包冷却中，本次跳过: %s", key)
                return None
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
            if key:
                self._last_sent_at[key] = now
            logger.info(f"已选择 {emotion} 表情包: {selected}")
            return os.path.join(target_dir, selected)
        except Exception as e:
            logger.error(f"获取表情包失败: {str(e)}", exc_info=True)
            return None

