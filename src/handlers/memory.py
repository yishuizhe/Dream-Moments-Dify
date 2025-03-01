import os
import logging
from typing import List
from services.ai.deepseek import DeepSeekAI
from datetime import datetime

logger = logging.getLogger(__name__)


class MemoryHandler:
    def __init__(self, root_dir: str, api_key: str, base_url: str, model: str, max_token: int, temperature: float, max_groups: int):
        self.root_dir = root_dir
        self.memory_dir = os.path.join(root_dir, "data", "memory")
        self.short_memory_path = os.path.join(self.memory_dir, "short_memory.txt")
        self.long_memory_buffer_path = os.path.join(self.memory_dir, "long_memory_buffer.txt")
        self.api_key = api_key
        self.base_url = base_url
        self.max_token = max_token
        self.temperature = temperature
        self.max_groups = max_groups
        self.model = model
        os.makedirs(self.memory_dir, exist_ok=True)



        # 如果长期记忆缓冲区不存在，则创建文件
        if not os.path.exists(self.long_memory_buffer_path):
            with open(self.long_memory_buffer_path, "w", encoding="utf-8"):
                logger.info("长期记忆缓冲区文件不存在，已创建新文件。")

    def _get_deepseek_client(self):

        return DeepSeekAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            max_token=self.max_token,
            temperature=self.temperature,
            max_groups=self.max_groups
        )
    def add_short_memory(self, message: str, reply: str):
        """添加短期记忆"""
        with open(self.short_memory_path, "a", encoding="utf-8") as f:
            f.write(f"用户: {message}\n")
            f.write(f"bot: {reply}\n\n")

    def summarize_memories(self):
        """总结短期记忆到长期记忆"""
        if not os.path.exists(self.short_memory_path):
            return

        with open(self.short_memory_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if len(lines) >= 30:  # 15组对话
            max_retries = 3  # 最大重试次数
            retries = 0
            while retries < max_retries:
                try:
                    deepseek = self._get_deepseek_client()
                    summary = deepseek.get_response(
                        message="".join(lines[-30:]),
                        user_id="system",
                        system_prompt="请将以下对话记录总结为最重要的几条长期记忆，总结内容应包含地点，事件，人物（如果对话记录中有的话）用中文简要表述："
                    )
                    logger.debug(f"总结结果:\n{summary}")

                    # 检查是否需要重试
                    retry_sentences = [
                        "好像有些小状况，请再试一次吧～",
                        "信号好像不太稳定呢（皱眉）",
                        "思考被打断了，请再说一次好吗？"
                    ]
                    if summary in retry_sentences:
                        logger.warning(f"收到需要重试的总结结果: {summary}")
                        retries += 1

                        continue

                    # 如果不需要重试，写入长期记忆缓冲区
                    with open(self.long_memory_buffer_path, "a", encoding="utf-8") as f:
                        f.write(f"总结时间: {datetime.now()}\n")
                        f.write(summary + "\n\n")

                    # 清空短期记忆
                    open(self.short_memory_path, "w").close()
                    break  # 成功后退出循环

                except Exception as e:
                    logger.error(f"记忆总结失败: {str(e)}")
                    retries += 1
                    if retries >= max_retries:
                        logger.error("达到最大重试次数，放弃总结")
                        break

    def get_relevant_memories(self, query: str) -> List[str]:
        """获取相关记忆（增加空值检查和日志）"""
        # 检查长期记忆缓冲区是否存在，如果不存在则尝试创建
        if not os.path.exists(self.long_memory_buffer_path):
            logger.warning("长期记忆缓冲区不存在，尝试创建...")
            try:
                with open(self.long_memory_buffer_path, "w", encoding="utf-8"):
                    logger.info("长期记忆缓冲区文件已创建。")
            except Exception as e:
                logger.error(f"创建长期记忆缓冲区文件失败: {str(e)}")
                return []

        max_retries = 3  # 设置最大重试次数
        for retry_count in range(max_retries):
            try:
                with open(self.long_memory_buffer_path, "r", encoding="utf-8") as f:
                    memories = [line.strip() for line in f if line.strip()]

                if not memories:
                    logger.debug("长期记忆缓冲区为空")
                    return []

                deepseek = self._get_deepseek_client()
                response = deepseek.get_response(
                    message="\n".join(memories[-20:]),
                    user_id="retrieval",
                    system_prompt=f"请从以下记忆中找到与'{query}'最相关的条目，按相关性排序返回最多3条:"
                )

                # 检查是否需要重试
                retry_sentences = [
                    "好像有些小状况，请再试一次吧～",
                    "信号好像不太稳定呢（皱眉）",
                    "思考被打断了，请再说一次好吗？"
                ]
                if response in retry_sentences:
                    if retry_count < max_retries - 1:
                        logger.warning(f"第 {retry_count + 1} 次重试：收到需要重试的响应: {response}")
                        continue  # 重试
                    else:
                        logger.error(f"达到最大重试次数：最后一次响应为 {response}")
                        return []
                else:
                    # 返回处理后的响应
                    return [line.strip() for line in response.split("\n") if line.strip()]

            except Exception as e:
                logger.error(f"第 {retry_count + 1} 次尝试失败: {str(e)}")
                if retry_count < max_retries - 1:
                    continue
                else:
                    logger.error(f"达到最大重试次数: {str(e)}")
                return []

        return []