"""Failover routing for OpenAI-compatible chat providers."""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any

from services.ai.deepseek import DeepSeekAI


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Route:
    name: str
    client: DeepSeekAI
    complex_only: bool = False
    failed_until: float = 0.0


class FailoverAI:
    """Try configured routes in order while keeping their chat context in sync."""

    COMPLEX_RE = re.compile(
        r"深入分析|详细分析|复杂推理|严格证明|架构设计|系统设计|"
        r"调试代码|排查故障|完整方案|代码审查|风险评估|对比评估"
    )

    def __init__(
        self,
        routes: list[dict[str, Any]],
        *,
        max_groups: int,
        max_tokens: int,
        temperature: float,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self.cooldown_seconds = max(5.0, float(cooldown_seconds))
        self.routes: list[_Route] = []
        for item in routes:
            if not bool(item.get("enabled", True)):
                continue
            api_key = str(item.get("api_key") or "").strip()
            base_url = str(item.get("base_url") or "").strip()
            model = str(item.get("model") or "").strip()
            if not api_key or not base_url or not model:
                continue
            name = str(item.get("name") or model).strip()
            client = DeepSeekAI(
                api_key=api_key,
                base_url=base_url,
                model=model,
                max_token=int(item.get("max_tokens") or max_tokens),
                temperature=float(item.get("temperature", temperature)),
                max_groups=max_groups,
                raise_errors=True,
                provider_name=name,
            )
            self.routes.append(_Route(name, client, bool(item.get("complex_only", False))))
        if not self.routes:
            raise ValueError("没有配置可用的 OpenAI 兼容 AI 线路")
        self.active_route_name = self.routes[0].name

    def get_response(self, message: str, user_id: str, system_prompt: str) -> str:
        complex_request = len(str(message or "")) >= 500 or bool(self.COMPLEX_RE.search(str(message or "")))
        now = time.monotonic()
        attempted = 0
        for route in self.routes:
            if route.complex_only and not complex_request:
                continue
            if route.failed_until > now:
                continue
            attempted += 1
            try:
                reply = route.client.get_response(message, user_id, system_prompt)
            except Exception as exc:
                route.failed_until = time.monotonic() + self.cooldown_seconds
                logger.warning(
                    "AI 线路 %s 失败，暂停 %.0f 秒后尝试下一条（%s）",
                    route.name,
                    self.cooldown_seconds,
                    type(exc).__name__,
                )
                continue
            self.active_route_name = route.name
            self._sync_context(route.client, user_id)
            if attempted > 1:
                logger.info("AI 已切换到备用线路: %s", route.name)
            return reply
        logger.error("AI 所有符合条件的线路均不可用")
        return random.choice(("这会儿线路都有点忙，等一下再说吧。", "我这边刚刚断了一下，稍后再试试。"))

    def _sync_context(self, source: DeepSeekAI, user_id: str) -> None:
        context = [dict(item) for item in source.chat_contexts.get(user_id, [])]
        for route in self.routes:
            if route.client is not source:
                route.client.chat_contexts[user_id] = [dict(item) for item in context]

    def clear_history(self, user_id: str) -> bool:
        cleared = False
        for route in self.routes:
            cleared = route.client.clear_history(user_id) or cleared
        return cleared

    clear_context = clear_history
