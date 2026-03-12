# Handoff: Telegram -> Claude Code Bot

Created: 2026-03-12

## Goal

Control Claude Code running on MacBook 2 from Telegram on MacBook 1.

## Current Structure

- Repo path: `/Users/chulwan/Documents/GitHub/telegrambot-formymac`
- Runtime install target on server Mac: `~/github/claude-telegram-bot`
- Telegram bot username: `@cwpark_bot`
- Allowed chat id collected earlier: `387557093`

## What The Bot Does

- Receives Telegram messages through long polling
- Blocks unauthorized chats using a `chat_id` allowlist
- Runs `claude -p "<prompt>"` in a chosen working directory
- Returns the CLI output to Telegram
- Keeps short in-memory history for normal messages
- Applies timeout and prompt-budget limits to avoid stuck sessions

## Key Files

- `bot.py`
  - Main runtime
  - Session history management
  - Telegram command handlers
  - Claude subprocess execution
- `config.example.json`
  - Safe template for repository use
- `config.json`
  - Local secrets and runtime values
- `install.sh`
  - Clone or update repo
  - Create virtualenv
  - Install dependencies
  - Register `launchd`
- `README.md`
  - Setup and command overview

## Runtime Commands

- `/start`
  - Show help and current `chat_id`
- `/status`
  - Show current working directory, history count, Claude path
- `/pwd`
  - Show working directory
- `/cd /path`
  - Change working directory for the current chat if the path already exists
- `/new`
  - Clear session history
- `/p prompt`
  - One-shot prompt
- Plain message
  - Session mode with short remembered history

## Install on Server Mac

```bash
git clone https://github.com/wani3000/telegram-bot-for-my-mac-.git ~/github/claude-telegram-bot
cd ~/github/claude-telegram-bot
chmod +x install.sh
./install.sh
```

If `config.json` still contains placeholders, edit it and restart:

```bash
launchctl kickstart -k gui/$(id -u)/com.cwpark.claudebot
```

## Manual Test

```bash
cd ~/github/claude-telegram-bot
. .venv/bin/activate
python bot.py
```

Then message the bot on Telegram:

- `/start`
- `/status`
- `/p say hello`

## Logs

```bash
tail -f ~/github/claude-telegram-bot/bot.log
tail -f ~/github/claude-telegram-bot/stderr.log
tail -f ~/github/claude-telegram-bot/stdout.log
```

## Risks / Follow-ups

- The token shown in the earlier chat was exposed. Rotation is strongly recommended.
- Session history is in memory only and resets on restart.
- This implementation assumes the Claude CLI supports `claude -p "<prompt>"`.
- Long-running jobs are serialized per chat to avoid overlapping replies.
- Claude commands now fail fast on timeout, but very long interactive workflows are still not ideal over Telegram.

## Suggested Next Task For Claude Code

1. Add a `/shell` command restricted to the allowlist owner.
2. Persist session history to disk if restart recovery matters.
3. Add a queue or cancellation support for long Claude tasks.
