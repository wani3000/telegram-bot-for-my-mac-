# Telegram -> Claude Code Bot for Mac

This project lets you control a server-side Claude Code CLI from Telegram.

Flow:

`Telegram app on MacBook 1 -> Telegram Bot API -> bot.py on MacBook 2 -> claude CLI -> reply back to Telegram`

## Features

- Whitelist access by `chat_id`
- Session mode for normal messages
- One-shot mode with `/p`
- `/cd`, `/pwd`, `/new`, `/status`, `/start`
- `launchd` auto-start support for macOS
- Claude timeout protection and prompt-size trimming

## Files

- `bot.py`: Telegram bot server
- `config.example.json`: safe template for Git
- `config.json`: local runtime config, excluded from Git
- `install.sh`: macOS installer and `launchd` registration
- `handoff-cwpark-bot.md`: operational handoff

## Quick Start

1. Clone this repo on the server Mac.
2. Run:

```bash
chmod +x install.sh
./install.sh
```

3. Edit `config.json`.
4. Restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.cwpark.claudebot
```

5. Open Telegram and send `/start` to your bot.

## Example `config.json`

```json
{
  "BOT_TOKEN": "replace-with-your-telegram-token",
  "ALLOWED_CHAT_IDS": [123456789],
  "WORK_DIR": "/Users/yourname/github/claude-telegram-bot",
  "CLAUDE_BIN": "claude",
  "CLAUDE_ARGS": ["-p"],
  "CLAUDE_TIMEOUT_SECONDS": 600,
  "MAX_HISTORY_TURNS": 12,
  "MAX_PROMPT_CHARS": 20000,
  "MAX_MESSAGE_CHARS": 3500
}
```

## Commands

- Normal message: session conversation with remembered context
- `/p <prompt>`: one-shot prompt without session history
- `/new`: clear session history
- `/cd <path>`: change working directory for this chat, only if the directory already exists
- `/pwd`: show current working directory
- `/status`: inspect bot state
- `/start`: help and current `chat_id`

## Notes

- `config.json` is ignored by Git so secrets stay local.
- If your Telegram token was ever exposed, rotate it in `@BotFather`.
- This bot uses polling, so no webhook or public server is required.
- `install.sh` does not auto-start the service until `config.json` has a real token.
