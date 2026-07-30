"""
Moonshot AI服务模块
提供与Moonshot API的交互功能，包括:
- 图像识别
- 文本生成
- API请求处理
- 错误处理
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

VISION_MODELS = (
    "moonshot-v1-8k-vision-preview",
    "moonshot-v1-32k-vision-preview",
    "moonshot-v1-128k-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
)


class MoonShotAI:
    def __init__(self, api_key: str, base_url: str, temperature: float, model: str | None = None):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.temperature = min(max(0.0, float(temperature or 0.3)), 1.0)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.model = str(model or VISION_MODELS[0]).strip() or VISION_MODELS[0]
        self.last_error = ""

        if not self.api_key:
            logger.warning("图片识别 API Key 为空，识图将不可用")
        elif self.api_key.startswith("ak-"):
            logger.warning(
                "图片识别 API Key 以 ak- 开头，Moonshot 官方密钥通常是 sk- 开头，当前密钥很可能无效"
            )

    def validate_credentials(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "未配置图片识别 API Key"
        if not self.base_url:
            return False, "未配置图片识别 API 地址"
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self.headers,
                timeout=12,
            )
            if response.status_code == 401:
                return False, "图片识别 API Key 无效（401）"
            if response.status_code >= 400:
                return False, f"图片识别服务异常（HTTP {response.status_code}）"
            return True, "ok"
        except Exception as exc:
            return False, f"无法连接图片识别服务：{type(exc).__name__}"

    def _guess_mime(self, image_path: str) -> str:
        mime, _ = mimetypes.guess_type(image_path)
        if mime:
            return mime
        lower = image_path.lower()
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".gif"):
            return "image/gif"
        if lower.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"

    def recognize_image(self, image_path: str, is_emoji: bool = False) -> str:
        """使用视觉模型识别图片内容并返回文本。失败时返回明确错误，不编造内容。"""
        self.last_error = ""
        try:
            if not self.api_key:
                self.last_error = "未配置图片识别 API Key"
                return "IMAGE_RECOGNITION_FAILED: 未配置图片识别 API Key"

            if not image_path or not os.path.exists(image_path):
                self.last_error = f"图片文件不存在: {image_path}"
                logger.error(self.last_error)
                return "IMAGE_RECOGNITION_FAILED: 图片文件不存在"

            if not os.path.isfile(image_path) or not os.access(image_path, os.R_OK):
                self.last_error = f"image file is not readable: {image_path}"
                return "IMAGE_RECOGNITION_FAILED: image file is not readable"

            file_size = os.path.getsize(image_path) / (1024 * 1024)
            if file_size <= 0:
                self.last_error = "图片文件为空"
                return "IMAGE_RECOGNITION_FAILED: 图片文件为空"
            if file_size > 20:
                self.last_error = f"图片过大: {file_size:.2f}MB"
                return "IMAGE_RECOGNITION_FAILED: 图片文件太大了"

            with open(image_path, "rb") as img_file:
                image_content = base64.b64encode(img_file.read()).decode("utf-8")

            mime = self._guess_mime(image_path)
            logger.info("Vision input ready: path=%s size=%.2fMB mime=%s model=%s", image_path, file_size, mime, self.model)
            text_prompt = (
                "请客观描述这张聊天截图/表情里最后一张表情包的内容，不要猜测看不见的信息。"
                if is_emoji
                else "请客观描述这张图片里你确实能看到的内容。如果看不清就直说看不清，不要编造。"
            )

            models_to_try = [self.model] + [m for m in VISION_MODELS if m != self.model]
            last_err = ""
            for model in models_to_try:
                data = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{image_content}"
                                    },
                                },
                                {"type": "text", "text": text_prompt},
                            ],
                        }
                    ],
                    "temperature": self.temperature,
                }
                try:
                    response = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers=self.headers,
                        json=data,
                        timeout=45,
                    )
                except requests.exceptions.Timeout:
                    last_err = "请求超时"
                    continue
                except requests.exceptions.RequestException as exc:
                    last_err = f"请求异常: {type(exc).__name__}"
                    continue

                if response.status_code == 401:
                    self.last_error = "图片识别 API Key 无效"
                    logger.error("Vision API 401 invalid key")
                    return "IMAGE_RECOGNITION_FAILED: 图片识别 API Key 无效"

                if response.status_code != 200:
                    last_err = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.error("Vision API failed with %s using model %s", response.status_code, model)
                    continue

                result = response.json()
                choices = result.get("choices") or []
                if not choices:
                    last_err = f"响应无 choices: {str(result)[:200]}"
                    continue

                recognized_text = str(choices[0].get("message", {}).get("content") or "").strip()
                if not recognized_text:
                    last_err = "模型返回空内容"
                    continue

                if is_emoji:
                    if "最后一张表情包是" in recognized_text:
                        recognized_text = recognized_text.split("最后一张表情包是", 1)[1].strip()
                    recognized_text = "发送了表情包：" + recognized_text
                else:
                    recognized_text = "发送了图片：" + recognized_text

                logger.info("Vision recognition ok via model %s", model)
                return recognized_text

            self.last_error = last_err or "图片识别失败"
            logger.error("Vision recognition failed: %s", self.last_error)
            return f"IMAGE_RECOGNITION_FAILED: {self.last_error}"

        except Exception as exc:
            self.last_error = str(exc)
            logger.error("图片识别过程失败: %s", str(exc), exc_info=True)
            return "IMAGE_RECOGNITION_FAILED: 图片识别过程出现错误"

    def chat_completion(self, messages: list, **kwargs) -> Optional[str]:
        try:
            data = {
                "model": self.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.temperature),
            }
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=data,
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("Moonshot AI 聊天请求失败: %s", str(exc))
            return None
