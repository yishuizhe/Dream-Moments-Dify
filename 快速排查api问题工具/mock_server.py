"""
API模拟测试(支持本地和局域网):
负责模拟DeepSeek API的标准请求，包括
- 请求模拟
- 动态响应
- 异常测试
- 延时响应
"""

import argparse
import time
from threading import Lock
from flask import Flask, request, jsonify
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DeepSeekAPIMockServer:
    def __init__(self):
        # 初始化 Flask 应用
        self.app = Flask(__name__)
        # 初始化锁，用于线程安全
        self.response_lock = Lock()
        # 全局配置存储
        self.config = {
            "default_response": {"content": "这是默认测试响应"},
            "enable_test_endpoints": False
        }
        # 注册路由
        self.register_routes()

    def register_routes(self):
        # 模拟 DeepSeek 标准 API 端点
        @self.app.route('/v1/chat/completions', methods=['POST'])
        def api_handler():
            """模拟DeepSeek标准API端点"""
            with self.response_lock:
                current_response = self.config['default_response'].copy()
            # 记录请求日志
            logging.info("\n[请求日志]")
            logging.info(f"Headers: {dict(request.headers)}")
            logging.info(f"Body: {request.json}")
            # 构造响应
            return jsonify({
                "choices": [{
                    "message": {
                        "content": current_response['content']
                    }
                }]
            })

        # 动态修改响应内容
        @self.app.route('/control/set_response', methods=['POST'])
        def set_custom_response():
            """动态修改响应内容"""
            if not request.is_json:
                return jsonify({"error": "需要JSON格式"}), 400
            new_response = request.json
            with self.response_lock:
                self.config['default_response'].update(new_response)
            logging.info(f"\n[配置更新] 新响应内容: {new_response}")
            return jsonify({"status": "success", "new_response": new_response})

        # 模拟服务器错误
        @self.app.route('/test/500', methods=['GET', 'POST'])
        def mock_500_error():
            """模拟服务器错误"""
            return jsonify({
                "error": "测试用服务器错误",
                "detail": "这是模拟的500错误响应"
            }), 500

        # 模拟延时响应
        @self.app.route('/test/timeout/<int:delay>', methods=['GET'])
        def mock_timeout(delay):
            """模拟延时响应"""
            time.sleep(delay)
            return jsonify({
                "status": f"延时 {delay} 秒响应",
                "data": "请求最终成功"
            })

    def run(self):
        # 命令行参数配置
        parser = argparse.ArgumentParser(
            description='DeepSeek API模拟服务',
            formatter_class=argparse.ArgumentDefaultsHelpFormatter
        )
        parser.add_argument('--port', type=int, default=5000,
                            help='服务监听端口')
        parser.add_argument('--enable-test', action='store_true',
                            help='启用测试端点(/test/*)')
        args = parser.parse_args()

        # 根据参数配置功能
        self.config['enable_test_endpoints'] = args.enable_test

        # 启动提示信息
        logging.info(f"\n服务启动配置：")
        logging.info(f"监听端口: {args.port}")
        logging.info(f"测试端点: {'已启用' if args.enable_test else '已禁用'}")
        logging.info(f"控制接口: POST /control/set_response")
        logging.info(f"标准端点: POST /v1/chat/completions")

        # 启动服务（设置debug=False生产环境）
        self.app.run(host='0.0.0.0', port=args.port, debug=False)

if __name__ == '__main__':
    server = DeepSeekAPIMockServer()
    server.run()