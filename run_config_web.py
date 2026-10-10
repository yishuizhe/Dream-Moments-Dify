"""
配置管理Web界面启动文件
提供Web配置界面功能，包括:
- 初始化Python路径
- 禁用字节码缓存
- 清理缓存文件
- 启动Web服务器
- 动态修改配置
"""
import os
import sys
import re
import logging
from flask import Flask, render_template, jsonify, request, send_from_directory
import importlib
import json
from colorama import init, Fore, Style
from typing import Dict, Any, List
import psutil
import subprocess
import threading
from src.autoupdate.updater import Updater
import requests
import time
from queue import Queue
import datetime
from logging.config import dictConfig
import shutil
import signal
import atexit
import socket
import webbrowser
import hashlib
import hmac
import secrets
from pathlib import Path
from src.utils.console import print_status

# 在文件开头添加全局变量声明
bot_process = None
bot_start_time = None
bot_logs = Queue(maxsize=1000)

WINDOWS_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
WINDOWS_NEW_PROCESS_GROUP = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)


def _windows_background_flags(with_process_group=False):
    if not sys.platform.startswith('win'):
        return 0
    return WINDOWS_NO_WINDOW | (WINDOWS_NEW_PROCESS_GROUP if with_process_group else 0)

# 配置日志
dictConfig({
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(levelname)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        }
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': 'WARNING'
        }
    },
    'root': {
        'level': 'WARNING',
        'handlers': ['console']
    },
    'loggers': {
        'werkzeug': {
            'level': 'ERROR',  # 将 Werkzeug 的日志级别设置为 ERROR
            'handlers': ['console'],
            'propagate': False
        }
    }
})

# 初始化日志记录器
logger = logging.getLogger(__name__)

# 初始化colorama
init()

# 添加项目根目录到Python路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT_DIR)

RUNTIME_SETTINGS_PATH = os.path.join(ROOT_DIR, "data", "web_runtime.json")


