from mock_server import DeepSeekAPIMockServer
from api_request import APITester
import api_config
import threading
import time
import requests
import logging

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def start_mock_server():
    """启动 DeepSeek API 模拟服务器"""
    server = DeepSeekAPIMockServer()
    server.run()

def handle_api_error(e, server_type):
    """处理API请求错误"""
    error_msg = f"⚠️ 访问{server_type}遇到问题："
    
    if isinstance(e, requests.exceptions.ConnectionError):
        error_msg += "网络连接失败\n🔧 请检查：1.服务器是否启动 2.地址端口是否正确 3.网络是否通畅 4.防火墙设置"
    elif isinstance(e, requests.exceptions.Timeout):
        error_msg += "请求超时\n🔧 建议：1.稍后重试 2.检查网络速度 3.确认服务器负载情况"
    elif isinstance(e, requests.exceptions.SSLError):
        error_msg += "SSL证书验证失败\n🔧 请尝试：1.更新根证书 2.临时关闭证书验证（测试环境）"
    elif isinstance(e, requests.exceptions.HTTPError):
        status_code = e.response.status_code
        common_solution = "\n💡 解决方法：查看API文档，确认请求参数格式和权限设置"
        
        status_map = {
            400: ("请求格式错误", "检查JSON格式、参数名称和数据类型"),
            401: ("身份验证失败", "1.确认API密钥 2.检查授权头格式"),
            403: ("访问被拒绝", "确认账户权限或套餐是否有效"),
            404: ("接口不存在", "检查URL地址和接口版本号"),
            429: ("请求过于频繁", "降低调用频率或升级套餐"),
            500: ("服务器内部错误", "等待5分钟后重试，若持续报错请联系服务商"),
            502: ("网关错误", "服务器端网络问题，建议等待后重试"),
            503: ("服务不可用", "服务器维护中，请关注官方状态页")
        }
        
        desc, solution = status_map.get(status_code, (f"HTTP {status_code}错误", "查看对应状态码文档"))
        error_msg += f"{desc}\n🔧 {solution}{common_solution}"
    elif isinstance(e, ValueError) and 'Incorrect padding' in str(e):
        error_msg += "API密钥格式错误\n🔧 请检查密钥是否完整（通常以'sk-'开头，共64字符）"
    else:
        error_msg += f"未知错误：{type(e).__name__}\n🔧 建议：1.查看错误详情 2.联系技术支持"
    
    logging.error(error_msg)

def test_servers():
    """测试模拟服务器和实际 AI 对话服务器"""
    time.sleep(2)
    
    # 新增调试信息
    logging.info(f"📡 正在连接模拟服务器：{api_config.mock_server_base_url}")
    mock_tester = APITester(api_config.mock_server_base_url, api_config.api_key, api_config.model)

    try:
        logging.info("🔄 正在测试模拟服务器...")
        response = mock_tester.test_standard_api()
        
        # 新增响应内容检查
        if not response.text.startswith('{"'):
            logging.warning("⚠️ 模拟服务器返回了非JSON格式响应，请检查实现逻辑")
            
    except Exception as e:
        handle_api_error(e, "模拟服务器")
        return

    # 创建 APITester 实例，使用实际 AI 对话服务器的配置
    real_tester = APITester(
        api_config.real_server_base_url,
        api_config.api_key,
        api_config.model,
        messages=[{"role": "user", "content": "测试消息"}]  # 新增消息参数
    )

    try:
        logging.info("正在向实际 AI 对话服务器发送请求...")
        response = real_tester.test_standard_api()
        
        if response is None:
            logging.error("实际服务器返回空响应，请检查服务器状态或请求参数")
            return
        
        if response.status_code != 200:
            logging.error(f"服务器返回异常状态码: {response.status_code}，错误信息: {response.text}")
            return
    
        response_text = response.text
        logging.info(f"实际 AI 对话服务器原始响应: {response_text}")
    
        try:
            response_json = response.json()
            logging.info(f"标准 API 端点响应: {response_json}")
            logging.info("实际 AI 对话服务器响应正常。")
        except ValueError as json_error:
            logging.error(f"解析实际 AI 对话服务器响应时出现 JSON 解析错误: {json_error}。响应内容: {response_text}")
    except Exception as e:
        handle_api_error(e, "实际 AI 对话服务器")

if __name__ == "__main__":
    # 启动模拟服务器线程
    mock_server_thread = threading.Thread(target=start_mock_server)
    mock_server_thread.daemon = True
    mock_server_thread.start()

    # 开始测试服务器
    test_servers()
