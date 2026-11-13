"""Small formatting helpers shared by the writers and the bot."""
from __future__ import annotations

from datetime import datetime

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def human_size(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def duration(seconds: int | None) -> str:
    seconds = int(seconds or 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def day_title(dt: datetime) -> str:
    """'13 November 2026' — the date separator used by Telegram Desktop."""
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def utc_offset(dt: datetime) -> str:
    offset = dt.utcoffset()
    total = int(offset.total_seconds()) if offset else 0
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"UTC{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def full_datetime(dt: datetime) -> str:
    """'13.11.2026 17:46:00 UTC+03:00' — tooltip format of Desktop."""
    return f"{dt:%d.%m.%Y %H:%M:%S} {utc_offset(dt)}"


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[1][0]).upper()
