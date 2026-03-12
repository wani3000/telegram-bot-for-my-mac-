#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import shlex
import shutil
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "bot.log"


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("cwpark_bot")


logger = setup_logging()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH}. Copy config.example.json to config.json and fill it in."
        )
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    required_keys = ["BOT_TOKEN", "ALLOWED_CHAT_IDS", "WORK_DIR", "CLAUDE_BIN"]
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    return data


CONFIG = load_config()
BOT_TOKEN = CONFIG["BOT_TOKEN"]
ALLOWED_CHAT_IDS = {int(chat_id) for chat_id in CONFIG["ALLOWED_CHAT_IDS"]}
DEFAULT_WORK_DIR = Path(CONFIG["WORK_DIR"]).expanduser()
CLAUDE_BIN = CONFIG.get("CLAUDE_BIN", "claude")
CLAUDE_ARGS = CONFIG.get("CLAUDE_ARGS", ["-p"])
MAX_HISTORY_TURNS = int(CONFIG.get("MAX_HISTORY_TURNS", 12))
MAX_MESSAGE_CHARS = int(CONFIG.get("MAX_MESSAGE_CHARS", 3500))
CLAUDE_TIMEOUT_SECONDS = int(CONFIG.get("CLAUDE_TIMEOUT_SECONDS", 600))
MAX_PROMPT_CHARS = int(CONFIG.get("MAX_PROMPT_CHARS", 20000))


@dataclass
class ChatState:
    work_dir: Path
    history: List[dict] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


CHAT_STATES: Dict[int, ChatState] = defaultdict(
    lambda: ChatState(work_dir=DEFAULT_WORK_DIR)
)


def is_allowed(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.id in ALLOWED_CHAT_IDS)


async def reject_if_not_allowed(update: Update) -> bool:
    if is_allowed(update):
        return False

    chat = update.effective_chat
    logger.warning("Blocked message from unauthorized chat_id=%s", getattr(chat, "id", None))
    if update.message:
        await update.message.reply_text("Access denied.")
    return True


def ensure_work_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def validate_startup_config() -> None:
    if not BOT_TOKEN or "replace-with-your-telegram-token" in BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not configured in config.json.")
    if not ALLOWED_CHAT_IDS:
        raise ValueError("ALLOWED_CHAT_IDS must contain at least one chat id.")
    if MAX_HISTORY_TURNS < 0:
        raise ValueError("MAX_HISTORY_TURNS must be zero or greater.")
    if MAX_MESSAGE_CHARS < 200:
        raise ValueError("MAX_MESSAGE_CHARS is too small.")
    if CLAUDE_TIMEOUT_SECONDS < 10:
        raise ValueError("CLAUDE_TIMEOUT_SECONDS must be at least 10 seconds.")


def get_chat_state(chat_id: int) -> ChatState:
    state = CHAT_STATES[chat_id]
    state.work_dir = ensure_work_dir(state.work_dir)
    return state