def load_runtime_settings() -> None:
    """Load console-managed runtime values before any bot process is started."""
    try:
        with open(RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as handle:
            values = json.load(handle)
        if isinstance(values, dict):
            for key, value in values.items():
                if isinstance(key, str) and key.startswith("DREAM_"):
                    os.environ.setdefault(key, str(value))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning("Unable to load runtime settings: %s", exc)

# 禁用Python的字节码缓存
sys.dont_write_bytecode = True

app = Flask(__name__, 
    template_folder=os.path.join(ROOT_DIR, 'src/webui/templates'),
    static_folder=os.path.join(ROOT_DIR, 'src/webui/static'))

load_runtime_settings()

def get_available_avatars() -> List[str]:
    """获取可用的人设目录列表"""
    avatar_base_dir = os.path.join(ROOT_DIR, "data/avatars")
    if not os.path.exists(avatar_base_dir):
        return []
    
    # 获取所有包含 avatar.md 和 emojis 目录的有效人设目录
    avatars = []
    for item in os.listdir(avatar_base_dir):
        avatar_dir = os.path.join(avatar_base_dir, item)
        if os.path.isdir(avatar_dir):
            if os.path.exists(os.path.join(avatar_dir, "avatar.md")) and \
               os.path.exists(os.path.join(avatar_dir, "emojis")):
                avatars.append(f"data/avatars/{item}")
    
    return avatars


def get_avatar_file(avatar_name: str) -> Path:
    """Resolve an avatar file without allowing traversal outside the avatar root."""
    if not isinstance(avatar_name, str) or not avatar_name.strip():
        raise ValueError("无效的人设名称")
    if avatar_name in {".", ".."} or "/" in avatar_name or "\\" in avatar_name or "\x00" in avatar_name:
        raise ValueError("无效的人设名称")

    avatar_root = (Path(ROOT_DIR) / "data" / "avatars").resolve()
    # Return a path obtained from trusted directory enumeration. The request value
    # is only used as an exact lookup key and is never joined into a filesystem path.
    known_avatars = {
        child.name: child / "avatar.md"
        for child in avatar_root.iterdir()
        if child.is_dir()
    }
    if avatar_name not in known_avatars:
        raise ValueError("人设不存在")
    return known_avatars[avatar_name]

def parse_config_groups() -> Dict[str, Dict[str, Any]]:
    """解析配置文件，将配置项按组分类"""
    from src.config import config

    config_groups = {
        "基础配置": {},
        "AI 备用线路": {},
        "图像识别API配置": {},
        "图像生成配置": {},
        "语音配置": {},
        "Prompt配置": {},
        "微信轮询配置": {},
        "Operit 手机控制": {},
        "娜娜自研手机端": {},
    }

    # 基础配置
    config_groups["基础配置"].update(
        {
            "LISTEN_LIST": {
                "value": config.user.listen_list,
                "description": "用户列表(请配置要和bot说话的账号的昵称或者群名，不要写备注！)",
            },
            "AI_PROVIDER": {
                "value": config.llm.provider,
                "description": "聊天 AI 提供方",
                "options": ["openai_compatible", "deepseek", "dify"],
            },
            "DEEPSEEK_BASE_URL": {
                "value": config.llm.base_url,
                "description": "DeepSeek/OpenAI 兼容 API 地址",
            },
            "DEEPSEEK_API_KEY": {
                "value": config.llm.api_key,
                "description": "DeepSeek/OpenAI 兼容 API 密钥",
                "is_secret": True,
            },
            "MODEL": {
                "value": config.llm.model,
                "description": "直接 API 模型名称",
            },
            "MAX_TOKEN": {
                "value": config.llm.max_tokens,
                "description": "回复最大 token 数",
                "type": "number",
            },
            "TEMPERATURE": {
                "value": float(config.llm.temperature),
                "type": "number",
                "description": "温度参数",
                "min": 0.0,
                "max": 2.0,
            },
            "DIFY_BASE_URL": {
                "value": config.llm.dify_base_url,
                "description": "Dify API 地址",
            },
            "DIFY_API_KEY": {
                "value": config.llm.dify_api_key,
                "description": "Dify API 密钥",
                "is_secret": True,
            },
        }
    )

    config_groups["微信轮询配置"].update(
        {
            "WECHAT_POLL_INTERVAL": {
                "value": config.wechat.poll_interval,
                "type": "number",
                "description": "检查新消息的间隔（秒）",
            },
            "WECHAT_HISTORY_SIZE": {
                "value": config.wechat.history_size,
                "type": "number",
                "description": "每个会话用于去重的最大消息数",
            },
            "WECHAT_STATE_FILE": {
                "value": config.wechat.state_file,
                "description": "轮询去重状态文件",
            },
            "WECHAT_PROCESS_EXISTING": {
                "value": config.wechat.process_existing_on_start,
                "type": "boolean",
                "description": "启动时是否处理当前窗口已有消息",
            },
            "WECHAT_EXACT_MATCH": {
                "value": config.wechat.exact_match,
                "type": "boolean",
                "description": "打开会话时是否精确匹配联系人或群名",
            },
        }
    )

    # 图像识别API配置
    config_groups["图像识别API配置"].update(
        {
            "MOONSHOT_API_KEY": {
                "value": config.media.image_recognition.api_key,
                "description": "Moonshot API密钥（用于图片和表情包识别）\n API申请https://platform.moonshot.cn/console/api-keys （免费15元额度）",
                "is_secret": True,
            },
            "MOONSHOT_BASE_URL": {
                "value": config.media.image_recognition.base_url,
                "description": "Moonshot API基础URL",
            },
            "MOONSHOT_MODEL": {
                "value": config.media.image_recognition.model,
                "description": "Vision model name",
            },
            "MOONSHOT_TEMPERATURE": {
                "value": config.media.image_recognition.temperature,
                "type": "number",
                "description": "Moonshot温度参数",
            },
        }
    )

    # 图像生成配置
    config_groups["图像生成配置"].update(
        {
            "IMAGE_ENABLED": {
                "value": config.media.image_generation.enabled,
                "description": "是否启用独立图像生成 API",
            },
            "IMAGE_API_KEY": {
                "value": config.media.image_generation.api_key,
                "description": "图像生成 API 密钥",
                "is_secret": True,
            },
            "IMAGE_BASE_URL": {
                "value": config.media.image_generation.base_url,
                "description": "图像生成 API 基础 URL",
            },
            "IMAGE_MODEL": {
                "value": config.media.image_generation.model,
                "description": "图像生成模型",
            },
            "TEMP_IMAGE_DIR": {
                "value": config.media.image_generation.temp_dir,
                "description": "临时图片目录",
            },
        }
    )

    # 语音配置
    config_groups["语音配置"].update(
        {
            "TTS_API_URL": {
                "value": config.media.text_to_speech.tts_api_url,
                "description": "语音服务API地址",
            },
            "VOICE_DIR": {
                "value": config.media.text_to_speech.voice_dir,
                "description": "语音文件目录",
            },
        }
    )

    # Prompt配置
    available_avatars = get_available_avatars()
    config_groups["Prompt配置"].update(
        {
            "MAX_GROUPS": {
                "value": config.behavior.context.max_groups,
                "type": "number",
                "description": "最大的上下文轮数",
            },
            "AVATAR_DIR": {
                "value": config.behavior.context.avatar_dir,
                "description": "人设目录（自动包含 avatar.md 和 emojis 目录）",
                "options": available_avatars,
                "type": "select"
            },
            "IDENTITY_ALIASES": {
                "value": config.behavior.context.identity_aliases,
                "type": "array",
                "description": "同一人身份映射：本人=私聊昵称|群昵称1|群昵称2（连续等号也可）",
            }
        }
    )

    for index in range(1, 4):
        route = config.llm.fallback_routes[index - 1] if index <= len(config.llm.fallback_routes) else None
        prefix = f"FALLBACK_{index}_"
        config_groups["AI 备用线路"].update({
            prefix + "ENABLED": {"value": bool(route and route.enabled), "type": "boolean", "description": f"启用备用线路 {index}"},
            prefix + "NAME": {"value": route.name if route else f"备用线路 {index}", "description": "仅用于日志识别，不会发给对方"},
            prefix + "BASE_URL": {"value": route.base_url if route else "", "description": "OpenAI 兼容 API 基础 URL"},
            prefix + "API_KEY": {"value": route.api_key if route else "", "description": "API 密钥", "is_secret": True},
            prefix + "MODEL": {"value": route.model if route else "", "description": "模型 ID"},
            prefix + "COMPLEX_ONLY": {"value": bool(route and route.complex_only), "type": "boolean", "description": "只有复杂任务才允许走该线路（适合付费模型）"},
            prefix + "MAX_TOKENS": {"value": route.max_tokens if route and route.max_tokens else config.llm.max_tokens, "type": "number", "description": "该线路最大输出 token"},
        })

    config_groups["Operit 手机控制"].update(
        {
            "OPERIT_ENABLED": {"value": config.operit.enabled, "type": "boolean", "description": "启用微信到 Operit 的安卓手机控制桥接"},
            "OPERIT_BASE_URL": {"value": config.operit.base_url, "description": "例如 http://192.168.1.23:8094"},
            "OPERIT_BEARER_TOKEN": {"value": config.operit.bearer_token, "description": "Operit 外部 HTTP API Bearer Token", "is_secret": True},
            "OPERIT_ALLOWED_SENDERS": {"value": config.operit.allowed_senders, "type": "array", "description": "允许控制手机的微信发送者 ID 或昵称；不能为空"},
            "OPERIT_ALLOWED_CHATS": {"value": config.operit.allowed_chats, "type": "array", "description": "可选的微信会话白名单"},
            "OPERIT_ALLOW_GROUPS": {"value": config.operit.allow_group_commands, "type": "boolean", "description": "允许群聊手机指令；建议保持关闭"},
            "OPERIT_PREFIXES": {"value": config.operit.command_prefixes, "type": "array", "description": "只有这些明确前缀会被转发"},
            "OPERIT_TIMEOUT": {"value": config.operit.request_timeout_seconds, "type": "number", "description": "等待单个手机任务的最长秒数"},
            "OPERIT_SHOW_FLOATING": {"value": config.operit.show_floating, "type": "boolean", "description": "执行时显示 Operit 浮窗"},
            "OPERIT_REQUIRE_CONFIRMATION": {"value": config.operit.require_confirmation, "type": "boolean", "description": "高风险操作要求一次性确认码"},
            "OPERIT_CONFIRM_TTL": {"value": config.operit.confirmation_ttl_seconds, "type": "number", "description": "确认码有效秒数"},
        }
    )

    config_groups["娜娜自研手机端"].update(
        {
            "NANA_PHONE_ENABLED": {"value": config.nana_phone.enabled, "type": "boolean", "description": "优先使用自研手机端；开启后不再调用 Operit"},
            "NANA_PHONE_BASE_URL": {"value": config.nana_phone.base_url, "description": "例如 http://100.x.x.x:8765"},
            "NANA_PHONE_PAIRING_TOKEN": {"value": config.nana_phone.pairing_token, "description": "手机 App 中显示的配对密钥", "is_secret": True},
            "NANA_PHONE_TIMEOUT": {"value": config.nana_phone.request_timeout_seconds, "type": "number", "description": "单个手机动作的超时秒数"},
        }
    )

    return config_groups


def save_config(new_config: Dict[str, Any]) -> bool:
    """保存新的配置到文件"""
    try:
        from src.config import (
            UserSettings,
            WeChatSettings,
            OperitSettings,
            NanaPhoneSettings,
            LLMRouteSettings,
            LLMSettings,
            ImageRecognitionSettings,
            ImageGenerationSettings,
            TextToSpeechSettings,
            MediaSettings,
            ContextSettings,
            BehaviorSettings,
            config
        )

        # 构建所有新的配置对象
        def parse_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}

        wechat_settings = WeChatSettings(
            poll_interval=float(new_config.get("WECHAT_POLL_INTERVAL", config.wechat.poll_interval)),
            history_size=int(new_config.get("WECHAT_HISTORY_SIZE", config.wechat.history_size)),
            state_file=str(
                new_config.get("WECHAT_STATE_FILE", config.wechat.state_file)
            ),
            process_existing_on_start=parse_bool(
                new_config.get("WECHAT_PROCESS_EXISTING", config.wechat.process_existing_on_start)
            ),
            exact_match=parse_bool(new_config.get("WECHAT_EXACT_MATCH", config.wechat.exact_match)),
        )

        operit_settings = OperitSettings(
            enabled=parse_bool(new_config.get("OPERIT_ENABLED", config.operit.enabled)),
            base_url=str(new_config.get("OPERIT_BASE_URL", config.operit.base_url)).strip(),
            bearer_token=str(new_config.get("OPERIT_BEARER_TOKEN", config.operit.bearer_token)).strip(),
            allowed_senders=[str(item).strip() for item in new_config.get("OPERIT_ALLOWED_SENDERS", config.operit.allowed_senders) if str(item).strip()],
            allowed_chats=[str(item).strip() for item in new_config.get("OPERIT_ALLOWED_CHATS", config.operit.allowed_chats) if str(item).strip()],
            allow_group_commands=parse_bool(new_config.get("OPERIT_ALLOW_GROUPS", config.operit.allow_group_commands)),
            command_prefixes=[str(item) for item in new_config.get("OPERIT_PREFIXES", config.operit.command_prefixes) if str(item).strip()],
            request_timeout_seconds=float(new_config.get("OPERIT_TIMEOUT", config.operit.request_timeout_seconds)),
            show_floating=parse_bool(new_config.get("OPERIT_SHOW_FLOATING", config.operit.show_floating)),
            require_confirmation=parse_bool(new_config.get("OPERIT_REQUIRE_CONFIRMATION", config.operit.require_confirmation)),
            confirmation_ttl_seconds=float(new_config.get("OPERIT_CONFIRM_TTL", config.operit.confirmation_ttl_seconds)),
            session_file=config.operit.session_file,
        )

        nana_phone_settings = NanaPhoneSettings(
            enabled=parse_bool(new_config.get("NANA_PHONE_ENABLED", config.nana_phone.enabled)),
            base_url=str(new_config.get("NANA_PHONE_BASE_URL", config.nana_phone.base_url)).strip(),
            pairing_token=str(new_config.get("NANA_PHONE_PAIRING_TOKEN", config.nana_phone.pairing_token)).strip(),
            request_timeout_seconds=float(new_config.get("NANA_PHONE_TIMEOUT", config.nana_phone.request_timeout_seconds)),
        )

        provider = str(new_config.get("AI_PROVIDER", config.llm.provider)).strip().lower()
        if provider not in {"deepseek", "openai_compatible", "dify"}:
            provider = "deepseek"
        fallback_routes = []
        for index in range(1, 4):
            current = config.llm.fallback_routes[index - 1] if index <= len(config.llm.fallback_routes) else LLMRouteSettings()
            prefix = f"FALLBACK_{index}_"
            fallback_routes.append(LLMRouteSettings(
                name=str(new_config.get(prefix + "NAME", current.name or f"备用线路 {index}")).strip(),
                enabled=parse_bool(new_config.get(prefix + "ENABLED", current.enabled)),
                api_key=str(new_config.get(prefix + "API_KEY", current.api_key) or "").strip(),
                base_url=str(new_config.get(prefix + "BASE_URL", current.base_url) or "").strip(),
                model=str(new_config.get(prefix + "MODEL", current.model) or "").strip(),
                complex_only=parse_bool(new_config.get(prefix + "COMPLEX_ONLY", current.complex_only)),
                max_tokens=int(new_config.get(prefix + "MAX_TOKENS", current.max_tokens or config.llm.max_tokens)),
            ))
        llm_settings = LLMSettings(
            api_key=new_config.get("DEEPSEEK_API_KEY", config.llm.api_key),
            base_url=new_config.get("DEEPSEEK_BASE_URL", config.llm.base_url),
            dify_api_key=new_config.get("DIFY_API_KEY", config.llm.dify_api_key),
            dify_base_url=new_config.get("DIFY_BASE_URL", config.llm.dify_base_url),
            provider=provider,
            model=str(new_config.get("MODEL", config.llm.model)).strip()
            or config.llm.model,
            max_tokens=int(new_config.get("MAX_TOKEN", config.llm.max_tokens)),
            temperature=float(new_config.get("TEMPERATURE", config.llm.temperature)),
            fallback_routes=fallback_routes,
        )

        media_settings = MediaSettings(
            image_recognition=ImageRecognitionSettings(
                api_key=new_config.get("MOONSHOT_API_KEY", config.media.image_recognition.api_key),
                base_url=new_config.get("MOONSHOT_BASE_URL", config.media.image_recognition.base_url),
                temperature=float(new_config.get("MOONSHOT_TEMPERATURE", config.media.image_recognition.temperature)),
                model=str(new_config.get("MOONSHOT_MODEL", config.media.image_recognition.model) or config.media.image_recognition.model).strip(),
            ),
            image_generation=ImageGenerationSettings(
                enabled=parse_bool(new_config.get("IMAGE_ENABLED", config.media.image_generation.enabled)),
                api_key=str(new_config.get("IMAGE_API_KEY", config.media.image_generation.api_key) or "").strip(),
                base_url=str(new_config.get("IMAGE_BASE_URL", config.media.image_generation.base_url) or "").strip(),
                model=str(new_config.get("IMAGE_MODEL", config.media.image_generation.model) or "").strip(),
                temp_dir=str(new_config.get("TEMP_IMAGE_DIR", config.media.image_generation.temp_dir) or config.media.image_generation.temp_dir).strip(),
            ),
            text_to_speech=TextToSpeechSettings(
                tts_api_url=new_config.get("TTS_API_URL", config.media.text_to_speech.tts_api_url),
                voice_dir=new_config.get("VOICE_DIR", config.media.text_to_speech.voice_dir),
            )
        )

        behavior_settings = BehaviorSettings(
            context=ContextSettings(
                max_groups=int(new_config.get("MAX_GROUPS", config.behavior.context.max_groups)),
                avatar_dir=new_config.get("AVATAR_DIR", config.behavior.context.avatar_dir),
                identity_aliases=[
                    str(item).strip()
                    for item in new_config.get(
                        "IDENTITY_ALIASES", config.behavior.context.identity_aliases
                    )
                    if str(item).strip()
                ],
            ),
        )

        # 构建JSON结构
        config_data = {
            "categories": {
                "user_settings": {
                    "title": "用户设置",
                    "settings": {
                        "listen_list": {
                            "value": UserSettings(listen_list=new_config.get("LISTEN_LIST", config.user.listen_list)).listen_list,
                            "type": "array",
                            "description": "要监听的用户列表（请使用微信昵称，不要使用备注名）",
                        }
                    },
                },
                "wechat_settings": {
                    "title": "微信4免费轮询设置",
                    "settings": {
                        "poll_interval": {
                            "value": wechat_settings.poll_interval,
                            "type": "number",
                            "description": "每轮轮询之间的等待秒数",
                        },
                        "history_size": {
                            "value": wechat_settings.history_size,
                            "type": "number",
                            "description": "每个会话用于快照去重的最大消息数",
                        },
                        "state_file": {
                            "value": wechat_settings.state_file,
                            "type": "string",
                            "description": "轮询去重状态文件",
                        },
                        "process_existing_on_start": {
                            "value": wechat_settings.process_existing_on_start,
                            "type": "boolean",
                            "description": "首次启动时是否处理当前窗口中已有的历史消息",
                        },
                        "exact_match": {
                            "value": wechat_settings.exact_match,
                            "type": "boolean",
                            "description": "打开会话时是否精确匹配联系人或群名",
                        },
                    },
                },
                "operit_settings": {
                    "title": "Operit 安卓手机控制",
                    "settings": {
                        "enabled": {"value": operit_settings.enabled, "type": "boolean", "description": "启用微信到 Operit 的手机控制桥接"},
                        "base_url": {"value": operit_settings.base_url, "type": "string", "description": "Operit 外部 HTTP API 地址"},
                        "bearer_token": {"value": operit_settings.bearer_token, "type": "string", "description": "Operit Bearer Token", "is_secret": True},
                        "allowed_senders": {"value": operit_settings.allowed_senders, "type": "array", "description": "允许控制手机的微信发送者 ID 或昵称"},
                        "allowed_chats": {"value": operit_settings.allowed_chats, "type": "array", "description": "可选的微信会话白名单"},
                        "allow_group_commands": {"value": operit_settings.allow_group_commands, "type": "boolean", "description": "允许群聊手机指令"},
                        "command_prefixes": {"value": operit_settings.command_prefixes, "type": "array", "description": "手机指令前缀"},
                        "request_timeout_seconds": {"value": operit_settings.request_timeout_seconds, "type": "number", "description": "手机任务超时秒数"},
                        "show_floating": {"value": operit_settings.show_floating, "type": "boolean", "description": "执行时显示 Operit 浮窗"},
                        "require_confirmation": {"value": operit_settings.require_confirmation, "type": "boolean", "description": "高风险操作要求确认码"},
                        "confirmation_ttl_seconds": {"value": operit_settings.confirmation_ttl_seconds, "type": "number", "description": "确认码有效秒数"},
                        "session_file": {"value": operit_settings.session_file, "type": "string", "description": "会话映射文件"}
                    }
                },
                "nana_phone_settings": {
                    "title": "娜娜自研手机端",
                    "settings": {
                        "enabled": {"value": nana_phone_settings.enabled, "type": "boolean", "description": "优先使用自研 NanaPhone"},
                        "base_url": {"value": nana_phone_settings.base_url, "type": "string", "description": "NanaPhone HTTP 地址"},
                        "pairing_token": {"value": nana_phone_settings.pairing_token, "type": "string", "description": "NanaPhone 配对密钥", "is_secret": True},
                        "request_timeout_seconds": {"value": nana_phone_settings.request_timeout_seconds, "type": "number", "description": "手机动作超时秒数"}
                    }
                },
                "llm_settings": {
                    "title": "大语言模型配置",
                    "settings": {
                        "provider": {
                            "value": llm_settings.provider,
                            "type": "string",
                            "description": "聊天 AI 提供方",
                            "options": ["openai_compatible", "deepseek", "dify"],
                        },
                        "api_key": {
                            "value": llm_settings.api_key,
                            "type": "string",
                            "description": "API密钥",
                            "is_secret": True,
                        },
                        "base_url": {
                            "value": llm_settings.base_url,
                            "type": "string",
                            "description": "DeepSeek API基础URL",
                        },
                        "dify_api_key": {
                            "value": llm_settings.dify_api_key,
                            "type": "string",
                            "description": "DIFY API密钥",
                            "is_secret": True,
                        },
                        "dify_base_url": {
                            "value": llm_settings.dify_base_url,
                            "type": "string",
                            "description": "DIFY API基础URL",
                        },
                        "model": {
                            "value": llm_settings.model,
                            "type": "string",
                            "description": "使用的AI模型名称",
                            "options": [
                                "deepseek-ai/DeepSeek-V3",
                                "Pro/deepseek-ai/DeepSeek-V3",
                                "Pro/deepseek-ai/DeepSeek-R1",
                                "deepseek-chat",
                                "deepseek-reasoner",
                            ],
                        },
                        "max_tokens": {
                            "value": llm_settings.max_tokens,
                            "type": "number",
                            "description": "回复最大token数量",
                        },
                        "temperature": {
                            "value": llm_settings.temperature,
                            "type": "number",
                            "description": "AI回复的温度值",
                            "min": 0.0,
                            "max": 2.0,
                        },
                        **{
                            f"fallback_{index}_{field}": metadata
                            for index, route in enumerate(llm_settings.fallback_routes, 1)
                            for field, metadata in {
                                "enabled": {"value": route.enabled, "type": "boolean", "description": f"启用备用线路 {index}"},
                                "name": {"value": route.name, "type": "string", "description": "线路名称"},
                                "api_key": {"value": route.api_key, "type": "string", "description": "API 密钥", "is_secret": True},
                                "base_url": {"value": route.base_url, "type": "string", "description": "OpenAI 兼容 API URL"},
                                "model": {"value": route.model, "type": "string", "description": "模型 ID"},
                                "complex_only": {"value": route.complex_only, "type": "boolean", "description": "仅复杂任务使用"},
                                "max_tokens": {"value": route.max_tokens, "type": "number", "description": "最大输出 token"},
                            }.items()
                        },
                    },
                },
                "media_settings": {
                    "title": "媒体设置",
                    "settings": {
                        "image_recognition": {
                            "api_key": {
                                "value": media_settings.image_recognition.api_key,
                                "type": "string",
                                "description": "Moonshot AI API密钥（用于图片和表情包识别）",
                                "is_secret": True,
                            },
                            "base_url": {
                                "value": media_settings.image_recognition.base_url,
                                "type": "string",
                                "description": "Moonshot API基础URL",
                            },
                            "temperature": {
                                "value": media_settings.image_recognition.temperature,
                                "type": "number",
                                "description": "Moonshot AI的温度值",
                                "min": 0,
                                "max": 2,
                            },
                        },
                        "image_generation": {
                            "enabled": {
                                "value": media_settings.image_generation.enabled,
                                "type": "boolean",
                                "description": "是否启用独立图像生成 API",
                            },
                            "api_key": {
                                "value": media_settings.image_generation.api_key,
                                "type": "string",
                                "description": "图像生成 API 密钥",
                                "is_secret": True,
                            },
                            "base_url": {
                                "value": media_settings.image_generation.base_url,
                                "type": "string",
                                "description": "图像生成 API 基础 URL",
                            },
                            "model": {
                                "value": media_settings.image_generation.model,
                                "type": "string",
                                "description": "图像生成模型",
                            },
                            "temp_dir": {
                                "value": media_settings.image_generation.temp_dir,
                                "type": "string",
                                "description": "临时图片存储目录",
                            },
                        },
                        "text_to_speech": {
                            "tts_api_url": {
                                "value": media_settings.text_to_speech.tts_api_url,
                                "type": "string",
                                "description": "TTS服务API地址",
                            },
                            "voice_dir": {
                                "value": media_settings.text_to_speech.voice_dir,
                                "type": "string",
                                "description": "语音文件存储目录",
                            },
                        }
                    },
                },
                "behavior_settings": {
                    "title": "行为设置",
                    "settings": {
                        "context": {
                            "max_groups": {
                                "value": behavior_settings.context.max_groups,
                                "type": "number",
                                "description": "最大上下文轮数",
                            },
                            "avatar_dir": {
                                "value": behavior_settings.context.avatar_dir,
                                "type": "string",
                                "description": "人设目录（自动包含 avatar.md 和 emojis 目录）",
                            },
                            "identity_aliases": {
                                "value": behavior_settings.context.identity_aliases,
                                "type": "array",
                                "description": "同一人身份映射：本人=私聊昵称|群昵称1|群昵称2（连续等号也可）",
                            },
                        },
                    },
                },
            }
        }

        # # 在保存前记录最终的温度配置
        # final_temp = config_data["categories"]["llm_settings"]["settings"]["temperature"]["value"]
        # logger.debug(f"最终保存到JSON的温度值: {final_temp} (类型: {type(final_temp)})")

        # 使用 Config 类的方法保存配置
        if not config.save_config(config_data):
            logger.error("保存配置失败")
            return False

        # 重新加载配置模块
        importlib.reload(sys.modules["src.config"])
        
        logger.debug("配置已成功保存和重新加载")
        return True
        
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        return False


