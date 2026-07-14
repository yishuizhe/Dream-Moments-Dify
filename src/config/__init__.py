import os
import json
import logging
import shutil
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


def _as_bool(value, default: bool = False) -> bool:
    """兼容 JSON 布尔值以及 Web 表单常见的字符串布尔值。"""

    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return default

@dataclass
class UserSettings:
    listen_list: List[str]

@dataclass
class WeChatSettings:
    poll_interval: float = 2.0
    history_size: int = 50
    state_file: str = "data/wechat_poll_state.json"
    process_existing_on_start: bool = False
    exact_match: bool = True

@dataclass
class LLMSettings:
    api_key: str
    base_url: str
    dify_api_key: str
    dify_base_url: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    max_tokens: int = 2000
    temperature: float = 1.0

@dataclass
class ImageRecognitionSettings:
    api_key: str
    base_url: str
    temperature: float

@dataclass
class ImageGenerationSettings:
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temp_dir: str = "data/images/temp"

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

@dataclass
class AuthSettings:
    admin_password: str

@dataclass
class Config:
    def __init__(self):
        self.user: UserSettings
        self.wechat: WeChatSettings
        self.llm: LLMSettings
        self.media: MediaSettings
        self.behavior: BehaviorSettings
        self.auth: AuthSettings
        self.load_config()
    
    @property
    def config_dir(self) -> str:
        """返回配置文件所在目录"""
        return os.path.dirname(__file__)
    
    @property
    def config_path(self) -> str:
        """返回配置文件完整路径"""
        return os.path.join(self.config_dir, 'config.json')
    
    @property
    def config_template_path(self) -> str:
        """返回配置模板文件完整路径"""
        return os.path.join(self.config_dir, 'config.json.template')
    
    def save_config(self, config_data: dict) -> bool:
        """保存配置到文件"""
        try:
            # 读取现有配置
            with open(self.config_path, 'r', encoding='utf-8') as f:
                current_config = json.load(f)
            
            # 递归合并配置
            def merge_config(current: dict, new: dict):
                for key, value in new.items():
                    if key in current and isinstance(current[key], dict) and isinstance(value, dict):
                        merge_config(current[key], value)
                    else:
                        current[key] = value
            
            # 合并新配置
            merge_config(current_config, config_data)
            
            # 保存更新后的配置
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(current_config, f, indent=4, ensure_ascii=False)
            
            return True
        except Exception as e:
            logger.error(f"保存配置失败: {str(e)}")
            return False
    
    def load_config(self) -> None:
        """加载配置文件"""
        try:
            # 如果配置文件不存在，从模板创建
            if not os.path.exists(self.config_path):
                if os.path.exists(self.config_template_path):
                    logger.info("配置文件不存在，正在从模板创建...")
                    shutil.copy2(self.config_template_path, self.config_path)
                    logger.info(f"已从模板创建配置文件: {self.config_path}")
                # 如果配置文件仍然不存在，说明模板也不存在
                if not os.path.exists(self.config_path):
                    raise FileNotFoundError(f"配置文件不存在，且未找到模板文件: {self.config_template_path}")

            # 读取配置文件
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                categories = config_data['categories']
                
                # 用户设置
                user_data = categories['user_settings']['settings']
                self.user = UserSettings(
                    listen_list=user_data['listen_list']['value']
                )

                # WeChat 4 free polling settings; keep old configs compatible.
                wechat_data = categories.get('wechat_settings', {}).get('settings', {})
                self.wechat = WeChatSettings(
                    poll_interval=float(
                        wechat_data.get('poll_interval', {}).get('value', 2.0)
                    ),
                    history_size=int(
                        wechat_data.get('history_size', {}).get('value', 50)
                    ),
                    state_file=str(
                        wechat_data.get('state_file', {}).get(
                            'value',
                            'data/wechat_poll_state.json',
                        )
                    ),
                    process_existing_on_start=_as_bool(
                        wechat_data.get('process_existing_on_start', {}).get(
                            'value',
                            False,
                        ),
                        default=False,
                    ),
                    exact_match=_as_bool(
                        wechat_data.get('exact_match', {}).get('value', True),
                        default=True,
                    ),
                )
                
                # LLM设置
                llm_data = categories['llm_settings']['settings']
                provider = str(
                    llm_data.get('provider', {}).get('value', 'deepseek')
                ).strip().lower()
                if provider not in {"deepseek", "dify"}:
                    provider = "deepseek"
                self.llm = LLMSettings(
                    api_key=llm_data.get('api_key', {}).get('value', ''),
                    base_url=llm_data.get('base_url', {}).get('value', ''),
                    dify_api_key=llm_data.get('dify_api_key', {}).get('value', ''),
                    dify_base_url=llm_data.get('dify_base_url', {}).get('value', 'https://api.dify.ai/v1/'),
                    provider=provider,
                    model=str(
                        llm_data.get('model', {}).get('value', 'deepseek-chat')
                    ).strip() or 'deepseek-chat',
                    max_tokens=int(
                        llm_data.get('max_tokens', {}).get('value', 2000)
                    ),
                    temperature=float(
                        llm_data.get('temperature', {}).get('value', 1.0)
                    ),
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
                        enabled=_as_bool(
                            media_data.get('image_generation', {}).get('enabled', {}).get('value', False),
                            default=False,
                        ),
                        api_key=str(
                            media_data.get('image_generation', {}).get('api_key', {}).get('value', '')
                        ).strip(),
                        base_url=str(
                            media_data.get('image_generation', {}).get('base_url', {}).get('value', '')
                        ).strip(),
                        model=str(
                            media_data.get('image_generation', {}).get('model', {}).get('value', '')
                        ).strip(),
                        temp_dir=str(
                            media_data.get('image_generation', {}).get('temp_dir', {}).get(
                                'value', 'data/images/temp'
                            )
                        ).strip() or 'data/images/temp',
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
                
                # 认证设置
                auth_data = categories['auth_settings']['settings']
                self.auth = AuthSettings(
                    admin_password=auth_data['admin_password']['value']
                )
                
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            raise

    # 更新管理员密码
    def update_password(self, password: str) -> bool:
        try:
            config_data = {
                'categories': {
                    'auth_settings': {
                        'settings': {
                            'admin_password': {
                                'value': password
                            }
                        }
                    }
                }
            }
            return self.save_config(config_data)
        except Exception as e:
            logger.error(f"更新密码失败: {str(e)}")
            return False

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