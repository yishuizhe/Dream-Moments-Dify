import json
import logging
import requests
from typing import List, Dict

logger = logging.getLogger(__name__)

class DifyAI:
    def __init__(self, api_key: str, base_url: str, max_groups: int):
        """
        初始化 dify AI 客户端
        
        Args:
            api_key: API密钥
            base_url: API基础URL
            max_groups: 最大对话组数
        """
        self.max_groups = max_groups
        self.base_url = base_url  # 初始化 base_url
        
        # API请求头
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        # 对话上下文管理
        self.chat_contexts: Dict[str, List[Dict[str, str]]] = {}

    def _manage_context(self, user_id: str, message: str, is_assistant: bool = False):
        """管理对话上下文"""
        if user_id not in self.chat_contexts:
            self.chat_contexts[user_id] = []

        role = "assistant" if is_assistant else "user"
        self.chat_contexts[user_id].append({"role": role, "content": message})

        # 保持对话历史在限定长度内
        while len(self.chat_contexts[user_id]) > self.max_groups * 2:
            if len(self.chat_contexts[user_id]) >= 2:
                del self.chat_contexts[user_id][0:2]  # 每次删除一组对话
            else:
                del self.chat_contexts[user_id][0]

    def get_response(self, message: str, user_id: str, system_prompt: str) -> str:
        """
        获取 API 回复
        
        Args:
            message: 用户消息
            user_id: 用户ID
            system_prompt: 系统提示词
            
        Returns:
            str: API 回复内容
        """
        try:
            logger.info(f"调用 dify API - 用户ID: {user_id}, 消息: {message}")
            
            # 添加用户消息到上下文
            self._manage_context(user_id, message)

            try:
                # 准备消息列表
                messages = [
                    {"role": "system", "content": system_prompt},
                    *self.chat_contexts[user_id][-self.max_groups * 2:]
                ]

                # 准备请求数据
                data = {
                    "inputs": {},
                    "query": message,
                    "response_mode": "streaming",
                    "conversation_id": "",  # 如果需要的话可以传递一个唯一的会话ID
                    "user": user_id,
                    "files": []  # 如果需要传递文件，可在此添加
                }

                # 打印请求的完整URL和数据
                request_url = f"{self.base_url}chat-messages"
                logger.info(f"请求URL: {request_url}")
                logger.info(f"请求数据: {data}")

                # 发送请求
                response = requests.post(
                    request_url,  # 使用 base_url
                    headers=self.headers,
                    json=data
                )

                # 检查响应状态码
                if response.status_code != 200:
                    logger.error(f"API请求失败，状态码: {response.status_code}")
                    logger.error(f"响应内容: {response.text}")
                    return "抱歉主人，服务响应异常，请稍后再试"

                # 打印响应内容
                logger.info(f"API响应内容: {response.text}")

                # 确保解析正确的部分
                response_content = response.text.split('data: ')[1] if 'data: ' in response.text else response.text

                # 解析为 JSON
                try:
                    response_json = json.loads(response_content)
                    if 'answer' in response_json:
                        reply = response_json['answer']
                        logger.info(f"API响应 - 用户ID: {user_id}")
                        logger.info(f"响应内容: {reply}")
                    else:
                        logger.error("API返回空answer: %s", response_json)
                        return "抱歉主人，服务响应异常，请稍后再试"
                except Exception as json_error:
                    logger.error(f"解析JSON失败: {str(json_error)}")
                    logger.error(f"响应内容: {response.text}")
                    return "抱歉主人，服务响应格式异常，请稍后再试"

                # 添加助手回复到上下文
                self._manage_context(user_id, reply, is_assistant=True)
                
                return reply

            except Exception as api_error:
                logger.error(f"API调用失败: {str(api_error)}")
                return "抱歉主人，我现在有点累，请稍后再试..."

        except Exception as e:
            logger.error(f"Dify调用失败: {str(e)}", exc_info=True)
            return "抱歉主人，刚刚不小心睡着了..."

    def clear_context(self, user_id: str):
        """清除指定用户的对话上下文"""
        if user_id in self.chat_contexts:
            del self.chat_contexts[user_id]
            logger.info(f"已清除用户 {user_id} 的对话上下文")

    def get_context(self, user_id: str) -> List[Dict[str, str]]:
        """获取指定用户的对话上下文"""
        return self.chat_contexts.get(user_id, [])