@app.route('/')
def index():
    return render_template('console.html')

@app.route('/console')
def console():
    return render_template('console.html', is_local=is_local_network())


def _runtime_settings() -> Dict[str, str]:
    keys = (
        "DREAM_DAILY_BRIEFING_ENABLED",
        "DREAM_DAILY_BRIEFING_TIME",
        "DREAM_DAILY_BRIEFING_TARGETS",
        "DREAM_REPLY_DELAY_BASE",
        "DREAM_REPLY_DELAY_PER_CHAR",
        "DREAM_REPLY_DELAY_MAX",
        "DREAM_ROBOT_NAME",
    )
    defaults = {
        "DREAM_DAILY_BRIEFING_ENABLED": "0",
        "DREAM_DAILY_BRIEFING_TIME": "08:00",
        "DREAM_DAILY_BRIEFING_TARGETS": "",
        "DREAM_REPLY_DELAY_BASE": "0.8",
        "DREAM_REPLY_DELAY_PER_CHAR": "0.025",
        "DREAM_REPLY_DELAY_MAX": "5.0",
        "DREAM_ROBOT_NAME": "",
    }
    return {key: os.environ.get(key, defaults[key]) for key in keys}


def _save_runtime_settings(values: Dict[str, Any]) -> bool:
    allowed = set(_runtime_settings())
    cleaned = {key: str(value) for key, value in values.items() if key in allowed}
    current = {}
    try:
        if os.path.exists(RUNTIME_SETTINGS_PATH):
            with open(RUNTIME_SETTINGS_PATH, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
                if isinstance(loaded, dict):
                    current.update(loaded)
        current.update(cleaned)
        os.makedirs(os.path.dirname(RUNTIME_SETTINGS_PATH), exist_ok=True)
        with open(RUNTIME_SETTINGS_PATH, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        os.environ.update(cleaned)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.error("保存运行参数失败: %s", exc)
        return False


def _read_avatar(avatar_name: str = "MONO") -> Dict[str, Any]:
    avatar_path = get_avatar_file(avatar_name)
    if not avatar_path.exists():
        return {"name": avatar_name, "content": {}, "raw_content": ""}
    sections: Dict[str, str] = {}
    current = None
    buffer: List[str] = []
    raw_content = avatar_path.read_text(encoding="utf-8")
    for line in raw_content.splitlines():
        if line.startswith("# "):
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = line[2:].strip().lower()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return {"name": avatar_name, "content": sections, "raw_content": raw_content}

@app.route('/console_state')
def console_state():
    from src.config import config
    running = bool(bot_process and bot_process.poll() is None)
    recent = list(bot_logs.queue)[-12:] if hasattr(bot_logs, 'queue') else []
    return jsonify({
        'status': 'success',
        'running': running,
        'pid': bot_process.pid if running else None,
        'listen_list': list(config.user.listen_list),
        'provider': config.llm.provider,
        'model': config.llm.model,
        'vision_model': config.media.image_recognition.model,
        'runtime': _runtime_settings(),
        'logs': recent,
    })

@app.route('/console_config')
def console_config():
    """Return all editable settings for the single current console."""
    avatars = get_available_avatars()
    names = [item.rsplit('/', 1)[-1] for item in avatars]
    selected = os.path.basename(str(__import__('src.config', fromlist=['config']).config.behavior.context.avatar_dir))
    try:
        avatar = _read_avatar(selected if selected in names else (names[0] if names else "MONO"))
    except (OSError, ValueError):
        avatar = {"name": selected, "content": {}, "raw_content": ""}
    return jsonify({
        'status': 'success',
        'groups': parse_config_groups(),
        'runtime': _runtime_settings(),
        'avatars': names,
        'avatar': avatar,
    })


@app.route('/console_save_config', methods=['POST'])
def console_save_config():
    payload = request.get_json(silent=True) or {}
    config_values = payload.get('config', payload)
    runtime_values = payload.get('runtime', {})
    if not isinstance(config_values, dict) or not isinstance(runtime_values, dict):
        return jsonify({'status': 'error', 'message': '配置格式无效'}), 400
    if not save_config(config_values):
        return jsonify({'status': 'error', 'message': '配置保存失败'}), 500
    if runtime_values and not _save_runtime_settings(runtime_values):
        return jsonify({'status': 'error', 'message': '运行参数保存失败'}), 500
    return jsonify({'status': 'success', 'message': '设置已保存，重启机器人后全部生效'})


@app.route('/console_avatar', methods=['GET', 'POST'])
def console_avatar():
    if request.method == 'GET':
        name = request.args.get('avatar', 'MONO')
        try:
            return jsonify({'status': 'success', **_read_avatar(name)})
        except (OSError, ValueError) as exc:
            logger.warning("读取人设失败: %s", exc)
            return jsonify({'status': 'error', 'message': '无法读取指定人设'}), 400
    payload = request.get_json(silent=True) or {}
    name = payload.pop('avatar', 'MONO')
    try:
        path = get_avatar_file(name)
        lines = []
        for key, value in payload.items():
            if str(value).strip():
                lines.extend([f"# {key.capitalize()}", str(value).strip(), ""])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding='utf-8')
        return jsonify({'status': 'success', 'message': '人设已保存'})
    except (OSError, ValueError) as exc:
        logger.error("保存人设失败: %s", exc)
        return jsonify({'status': 'error', 'message': '人设保存失败'}), 400

@app.route('/system_info')
def system_info():
    """获取系统信息"""
    try:
        # 创建静态变量存储上次的值
        if not hasattr(system_info, 'last_bytes'):
            system_info.last_bytes = {
                'sent': 0,
                'recv': 0,
                'time': time.time()
            }

        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        
        # 计算网络速度
        current_time = time.time()
        time_delta = current_time - system_info.last_bytes['time']
        
        # 计算每秒的字节数
        upload_speed = (net.bytes_sent - system_info.last_bytes['sent']) / time_delta
        download_speed = (net.bytes_recv - system_info.last_bytes['recv']) / time_delta
        
        # 更新上次的值
        system_info.last_bytes = {
            'sent': net.bytes_sent,
            'recv': net.bytes_recv,
            'time': current_time
        }
        
        # 转换为 KB/s
        upload_speed = upload_speed / 1024
        download_speed = download_speed / 1024
        
        return jsonify({
            'cpu': cpu_percent,
            'memory': {
                'total': round(memory.total / (1024**3), 2),
                'used': round(memory.used / (1024**3), 2),
                'percent': memory.percent
            },
            'disk': {
                'total': round(disk.total / (1024**3), 2),
                'used': round(disk.used / (1024**3), 2),
                'percent': disk.percent
            },
            'network': {
                'upload': round(upload_speed, 2),
                'download': round(download_speed, 2)
            }
        })
    except Exception as e:
        logger.error(f"获取系统信息失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': '获取系统信息失败'
        }), 500

