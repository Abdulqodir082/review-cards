"""Entry point: starts the user client (MTProto, your account) and the bot client."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from telethon import TelegramClient, functions, types

from .bot.handlers import register
from .bot.jobs import BotContext
from .bot.states import JobManager, UiState
from .config import ConfigError, load_config
from .export.checkpoint import Checkpoint
from .utils.logging_setup import setup_logging

log = logging.getLogger("app")

BOT_COMMANDS = [
    ("chats", "Pick a chat to export"),
    ("search", "Find a chat by name or @username"),
    ("status", "Current export"),
    ("cancel", "Stop the current export"),
    ("resume", "Continue an interrupted export"),
    ("discard", "Delete an unfinished export"),
    ("help", "How to use this bot"),
]


def _secure(path_without_ext) -> None:
    session_file = f"{path_without_ext}.session"
    if os.path.exists(session_file):
        os.chmod(session_file, 0o600)


async def run() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    setup_logging(cfg.log_dir, cfg.log_level)
    cfg.export_dir.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(f"{cfg.user_session_path}.session"):
        log.error("user session not found — run `python login.py` first", extra={"path": str(cfg.user_session_path)})
        return 3

    user = TelegramClient(
        str(cfg.user_session_path),
        cfg.api_id,
        cfg.api_hash,
        flood_sleep_threshold=0,  # FloodWaitError is handled (and shown) by the exporter
        receive_updates=False,
        device_model="Chat Exporter",
    )
    await user.connect()
    if not await user.is_user_authorized():
        log.error("user session is not authorized — run `python login.py` again")
        await user.disconnect()
        return 3
    _secure(cfg.user_session_path)
    me = await user.get_me()
    log.info("user client ready", extra={"user_id": me.id})

    bot = TelegramClient(str(cfg.bot_session_path), cfg.api_id, cfg.api_hash)
    await bot.start(bot_token=cfg.bot_token)
    _secure(cfg.bot_session_path)
    bot_me = await bot.get_me()
    log.info("bot client ready", extra={"bot": bot_me.username, "owner_id": cfg.owner_id})

    try:
        await bot(
            functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(),
                lang_code="",
                commands=[types.BotCommand(c, d) for c, d in BOT_COMMANDS],
            )
        )
    except Exception:  # noqa: BLE001 - cosmetic
        log.warning("could not set bot command list")

    ctx = BotContext(
        bot=bot, user=user, cfg=cfg, state=UiState(), jobs=JobManager(), checkpoint=Checkpoint(cfg.state_dir)
    )
    register(ctx)

    if ctx.checkpoint.exists():
        try:
            job = ctx.checkpoint.load_job()
            await bot.send_message(
                cfg.owner_id,
                f"♻️ Found an unfinished export of **{job.chat.name}**.\n/resume to continue or /discard to delete it.",
            )
        except Exception:  # noqa: BLE001 - the owner may not have started the bot yet
            log.warning("could not notify owner about unfinished export")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    log.info("running — send /start to the bot from your account")
    disconnected = asyncio.ensure_future(bot.run_until_disconnected())
    stopper = asyncio.ensure_future(stop.wait())
    await asyncio.wait({disconnected, stopper}, return_when=asyncio.FIRST_COMPLETED)

    log.info("shutting down")
    if ctx.jobs.busy:
        await ctx.jobs.cancel()  # checkpoint stays on disk for /resume
    await bot.disconnect()
    await user.disconnect()
    stopper.cancel()
    return 0


def main() -> None:
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
