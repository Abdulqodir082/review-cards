"""Bot commands and button callbacks. Only OWNER_ID is ever answered."""
from __future__ import annotations

import logging
import time
from typing import Any

from telethon import events, utils
from telethon.tl import types

from ..export.checkpoint import JobSpec
from ..export.exporter import chat_info, flood_retry, new_output_dir
from ..export.models import MEDIA_OPTION_KEYS, SIZE_LIMITS_MB, parse_custom_range
from .jobs import BotContext, create_progress, discard_unfinished, run_job
from .keyboards import dialogs_keyboard, options_keyboard, options_text
from .states import DialogItem

log = logging.getLogger(__name__)

HELP = (
    "**Telegram chat exporter**\n\n"
    "/chats — pick a chat to export\n"
    "/search <text> — find a chat by name or @username\n"
    "/status — current export\n"
    "/cancel — stop the current export (progress is kept)\n"
    "/resume — continue an interrupted export\n"
    "/discard — delete an unfinished export\n\n"
    "Exports use the same layout as Telegram Desktop "
    "(messages.html + result.json + media folders) and arrive here as a zip."
)


def _dialog_kind(entity: Any) -> str:
    if isinstance(entity, types.User):
        if entity.is_self:
            return "saved"
        return "bot" if entity.bot else "private"
    if isinstance(entity, types.Channel) and not entity.megagroup:
        return "channel"
    return "group"