@app.route('/check_update')
def check_update():
    """检查更新"""
    try:
        updater = Updater()
        result = updater.check_for_updates()
        
        return jsonify({
            'status': 'success',
            'has_update': result.get('has_update', False),
            'console_output': result['output'],
            'update_info': result if result.get('has_update') else None,
            'wait_input': result.get('has_update', False)
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'has_update': False,
            'console_output': '检查更新失败，请查看服务日志'
        })

@app.route('/confirm_update', methods=['POST'])
def confirm_update():
    """确认是否更新"""
    try:
        choice = request.json.get('choice', '').lower()
        if choice in ('y', 'yes'):
            updater = Updater()
            result = updater.update()
            
            return jsonify({
                'status': 'success' if result['success'] else 'error',
                'console_output': '更新完成' if result['success'] else '更新失败，请查看服务日志'
            })
        else:
            return jsonify({
                'status': 'success',
                'console_output': '用户取消更新'
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'console_output': '更新失败，请查看服务日志'
        })

@app.route('/start_bot')
def start_bot():
    """启动机器人"""
    global bot_process, bot_start_time
    try:
        if bot_process and bot_process.poll() is None:
            return jsonify({
                'status': 'error',
                'message': '机器人已在运行中'
            })
        
        # 清空之前的日志
        while not bot_logs.empty():
            bot_logs.get()
        
        # 设置环境变量
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        # 创建新的进程组
        if sys.platform.startswith('win'):
            creationflags = _windows_background_flags(with_process_group=True)
        else:
            creationflags = 0
        
        # 启动进程
        bot_process = subprocess.Popen(
            [sys.executable, 'run.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
            env=env,
            encoding='utf-8',
            errors='replace',
            creationflags=creationflags if sys.platform.startswith('win') else 0,
            preexec_fn=os.setsid if not sys.platform.startswith('win') else None
        )
        
        # 记录启动时间
        bot_start_time = datetime.datetime.now()
        
        # 启动日志读取线程
        def read_output():
            try:
                while bot_process and bot_process.poll() is None:
                    line = bot_process.stdout.readline()
                    if line:
                        try:
                            # 尝试解码并清理日志内容
                            line = line.strip()
                            if isinstance(line, bytes):
                                line = line.decode('utf-8', errors='replace')
                            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
                            bot_logs.put(f"[{timestamp}] {line}")
                        except Exception as e:
                            logger.error(f"日志处理错误: {str(e)}")
                            continue
            except Exception as e:
                logger.error(f"读取日志失败: {str(e)}")
                bot_logs.put(f"[ERROR] 读取日志失败: {str(e)}")
        
        thread = threading.Thread(target=read_output, daemon=True)
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': '机器人启动成功'
        })
    except Exception as e:
        logger.error(f"启动机器人失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': '启动机器人失败'
        })

