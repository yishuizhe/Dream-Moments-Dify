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
from werkzeug.utils import secure_filename
from typing import Dict, Any, List

# 初始化日志记录器
logger = logging.getLogger(__name__)

# 初始化colorama
init()

# 添加项目根目录到Python路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(ROOT_DIR)

# 禁用Python的字节码缓存
sys.dont_write_bytecode = True

app = Flask(__name__, 
    template_folder=os.path.join(ROOT_DIR, 'src/webui/templates'),
    static_folder=os.path.join(ROOT_DIR, 'src/webui/static'))

# 添加配置
app.config['UPLOAD_FOLDER'] = os.path.join(ROOT_DIR, 'src/webui/background_image')

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def print_status(message: str, status: str = "info", emoji: str = ""):
    """打印带颜色和表情的状态消息"""
    colors = {
        "success": Fore.GREEN,
        "info": Fore.BLUE,
        "warning": Fore.YELLOW,
        "error": Fore.RED
    }
    color = colors.get(status, Fore.WHITE)
    print(f"{color}{emoji} {message}{Style.RESET_ALL}")


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

def parse_config_groups() -> Dict[str, Dict[str, Any]]:
    """解析配置文件，将配置项按组分类"""
    from src.config import config

    config_groups = {
        "基础配置": {},
        "图像识别API配置": {},
        "图像生成配置": {},
        "时间配置": {},
        "语音配置": {},
        "Prompt配置": {},
    }

    # 基础配置
    config_groups["基础配置"].update(
        {
            "LISTEN_LIST": {
                "value": config.user.listen_list,
                "description": "用户列表(请配置要和bot说话的账号的昵称或者群名，不要写备注！)",
            },
            
 #           "MODEL": {"value": config.llm.model, "description": "AI模型选择"},
            "DEEPSEEK_BASE_URL": {
                "value": config.llm.base_url,
                "description": "硅基流动API注册地址",
            },
            "DEEPSEEK_API_KEY": {
                "value": config.llm.api_key,
                "description": "DeepSeek API密钥",
            },
            "DIFY_BASE_URL": {
                "value": config.llm.dify_base_url,
                "description": "DIFY注册地址",
            },
            "DIFY_API_KEY": {
                "value": config.llm.dify_api_key,
                "description": "DIFY API密钥",
            },
            # "MAX_TOKEN": {
            #     "value": config.llm.max_tokens,
            #     "description": "回复最大token数",
            # },
       #     "TEMPERATURE": {"value": config.llm.temperature, "description": "温度参数"},
        }
    )

    # 图像识别API配置
    config_groups["图像识别API配置"].update(
        {
            "MOONSHOT_API_KEY": {
                "value": config.media.image_recognition.api_key,
                "description": "Moonshot API密钥（用于图片和表情包识别）",
            },
            "MOONSHOT_BASE_URL": {
                "value": config.media.image_recognition.base_url,
                "description": "Moonshot API基础URL",
            },
            "MOONSHOT_TEMPERATURE": {
                "value": config.media.image_recognition.temperature,
                "description": "Moonshot温度参数",
            },
        }
    )

    # 图像生成配置
    config_groups["图像生成配置"].update(
        {
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

    # 时间配置
    config_groups["时间配置"].update(
        {
            "AUTO_MESSAGE": {
                "value": config.behavior.auto_message.content,
                "description": "自动消息内容",
            },
            "MIN_COUNTDOWN_HOURS": {
                "value": config.behavior.auto_message.min_hours,
                "description": "最小倒计时时间（小时）",
            },
            "MAX_COUNTDOWN_HOURS": {
                "value": config.behavior.auto_message.max_hours,
                "description": "最大倒计时时间（小时）",
            },
            "QUIET_TIME_START": {
                "value": config.behavior.quiet_time.start,
                "description": "安静时间开始",
            },
            "QUIET_TIME_END": {
                "value": config.behavior.quiet_time.end,
                "description": "安静时间结束",
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
                "description": "最大的上下文轮数",
            },
            "AVATAR_DIR": {
                "value": config.behavior.context.avatar_dir,
                "description": "人设目录（自动包含 avatar.md 和 emojis 目录）",
                "options": available_avatars,
                "type": "select"
            }
        }
    )

    return config_groups


def save_config(new_config: Dict[str, Any]) -> bool:
    """保存新的配置到文件"""
    try:
        from src.config import (
            UserSettings,
            LLMSettings,
            ImageRecognitionSettings,
            ImageGenerationSettings,
            TextToSpeechSettings,
            MediaSettings,
            AutoMessageSettings,
            QuietTimeSettings,
            ContextSettings,
            BehaviorSettings,
            config
        )

        # 构建新的配置对象
        user_settings = UserSettings(listen_list=new_config.get("LISTEN_LIST", []))

        llm_settings = LLMSettings(
            api_key=new_config.get("DEEPSEEK_API_KEY", ""),
            base_url=new_config.get("DEEPSEEK_BASE_URL", ""),
            dify_api_key=new_config.get("DIFY_API_KEY",""),
            dify_base_url=new_config.get("DIFY_BASE_URL",""),
           # model=new_config.get("MODEL", ""),
           # max_tokens=new_config.get("MAX_TOKEN", 2000),
           # temperature=float(new_config.get("TEMPERATURE", 1.1)),
        )

        media_settings = MediaSettings(
            image_recognition=ImageRecognitionSettings(
                api_key=new_config.get("MOONSHOT_API_KEY", ""),
                base_url=new_config.get("MOONSHOT_BASE_URL", ""),
                temperature=float(new_config.get("MOONSHOT_TEMPERATURE", 1.1)),
            ),
            image_generation=ImageGenerationSettings(
                model=new_config.get("IMAGE_MODEL", ""),
                temp_dir=new_config.get("TEMP_IMAGE_DIR", ""),
            ),
            text_to_speech=TextToSpeechSettings(
                tts_api_url=new_config.get("TTS_API_URL", ""),
                voice_dir=new_config.get("VOICE_DIR", ""),
            )
        )

        behavior_settings = BehaviorSettings(
            auto_message=AutoMessageSettings(
                content=new_config.get("AUTO_MESSAGE", ""),
                min_hours=int(new_config.get("MIN_COUNTDOWN_HOURS", 1)),
                max_hours=int(new_config.get("MAX_COUNTDOWN_HOURS", 3)),
            ),
            quiet_time=QuietTimeSettings(
                start=new_config.get("QUIET_TIME_START", ""),
                end=new_config.get("QUIET_TIME_END", ""),
            ),
            context=ContextSettings(
                max_groups=int(new_config.get("MAX_GROUPS", 15)),
                avatar_dir=new_config.get("AVATAR_DIR", ""),
            ),
        )

        # 构建JSON结构
        config_data = {
            "categories": {
                "user_settings": {
                    "title": "用户设置",
                    "settings": {
                        "listen_list": {
                            "value": user_settings.listen_list,
                            "type": "array",
                            "description": "要监听的用户列表（请使用微信昵称，不要使用备注名）",
                        }
                    },
                },
                "llm_settings": {
                    "title": "大语言模型配置",
                    "settings": {
                        "api_key": {
                            "value": llm_settings.api_key,
                            "type": "string",
                            "description": "DeepSeek API密钥",
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
                        # "model": {
                        #     "value": llm_settings.model,
                        #     "type": "string",
                        #     "description": "使用的AI模型名称",
                        #     "options": [
                        #         "deepseek-ai/DeepSeek-V3",
                        #         "Pro/deepseek-ai/DeepSeek-V3",
                        #         "Pro/deepseek-ai/DeepSeek-R1",
                        #     ],
                        # },
                        # "max_tokens": {
                        #     "value": llm_settings.max_tokens,
                        #     "type": "number",
                        #     "description": "回复最大token数量",
                        # },
                        # "temperature": {
                        #     "value": llm_settings.temperature,
                        #     "type": "number",
                        #     "description": "AI回复的温度值",
                        #     "min": 0,
                        #     "max": 2,
                        # },
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
                        "auto_message": {
                            "content": {
                                "value": behavior_settings.auto_message.content,
                                "type": "string",
                                "description": "自动消息内容",
                            },
                            "countdown": {
                                "min_hours": {
                                    "value": behavior_settings.auto_message.min_hours,
                                    "type": "number",
                                    "description": "最小倒计时时间（小时）",
                                },
                                "max_hours": {
                                    "value": behavior_settings.auto_message.max_hours,
                                    "type": "number",
                                    "description": "最大倒计时时间（小时）",
                                },
                            },
                        },
                        "quiet_time": {
                            "start": {
                                "value": behavior_settings.quiet_time.start,
                                "type": "string",
                                "description": "安静时间开始",
                            },
                            "end": {
                                "value": behavior_settings.quiet_time.end,
                                "type": "string",
                                "description": "安静时间结束",
                            },
                        },
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
                        },
                    },
                },
            }
        }

        # 使用 Config 类的方法保存配置
        if not config.save_config(config_data):
            return False

        # 重新加载配置模块
        importlib.reload(sys.modules["src.config"])

        return True
    except Exception as e:
        logger.error(f"保存配置失败: {str(e)}")
        return False


@app.route('/')
def index():
    """渲染配置页面"""
    config_groups = parse_config_groups()
    return render_template('config.html', config_groups=config_groups)

@app.route('/save', methods=['POST'])
def save():
    """保存配置"""
    try:
        new_config = request.json
        if save_config(new_config):
            return jsonify({"status": "success", "message": "配置已保存"})
        return jsonify({"status": "error", "message": "保存失败"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"保存失败: {str(e)}"})

# 添加上传处理路由
@app.route('/upload_background', methods=['POST'])
def upload_background():
    if 'background' not in request.files:
        return jsonify({"status": "error", "message": "没有选择文件"})
    
    file = request.files['background']
    if file.filename == '':
        return jsonify({"status": "error", "message": "没有选择文件"})
    
    if file:
        filename = secure_filename(file.filename)
        # 清理旧的背景图片
        for old_file in os.listdir(app.config['UPLOAD_FOLDER']):
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old_file))
        # 保存新图片
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({
            "status": "success", 
            "message": "背景图片已更新",
            "path": f"/background_image/{filename}"
        })

