"""
主程序入口文件。
负责设置 Python 路径、统一输出编码并启动聊天机器人。
"""

import codecs
import os
import sys

from colorama import init
from src.utils.console import print_banner, print_status


if sys.platform.startswith("win"):
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer)
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer)

init()
sys.dont_write_bytecode = True

src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if src_path not in sys.path:
    sys.path.append(src_path)


def initialize_system():
    """加载主程序；初始化与清理由 ``src.main`` 统一负责。"""

    try:
        from src.main import main

        print_banner()
        main()
    except ImportError as exc:
        print_status(f"导入模块失败: {exc}", "error", "CROSS")
        sys.exit(1)
    except Exception as exc:
        print_status(f"初始化失败: {exc}", "error", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    try:
        initialize_system()
    except KeyboardInterrupt:
        print("\n")
        print_status("正在关闭系统...", "warning", "STOP")
        print_status("感谢使用，再见！", "info", "BYE")
        print("\n")
    except Exception as exc:
        print_status(f"系统错误: {exc}", "error", "ERROR")
        sys.exit(1)
