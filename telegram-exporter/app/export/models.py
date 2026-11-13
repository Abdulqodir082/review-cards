"""Telethon-independent data model shared by the exporter and the writers.

The exporter converts every Telethon message into an :class:`ExportMessage`
and appends it to a JSONL checkpoint file.  The JSON and HTML writers only
ever see these objects, which keeps them deterministic and unit-testable.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# --- media ---------------------------------------------------------------

# media "kind" -> (Desktop media_type value or None, output sub-folder, option key)
MEDIA_KINDS: dict[str, tuple[str | None, str, str]] = {
    "photo": (None, "photos", "photos"),
    "video_file": ("video_file", "video_files", "videos"),
    "voice_message": ("voice_message", "voice_messages", "voice"),
    "video_message": ("video_message", "round_video_messages", "round"),
    "sticker": ("sticker", "stickers", "stickers"),
    "animation": ("animation", "video_files", "gifs"),
    "audio_file": ("audio_file", "files", "files"),
    "file": (None, "files", "files"),
}

SKIP_SIZE = "size"
SKIP_TYPE = "type"
SKIP_FAILED = "failed"

# Exact wording used by Telegram Desktop for media that was not downloaded.
SKIP_TEXT = {
    SKIP_SIZE: "File exceeds maximum size. Change data exporting settings to download.",
    SKIP_TYPE: "File not included. Change data exporting settings to download.",
    SKIP_FAILED: "File unavailable, please try again later",
}


@dataclass
class Media:
    kind: str
    path: str | None = None  # relative to the export folder, "/" separators
    skipped: str | None = None  # SKIP_SIZE / SKIP_TYPE / SKIP_FAILED
    thumbnail: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    size: int | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    sticker_emoji: str | None = None
    performer: str | None = None
    title: str | None = None


@dataclass
class ExportMessage:
    id: int
    type: str  # "message" | "service"
    date: int  # unix timestamp (UTC)
    edited: int | None = None
    from_name: str | None = None
    from_id: str | None = None  # "user123" / "channel123" / "chat123"
    author: str | None = None  # signed channel posts
    text: str = ""
    entities: list[dict[str, Any]] = field(default_factory=list)
    reply_to_message_id: int | None = None
    forwarded_from: str | None = None
    via_bot: str | None = None
    media: Media | None = None
    poll: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    venue: dict[str, Any] | None = None
    dice: dict[str, Any] | None = None
    # service messages
    action: str | None = None
    actor: str | None = None
    actor_id: str | None = None
    action_data: dict[str, Any] = field(default_factory=dict)
    reactions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportMessage":
        data = dict(data)
        media = data.pop("media", None)
        msg = cls(**data)
        if media:
            msg.media = Media(**media)
        return msg


# --- chat + options ------------------------------------------------------

@dataclass
class ChatInfo:
    id: int  # bare id, as Desktop writes it
    peer_id: int  # Telethon "marked" id used to resolve the entity again
    name: str
    type: str  # Desktop chat type, e.g. "personal_chat", "public_channel"


MEDIA_OPTION_KEYS = ["photos", "videos", "voice", "round", "stickers", "gifs", "files"]
MEDIA_OPTION_LABELS = {
    "photos": "Photos",
    "videos": "Videos",
    "voice": "Voice messages",
    "round": "Video messages",
    "stickers": "Stickers",
    "gifs": "GIFs",
    "files": "Files",
}
SIZE_LIMITS_MB: list[int | None] = [8, 50, 500, None]
DATE_PRESETS = ["all", "7d", "30d", "custom"]
FORMATS = ["html", "json", "both"]


@dataclass
class ExportOptions:
    media: dict[str, bool] = field(default_factory=lambda: {k: True for k in MEDIA_OPTION_KEYS})
    size_limit_mb: int | None = 50
    date_preset: str = "all"
    date_from: str | None = None  # YYYY-MM-DD, only for "custom"
    date_to: str | None = None
    format: str = "both"

    @property
    def size_limit_bytes(self) -> int | None:
        return None if self.size_limit_mb is None else self.size_limit_mb * 1024 * 1024

    @property
    def write_html(self) -> bool:
        return self.format in ("html", "both")

    @property
    def write_json(self) -> bool:
        return self.format in ("json", "both")

    def date_range(self, tz: ZoneInfo, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
        """Return (start, end) as aware UTC datetimes; ``None`` means unbounded."""
        now = now or datetime.now(timezone.utc)
        if self.date_preset == "7d":
            return now - timedelta(days=7), None
        if self.date_preset == "30d":
            return now - timedelta(days=30), None
        if self.date_preset == "custom" and self.date_from and self.date_to:
            start_d = date.fromisoformat(self.date_from)
            end_d = date.fromisoformat(self.date_to)
            start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=tz)
            end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz) + timedelta(days=1)
            return start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        return None, None

    def describe_dates(self) -> str:
        return {
            "all": "All time",
            "7d": "Last 7 days",
            "30d": "Last 30 days",
        }.get(self.date_preset) or f"{self.date_from} → {self.date_to}"

    def describe_size(self) -> str:
        return "No limit" if self.size_limit_mb is None else f"{self.size_limit_mb} MB"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExportOptions":
        return cls(**data)


def parse_custom_range(text: str) -> tuple[str, str]:
    """Parse 'YYYY-MM-DD YYYY-MM-DD'. Raises ValueError with a friendly message."""
    parts = text.replace("—", " ").replace("–", " ").split()
    if len(parts) != 2:
        raise ValueError("Send exactly two dates: YYYY-MM-DD YYYY-MM-DD")
    try:
        start, end = date.fromisoformat(parts[0]), date.fromisoformat(parts[1])
    except ValueError:
        raise ValueError("Dates must look like 2024-01-31") from None
    if start > end:
        raise ValueError("The start date must not be after the end date")
    return start.isoformat(), end.isoformat()
