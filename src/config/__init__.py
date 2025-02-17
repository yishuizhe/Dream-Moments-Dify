import os
import json
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class UserSettings:
    listen_list: List[str]

@dataclass
class LLMSettings:
    api_key: str
    base_url: str
    dify_api_key: str
    dify_base_url: str
    # model: str
    # max_tokens: int
    # temperature: float

@dataclass
class ImageRecognitionSettings:
    api_key: str
    base_url: str
    temperature: float

@dataclass
class ImageGenerationSettings:
    model: str
    temp_dir: str

@dataclass
class TextToSpeechSettings:
    tts_api_url: str
    voice_dir: str

@dataclass
class MediaSettings:
    image_recognition: ImageRecognitionSettings
    image_generation: ImageGenerationSettings
    text_to_speech: TextToSpeechSettings

@dataclass
class AutoMessageSettings:
    content: str
    min_hours: float
    max_hours: float

@dataclass
class QuietTimeSettings:
    start: str
    end: str

@dataclass
class ContextSettings:
    max_groups: int
    avatar_dir: str  # 人设目录路径，prompt文件和表情包目录都将基于此路径

@dataclass
class BehaviorSettings:
    auto_message: AutoMessageSettings
    quiet_time: QuietTimeSettings
    context: ContextSettings

class Config:
    def __init__(self):
        self.user: UserSettings
        self.llm: LLMSettings
        self.media: MediaSettings
        self.behavior: BehaviorSettings
        self.load_config()
    
    @property
    def config_dir(self) -> str:
        """返回配置文件所在目录"""
        return os.path.dirname(__file__)
    
    @property
    def config_path(self) -> str:
        """返回配置文件完整路径"""
        return os.path.join(self.config_dir, 'config.json')
    
    def save_config(self, config_data: dict) -> bool:
        """保存配置到文件
        
        Args:
            config_data: 要保存的配置数据
            
        Returns:
            bool: 保存是否成功
        """
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            return False
    
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_path):
                raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
                
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            categories = data['categories']
            
            # 用户设置
            user_data = categories['user_settings']['settings']
            self.user = UserSettings(
                listen_list=user_data['listen_list']['value']
            )
            
            # LLM设置
            llm_data = categories['llm_settings']['settings']
            self.llm = LLMSettings(
                api_key=llm_data['api_key']['value'],
                base_url=llm_data['base_url']['value'],
                dify_api_key=llm_data['dify_api_key']['value'],
                dify_base_url=llm_data['dify_base_url']['value'],
                # model=llm_data['model']['value'],
                # max_tokens=llm_data['max_tokens']['value'],
                # temperature=llm_data['temperature']['value']
            )
            
            # 媒体设置
            media_data = categories['media_settings']['settings']
            self.media = MediaSettings(
                image_recognition=ImageRecognitionSettings(
                    api_key=media_data['image_recognition']['api_key']['value'],
                    base_url=media_data['image_recognition']['base_url']['value'],
                    temperature=media_data['image_recognition']['temperature']['value']
                ),
                image_generation=ImageGenerationSettings(
                    model=media_data['image_generation']['model']['value'],
                    temp_dir=media_data['image_generation']['temp_dir']['value']
                ),
                text_to_speech=TextToSpeechSettings(
                    tts_api_url=media_data['text_to_speech']['tts_api_url']['value'],
                    voice_dir=media_data['text_to_speech']['voice_dir']['value']
                )
            )
            
            # 行为设置
            behavior_data = categories['behavior_settings']['settings']
            self.behavior = BehaviorSettings(
                auto_message=AutoMessageSettings(
                    content=behavior_data['auto_message']['content']['value'],
                    min_hours=behavior_data['auto_message']['countdown']['min_hours']['value'],
                    max_hours=behavior_data['auto_message']['countdown']['max_hours']['value']
                ),
                quiet_time=QuietTimeSettings(
                    start=behavior_data['quiet_time']['start']['value'],
                    end=behavior_data['quiet_time']['end']['value']
                ),
                context=ContextSettings(
                    max_groups=behavior_data['context']['max_groups']['value'],
                    avatar_dir=behavior_data['context']['avatar_dir']['value']
                )
            )
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            raise

# 创建全局配置实例
config = Config()

# 为了兼容性保留的旧变量（将在未来版本中移除）
LISTEN_LIST = config.user.listen_list
DEEPSEEK_API_KEY = config.llm.api_key
DEEPSEEK_BASE_URL = config.llm.base_url
# MODEL = config.llm.model
# MAX_TOKEN = config.llm.max_tokens
# TEMPERATURE = config.llm.temperature
MOONSHOT_API_KEY = config.media.image_recognition.api_key
MOONSHOT_BASE_URL = config.media.image_recognition.base_url
MOONSHOT_TEMPERATURE = config.media.image_recognition.temperature
IMAGE_MODEL = config.media.image_generation.model
TEMP_IMAGE_DIR = config.media.image_generation.temp_dir
MAX_GROUPS = config.behavior.context.max_groups
TTS_API_URL = config.media.text_to_speech.tts_api_url
VOICE_DIR = config.media.text_to_speech.voice_dir
AUTO_MESSAGE = config.behavior.auto_message.content
MIN_COUNTDOWN_HOURS = config.behavior.auto_message.min_hours
MAX_COUNTDOWN_HOURS = config.behavior.auto_message.max_hours
QUIET_TIME_START = config.behavior.quiet_time.start
QUIET_TIME_END = config.behavior.quiet_time.end 