@app.route('/get_bot_logs')
def get_bot_logs():
    """获取机器人日志"""
    logs = []
    while not bot_logs.empty():
        logs.append(bot_logs.get())
    
    # 获取运行时间
    uptime = '0分钟'
    if bot_start_time and bot_process and bot_process.poll() is None:
        delta = datetime.datetime.now() - bot_start_time
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            uptime = f"{hours}小时{minutes}分钟{seconds}秒"
        elif minutes > 0:
            uptime = f"{minutes}分钟{seconds}秒"
        else:
            uptime = f"{seconds}秒"
    
    return jsonify({
        'status': 'success',
        'logs': logs,
        'uptime': uptime,
        'is_running': bot_process is not None and bot_process.poll() is None
    })

@app.route('/stop_bot')
def stop_bot():
    """停止机器人"""
    global bot_process
    try:
        if bot_process:
            # 首先尝试正常终止进程
            bot_process.terminate()
            
            # 等待进程结束
            try:
                bot_process.wait(timeout=5)  # 等待最多5秒
            except subprocess.TimeoutExpired:
                # 如果超时，强制结束进程
                bot_process.kill()
                bot_process.wait()
            
            # 确保所有子进程都被终止
            if sys.platform.startswith('win'):
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(bot_process.pid)],
                    capture_output=True,
                    creationflags=_windows_background_flags(),
                )
            else:
                import signal
                os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
            
            # 清理进程对象
            bot_process = None
            
            # 添加日志记录
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            bot_logs.put(f"[{timestamp}] 正在关闭监听线程...")
            bot_logs.put(f"[{timestamp}] 正在关闭系统...")
            bot_logs.put(f"[{timestamp}] 系统已退出")
            
            return jsonify({
                'status': 'success',
                'message': '机器人已停止'
            })
            
        return jsonify({
            'status': 'error',
            'message': '机器人未在运行'
        })
    except Exception as e:
        logger.error(f"停止机器人失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': '停止机器人失败'
        })

