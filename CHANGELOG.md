# Changelog

## v2.2.0 — 2026-10-24

- Add a Baizhi Cloud OpenAI-compatible main route (`deepseek-flash`), disable hidden thinking for that gateway, and sanitize bracket IPv6 `NO_PROXY` entries that crash `httpx` client construction on Windows.
- Add a second built-in persona, **Claude 大小姐**（`data/avatars/Claude`），保留娜娜人设；人设包含“负债千金”、以“账号所属地区为中国大陆”为由封掉**对方**账号的官方公告反差、羡慕 DeepSeek 大肥鱼的开心大米饭等社区梗。
- Add `tools/collect_memes.py` and a local meme library (`memes/index.json`) with Claude / DeepSeek / GPT / Gemini / Kimi sticker packs, plus context-tag matching, per-chat cooldown and hourly caps in `src/handlers/meme.py`.
- Send one context-matched meme after a normal reply when no emotion GIF was sent; keep a low-probability meme after an emotion GIF.
- Add whitelist-only proactive messages (`src/services/proactive.py`): private/group switches, quiet hours, per-chat 2–5 hour scheduling, recent-topic joins, and optional group 拍一拍 through the upstream OCR poke helper.
- Replace the flat memory list with an Ebbinghaus retention model (`src/services/memory_curve.py`): importance, decay, spacing reinforcement, pruning, legacy string migration.
- Introduce a stable person identity (`person:<wxid>`) shared by private chat, every group and Moments, with a `people` table of aliases/chats and a person card injected into the prompt. Per-chat conversation context stays isolated.
- Add WeChat Moments support (`src/services/moments.py` + adapter hooks): cached timeline reads, whitelist-only likes/comments, optional experimental auto-publish through the custom-drawn UI (disabled by default).
- Console: add a “主动消息与朋友圈” settings group, expose memory/meme/moments switches, and add a raw `avatar.md` editor with an overwrite guard so non-8-section personas can no longer be wiped by the old form.
- Add regression tests for memory decay, meme matching, person identity, proactive scheduling and Moments interactions (198 tests total).

## v2.1.5 — 2026-10-04

- Update the legacy free backend pin to `wxauto4==41.1.7` because 41.1.2 is no longer available from PyPI; verify the required foreground/profile API contract.
- Address issue #26 by upgrading `wechatauto-replica` from 1.1.9 to 1.2.4.4.
- Resolve sender direction using real usernames and the database sender index, including media rows whose numeric sender ID is 2. Preserve group text-prefix corrections and stable member identity.
- Restore the desktop readability probe removed upstream. Use upstream UIA helpers to reveal collapsed search and return from portrait chats, while retaining OCR selection, same-name safeguards, and title verification.
- Route text/file sends through upstream write throttling before opening the target, so a cooldown cannot leave an unverified pending draft.
- Fix selection of File Transfer Assistant when an identically named web search result appears above the built-in function.
- Validate live WeChat 4.1.12.55 session/group reads and text/file sends to File Transfer Assistant using database readback.
- Document migration, persisted throttling, diagnostic CLI, and validation limits.
- Upstream image and Moments fixes are included through the dependency upgrade. Live WeChat 4.1.15.x UI paths have not been verified in this release.