def build_session_prompt(history: List[dict], user_message: str) -> str:
    trimmed = history[-MAX_HISTORY_TURNS * 2 :]
    lines = [
        "You are Claude Code running in a Telegram bridge.",
        "Continue the conversation using the history below.",
        "Be concise but complete, and include actionable terminal-oriented help when relevant.",
        "",
    ]

    for item in trimmed:
        role = item["role"].upper()
        lines.append(f"{role}:")
        lines.append(item["content"])
        lines.append("")

    lines.append("USER:")
    lines.append(user_message)
    lines.append("")
    lines.append("ASSISTANT:")
    prompt = "\n".join(lines)
    if len(prompt) <= MAX_PROMPT_CHARS:
        return prompt

    # Trim oldest items until the prompt fits within the configured budget.
    while trimmed and len(prompt) > MAX_PROMPT_CHARS:
        trimmed = trimmed[2:]
        lines = [
            "You are Claude Code running in a Telegram bridge.",
            "Continue the conversation using the history below.",
            "Be concise but complete, and include actionable terminal-oriented help when relevant.",
            "",
        ]
        for item in trimmed:
            role = item["role"].upper()
            lines.append(f"{role}:")
            lines.append(item["content"])
            lines.append("")
        lines.append("USER:")
        lines.append(user_message)
        lines.append("")
        lines.append("ASSISTANT:")
        prompt = "\n".join(lines)

    if len(prompt) <= MAX_PROMPT_CHARS:
        return prompt

    clipped_user_message = user_message[-max(1000, MAX_PROMPT_CHARS // 2) :]
    return textwrap.dedent(
        f"""\
        You are Claude Code running in a Telegram bridge.
        Earlier conversation was truncated because it exceeded the prompt size budget.

        USER:
        {clipped_user_message}

        ASSISTANT:
        """
    )


def find_claude_binary() -> str:
    if os.path.sep in CLAUDE_BIN:
        return CLAUDE_BIN

    resolved = shutil.which(CLAUDE_BIN)
    if not resolved:
        raise FileNotFoundError(
            f"Could not find Claude binary '{CLAUDE_BIN}'. Update CLAUDE_BIN in config.json."
        )
    return resolved


async def run_claude(prompt: str, work_dir: Path) -> str:
    work_dir = ensure_work_dir(work_dir)
    claude_bin = find_claude_binary()
    command = [claude_bin, *CLAUDE_ARGS, prompt]
    logger.info("Running command: %s (cwd=%s)", shlex.join(command), work_dir)

    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        logger.error("Claude command timed out after %s seconds", CLAUDE_TIMEOUT_SECONDS)
        raise RuntimeError(
            f"Claude timed out after {CLAUDE_TIMEOUT_SECONDS} seconds. "
            "Try a shorter prompt or check whether the CLI is waiting for input."
        )
    output = stdout.decode("utf-8", errors="replace").strip()
    error = stderr.decode("utf-8", errors="replace").strip()

    if process.returncode != 0:
        logger.error("Claude command failed (%s): %s", process.returncode, error or output)
        raise RuntimeError(error or output or f"Claude exited with code {process.returncode}")

    return output or "(empty response)"


def chunk_text(text: str, limit: int) -> List[str]:
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


async def send_long_message(update: Update, text: str) -> None:
    if not update.message:
        return
    for chunk in chunk_text(text, MAX_MESSAGE_CHARS):
        await update.message.reply_text(chunk)


async def send_typing(update: Update) -> None:
    if update.effective_chat:
        await update.get_bot().send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    text = (
        "Telegram -> Claude Code bot is ready.\n\n"
        "Commands:\n"
        "/p <prompt> : one-shot prompt\n"
        "/new : clear session history\n"
        "/cd <path> : change working directory\n"
        "/pwd : show working directory\n"
        "/status : show bot status\n"
        "/start : show this help\n\n"
        f"Your chat_id: {update.effective_chat.id}"
    )
    await update.message.reply_text(text)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    state = get_chat_state(update.effective_chat.id)
    claude_path = shutil.which(CLAUDE_BIN) if os.path.sep not in CLAUDE_BIN else CLAUDE_BIN
    text = (
        f"work_dir: {state.work_dir}\n"
        f"history_items: {len(state.history)}\n"
        f"allowed_chat_ids: {sorted(ALLOWED_CHAT_IDS)}\n"
        f"claude_bin: {claude_path or 'not found'}\n"
        f"claude_args: {CLAUDE_ARGS}"
    )
    await update.message.reply_text(text)


async def cmd_pwd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    state = get_chat_state(update.effective_chat.id)
    await update.message.reply_text(str(state.work_dir))


async def cmd_cd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    if not context.args:
        await update.message.reply_text("Usage: /cd /absolute/or/relative/path")
        return

    raw_path = " ".join(context.args).strip()
    state = get_chat_state(update.effective_chat.id)
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (state.work_dir / candidate).resolve()

    if not candidate.exists():
        await update.message.reply_text(f"Path does not exist:\n{candidate}")
        return
    if not candidate.is_dir():
        await update.message.reply_text(f"Path is not a directory:\n{candidate}")
        return

    state.work_dir = candidate.resolve()
    await update.message.reply_text(f"Changed directory to:\n{state.work_dir}")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    state = get_chat_state(update.effective_chat.id)
    state.history.clear()
    await update.message.reply_text("Session history cleared.")


async def cmd_print(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /p <prompt>")
        return

    state = get_chat_state(update.effective_chat.id)
    async with state.lock:
        await send_typing(update)
        try:
            result = await run_claude(prompt, state.work_dir)
        except Exception as exc:
            await update.message.reply_text(f"Error: {exc}")
            return

    await send_long_message(update, result)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_not_allowed(update):
        return

    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    if not user_text:
        return

    state = get_chat_state(update.effective_chat.id)
    async with state.lock:
        await send_typing(update)
        prompt = build_session_prompt(state.history, user_text)

        try:
            result = await run_claude(prompt, state.work_dir)
        except Exception as exc:
            await update.message.reply_text(f"Error: {exc}")
            return

        state.history.append({"role": "user", "content": user_text})
        state.history.append({"role": "assistant", "content": result})
        state.history[:] = state.history[-MAX_HISTORY_TURNS * 2 :]

    await send_long_message(update, result)


def main() -> None:
    validate_startup_config()
    DEFAULT_WORK_DIR.mkdir(parents=True, exist_ok=True)
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("p", cmd_print))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting cwpark Telegram bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
