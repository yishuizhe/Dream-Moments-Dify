import requests

class APITester:
    def __init__(self, base_url, api_key, model, messages=None):  # 添加messages参数
        """
        初始化 API 测试类
        :param messages: 对话消息列表
        """
        self.messages = messages or [{"role": "user", "content": "测试消息"}]
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def test_standard_api(self):
        """测试标准 API 端点 /v1/chat/completions"""
        url = f'{self.base_url}/v1/chat/completions'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        data = {
            "model": self.model,
            "messages": self.messages  # 替换原来的prompt字段
        }
        
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # 新增状态码检查
        return response  # 新增返回响应对象

    def test_set_custom_response(self):
        """
        测试动态修改响应内容的接口 /control/set_response
        """
        url = f'{self.base_url}/control/set_response'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        new_response = {
            "content": "这是自定义的测试响应"
        }
        response = requests.post(url, headers=headers, json=new_response)
        print("动态修改响应内容的接口响应:")
        print(response.json())

    def test_mock_500_error(self):
        """
        测试模拟服务器错误的接口 /test/500
        """
        url = f'{self.base_url}/test/500'
        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }
        response = requests.get(url, headers=headers)
        print("模拟服务器错误的接口响应:")
        print(response.status_code)
        print(response.json())

    def test_mock_timeout(self):
        """
        测试模拟延时响应的接口 /test/timeout/<delay>
        """
        delay = 5  # 延时 5 秒
        url = f'{self.base_url}/test/timeout/{delay}'
        headers = {
            'Authorization': f'Bearer {self.api_key}'
        }
        response = requests.get(url, headers=headers)
        print("模拟延时响应的接口响应:")
        print(response.json())


if __name__ == "__main__":
    # 服务地址和端口，这里替换为实际的服务器地址
    base_url = 'http://your-server-address:port'
    # 替换为实际的 API 密钥
    api_key = 'your-api-key'
    # 选择要使用的模型
    model = "your-model-name"

    tester = APITester(base_url, api_key, model)

    # 测试标准 API 端点
    tester.test_standard_api()

    # 动态修改响应内容
    tester.test_set_custom_response()

    # 再次测试标准 API 端点，验证响应内容是否已修改
    tester.test_standard_api()

    # 模拟服务器错误
    tester.test_mock_500_error()

    # 模拟延时响应
    tester.test_mock_timeout()