def register(ctx: BotContext) -> None:
    bot, cfg, state, jobs = ctx.bot, ctx.cfg, ctx.state, ctx.jobs
    owner = cfg.owner_id

    def is_owner_msg(event: events.NewMessage.Event) -> bool:
        return event.is_private and event.sender_id == owner

    def is_owner_cb(event: events.CallbackQuery.Event) -> bool:
        return event.sender_id == owner

    async def load_dialogs(force: bool = False) -> list[DialogItem]:
        if state.dialogs_fresh() and not force:
            return state.dialogs
        dialogs = await flood_retry(lambda: ctx.user.get_dialogs())
        state.dialogs = [
            DialogItem(
                peer_id=d.id,
                name=("Saved Messages" if isinstance(d.entity, types.User) and d.entity.is_self else d.name)
                or "Deleted Account",
                kind=_dialog_kind(d.entity),
                username=getattr(d.entity, "username", None),
                entity=d.entity,
            )
            for d in dialogs
        ]
        state.dialogs_fetched_at = time.monotonic()
        return state.dialogs

    def list_text() -> str:
        return f"**{state.listing_title}** ({len(state.listing)}) — choose a chat to export:"

    # ---- commands -------------------------------------------------------

    @bot.on(events.NewMessage(pattern=r"^/(start|help)(@\w+)?$", func=is_owner_msg))
    async def cmd_start(event: events.NewMessage.Event) -> None:
        await event.respond(HELP)

    @bot.on(events.NewMessage(pattern=r"^/chats(@\w+)?$", func=is_owner_msg))
    async def cmd_chats(event: events.NewMessage.Event) -> None:
        await load_dialogs(force=True)
        state.listing, state.listing_title = state.dialogs, "Your chats"
        if not state.listing:
            await event.respond("No chats found.")
            return
        await event.respond(list_text(), buttons=dialogs_keyboard(state.listing, 0))

    @bot.on(events.NewMessage(pattern=r"^/search(@\w+)?(\s+(?P<q>.+))?$", func=is_owner_msg))
    async def cmd_search(event: events.NewMessage.Event) -> None:
        query = (event.pattern_match.group("q") or "").strip()
        if not query:
            state.awaiting_search = True
            state.awaiting_dates = False
            await event.respond("Send the chat name or @username to search for. /cancel to abort.")
            return
        await run_search(event, query)

    async def run_search(event: events.NewMessage.Event, query: str) -> None:
        await load_dialogs()
        results = state.search(query)
        if not results:
            await event.respond(f"No chats match “{query}”. Try another name, or /chats to browse.")
            return
        state.listing, state.listing_title = results, f"Search: {query}"
        await event.respond(list_text(), buttons=dialogs_keyboard(results, 0))

    @bot.on(events.NewMessage(pattern=r"^/status(@\w+)?$", func=is_owner_msg))
    async def cmd_status(event: events.NewMessage.Event) -> None:
        if jobs.busy and jobs.progress:
            await event.respond(jobs.progress.render())
        elif ctx.checkpoint.exists():
            job = ctx.checkpoint.load_job()
            count, _ = ctx.checkpoint.summary()
            await event.respond(
                f"Unfinished export of **{job.chat.name}** ({count:,} messages saved).\n"
                "/resume to continue or /discard to delete it."
            )
        else:
            await event.respond("No export is running.")

    @bot.on(events.NewMessage(pattern=r"^/cancel(@\w+)?$", func=is_owner_msg))
    async def cmd_cancel(event: events.NewMessage.Event) -> None:
        if jobs.busy:
            await jobs.cancel()
        elif state.awaiting_dates or state.awaiting_search:
            state.awaiting_dates = state.awaiting_search = False
            await event.respond("Cancelled.")
        else:
            await event.respond("Nothing to cancel.")

    @bot.on(events.NewMessage(pattern=r"^/resume(@\w+)?$", func=is_owner_msg))
    async def cmd_resume(event: events.NewMessage.Event) -> None:
        if jobs.busy:
            await event.respond("An export is already running — see /status.")
            return
        if not ctx.checkpoint.exists():
            await event.respond("There is no interrupted export to resume.")
            return
        job = ctx.checkpoint.load_job()
        progress = await create_progress(ctx, job.chat.name)
        jobs.start(job.chat.name, progress, lambda: run_job(ctx, job, progress, resume=True))

    @bot.on(events.NewMessage(pattern=r"^/discard(@\w+)?$", func=is_owner_msg))
    async def cmd_discard(event: events.NewMessage.Event) -> None:
        if jobs.busy:
            await event.respond("Stop the running export first (/cancel).")
            return
        name = discard_unfinished(ctx)
        await event.respond(f"Deleted the unfinished export of {name}." if name else "Nothing to discard.")

    @bot.on(events.NewMessage(func=lambda e: is_owner_msg(e) and not (e.raw_text or "").startswith("/")))
    async def on_text(event: events.NewMessage.Event) -> None:
        if state.awaiting_search:
            state.awaiting_search = False
            await run_search(event, event.raw_text or "")
            return
        if not state.awaiting_dates:
            await event.respond("Send /chats to pick a chat, or /help.")
            return
        try:
            start, end = parse_custom_range(event.raw_text or "")
        except ValueError as exc:
            await event.respond(f"⚠️ {exc}\nTry again, or /cancel.")
            return
        state.awaiting_dates = False
        state.options.date_preset, state.options.date_from, state.options.date_to = "custom", start, end
        if state.selected:
            await event.respond(options_text(state.selected, state.options), buttons=options_keyboard(state.options))

    # ---- callbacks ------------------------------------------------------

    @bot.on(events.CallbackQuery(func=is_owner_cb))
    async def on_callback(event: events.CallbackQuery.Event) -> None:
        data = event.data.decode(errors="ignore")
        try:
            await dispatch(event, data)
        except Exception:  # noqa: BLE001
            log.exception("callback failed", extra={"data": data})
            await event.answer("Something went wrong — check the logs.", alert=True)

    async def show_options(event: events.CallbackQuery.Event) -> None:
        assert state.selected is not None
        await event.edit(options_text(state.selected, state.options), buttons=options_keyboard(state.options))

    async def dispatch(event: events.CallbackQuery.Event, data: str) -> None:
        if data == "noop":
            await event.answer()
            return
        if data.startswith("pg:"):
            if not state.listing:
                await load_dialogs()
                state.listing = state.dialogs
            await event.edit(list_text(), buttons=dialogs_keyboard(state.listing, int(data[3:])))
            return
        if data.startswith("sel:"):
            peer_id = int(data[4:])
            item = state.find(peer_id)
            if item is None:
                entity = await flood_retry(lambda: ctx.user.get_entity(peer_id))
                item = DialogItem(peer_id, utils.get_display_name(entity), _dialog_kind(entity), entity=entity)
            state.selected = item
            state.awaiting_dates = False
            await show_options(event)
            await event.answer()
            return
        if data == "stop":
            if jobs.busy:
                await event.answer("Stopping…")
                await jobs.cancel()
            else:
                await event.answer("No export is running.")
            return

        if state.selected is None:
            await event.answer("Pick a chat first with /chats.", alert=True)
            return
        opts = state.options

        if data.startswith("t:") and data[2:] in MEDIA_OPTION_KEYS:
            key = data[2:]
            opts.media[key] = not opts.media.get(key, False)
            await show_options(event)
        elif data.startswith("sz:"):
            value = None if data[3:] == "none" else int(data[3:])
            if value in SIZE_LIMITS_MB:
                opts.size_limit_mb = value
            await show_options(event)
        elif data.startswith("dt:"):
            preset = data[3:]
            if preset == "custom":
                state.awaiting_dates = True
                state.awaiting_search = False
                await event.answer()
                await event.respond(
                    "Send the date range as `YYYY-MM-DD YYYY-MM-DD` (both inclusive), "
                    "e.g. `2024-01-01 2024-03-31`. /cancel to abort."
                )
                return
            opts.date_preset, opts.date_from, opts.date_to = preset, None, None
            await show_options(event)
        elif data.startswith("fmt:"):
            opts.format = data[4:]
            await show_options(event)
        elif data == "cx":
            state.selected = None
            state.awaiting_dates = False
            await event.edit("Export cancelled. /chats to pick another chat.")
        elif data == "go":
            await start_export(event)  # answers the callback itself
            return
        await event.answer()

    async def start_export(event: events.CallbackQuery.Event) -> None:
        if jobs.busy:
            await event.answer("An export is already running — wait for it or /cancel it.", alert=True)
            return
        if ctx.checkpoint.exists():
            await event.answer("There is an unfinished export. Use /resume or /discard first.", alert=True)
            return
        assert state.selected is not None
        selected = state.selected
        entity = selected.entity or await flood_retry(lambda: ctx.user.get_entity(selected.peer_id))
        me = await ctx.user.get_me()
        info = chat_info(entity, me.id if me else None)
        if selected.kind == "saved":
            info.name = "Saved Messages"
        job = JobSpec(
            chat=info,
            options=state.options.from_dict(state.options.to_dict()),
            output_dir=str(new_output_dir(cfg.export_dir)),
            created_at=int(time.time()),
        )
        ctx.checkpoint.start(job)
        await event.edit(options_text(selected, job.options) + "\n\n▶️ Export started.")
        progress = await create_progress(ctx, info.name)
        jobs.start(info.name, progress, lambda: run_job(ctx, job, progress, resume=False))
        await event.answer("Export started")
        log.info("export started", extra={"chat": info.name, "options": job.options.to_dict()})
