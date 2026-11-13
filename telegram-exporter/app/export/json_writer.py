"""Writes ``result.json`` using the same schema as Telegram Desktop."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .entities import to_desktop_entities, to_desktop_text
from .models import MEDIA_KINDS, SKIP_TEXT, ChatInfo, ExportMessage, Media


def _local_iso(ts: int, tz) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S")


def _placeholder(media: Media) -> str:
    return f"({SKIP_TEXT[media.skipped or 'failed']})"


def _media_fields(media: Media) -> dict[str, Any]:
    out: dict[str, Any] = {}
    location = media.path if media.path else _placeholder(media)
    if media.kind == "photo":
        out["photo"] = location
        if media.size is not None:
            out["photo_file_size"] = media.size
    else:
        out["file"] = location
        if media.file_name:
            out["file_name"] = media.file_name
        if media.size is not None:
            out["file_size"] = media.size
        if media.thumbnail:
            out["thumbnail"] = media.thumbnail
        media_type = MEDIA_KINDS.get(media.kind, (None,))[0]
        if media_type:
            out["media_type"] = media_type
        if media.sticker_emoji:
            out["sticker_emoji"] = media.sticker_emoji
        if media.performer:
            out["performer"] = media.performer
        if media.title:
            out["title"] = media.title
        if media.mime_type:
            out["mime_type"] = media.mime_type
        if media.duration is not None:
            out["duration_seconds"] = media.duration
    if media.width is not None:
        out["width"] = media.width
    if media.height is not None:
        out["height"] = media.height
    return out


def message_to_json(msg: ExportMessage, tz=timezone.utc) -> dict[str, Any]:
    """Convert one message into the dict Desktop writes into ``messages[]``."""
    out: dict[str, Any] = {
        "id": msg.id,
        "type": msg.type,
        "date": _local_iso(msg.date, tz),
        "date_unixtime": str(msg.date),
    }
    if msg.edited:
        out["edited"] = _local_iso(msg.edited, tz)
        out["edited_unixtime"] = str(msg.edited)

    if msg.type == "service":
        out["actor"] = msg.actor
        out["actor_id"] = msg.actor_id
        out["action"] = msg.action
        for key, value in msg.action_data.items():
            out[key] = value
        if msg.reply_to_message_id and "message_id" not in out:
            out["message_id"] = msg.reply_to_message_id
    else:
        out["from"] = msg.from_name
        out["from_id"] = msg.from_id
        if msg.author:
            out["author"] = msg.author
        if msg.forwarded_from:
            out["forwarded_from"] = msg.forwarded_from
        if msg.reply_to_message_id:
            out["reply_to_message_id"] = msg.reply_to_message_id
        if msg.via_bot:
            out["via_bot"] = msg.via_bot
        if msg.media:
            out.update(_media_fields(msg.media))
        if msg.poll:
            out["poll"] = msg.poll
        if msg.contact:
            out["contact_information"] = msg.contact
        if msg.venue:
            out["place_name"] = msg.venue.get("title", "")
            out["address"] = msg.venue.get("address", "")
        if msg.location:
            out["location_information"] = {
                "latitude": msg.location["latitude"],
                "longitude": msg.location["longitude"],
            }
            if msg.location.get("live_period"):
                out["live_location_period_seconds"] = msg.location["live_period"]
        if msg.dice:
            out["dice"] = msg.dice

    out["text"] = to_desktop_text(msg.text, msg.entities)
    out["text_entities"] = to_desktop_entities(msg.text, msg.entities)
    if msg.reactions:
        out["reactions"] = msg.reactions
    return out


def write_json(
    out_dir: Path,
    chat: ChatInfo,
    messages: Iterable[ExportMessage],
    tz=timezone.utc,
) -> Path:
    """Stream ``result.json`` to disk (messages are not all held in memory)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "result.json"
    tmp = path.with_suffix(".json.part")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write("{\n")
        fh.write(f' "name": {json.dumps(chat.name, ensure_ascii=False)},\n')
        fh.write(f' "type": {json.dumps(chat.type)},\n')
        fh.write(f' "id": {chat.id},\n')
        fh.write(' "messages": [')
        first = True
        for msg in messages:
            body = json.dumps(message_to_json(msg, tz), ensure_ascii=False, indent=1)
            body = "\n".join("  " + line for line in body.splitlines())
            fh.write(("\n" if first else ",\n") + body)
            first = False
        fh.write("\n ]\n}\n" if not first else "]\n}\n")
    tmp.replace(path)
    return path
