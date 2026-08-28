import os
import json
import logging
import shutil
from dataclasses import dataclass, field
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
class OperitSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8094"
    bearer_token: str = ""
    allowed_senders: List[str] = field(default_factory=list)
    allowed_chats: List[str] = field(default_factory=list)
    allow_group_commands: bool = False
    command_prefixes: List[str] = field(
        default_factory=lambda: ["手机：", "手机:", "/手机 ", "/phone "]
    )
    request_timeout_seconds: float = 180.0
    show_floating: bool = True
    require_confirmation: bool = True
    confirmation_ttl_seconds: float = 120.0
    session_file: str = "data/operit_sessions.json"

@dataclass
class NanaPhoneSettings:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8765"
    pairing_token: str = ""
    request_timeout_seconds: float = 20.0

@dataclass
class LLMRouteSettings:
    name: str = ""
    enabled: bool = False
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    complex_only: bool = False
    max_tokens: int = 0

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
    fallback_routes: List[LLMRouteSettings] = field(default_factory=list)

@dataclass
class ImageRecognitionSettings:
    api_key: str
    base_url: str
    temperature: float
    model: str = "moonshot-v1-8k-vision-preview"

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
class ContextSettings:
    max_groups: int
    avatar_dir: str  # 人设目录路径，prompt文件和表情包目录都将基于此路径
    identity_aliases: List[str] = field(default_factory=list)

@dataclass
class BehaviorSettings:
    context: ContextSettings

@dataclass
class AuthSettings:
    admin_password: str

@dataclass
class Config:
    def __init__(self):
        self.user: UserSettings
        self.wechat: WeChatSettings
        self.operit: OperitSettings
        self.nana_phone: NanaPhoneSettings
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

                # Operit phone-control bridge. It is disabled and deny-by-default
                # so old configurations cannot accidentally expose a phone.
                operit_data = categories.get('operit_settings', {}).get('settings', {})
                self.operit = OperitSettings(
                    enabled=_as_bool(
                        operit_data.get('enabled', {}).get('value', False),
                        default=False,
                    ),
                    base_url=str(
                        operit_data.get('base_url', {}).get(
                            'value', 'http://127.0.0.1:8094'
                        )
                    ).strip() or 'http://127.0.0.1:8094',
                    bearer_token=str(
                        operit_data.get('bearer_token', {}).get('value', '')
                    ).strip(),
                    allowed_senders=[
                        str(item).strip()
                        for item in operit_data.get('allowed_senders', {}).get('value', [])
                        if str(item).strip()
                    ],
                    allowed_chats=[
                        str(item).strip()
                        for item in operit_data.get('allowed_chats', {}).get('value', [])
                        if str(item).strip()
                    ],
                    allow_group_commands=_as_bool(
                        operit_data.get('allow_group_commands', {}).get('value', False),
                        default=False,
                    ),
                    command_prefixes=[
                        str(item)
                        for item in operit_data.get('command_prefixes', {}).get(
                            'value', ["手机：", "手机:", "/手机 ", "/phone "]
                        )
                        if str(item).strip()
                    ],
                    request_timeout_seconds=float(
                        operit_data.get('request_timeout_seconds', {}).get('value', 180.0)
                    ),
                    show_floating=_as_bool(
                        operit_data.get('show_floating', {}).get('value', True),
                        default=True,
                    ),
                    require_confirmation=_as_bool(
                        operit_data.get('require_confirmation', {}).get('value', True),
                        default=True,
                    ),
                    confirmation_ttl_seconds=float(
                        operit_data.get('confirmation_ttl_seconds', {}).get('value', 120.0)
                    ),
                    session_file=str(
                        operit_data.get('session_file', {}).get(
                            'value', 'data/operit_sessions.json'
                        )
                    ).strip() or 'data/operit_sessions.json',
                )

                nana_phone_data = categories.get('nana_phone_settings', {}).get('settings', {})
                self.nana_phone = NanaPhoneSettings(
                    enabled=_as_bool(
                        nana_phone_data.get('enabled', {}).get('value', False),
                        default=False,
                    ),
                    base_url=str(
                        nana_phone_data.get('base_url', {}).get(
                            'value', 'http://127.0.0.1:8765'
                        )
                    ).strip() or 'http://127.0.0.1:8765',
                    pairing_token=str(
                        nana_phone_data.get('pairing_token', {}).get('value', '')
                    ).strip(),
                    request_timeout_seconds=float(
                        nana_phone_data.get('request_timeout_seconds', {}).get('value', 20.0)
                    ),
                )
                
                # LLM设置
                llm_data = categories['llm_settings']['settings']
                provider = str(
                    llm_data.get('provider', {}).get('value', 'deepseek')
                ).strip().lower()
                if provider not in {"deepseek", "openai_compatible", "dify"}:
                    provider = "deepseek"
                fallback_routes = []
                for index in range(1, 4):
                    prefix = f"fallback_{index}_"
                    route = LLMRouteSettings(
                        name=str(llm_data.get(prefix + 'name', {}).get('value', f'备用线路 {index}')).strip(),
                        enabled=_as_bool(llm_data.get(prefix + 'enabled', {}).get('value', False)),
                        api_key=str(llm_data.get(prefix + 'api_key', {}).get('value', '')).strip(),
                        base_url=str(llm_data.get(prefix + 'base_url', {}).get('value', '')).strip(),
                        model=str(llm_data.get(prefix + 'model', {}).get('value', '')).strip(),
                        complex_only=_as_bool(llm_data.get(prefix + 'complex_only', {}).get('value', False)),
                        max_tokens=int(llm_data.get(prefix + 'max_tokens', {}).get('value', 0) or 0),
                    )
                    if route.enabled or route.api_key or route.base_url or route.model:
                        fallback_routes.append(route)
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
                    fallback_routes=fallback_routes,
                )
                
                # 媒体设置
                media_data = categories['media_settings']['settings']
                self.media = MediaSettings(
                    image_recognition=ImageRecognitionSettings(
                        api_key=media_data['image_recognition']['api_key']['value'],
                        base_url=media_data['image_recognition']['base_url']['value'],
                        temperature=media_data['image_recognition']['temperature']['value'],
                        model=str(media_data['image_recognition'].get('model', {}).get('value', 'moonshot-v1-8k-vision-preview')).strip() or 'moonshot-v1-8k-vision-preview'
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
                behavior_data = categories.get('behavior_settings', {}).get('settings', {})
                context_data = behavior_data.get('context', {})
                self.behavior = BehaviorSettings(
                    context=ContextSettings(
                        max_groups=int(context_data.get('max_groups', {}).get('value', 5)),
                        avatar_dir=str(
                            context_data.get('avatar_dir', {}).get(
                                'value', 'data/avatars/NANA'
                            )
                        ).strip() or 'data/avatars/NANA',
                        identity_aliases=[
                            str(item).strip()
                            for item in context_data.get('identity_aliases', {}).get('value', [])
                            if str(item).strip()
                        ],
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