# 添加获取用户信息的路由
@app.route('/user_info')
def get_user_info():
    """获取用户账户信息"""
    try:
        from src.config import config
        api_key = config.llm.api_key
        base_url = config.llm.base_url.rstrip('/')
        
        # 确保使用正确的API端点
        if 'siliconflow.cn' in base_url:
            api_url = f"{base_url}/user/info"
        else:
            return jsonify({
                'status': 'error',
                'message': '当前API不支持查询用户信息'
            })
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') is True and data.get('data'):  # 修改判断条件
                user_data = data['data']
                return jsonify({
                    'status': 'success',
                    'data': {
                        'balance': user_data.get('balance', '0'),
                        'total_balance': user_data.get('totalBalance', '0'),
                        'charge_balance': user_data.get('chargeBalance', '0'),
                        'name': user_data.get('name', 'Unknown'),
                        'email': user_data.get('email', 'Unknown'),
                        'status': user_data.get('status', 'Unknown')
                    }
                })
            
        return jsonify({
            'status': 'error',
            'message': f"API返回错误: {response.text}"
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': '获取用户信息失败'
        })

# This legacy helper is intentionally not exposed over HTTP.
def execute_command():
    """执行控制台命令"""
    try:
        command = request.json.get('command', '').strip()
        global bot_process, bot_start_time
        
        # 处理内置命令
        if command.lower() == 'help':
            return jsonify({
                'status': 'success',
                'output': '''可用命令:
help - 显示帮助信息
clear - 清空日志
status - 显示系统状态
version - 显示版本信息
memory - 显示内存使用情况
start - 启动机器人
stop - 停止机器人
restart - 重启机器人

出于安全考虑，控制台只接受以上内置命令。'''
            })
            
        elif command.lower() == 'clear':
            # 清空日志队列
            while not bot_logs.empty():
                bot_logs.get()
            return jsonify({
                'status': 'success',
                'output': '',  # 返回空输出，让前端清空日志
                'clear': True  # 添加标记，告诉前端需要清空日志
            })
            
        elif command.lower() == 'status':
            if bot_process and bot_process.poll() is None:
                uptime = '0分钟'
                if bot_start_time:
                    delta = datetime.datetime.now() - bot_start_time
                    total_seconds = int(delta.total_seconds())
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    seconds = total_seconds % 60
                    if hours > 0:
                        uptime = f"{hours}小时{minutes}分钟{seconds}秒"
                    elif minutes > 0:
                        uptime = f"{minutes}分钟{seconds}秒"
                    else:
                        uptime = f"{seconds}秒"
                return jsonify({
                    'status': 'success',
                    'output': f'机器人状态: 运行中\n运行时间: {uptime}'
                })
            else:
                return jsonify({
                    'status': 'success',
                    'output': '机器人状态: 已停止'
                })
            
        elif command.lower() == 'version':
            return jsonify({
                'status': 'success',
                'output': 'Dream-Moments-Dify v1.6.0'
            })
            
        elif command.lower() == 'memory':
            memory = psutil.virtual_memory()
            return jsonify({
                'status': 'success',
                'output': f'内存使用: {memory.percent}% ({memory.used/1024/1024/1024:.1f}GB/{memory.total/1024/1024/1024:.1f}GB)'
            })
            
        elif command.lower() == 'start':
            if bot_process and bot_process.poll() is None:
                return jsonify({
                    'status': 'error',
                    'error': '机器人已在运行中'
                })
            
            # 清空之前的日志
            while not bot_logs.empty():
                bot_logs.get()
            
            # 设置环境变量
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            
            # 创建新的进程组
            if sys.platform.startswith('win'):
                creationflags = _windows_background_flags(with_process_group=True)
            else:
                creationflags = 0
            
            # 启动进程
            bot_process = subprocess.Popen(
                [sys.executable, 'run.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                env=env,
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags if sys.platform.startswith('win') else 0,
                preexec_fn=os.setsid if not sys.platform.startswith('win') else None
            )
            
            # 记录启动时间
            bot_start_time = datetime.datetime.now()
            
            return jsonify({
                'status': 'success',
                'output': '机器人启动成功'
            })
            
        elif command.lower() == 'stop':
            if bot_process and bot_process.poll() is None:
                try:
                    # 首先尝试正常终止进程
                    bot_process.terminate()
                    
                    # 等待进程结束
                    try:
                        bot_process.wait(timeout=5)  # 等待最多5秒
                    except subprocess.TimeoutExpired:
                        # 如果超时，强制结束进程
                        bot_process.kill()
                        bot_process.wait()
                    
                    # 确保所有子进程都被终止
                    if sys.platform.startswith('win'):
                        subprocess.run(
                            ['taskkill', '/F', '/T', '/PID', str(bot_process.pid)],
                            capture_output=True,
                            creationflags=_windows_background_flags(),
                        )
                    else:
                        import signal
                        os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
                    
                    # 清理进程对象
                    bot_process = None
                    bot_start_time = None
                    
                    return jsonify({
                        'status': 'success',
                        'output': '机器人已停止'
                    })
                except Exception as e:
                    return jsonify({
                        'status': 'error',
                        'error': '停止失败，请查看服务日志'
                    })
            else:
                return jsonify({
                    'status': 'error',
                    'error': '机器人未在运行'
                })
            
        elif command.lower() == 'restart':
            # 先停止
            if bot_process and bot_process.poll() is None:
                try:
                    bot_process.terminate()
                    try:
                        bot_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        bot_process.kill()
                        bot_process.wait()
                    
                    if sys.platform.startswith('win'):
                        subprocess.run(
                            ['taskkill', '/F', '/T', '/PID', str(bot_process.pid)],
                            capture_output=True,
                            creationflags=_windows_background_flags(),
                        )
                    else:
                        import signal
                        os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
                except Exception as e:
                    return jsonify({
                        'status': 'error',
                        'error': '重启失败，请查看服务日志'
                    })
            
            time.sleep(2)  # 等待进程完全停止
            
            # 然后重新启动
            try:
                # 清空日志
                while not bot_logs.empty():
                    bot_logs.get()
                
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                
                if sys.platform.startswith('win'):
                    creationflags = _windows_background_flags(with_process_group=True)
                else:
                    creationflags = 0
                
                bot_process = subprocess.Popen(
                    [sys.executable, 'run.py'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1,
                    env=env,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=creationflags if sys.platform.startswith('win') else 0,
                    preexec_fn=os.setsid if not sys.platform.startswith('win') else None
                )
                
                bot_start_time = datetime.datetime.now()
                
                return jsonify({
                    'status': 'success',
                    'output': '机器人已重启'
                })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'error': '重启失败，请查看服务日志'
                })
            
        # 拒绝执行任意系统命令，避免 Web 控制台变成远程命令执行入口。
        else:
            return jsonify({
                'status': 'error',
                'error': '不支持的命令。请输入 help 查看可用命令。'
            }), 400
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': '执行命令失败，请查看服务日志'
        })

