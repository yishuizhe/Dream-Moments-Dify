import logging
import json
import requests
from typing import Dict, List
from tenacity import retry, stop_after_attempt, wait_random_exponential

logger = logging.getLogger(__name__)

class DifyAI:
    def __init__(self, dify_api_key: str, dify_base_url: str, max_groups: int):
        """
        初始化 dify AI 客户端
        
        Args:
            dify_api_key: API密钥
            dify_base_url: API基础URL
            max_groups: 最大对话组数
        """
        self.max_groups = max_groups
        self.dify_base_url = dify_base_url
        self.headers = {
            'Authorization': f'Bearer {dify_api_key}',
            'Content-Type': 'application/json'
        }
        self.chat_contexts: Dict[str, List[Dict[str, str]]] = {}

    def _manage_context(self, user_id: str, message: str, is_assistant: bool = False):
        """管理对话上下文"""
        self.chat_contexts.setdefault(user_id, [])
        role = "assistant" if is_assistant else "user"
        self.chat_contexts[user_id].append({"role": role, "content": message})
        
        while len(self.chat_contexts[user_id]) > self.max_groups * 2:
            del self.chat_contexts[user_id][:2]

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(min=1, max=5))
    def get_response(self, message: str, user_id: str, system_prompt: str) -> str:
        try:
            logger.debug("Calling Dify API")
            self._manage_context(user_id, message)

            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    *self.chat_contexts[user_id][-self.max_groups * 2:]
                ]

                data = {
                    "inputs": {},
                    "query": message,
                    "response_mode": "blocking",
                    "conversation_id": "",
                    "user": user_id,
                    "files": []
                }

                # 调试 base_url 和拼接的 URL
                if not self.dify_base_url.endswith('/'):
                    self.dify_base_url += '/'  # 确保 base_url 末尾有 /

                request_url = f"{self.dify_base_url}chat-messages"
                

                # 发送请求
                response = requests.post(
                    request_url,
                    headers=self.headers,
                    json=data,
                    timeout=60,
                )

                # 调试响应


                if response.status_code != 200:
                    logger.error("Dify API request failed (HTTP %s)", response.status_code)
                    return "抱歉主人，服务响应异常，请稍后再试"

                response_content = response.text.split('data: ')[1] if 'data: ' in response.text else response.text

                try:
                    response_json = json.loads(response_content)
                    if 'answer' in response_json:
                        reply = response_json['answer']
                        logger.debug("Dify API response received")
                    else:
                        keys = sorted(response_json) if isinstance(response_json, dict) else []
                        logger.error(
                            "Dify API response missing answer (type=%s keys=%s)",
                            type(response_json).__name__,
                            keys,
                        )
                        return "抱歉主人，服务响应异常，请稍后再试"
                except Exception as json_error:
                    logger.error("Dify response JSON parsing failed: %s", type(json_error).__name__)
                    return "抱歉主人，服务响应格式异常，请稍后再试"

                self._manage_context(user_id, reply, is_assistant=True)
                return reply

            except Exception as api_error:
                logger.error("Dify API call failed: %s", type(api_error).__name__)
                return "抱歉主人，我现在有点累，请稍后再试..."

        except Exception as e:
            logger.error("Dify call failed: %s", type(e).__name__, exc_info=True)
            return "抱歉主人，刚刚不小心睡着了..."       
    
    def clear_context(self, user_id: str):
        """清除指定用户的对话上下文"""
        self.chat_contexts.pop(user_id, None)
        logger.info(f"已清除用户 {user_id} 的对话上下文")
    
    def get_context(self, user_id: str) -> List[Dict[str, str]]:
        """获取指定用户的对话上下文"""
        return self.chat_contexts.get(user_id, [])
