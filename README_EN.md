# Dream-Moments-Dify

An experimental Windows WeChat 4 private chat bot derived from **My-Dream-Moments / KouriChat**.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

This project preserves the original attribution and GPLv3 license. It does not bypass `wxautox4` Plus licensing; WeChat automation uses the public APIs of the free `wxauto4` package.

## Highlights

- Free `wxauto4==41.1.2` adapter with WeChat `4.1.11.x` nickname compatibility.
- `GetSession()`-driven polling: chats are opened once to build a baseline, then only unread or preview-changed whitelisted chats are opened.
- Direct DeepSeek/OpenAI-compatible Chat Completions or Dify Chat API.
- Group replies no longer automatically mention the triggering member.
- Emotion-aware animated cat GIFs from Google Noto Emoji Animation.
- One concise startup banner, WARNING+ console logs, and detailed INFO file logs.

## Requirements

- Windows 10/11
- A logged-in WeChat 4 client
- Python `>=3.9,<3.14`

```powershell
python -m pip install -r requirements.txt
Copy-Item src\config\config.json.template src\config\config.json
python run_config_web.py
python run.py
```

The local `src/config/config.json` is ignored by Git. Never commit API keys, contact names, private prompts, logs, screenshots, or chat records.

## Polling behavior

The first polling round opens whitelisted chats to build message baselines. Later rounds inspect the conversation list without switching chats and only open a chat when its unread count or preview changes. Sending a reply/file still requires foreground UI automation and may briefly change focus.

Group chats can trigger the bot with `@bot-name` or by mentioning the bot name as a standalone name. Replies are sent without automatically mentioning the sender.

## Emoji assets

Bundled GIFs live under `data/avatars/MONO/emojis/{happy,sad,angry,neutral}`. They are from **Noto Emoji Animation** by Google under CC BY 4.0. See `data/avatars/MONO/emojis/ATTRIBUTION.md`.

## Tests

```powershell
python -m unittest discover -s tests -v
python test.py
python -m compileall -q src tests run.py run_config_web.py test.py
```

## Upstream and license

- [KouriChat/KouriChat](https://github.com/KouriChat/KouriChat)
- [umaru-233/My-Dream-Moments](https://github.com/umaru-233/My-Dream-Moments)

Copyright remains with the respective original authors and contributors. This repository is distributed under [GNU GPLv3](LICENSE) without warranty. Third-party assets may have separate licenses documented next to those assets.