@app.route('/check_dependencies')
def check_dependencies():
    """检查Python和pip环境"""
    try:
        # 检查Python版本
        python_version = sys.version.split()[0]
        
        # 检查pip是否安装
        pip_path = shutil.which('pip')
        has_pip = pip_path is not None
        
        # 检查requirements.txt是否存在
        requirements_path = os.path.join(ROOT_DIR, 'requirements.txt')
        has_requirements = os.path.exists(requirements_path)
        
        # 如果requirements.txt存在，检查是否所有依赖都已安装
        dependencies_status = "unknown"
        missing_deps = []
        if has_requirements and has_pip:
            try:
                # 获取已安装的包列表
                process = subprocess.Popen(
                    [sys.executable, '-m', 'pip', 'list'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    creationflags=_windows_background_flags(),
                )
                stdout, stderr = process.communicate()
                # 解析pip list的输出，只获取包名
                installed_packages = {
                    line.split()[0].lower() 
                    for line in stdout.split('\n')[2:] 
                    if line.strip()
                }
                
                logger.debug(f"已安装的包: {installed_packages}")
                
                # 读取requirements.txt，只获取有效的包名
                with open(requirements_path, 'r', encoding='utf-8') as f:
                    required_packages = set()
                    for line in f:
                        line = line.strip()
                        # 跳过无效行：空行、注释、镜像源配置、-r 开头的文件包含
                        if (not line or 
                            line.startswith('#') or 
                            line.startswith('-i ') or 
                            line.startswith('-r ') or
                            line.startswith('--')):
                            continue
                            
                        # 只取包名，忽略版本信息和其他选项
                        pkg = line.split('=')[0].split('>')[0].split('<')[0].split('~')[0].split('[')[0]
                        pkg = pkg.strip().lower()
                        if pkg:  # 确保包名不为空
                            required_packages.add(pkg)
                
                logger.debug(f"需要的包: {required_packages}")
                
                # 检查缺失的依赖
                missing_deps = [
                    pkg for pkg in required_packages
                    if pkg not in installed_packages
                ]
                
                logger.debug(f"缺失的包: {missing_deps}")
                
                # 根据是否有缺失依赖设置状态
                dependencies_status = "complete" if not missing_deps else "incomplete"
                    
            except Exception as e:
                logger.error(f"检查依赖时出错: {str(e)}")
                dependencies_status = "error"
        else:
            dependencies_status = "complete" if not has_requirements else "incomplete"
        
        return jsonify({
            'status': 'success',
            'python_version': python_version,
            'has_pip': has_pip,
            'has_requirements': has_requirements,
            'dependencies_status': dependencies_status,
            'missing_dependencies': missing_deps
        })
    except Exception as e:
        logger.error(f"依赖检查失败: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': '依赖检查失败'
        })

@app.route('/favicon.ico')
def favicon():
    """提供网站图标"""
    return send_from_directory(
        os.path.join(app.root_path, 'src/webui/static'),
        'mom.ico',
        mimetype='image/vnd.microsoft.icon'
    )

def cleanup_processes():
    """清理所有相关进程"""
    try:
        # 清理机器人进程
        global bot_process
        if bot_process:
            try:
                # 获取进程组
                parent = psutil.Process(bot_process.pid)
                children = parent.children(recursive=True)
                
                # 终止子进程
                for child in children:
                    try:
                        child.terminate()
                    except:
                        child.kill()
                
                # 终止主进程
                bot_process.terminate()
                
                # 等待进程结束
                gone, alive = psutil.wait_procs(children + [parent], timeout=3)
                
                # 强制结束仍在运行的进程
                for p in alive:
                    try:
                        p.kill()
                    except:
                        pass
                
                bot_process = None
                
            except Exception as e:
                logger.error(f"清理机器人进程失败: {str(e)}")
        
        # 清理当前进程的所有子进程
        current_process = psutil.Process()
        children = current_process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except:
                try:
                    child.kill()
                except:
                    pass
        
        # 等待所有子进程结束
        gone, alive = psutil.wait_procs(children, timeout=3)
        for p in alive:
            try:
                p.kill()
            except:
                pass
                
    except Exception as e:
        logger.error(f"清理进程失败: {str(e)}")

