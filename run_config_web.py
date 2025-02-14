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
from flask import Flask, render_template, jsonify, request
import importlib
import json
from colorama import init, Fore, Style

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

def get_config_with_comments():
    """获取配置文件内容，包括注释"""
    config_path = os.path.join(ROOT_DIR, 'src/config/settings.py')
    with open(config_path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_config_groups():
    """解析配置文件，将配置项按组分类"""
    from src.config import settings
    
    config_content = get_config_with_comments()
    config_groups = {}
    current_group = "基础配置"
    
    # 使用正则表达式匹配注释
    comment_pattern = r'#\s*(.*?)\n'
    docstring_pattern = r'"""(.*?)"""'
    
    comments = {}
    # 提取所有注释
    for match in re.finditer(comment_pattern, config_content, re.MULTILINE):
        line_num = config_content.count('\n', 0, match.start())
        comments[line_num] = match.group(1).strip()
    
    # 获取所有配置项
    for name in dir(settings):
        if name.isupper():  # 只处理大写的配置项
            value = getattr(settings, name)
            if not callable(value):  # 排除方法
                # 在配置内容中查找该配置项的位置
                pattern = rf'{name}\s*='
                match = re.search(pattern, config_content, re.MULTILINE)
                if match:
                    line_num = config_content.count('\n', 0, match.start())
                    # 获取该配置项上方的注释
                    description = comments.get(line_num - 1, "")
                    
                    # 根据注释内容确定分组
                    if "API" in description.upper():
                        group = "API配置"
                    elif "图" in description or "Image" in description:
                        group = "图像配置"
                    elif "语音" in description or "Voice" in description:
                        group = "语音配置"
                    elif "时间" in description or "Time" in description:
                        group = "时间配置"
                    elif "更新" in description or "Update" in description:
                        group = "更新配置"
                    else:
                        group = "基础配置"
                        
                    if group not in config_groups:
                        config_groups[group] = {}
                    
                    config_groups[group][name] = {
                        "value": value,
                        "description": description
                    }
    
    return config_groups

def save_config(new_config):
    """保存新的配置到文件"""
    config_content = get_config_with_comments()
    
    # 更新配置内容
    for key, value in new_config.items():
        # 处理不同类型的值
        if isinstance(value, str):
            value_str = f"'{value}'"
        elif isinstance(value, list):
            value_str = str(value)
        elif isinstance(value, bool):
            value_str = str(value).lower()  # 布尔值转换为小写字符串
        elif isinstance(value, int):
            value_str = str(value)  # 整数保持为字符串
        else:
            value_str = str(value)  # 确保其他类型的值转换为字符串
            
        # 使用正则表达式替换配置值
        pattern = rf'{key}\s*=\s*[^#\n]+'
        config_content = re.sub(pattern, f'{key} = {value_str}', config_content)
    
    # 保存到文件
    config_path = os.path.join(ROOT_DIR, 'src/config/settings.py')
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(config_content)
    
    # 重新加载配置模块
    importlib.reload(sys.modules['src.config.settings'])
    
    return True

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

def main():
    """主函数"""
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
    if not os.path.exists(os.path.join(ROOT_DIR, 'src/config/settings.py')):
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