# 添加背景图片目录的路由
@app.route('/background_image/<filename>')
def background_image(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# 添加获取背景图片路由
@app.route('/get_background')
def get_background():
    """获取当前背景图片"""
    try:
        # 获取背景图片目录中的第一个文件
        files = os.listdir(app.config['UPLOAD_FOLDER'])
        if files:
            # 返回找到的第一个图片
            return jsonify({
                "status": "success",
                "path": f"/background_image/{files[0]}"
            })
        return jsonify({
            "status": "success",
            "path": None
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        })

def main():
    """主函数"""
    from src.config import config
    
    print("\n" + "="*50)
    print_status("配置管理系统启动中...", "info", "🚀")
    print("-"*50)
    
    # 检查必要目录
    print_status("检查系统目录...", "info", "📁")
    if not os.path.exists(os.path.join(ROOT_DIR, 'src/webui/templates')):
        print_status("错误：模板目录不存在！", "error", "❌")
        return
    print_status("系统目录检查完成", "success", "✅")
    
    # 检查配置文件
    print_status("检查配置文件...", "info", "⚙️")
    if not os.path.exists(config.config_path):
        print_status("错误：配置文件不存在！", "error", "❌")
        return
    print_status("配置文件检查完成", "success", "✅")
    
    # 清理缓存
    print_status("清理系统缓存...", "info", "🧹")
    cleanup_count = 0
    for root, dirs, files in os.walk(ROOT_DIR):
        if '__pycache__' in dirs:
            cleanup_count += 1
    if cleanup_count > 0:
        print_status(f"已清理 {cleanup_count} 个缓存目录", "success", "🗑️")
    else:
        print_status("没有需要清理的缓存", "info", "✨")
    
    # 启动服务器
    print_status("正在启动Web服务...", "info", "🌐")
    print("-"*50)
    print_status("配置管理系统已就绪！", "success", "✨")
    print_status("请访问: http://localhost:8501", "info", "🔗")
    print("="*50 + "\n")
    
    # 启动Web服务器
    app.run(host='0.0.0.0', port=8501, debug=True)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        print_status("正在关闭服务...", "warning", "🛑")
        print_status("配置管理系统已停止", "info", "👋")
        print("\n")
    except Exception as e:
        print_status(f"系统错误: {str(e)}", "error", "💥")
