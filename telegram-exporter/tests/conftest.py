"""Fake message objects for writer tests (no Telegram connection needed)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.export.models import ChatInfo, ExportMessage, Media

BASE_TS = int(datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc).timestamp())


def make_msg(id: int, offset: int = 0, **kw) -> ExportMessage:
    defaults = dict(
        type="message",
        date=BASE_TS + offset,
        from_name="Alice Smith",
        from_id="user111",
        text=f"message {id}",
    )
    defaults.update(kw)
    return ExportMessage(id=id, **defaults)


@pytest.fixture
def chat() -> ChatInfo:
    return ChatInfo(id=42, peer_id=42, name="Test <Chat>", type="personal_chat")


@pytest.fixture
def sample_messages() -> list[ExportMessage]:
    return [
        make_msg(1, 0, text="Hello **world**", entities=[{"type": "bold", "offset": 6, "length": 9}]),
        make_msg(2, 60, text="joined to previous"),
        make_msg(3, 120, from_name="Bob", from_id="user222", text="reply", reply_to_message_id=1),
        make_msg(
            4, 180, from_name="Bob", from_id="user222", text="",
            media=Media(kind="photo", path="photos/photo_4@01-03-2024_10-03-00.jpg", width=1280, height=960, size=123456),
        ),
        make_msg(
            5, 240, text="big video",
            media=Media(kind="video_file", skipped="size", file_name="clip.mp4", mime_type="video/mp4",
                        size=900_000_000, duration=75, width=1920, height=1080),
        ),
        make_msg(
            6, 86400, type="service", from_name=None, from_id=None, text="",
            action="invite_members", actor="Alice Smith", actor_id="user111",
            action_data={"members": ["Carol"]},
        ),
        make_msg(7, 86460, forwarded_from="News Channel", text="forwarded text"),
        make_msg(
            8, 86520, text="",
            poll={"question": "Lunch?", "closed": False, "total_voters": 3,
                  "answers": [{"text": "Yes", "voters": 2, "chosen": True}, {"text": "No", "voters": 1, "chosen": False}]},
        ),
        make_msg(9, 86580, text="nice", reactions=[{"type": "emoji", "count": 2, "emoji": "👍"}], edited=BASE_TS + 90000),
        make_msg(
            10, 86640, text="voice",
            media=Media(kind="voice_message", path="voice_messages/audio_10.ogg", mime_type="audio/ogg", duration=5, size=2048),
        ),
    ]
