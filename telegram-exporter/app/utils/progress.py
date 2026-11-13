"""Throttled progress reporting into a single editable bot message."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from .fmt import human_size

log = logging.getLogger(__name__)

EditFunc = Callable[[str, bool], Awaitable[None]]  # (text, show_stop_button)


class Progress:
    def __init__(self, title: str, edit: EditFunc | None = None, min_interval: float = 3.0):
        self.title = title
        self._edit = edit
        self.min_interval = min_interval
        self.phase = "Starting"
        self.processed = 0
        self.total: int | None = None
        self.media_downloaded = 0
        self.media_skipped = 0
        self.media_failed = 0
        self.bytes = 0
        self.waiting = 0  # seconds left of a Telegram flood wait
        self.upload: tuple[int, int, float] | None = None  # (part, parts, fraction)
        self._last_edit = 0.0
        self._last_text = ""
        self._lock = asyncio.Lock()
        self.finished = False

    def render(self) -> str:
        lines = [f"📦 Exporting: {self.title}", f"Stage: {self.phase}"]
        if self.total:
            pct = min(100, int(self.processed * 100 / self.total)) if self.total else 0
            lines.append(f"Messages: {self.processed:,} / ~{self.total:,} ({pct}%)")
        else:
            lines.append(f"Messages: {self.processed:,}")
        media = f"Media: {self.media_downloaded:,} downloaded"
        if self.media_skipped:
            media += f", {self.media_skipped:,} skipped"
        if self.media_failed:
            media += f", {self.media_failed:,} failed"
        lines.append(media)
        lines.append(f"Size: {human_size(self.bytes)}")
        if self.upload:
            part, parts, frac = self.upload
            lines.append(f"Uploading part {part}/{parts}: {int(frac * 100)}%")
        if self.waiting:
            lines.append(f"⏳ waiting {self.waiting}s (Telegram rate limit)")
        return "\n".join(lines)

    async def update(self, force: bool = False) -> None:
        """Edit the progress message if at least ``min_interval`` seconds passed.

        ``force`` bypasses the "nothing new" check but still never edits more often
        than every ``min_interval`` seconds — it waits for the window instead.
        """
        if self._edit is None or self.finished:
            return
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_edit)
        if wait > 0:
            if not force:
                return
            await asyncio.sleep(wait)
        async with self._lock:
            text = self.render()
            if text == self._last_text:
                return
            await self._safe_edit(text, True)

    async def finish(self, text: str) -> None:
        self.finished = True
        if self._edit is None:
            return
        wait = self.min_interval - (time.monotonic() - self._last_edit)
        if wait > 0:
            await asyncio.sleep(wait)
        async with self._lock:
            await self._safe_edit(text, False)

    async def _safe_edit(self, text: str, stop_button: bool) -> None:
        try:
            await self._edit(text, stop_button)  # type: ignore[misc]
            self._last_text = text
        except Exception as exc:  # noqa: BLE001 - progress must never break the export
            log.warning("progress edit failed", extra={"error": repr(exc)})
        finally:
            self._last_edit = time.monotonic()
