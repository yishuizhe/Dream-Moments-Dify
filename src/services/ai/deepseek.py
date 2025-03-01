"""
DeepSeek AI 服务模块
提供与DeepSeek API的完整交互实现，包含以下核心功能：
- API请求管理
- 上下文对话管理
- 响应安全处理
- 智能错误恢复
"""

import logging
import re
import os
import random
import json  # 新增导入
import time  # 新增导入
from typing import Dict, List, Optional
from openai import OpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type
)
import requests

logger = logging.getLogger(__name__)

class DeepSeekAI:
    def __init__(self, api_key: str, base_url: str, model: str,
                 max_token: int, temperature: float, max_groups: int):
        """
        强化版AI服务初始化

        :param api_key: API认证密钥
        :param base_url: API基础URL
        :param model: 使用的模型名称
        :param max_token: 最大token限制
        :param temperature: 创造性参数(0~2)
        :param max_groups: 最大对话轮次记忆
        :param system_prompt: 系统级提示词
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "Content-Type": "application/json",
                "User-Agent": "MyDreamBot/1.0"
            }
        )
        self.config = {
            "model": model,
            "max_token": max_token,
            "temperature": temperature,
            "max_groups": max_groups,
        }
        self.chat_contexts: Dict[str, List[Dict]] = {}

        # 安全字符白名单（可根据需要扩展）
        self.safe_pattern = re.compile(r'[\x00-\x1F\u202E\u200B]')

        # 如果是 Ollama，获取可用模型列表
        if 'localhost:11434' in base_url:
            self.available_models = self.get_ollama_models()
        else:
            self.available_models = []

    def _manage_context(self, user_id: str, message: str, role: str = "user"):
        """
        上下文管理器（支持动态记忆窗口）

        :param user_id: 用户唯一标识
        :param message: 消息内容
        :param role: 角色类型(user/assistant)
        """
        if user_id not in self.chat_contexts:
            self.chat_contexts[user_id] = []

        # 添加新消息
        self.chat_contexts[user_id].append({"role": role, "content": message})

        # 维护上下文窗口
        while len(self.chat_contexts[user_id]) > self.config["max_groups"] * 2:
            # 优先保留最近的对话组
            self.chat_contexts[user_id] = self.chat_contexts[user_id][-self.config["max_groups"]*2:]

    def _sanitize_response(self, raw_text: str) -> str:
        """
        响应安全处理器
        1. 移除控制字符
        2. 标准化换行符
        3. 防止字符串截断异常
        """
        try:
            cleaned = re.sub(self.safe_pattern, '', raw_text)
            return cleaned.replace('\r\n', '\n').replace('\r', '\n')
        except Exception as e:
            logger.error(f"Response sanitization failed: {str(e)}")
            return "响应处理异常，请重新尝试"

    def _validate_response(self, response: dict) -> bool:
        """
        API响应校验增强版
        验证点涵盖：
        1. 基础字段存在性
        2. 字段类型校验
        3. 关键内容有效性
        4. 数据一致性校验
        """
        # DEBUG模式时可打印完整响应结构
        logger.debug("API响应调试信息：\n%s", json.dumps(response, indent=2, ensure_ascii=False))

        # —— 校验层级1：基础结构 ——
        required_root_keys = {"id", "object", "created", "model", "choices", "usage"}
        if missing := required_root_keys - response.keys():
            logger.error("根层级缺少必需字段：%s", missing)
            return False

        # —— 校验层级2：字段类型校验 ——
        type_checks = [
            ("id", str, "字段应为字符串"),
            ("object", str, "字段应为字符串"),
            ("created", int, "字段应为时间戳整数"),
            ("model", str, "字段应为模型名称字符串"),
            ("choices", list, "字段应为列表类型"),
            ("usage", dict, "字段应为使用量字典")
        ]

        for field, expected_type, error_msg in type_checks:
            if not isinstance(response.get(field), expected_type):
                logger.error("字段[%s]类型错误：%s", field, error_msg)
                return False

        # —— 校验层级3：字段内容有效性 ——
        # 检查模型名称格式
        if not re.match(r'^[a-zA-Z/-]*deepseek', response["model"], re.IGNORECASE):
            logger.error("模型名称格式异常：%s", response["model"])
            return False

        # 检查时间戳有效性（允许过去30年到未来5分钟）
        current_timestamp = int(time.time())
        if not (current_timestamp - 946080000 < response["created"] < current_timestamp + 300):
            logger.error("无效时间戳：%s", response["created"])
            return False

        # —— 校验层级4：choices数组结构 ——
        if len(response["choices"]) == 0:
            logger.error("空响应choices数组")
            return False

        for index, choice in enumerate(response["choices"]):
            if not isinstance(choice, dict):
                logger.error("第%d个choice类型错误", index)
                return False

            if missing := {"index", "message", "finish_reason"} - choice.keys():
                logger.error("choice%d缺少字段：%s", index, missing)
                return False

            # 校验message结构
            message = choice["message"]
            if missing := {"role", "content"} - message.keys():
                logger.error("message结构异常：缺少%s", missing)
                return False

            if message["role"] != "assistant":
                logger.error("非预期角色类型：%s", message["role"])
                return False

            if not isinstance(message["content"], str) or len(message["content"].strip()) == 0:
                logger.error("无效消息内容：%s", message["content"])
                return False

            # 校验finish_reason
            if choice["finish_reason"] not in ("stop", "length", "content_filter", None):
                logger.error("异常对话终止原因：%s", choice["finish_reason"])
                return False

        # —— 校验层级5：使用量统计 ——
        usage = response["usage"]
        usage_checks = [
            ("prompt_tokens", int, "应为非负整数"),
            ("completion_tokens", int, "应为非负整数"),
            ("total_tokens", int, "应为非负整数")
        ]

        for field, expected_type, error_msg in usage_checks:
            if not isinstance(usage.get(field), expected_type) or usage[field] < 0:
                logger.error("使用量字段[%s]无效：%s", field, error_msg)
                return False

        # 校验token总数一致性
        if usage["total_tokens"] != (usage["prompt_tokens"] + usage["completion_tokens"]):
            logger.error("Token总数不一致：prompt(%d) + completion(%d) ≠ total(%d)",
                         usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"])
            return False

        return True

    def get_response(self, message: str, user_id: str, system_prompt: str) -> str:
        """
        完整请求处理流程
        """
        try:
            # —— 阶段1：输入验证 ——
            if not message.strip():
                logger.warning("收到空消息请求")
                return "嗯...我好像收到了空白消息呢（歪头）"

            # —— 阶段2：上下文更新 ——
            self._manage_context(user_id, message)

            # —— 阶段3：构建请求参数 ——
            # 拼接基础Prompt
            try:
                # 从当前文件位置(deepseek.py)向上导航到项目根目录
                current_dir = os.path.dirname(os.path.abspath(__file__))  # src/services/ai
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))  # 项目根目录
                base_prompt_path = os.path.join(project_root, "data", "base", "base.md")
                
                with open(base_prompt_path, "r", encoding="utf-8") as f:
                    base_content = f.read()
            except Exception as e:
                logger.error(f"基础Prompt文件读取失败: {str(e)}")
                base_content = ""
            
            system_prompt = f"{system_prompt}\n{base_content}"
            # print(system_prompt) #测试拼接
            
            # 构建消息列表
            messages = [
                {"role": "system", "content": system_prompt},
                *self.chat_contexts.get(user_id, [])[-self.config["max_groups"] * 2:]
            ]

            # 为 Ollama 构建消息内容
            chat_history = self.chat_contexts.get(user_id, [])[-self.config["max_groups"] * 2:]
            history_text = "\n".join([
                f"{msg['role']}: {msg['content']}" 
                for msg in chat_history
            ])
            ollama_message = {
                "role": "user",
                "content": f"{system_prompt}\n\n对话历史：\n{history_text}\n\n用户问题：{message}"
            }

            # 检查是否是 Ollama API
            is_ollama = 'localhost:11434' in str(self.client.base_url)

            if is_ollama:
                # Ollama API 格式
                request_config = {
                    "model": self.config["model"].split('/')[-1],  # 移除路径前缀
                    "messages": [ollama_message],  # 将消息包装在列表中
                    "stream": False,
                    "options": {
                        "temperature": self.config["temperature"],
                        "max_tokens": self.config["max_token"]
                    }
                }
                
                # 使用 requests 库向 Ollama API 发送 POST 请求
                try:
                    response = requests.post(
                        f"{str(self.client.base_url)}",
                        json=request_config,
                        headers={"Content-Type": "application/json"}
                    )
                    response.raise_for_status()
                    response_data = response.json()
                    
                    # 检查响应中是否包含 message 字段
                    if response_data and "message" in response_data:
                        raw_content = response_data["message"]["content"]
                        logger.debug("Ollama API响应内容: %s", raw_content)
                    else:
                        raise ValueError("错误的API响应结构")
                        
                    clean_content = self._sanitize_response(raw_content)
                    self._manage_context(user_id, clean_content, "assistant")
                    return clean_content
                    
                except Exception as e:
                    logger.error(f"Ollama API请求失败: {str(e)}")
                    raise

            else:
                # 主要 api 请求（重要）
                # 标准 OpenAI 格式
                request_config = {
                    "model": self.config["model"],  # 模型名称
                    "messages": messages,  # 消息列表
                    "temperature": self.config["temperature"],  # 温度参数
                    "max_tokens": self.config["max_token"],  # 最大 token 数
                    "top_p": 0.95,  # top_p 参数
                    "frequency_penalty": 0.2  # 频率惩罚参数
                }
                
                # 使用 OpenAI 客户端发送请求
                response = self.client.chat.completions.create(**request_config)
                # 验证 API 响应结构
                if not self._validate_response(response.model_dump()):
                    raise ValueError("错误的API响应结构")
                    
                # 获取原始内容
                raw_content = response.choices[0].message.content
                # 清理响应内容
                clean_content = self._sanitize_response(raw_content)
                # 管理上下文
                self._manage_context(user_id, clean_content, "assistant")
                # 返回清理后的内容
                return clean_content

        except Exception as e:
            logger.error("深度求索服务调用失败: %s", str(e), exc_info=True)
            return random.choice([
                "好像有些小状况，请再试一次吧～",
                "信号好像不太稳定呢（皱眉）",
                "思考被打断了，请再说一次好吗？"
            ])

    def clear_history(self, user_id: str) -> bool:
        """
        清空指定用户的对话历史
        """
        if user_id in self.chat_contexts:
            del self.chat_contexts[user_id]
            logger.info("已清除用户 %s 的对话历史", user_id)
            return True
        return False

    def analyze_usage(self, response: dict) -> Dict:
        """
        用量分析工具
        """
        usage = response.get("usage", {})
        return {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "estimated_cost": (usage.get("total_tokens", 0) / 1000) * 0.02  # 示例计价
        }

    def chat(self, messages: list, **kwargs) -> str:
        """
        发送聊天请求并获取回复
        
        Args:
            messages: 消息列表，每个消息是包含 role 和 content 的字典
            **kwargs: 额外的参数配置
            
        Returns:
            str: AI的回复内容
        """
        try:
            response = self.client.chat.completions.create(
                model=self.config["model"],
                messages=messages,
                temperature=kwargs.get('temperature', self.config["temperature"]),
                max_tokens=self.config["max_token"]
            )
            
            if not self._validate_response(response.model_dump()):
                raise ValueError("Invalid API response structure")
                
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Chat completion failed: {str(e)}")
            return ""

    def get_ollama_models(self) -> List[Dict]:
        """获取本地 Ollama 可用的模型列表"""
        try:
            response = requests.get('http://localhost:11434/api/tags')
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [
                    {
                        "id": model['name'],
                        "name": model['name'],
                        "status": "active",
                        "type": "chat",
                        "context_length": 16000  # 默认上下文长度
                    }
                    for model in models
                ]
            return []
        except Exception as e:
            logger.error(f"获取Ollama模型列表失败: {str(e)}")
            return []
