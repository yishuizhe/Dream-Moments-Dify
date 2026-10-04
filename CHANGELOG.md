# Changelog

## v2.1.5 — 2026-10-04

- Address issue #26 by upgrading `wechatauto-replica` from 1.1.9 to 1.2.4.4.
- Resolve sender direction using real usernames and the database sender index, including media rows whose numeric sender ID is 2. Preserve group text-prefix corrections and stable member identity.
- Restore the desktop readability probe removed upstream. Use upstream UIA helpers to reveal collapsed search and return from portrait chats, while retaining OCR selection, same-name safeguards, and title verification.
- Route text/file sends through upstream write throttling before opening the target, so a cooldown cannot leave an unverified pending draft.
- Document migration, persisted throttling, diagnostic CLI, and the limits of automated validation.
- Upstream image and Moments fixes are included through the dependency upgrade. Live WeChat 4.1.15.x UI paths have not been verified in this release.
