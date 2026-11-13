"""In-memory UI state for the owner and the single-job manager."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..export.models import ExportOptions
from ..utils.progress import Progress

log = logging.getLogger(__name__)

DIALOG_CACHE_SECONDS = 300


@dataclass
class DialogItem:
    peer_id: int
    name: str
    kind: str  # "private" | "bot" | "group" | "channel" | "saved"
    username: str | None = None
    entity: Any = None


@dataclass
class UiState:
    dialogs: list[DialogItem] = field(default_factory=list)
    dialogs_fetched_at: float = 0.0
    listing: list[DialogItem] = field(default_factory=list)
    listing_title: str = "Your chats"
    selected: DialogItem | None = None
    options: ExportOptions = field(default_factory=ExportOptions)
    awaiting_dates: bool = False

    def dialogs_fresh(self) -> bool:
        return bool(self.dialogs) and time.monotonic() - self.dialogs_fetched_at < DIALOG_CACHE_SECONDS

    def find(self, peer_id: int) -> DialogItem | None:
        for item in self.listing + self.dialogs:
            if item.peer_id == peer_id:
                return item
        return None

    def search(self, query: str) -> list[DialogItem]:
        q = query.strip().lstrip("@").casefold()
        if not q:
            return []
        return [
            d for d in self.dialogs
            if q in d.name.casefold() or (d.username and q in d.username.casefold())
        ]


class JobManager:
    """Runs at most one export at a time."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.progress: Progress | None = None
        self.chat_name: str | None = None

    @property
    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, chat_name: str, progress: Progress, coro_factory: Callable[[], Awaitable[None]]) -> bool:
        if self.busy:
            return False
        self.chat_name = chat_name
        self.progress = progress

        async def runner() -> None:
            try:
                await coro_factory()
            finally:
                log.info("job finished", extra={"chat": chat_name})

        self.task = asyncio.create_task(runner(), name=f"export:{chat_name}")
        return True

    async def cancel(self) -> bool:
        if not self.busy:
            return False
        assert self.task is not None
        self.task.cancel()
        try:
            await self.task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001 - the runner reports its own errors
            pass
        return True
