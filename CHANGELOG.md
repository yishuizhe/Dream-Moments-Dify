# Changelog

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