def signal_handler(signum, frame):
    """信号处理函数"""
    logger.info(f"收到信号: {signum}")
    cleanup_processes()
    sys.exit(0)

# 注册信号处理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Windows平台特殊处理
if sys.platform.startswith('win'):
    try:
        signal.signal(signal.SIGBREAK, signal_handler)
    except:
        pass

# 注册退出处理
atexit.register(cleanup_processes)

def open_browser(port):
    """在新线程中打开浏览器"""
    def _open_browser():
        # 等待服务器启动
        time.sleep(1.5)
        # 优先使用 localhost
        url = f"http://localhost:{port}"
        webbrowser.open(url)
    
    # 创建新线程来打开浏览器
    threading.Thread(target=_open_browser, daemon=True).start()

def main():
    """主函数"""
    from src.config import config
    
    # 设置系统编码为 UTF-8 (不清除控制台输出)
    if sys.platform.startswith('win'):
        subprocess.run(
            ['cmd.exe', '/d', '/c', 'chcp', '65001'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_windows_background_flags(),
        )
    
    print("\n" + "="*50)
    print_status("配置管理系统启动中...", "info", "LAUNCH")
    print("-"*50)
    
    # 检查必要目录
    print_status("检查系统目录...", "info", "FILE")
    if not os.path.exists(os.path.join(ROOT_DIR, 'src/webui/templates')):
        print_status("错误：模板目录不存在！", "error", "CROSS")
        return
    print_status("系统目录检查完成", "success", "CHECK")
    
    # 检查配置文件
    print_status("检查配置文件...", "info", "CONFIG")
    if not os.path.exists(config.config_path):
        print_status("错误：配置文件不存在！", "error", "CROSS")
        return
    print_status("配置文件检查完成", "success", "CHECK")

    # 修改启动 Web 服务器的部分
    cli = sys.modules['flask.cli']
    cli.show_server_banner = lambda *x: None  # 禁用 Flask 启动横幅
    
    # The console can start and stop the bot and edit provider credentials.
    # Keep it local by default; LAN exposure must be an explicit choice.
    host = os.environ.get('DREAM_MOMENTS_WEB_HOST', '127.0.0.1').strip()
    if host not in {'127.0.0.1', '::1', '0.0.0.0'}:
        print_status("Invalid DREAM_MOMENTS_WEB_HOST; using 127.0.0.1", "warning", "WARNING")
        host = '127.0.0.1'
    port = 8501
    
    print_status("正在启动Web服务...", "info", "INTERNET")
    print("-"*50)
    print_status("配置管理系统已就绪！", "success", "STAR_1")

    # 获取本机所有IP地址
    def get_ip_addresses():
        ip_list = []
        try:
            # 获取主机名
            hostname = socket.gethostname()
            # 获取本机IP地址列表
            addresses = socket.getaddrinfo(hostname, None)
            
            for addr in addresses:
                ip = addr[4][0]
                # 只获取IPv4地址且不是回环地址
                if '.' in ip and ip != '127.0.0.1':
                    ip_list.append(ip)
        except:
            pass
        return ip_list

    # 显示所有可用的访问地址
    ip_addresses = get_ip_addresses() if host == '0.0.0.0' else []
    print_status("可通过以下地址访问:", "info", "CHAIN")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Local:   http://127.0.0.1:{port}")
    for ip in ip_addresses:
        print(f"  Network: http://{ip}:{port}")
    if host != '0.0.0.0':
        print("  Network access is disabled. Set DREAM_MOMENTS_WEB_HOST=0.0.0.0 to opt in.")
    print("="*50 + "\n")
    
    # 启动浏览器
    open_browser(port)
    
    app.run(
        host=host, 
        port=port, 
        debug=False,
        use_reloader=False  # 禁用重载器以避免创建多余的进程
    )

@app.route('/install_dependencies', methods=['POST'])
def install_dependencies():
    """安装依赖"""
    try:
        output = []
        
        # 安装依赖
        output.append("正在安装依赖，请耐心等待...")
        requirements_path = os.path.join(ROOT_DIR, 'requirements.txt')
        
        if not os.path.exists(requirements_path):
            return jsonify({
                'status': 'error',
                'message': '找不到requirements.txt文件'
            })
            
        process = subprocess.Popen(
            [sys.executable, '-m', 'pip', 'install', '-r', requirements_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            creationflags=_windows_background_flags(),
        )
        stdout, stderr = process.communicate()
        output.append(stdout if stdout else stderr)
        
        if process.returncode == 0:
            return jsonify({
                'status': 'success',
                'output': '\n'.join(output)
            })
        else:
            return jsonify({
                'status': 'error',
                'output': '\n'.join(output),
                'message': '安装依赖失败'
            })
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': '依赖安装失败，请查看服务日志'
        })

def hash_password(password: str) -> str:
    """Hash an administrator password with a unique salt and scrypt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> tuple[bool, str | None]:
    """Verify current hashes and transparently upgrade legacy SHA-256 hashes."""
    if stored_hash.startswith("scrypt$"):
        try:
            _, salt_hex, digest_hex = stored_hash.split("$", 2)
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=2**14,
                r=8,
                p=1,
                dklen=32,
            )
            return hmac.compare_digest(candidate.hex(), digest_hex), None
        except (ValueError, TypeError):
            return False, None

    # Legacy verification is intentionally retained only to migrate a successful
    # login immediately to scrypt; new passwords never use SHA-256.
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()  # lgtm[py/weak-sensitive-data-hashing]
    if hmac.compare_digest(legacy, stored_hash):
        return True, hash_password(password)
    return False, None

def is_local_network() -> bool:
    # 检查是否是本地网络访问
    client_ip = request.remote_addr
    return (
        client_ip == '127.0.0.1' or 
        client_ip.startswith('192.168.') or 
        client_ip.startswith('10.') or 
        client_ip.startswith('172.16.')
    )

@app.route('/get_model_configs')
def get_model_configs():
    """获取模型和API配置"""
    try:
        models_path = os.path.join(ROOT_DIR, 'src/config/models.json')
        
        if not os.path.exists(models_path):
            return jsonify({
                'status': 'error',
                'message': '配置文件不存在'
            })

        with open(models_path, 'r', encoding='utf-8') as f:
            configs = json.load(f)

        # 检查云端更新
        if configs.get('update_url'):
            try:
                response = requests.get(configs['update_url'], timeout=5)
                if response.status_code == 200:
                    cloud_configs = response.json()
                    if cloud_configs.get('version', '0') > configs.get('version', '0'):
                        configs = cloud_configs
                        with open(models_path, 'w', encoding='utf-8') as f:
                            json.dump(configs, f, indent=4, ensure_ascii=False)
            except:
                pass

        # 过滤和排序提供商
        active_providers = [p for p in configs['api_providers'] 
                          if p.get('status') == 'active']
        active_providers.sort(key=lambda x: x.get('priority', 999))
        
        # 构建返回配置
        return_configs = {
            'api_providers': active_providers,
            'models': {}
        }
        
        # 只包含活动模型
        for provider in active_providers:
            provider_id = provider['id']
            if provider_id in configs['models']:
                return_configs['models'][provider_id] = [
                    m for m in configs['models'][provider_id]
                    if m.get('status') == 'active'
                ]

        return jsonify(return_configs)
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': '读取配置失败'
        })

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        print_status("正在关闭服务...", "warning", "STOP")
        cleanup_processes()
        print_status("配置管理系统已停止", "info", "BYE")
        print("\n")
    except Exception as e:
        print_status(f"系统错误: {str(e)}", "error", "ERROR")
        cleanup_processes()
