"""Inline keyboards for the bot UI."""
from __future__ import annotations

from telethon import Button

from ..export.models import (
    MEDIA_OPTION_KEYS,
    MEDIA_OPTION_LABELS,
    SIZE_LIMITS_MB,
    ExportOptions,
)
from .states import DialogItem

PAGE_SIZE = 10

ICONS = {"private": "👤", "bot": "🤖", "group": "👥", "channel": "📢", "saved": "⭐"}


def _short(text: str, limit: int = 40) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def dialogs_keyboard(items: list[DialogItem], page: int) -> list[list[Button]]:
    pages = max(1, -(-len(items) // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    rows = [
        [Button.inline(f"{ICONS.get(d.kind, '💬')} {_short(d.name)}", f"sel:{d.peer_id}".encode())]
        for d in items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    ]
    nav = []
    if page > 0:
        nav.append(Button.inline("◀ Prev", f"pg:{page - 1}".encode()))
    nav.append(Button.inline(f"{page + 1}/{pages}", b"noop"))
    if page + 1 < pages:
        nav.append(Button.inline("Next ▶", f"pg:{page + 1}".encode()))
    rows.append(nav)
    return rows


def _check(on: bool, label: str) -> str:
    return f"{'✅' if on else '▫️'} {label}"


def _radio(on: bool, label: str) -> str:
    return f"● {label}" if on else label


def options_keyboard(opts: ExportOptions) -> list[list[Button]]:
    media_buttons = [
        Button.inline(_check(opts.media.get(k, False), MEDIA_OPTION_LABELS[k]), f"t:{k}".encode())
        for k in MEDIA_OPTION_KEYS
    ]
    rows = [media_buttons[i : i + 2] for i in range(0, len(media_buttons), 2)]
    rows.append(
        [
            Button.inline(
                _radio(opts.size_limit_mb == mb, "No limit" if mb is None else f"{mb} MB"),
                f"sz:{'none' if mb is None else mb}".encode(),
            )
            for mb in SIZE_LIMITS_MB
        ]
    )
    rows.append(
        [
            Button.inline(_radio(opts.date_preset == "all", "All time"), b"dt:all"),
            Button.inline(_radio(opts.date_preset == "7d", "7 days"), b"dt:7d"),
            Button.inline(_radio(opts.date_preset == "30d", "30 days"), b"dt:30d"),
            Button.inline(_radio(opts.date_preset == "custom", "Custom…"), b"dt:custom"),
        ]
    )
    rows.append(
        [
            Button.inline(_radio(opts.format == "html", "HTML"), b"fmt:html"),
            Button.inline(_radio(opts.format == "json", "JSON"), b"fmt:json"),
            Button.inline(_radio(opts.format == "both", "Both"), b"fmt:both"),
        ]
    )
    rows.append([Button.inline("▶️ Start export", b"go"), Button.inline("✖️ Cancel", b"cx")])
    return rows


def options_text(item: DialogItem, opts: ExportOptions) -> str:
    media = [MEDIA_OPTION_LABELS[k] for k in MEDIA_OPTION_KEYS if opts.media.get(k)]
    fmt = {"html": "HTML", "json": "Machine-readable JSON", "both": "HTML + JSON"}[opts.format]
    return (
        f"{ICONS.get(item.kind, '💬')} **{item.name}**\n\n"
        f"**Media:** {', '.join(media) if media else 'text only'}\n"
        f"**Max file size:** {opts.describe_size()}\n"
        f"**Period:** {opts.describe_dates()}\n"
        f"**Format:** {fmt}\n\n"
        "Tap to toggle, then Start export."
    )


def stop_keyboard() -> list[list[Button]]:
    return [[Button.inline("⏹ Stop", b"stop")]]
