"""Runs one export end to end: fetch → write → zip → upload → clean up."""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from telethon import TelegramClient, errors

from ..config import Config
from ..export.checkpoint import Checkpoint, JobSpec
from ..export.exporter import Exporter
from ..utils.fmt import human_size
from ..utils.progress import Progress
from ..utils.zipper import make_archive
from .keyboards import stop_keyboard
from .states import JobManager, UiState

log = logging.getLogger(__name__)


@dataclass
class BotContext:
    bot: TelegramClient
    user: TelegramClient
    cfg: Config
    state: UiState
    jobs: JobManager
    checkpoint: Checkpoint


async def create_progress(ctx: BotContext, title: str) -> Progress:
    message = await ctx.bot.send_message(ctx.cfg.owner_id, f"📦 Preparing export of {title}…", buttons=stop_keyboard())

    async def edit(text: str, stop_button: bool) -> None:
        try:
            await ctx.bot.edit_message(
                ctx.cfg.owner_id, message.id, text, buttons=stop_keyboard() if stop_button else None
            )
        except errors.MessageNotModifiedError:
            pass

    return Progress(title, edit)


async def _send_parts(ctx: BotContext, parts: list[Path], progress: Progress, chat_name: str) -> None:
    total = len(parts)
    for index, part in enumerate(parts, start=1):
        loop = asyncio.get_running_loop()
        last = [0.0]

        def on_upload(sent: int, size: int, index: int = index) -> None:
            progress.upload = (index, total, sent / size if size else 1.0)
            now = time.monotonic()
            if now - last[0] >= progress.min_interval:
                last[0] = now
                loop.create_task(progress.update())

        caption = f"{chat_name} — part {index}/{total}" if total > 1 else chat_name
        if index == 1 and total > 1:
            caption += (
                "\nMulti-part archive: download all parts and open the .001 file with "
                "7-Zip / ZArchiver, or run: cat *.zip.0* > export.zip"
            )
        for attempt in range(5):
            try:
                await ctx.bot.send_file(
                    ctx.cfg.owner_id, str(part), caption=caption, force_document=True, progress_callback=on_upload
                )
                break
            except errors.FloodWaitError as exc:
                progress.waiting = int(exc.seconds) + 1
                await progress.update(force=True)
                await asyncio.sleep(progress.waiting)
                progress.waiting = 0
        else:
            raise RuntimeError(f"could not upload {part.name}")
    progress.upload = None


def _cleanup(ctx: BotContext, out_dir: Path, parts: list[Path]) -> None:
    ctx.checkpoint.clear()
    if ctx.cfg.keep_exports:
        return
    for part in parts:
        part.unlink(missing_ok=True)
    shutil.rmtree(out_dir, ignore_errors=True)


async def run_job(ctx: BotContext, job: JobSpec, progress: Progress, resume: bool) -> None:
    started = time.monotonic()
    exporter = Exporter(ctx.user, ctx.cfg, ctx.checkpoint, progress)
    parts: list[Path] = []
    try:
        out_dir = await exporter.run(job, resume=resume)

        progress.phase = "Zipping"
        await progress.update(force=True)
        parts = await asyncio.to_thread(make_archive, out_dir, ctx.cfg.export_dir, ctx.cfg.max_part_size_bytes)
        archive_size = sum(p.stat().st_size for p in parts)

        progress.phase = "Uploading"
        await progress.update(force=True)
        await _send_parts(ctx, parts, progress, job.chat.name)

        elapsed = int(time.monotonic() - started)
        summary = (
            f"✅ Export of {job.chat.name} finished in {elapsed // 60}m {elapsed % 60}s\n"
            f"Messages: {progress.processed:,}\n"
            f"Media: {progress.media_downloaded:,} downloaded, {progress.media_skipped:,} skipped, "
            f"{progress.media_failed:,} failed\n"
            f"Archive: {human_size(archive_size)} in {len(parts)} file(s)"
        )
        if ctx.cfg.keep_exports:
            summary += f"\nKept on server: {out_dir}"
        _cleanup(ctx, out_dir, parts)
        await progress.finish(summary)
        log.info("job done", extra={"chat": job.chat.name, "messages": progress.processed, "seconds": elapsed})
    except asyncio.CancelledError:
        log.info("job stopped by owner", extra={"chat": job.chat.name})
        ctx.checkpoint.close()
        for part in parts:
            part.unlink(missing_ok=True)
        await progress.finish(
            f"⏹ Export of {job.chat.name} stopped after {progress.processed:,} messages.\n"
            "/resume to continue, /discard to delete the partial export."
        )
        raise
    except Exception as exc:  # noqa: BLE001 - reported to the owner, checkpoint kept
        log.exception("job failed", extra={"chat": job.chat.name})
        ctx.checkpoint.close()
        await progress.finish(
            f"❌ Export of {job.chat.name} failed: {exc!r}\n"
            "Progress is saved — /resume to retry, /discard to drop it."
        )


def discard_unfinished(ctx: BotContext) -> str | None:
    """Delete the checkpoint and partial output. Returns the chat name, if any."""
    if not ctx.checkpoint.exists():
        return None
    try:
        job = ctx.checkpoint.load_job()
        name = job.chat.name
        shutil.rmtree(job.output_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001 - corrupted state is discarded anyway
        name = "unknown chat"
    ctx.checkpoint.clear()
    return name
