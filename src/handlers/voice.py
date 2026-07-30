"""
语音处理模块
负责处理语音相关功能，包括:
- 语音请求识别
- TTS语音生成（本地 TTS -> edge-tts -> Windows SAPI）
- 语音文件管理
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class VoiceHandler:
    def __init__(self, root_dir, tts_api_url):
        self.root_dir = root_dir
        self.tts_api_url = str(tts_api_url or "").strip()
        self.voice_dir = os.path.join(root_dir, "data", "voices")
        self.edge_voice = "zh-CN-XiaoxiaoNeural"
        self.last_error = ""
        os.makedirs(self.voice_dir, exist_ok=True)

    def is_voice_request(self, text: str) -> bool:
        voice_keywords = ["语音", "用语音", "发语音", "语音回复", "语音回答", "语音说"]
        return any(keyword in str(text or "") for keyword in voice_keywords)

    def clean_voice_prompt(self, text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"(请)?(用)?语音(回复|回答|发送|发我|给我|说)?", " ", cleaned)
        cleaned = re.sub(r"(发语音|语音消息)", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or str(text or "").strip()

    def generate_voice(self, text: str) -> Optional[str]:
        self.last_error = ""
        content = re.sub(r"\s+", " ", str(text or "")).strip()
        if not content:
            self.last_error = "没有可转换的文本"
            return None
        if len(content) > 260:
            content = content[:260].rstrip() + "……"

        os.makedirs(self.voice_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        for producer, name in (
            (lambda: self._generate_with_local_tts(content, timestamp), "local_tts"),
            (lambda: self._generate_with_edge_tts(content, timestamp), "edge_tts"),
            (lambda: self._generate_with_sapi(content, timestamp), "sapi"),
        ):
            try:
                path = producer()
            except Exception as exc:
                logger.warning("TTS provider %s crashed: %s", name, type(exc).__name__)
                path = None
            if path and os.path.exists(path) and os.path.getsize(path) > 64:
                logger.info("Voice generated via %s: %s (%s bytes)", name, path, os.path.getsize(path))
                return path
            logger.warning("TTS provider %s unavailable", name)

        self.last_error = self.last_error or "所有语音合成方式都失败了"
        logger.error("语音生成失败: %s", self.last_error)
        return None

    def _generate_with_local_tts(self, text: str, timestamp: str) -> Optional[str]:
        if not self.tts_api_url:
            return None
        voice_path = os.path.join(self.voice_dir, f"voice_{timestamp}.wav")
        try:
            response = requests.get(
                f"{self.tts_api_url}?text={quote(text)}",
                stream=True,
                timeout=20,
            )
            if response.status_code != 200:
                self.last_error = f"本地 TTS HTTP {response.status_code}"
                return None
            with open(voice_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(voice_path) < 64:
                os.remove(voice_path)
                return None
            return voice_path
        except Exception as exc:
            self.last_error = f"本地 TTS 不可用: {type(exc).__name__}"
            try:
                if os.path.exists(voice_path):
                    os.remove(voice_path)
            except Exception:
                pass
            return None

    def _generate_with_edge_tts(self, text: str, timestamp: str) -> Optional[str]:
        voice_path = os.path.join(self.voice_dir, f"voice_{timestamp}.mp3")
        try:
            import edge_tts  # type: ignore
        except Exception:
            self.last_error = "未安装 edge-tts"
            return None

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, self.edge_voice)
            await communicate.save(voice_path)

        try:
            try:
                asyncio.get_running_loop()
                has_loop = True
            except RuntimeError:
                has_loop = False

            if not has_loop:
                asyncio.run(_run())
            else:
                # Timer / nested contexts: run in a fresh thread with its own loop.
                box: dict[str, Exception | None] = {"err": None}

                def _thread_main() -> None:
                    try:
                        asyncio.run(_run())
                    except Exception as exc:  # pragma: no cover
                        box["err"] = exc

                th = threading.Thread(target=_thread_main, daemon=True)
                th.start()
                th.join(timeout=60)
                if th.is_alive():
                    self.last_error = "edge-tts 超时"
                    return None
                if box["err"] is not None:
                    raise box["err"]

            if os.path.exists(voice_path) and os.path.getsize(voice_path) > 64:
                return voice_path
            self.last_error = "edge-tts 未生成有效文件"
            return None
        except Exception as exc:
            self.last_error = f"edge-tts 失败: {type(exc).__name__}"
            logger.error("edge-tts 语音生成失败: %s", exc)
            try:
                if os.path.exists(voice_path):
                    os.remove(voice_path)
            except Exception:
                pass
            return None

    def _generate_with_sapi(self, text: str, timestamp: str) -> Optional[str]:
        """Windows 自带语音，不依赖外网，作为最终兜底。"""
        voice_path = os.path.join(self.voice_dir, f"voice_{timestamp}.wav")
        try:
            import win32com.client  # type: ignore
        except Exception:
            self.last_error = "未安装 pywin32，无法使用 Windows 语音"
            return None

        try:
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            # SSFMCreateForWrite = 3
            stream.Open(voice_path, 3)
            old_stream = voice.AudioOutputStream
            voice.AudioOutputStream = stream
            voice.Speak(text)
            voice.AudioOutputStream = old_stream
            stream.Close()
            if os.path.exists(voice_path) and os.path.getsize(voice_path) > 64:
                return voice_path
            self.last_error = "Windows 语音未生成有效文件"
            return None
        except Exception as exc:
            self.last_error = f"Windows 语音失败: {type(exc).__name__}"
            logger.error("SAPI 语音生成失败: %s", exc)
            try:
                if os.path.exists(voice_path):
                    os.remove(voice_path)
            except Exception:
                pass
            return None

    def cleanup_voice_dir(self):
        try:
            if os.path.exists(self.voice_dir):
                for file in os.listdir(self.voice_dir):
                    file_path = os.path.join(self.voice_dir, file)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            logger.info("清理旧语音文件: %s", file_path)
                    except Exception as e:
                        logger.error("清理语音文件失败 %s: %s", file_path, str(e))
        except Exception as e:
            logger.error("清理语音目录失败: %s", str(e))
