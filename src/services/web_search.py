"""Lightweight web search helpers for chat enrichment."""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

SEARCH_HINTS = (
    "联网搜索",
    "联网查",
    "联网查一下",
    "搜索一下",
    "搜一下",
    "帮我搜",
    "查一下",
    "搜索：",
    "搜索:",
    "web search",
    "search:",
)


def is_search_request(text: str) -> bool:
    value = str(text or "")
    lower = value.lower()
    return any(hint in value or hint in lower for hint in SEARCH_HINTS)


def extract_search_query(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    # Prefer explicit "搜索：xxx"
    m = re.search(r"(?:搜索|搜一下|查一下|联网搜索|联网查一下|帮我搜)[：:\s]*(.+)$", value)
    if m:
        return m.group(1).strip(" 。.!！?？")
    cleaned = value
    for hint in SEARCH_HINTS:
        cleaned = cleaned.replace(hint, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" 。.!！?？:：")
    return cleaned


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """Search the public web. Uses DuckDuckGo HTML results as a free default."""
    q = str(query or "").strip()
    if not q:
        return []
    max_results = max(1, min(int(max_results), 8))
    results: list[dict] = []

    # 1) Instant Answer API (may be sparse, but free and stable).
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={
                "q": q,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
            timeout=12,
            headers={"User-Agent": "Dream-Moments-Bot/1.0"},
        )
        if resp.ok:
            data = resp.json()
            abstract = str(data.get("AbstractText") or "").strip()
            abstract_url = str(data.get("AbstractURL") or "").strip()
            if abstract:
                results.append(
                    {
                        "title": str(data.get("Heading") or q),
                        "snippet": abstract,
                        "url": abstract_url,
                    }
                )
            for item in data.get("RelatedTopics") or []:
                if len(results) >= max_results:
                    break
                if not isinstance(item, dict):
                    continue
                text = str(item.get("Text") or "").strip()
                url = str(item.get("FirstURL") or "").strip()
                if text:
                    results.append({"title": text[:40], "snippet": text, "url": url})
    except Exception as exc:
        logger.warning("DuckDuckGo instant answer failed: %s", type(exc).__name__)

    # 2) HTML lite endpoint for more organic results.
    if len(results) < max_results:
        try:
            html_resp = requests.get(
                "https://html.duckduckgo.com/html/",
                data={"q": q},
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DreamMomentsBot/1.0)",
                },
            )
            if html_resp.ok:
                html = html_resp.text
                # result__a and result__snippet classes
                titles = re.findall(
                    r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                    html,
                    flags=re.I | re.S,
                )
                snippets = re.findall(
                    r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
                    html,
                    flags=re.I | re.S,
                )
                for idx, (url, title_html) in enumerate(titles):
                    if len(results) >= max_results:
                        break
                    title = re.sub(r"<[^>]+>", "", title_html)
                    title = re.sub(r"\s+", " ", title).strip()
                    snippet = ""
                    if idx < len(snippets):
                        snippet = re.sub(r"<[^>]+>", "", snippets[idx])
                        snippet = re.sub(r"\s+", " ", snippet).strip()
                    if title or snippet:
                        results.append({"title": title or q, "snippet": snippet, "url": url})
        except Exception as exc:
            logger.warning("DuckDuckGo HTML search failed: %s", type(exc).__name__)

    # de-dup by title/url
    deduped: list[dict] = []
    seen = set()
    for item in results:
        key = (item.get("url") or "") + "|" + (item.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:max_results]


def format_search_context(query: str, results: list[dict]) -> str:
    if not results:
        return (
            f"用户希望联网搜索：{query}\n"
            "当前没有检索到可靠网页结果。请基于已有知识谨慎回答，并明确可能过时。"
        )
    lines = [f"以下是关于“{query}”的联网检索结果，请优先依据这些资料回答，并注明不确定处："]
    for i, item in enumerate(results, 1):
        title = item.get("title") or f"结果{i}"
        snippet = item.get("snippet") or ""
        url = item.get("url") or ""
        lines.append(f"{i}. {title}")
        if snippet:
            lines.append(f"   摘要：{snippet}")
        if url:
            lines.append(f"   链接：{url}")
    return "\n".join(lines)


def enrich_message_with_search(message: str) -> tuple[str, Optional[str]]:
    """If message looks like a search request, append web context.

    Returns (message_for_model, query_or_none).
    """
    text = str(message or "")
    if not is_search_request(text):
        return text, None
    query = extract_search_query(text)
    if not query:
        return text, None
    results = search_web(query)
    context = format_search_context(query, results)
    enriched = (
        f"{text}\n\n"
        f"【联网搜索结果】\n{context}\n"
        "请结合以上结果作答；如果结果不足，请直说。"
    )
    return enriched, query
