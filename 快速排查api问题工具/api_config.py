# 模拟服务器的配置
mock_server_base_url = 'http://localhost:5000'
# 实际 AI 对话服务器的配置
real_server_base_url = 'http://127.0.0.1:1234'
api_key = 'sk-'
model = 'deepseek-r1-distill-llama-8b@q4_k_m'
messages = [
    {
        "role": "user",
        "content": "你好，请返回【测试成功】"
    }
]
#呜呜呜，前端大佬看到这句话请把它写成webui的格式好吗？