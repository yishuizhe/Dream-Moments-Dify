"""
控制台输出相关的工具函数
包含:
- 状态信息打印
- 横幅打印
等功能
"""

from colorama import Fore, Style
import sys

def print_status(message: str, status: str = "info", icon: str = ""):
    """
    打印带颜色和表情的状态消息
    
    Args:
        message (str): 要打印的消息
        status (str): 状态类型 ("success", "info", "warning", "error")
        icon (str): 消息前的图标
    """
    try:
        colors = {
            "success": Fore.GREEN,
            "info": Fore.BLUE,
            "warning": Fore.YELLOW,
            "error": Fore.RED
        }
        color = colors.get(status, Fore.WHITE)

        # ASCII文本到emoji的映射
        icon_map = {
            "LAUNCH": "🚀",
            "FILE": "📁",
            "CONFIG": "⚙️",
            "CHECK": "✅",
            "CROSS": "❌",
            "CLEAN": "🧹",
            "TRASH": "🗑️",
            "STAR_1": "✨",
            "STAR_2": "🌟",
            "BOT": "🤖",
            "STOP": "🛑",
            "BYE": "👋",
            "ERROR": "💥",
            "SEARCH": "🔍",
            "BRAIN": "🧠",
            "ANTENNA": "📡",
            "CHAIN": "🔗",
            "INTERNET": "🌐",
            "CLOCK": "⏰",
            "SYNC": "🔄",
            "WARNING": "⚠️",
            "+": "📁",
            "*": "⚙️",
            "X": "❌",
            ">>": "🚀",
        }

        safe_icon = icon_map.get(icon, icon)  # 如果找不到映射，保留原始输入
        print(f"{color}{safe_icon} {message}{Style.RESET_ALL}")
    except Exception:
        # 如果出现编码错误，不使用颜色和图标
        print(f"{message}")

def print_banner():
    """Print one concise startup banner; full notices remain in README/LICENSE."""
    try:
        banner = f"""
{Fore.CYAN}==================================================
 Dream-Moments-Dify
 Based on My-Dream-Moments / KouriChat
 GPLv3 | https://github.com/KouriChat/KouriChat
=================================================={Style.RESET_ALL}"""
        print(banner)
    except Exception:
        print("\nDream-Moments-Dify (GPLv3, based on KouriChat)\n")
