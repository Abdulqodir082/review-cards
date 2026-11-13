import json
from datetime import timezone
from zoneinfo import ZoneInfo

from app.export.entities import to_desktop_entities, to_desktop_text
from app.export.json_writer import message_to_json, write_json
from app.export.models import Media

from .conftest import make_msg


def test_top_level_schema(tmp_path, chat, sample_messages):
    path = write_json(tmp_path, chat, sample_messages)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["name", "type", "id", "messages"]
    assert data["name"] == "Test <Chat>"
    assert data["type"] == "personal_chat"
    assert data["id"] == 42
    assert [m["id"] for m in data["messages"]] == list(range(1, 11))
    assert not (tmp_path / "result.json.part").exists()


def test_empty_export_is_valid_json(tmp_path, chat):
    data = json.loads(write_json(tmp_path, chat, []).read_text(encoding="utf-8"))
    assert data["messages"] == []


def test_plain_message_fields():
    out = message_to_json(make_msg(5, text="hi"), timezone.utc)
    assert out["type"] == "message"
    assert out["date"] == "2024-03-01T10:00:00"
    assert out["date_unixtime"] == "1709287200"
    assert out["from"] == "Alice Smith"
    assert out["from_id"] == "user111"
    assert out["text"] == "hi"
    assert out["text_entities"] == [{"type": "plain", "text": "hi"}]
    for absent in ("edited", "reply_to_message_id", "forwarded_from", "via_bot", "photo", "file", "reactions"):
        assert absent not in out


def test_date_uses_configured_timezone():
    out = message_to_json(make_msg(1), ZoneInfo("Asia/Tashkent"))
    assert out["date"] == "2024-03-01T15:00:00"
    assert out["date_unixtime"] == "1709287200"


def test_mixed_text_array_for_entities():
    msg = make_msg(
        1,
        text="Hello bold and link",
        entities=[
            {"type": "bold", "offset": 6, "length": 4},
            {"type": "text_link", "offset": 15, "length": 4, "href": "https://example.com"},
        ],
    )
    out = message_to_json(msg)
    assert out["text"] == [
        "Hello ",
        {"type": "bold", "text": "bold"},
        " and ",
        {"type": "text_link", "text": "link", "href": "https://example.com"},
    ]
    assert out["text_entities"][1] == {"type": "bold", "text": "bold"}
    assert out["text_entities"][0] == {"type": "plain", "text": "Hello "}


def test_entities_use_utf16_offsets():
    # "😀" is two UTF-16 code units, so "bold" starts at offset 3, not 2.
    text = "😀 bold"
    ents = [{"type": "bold", "offset": 3, "length": 4}]
    assert to_desktop_text(text, ents) == ["😀 ", {"type": "bold", "text": "bold"}]


def test_pre_entity_keeps_language():
    items = to_desktop_entities("x = 1", [{"type": "pre", "offset": 0, "length": 5, "language": "python"}])
    assert items == [{"type": "pre", "text": "x = 1", "language": "python"}]


def test_reply_forward_via_bot_edited_reactions():
    msg = make_msg(
        9,
        reply_to_message_id=3,
        forwarded_from="News",
        via_bot="@gif",
        edited=1709290800,
        reactions=[{"type": "emoji", "count": 2, "emoji": "👍"}],
        author="Editor",
    )
    out = message_to_json(msg)
    assert out["reply_to_message_id"] == 3
    assert out["forwarded_from"] == "News"
    assert out["via_bot"] == "@gif"
    assert out["edited"] == "2024-03-01T11:00:00"
    assert out["edited_unixtime"] == "1709290800"
    assert out["reactions"] == [{"type": "emoji", "count": 2, "emoji": "👍"}]
    assert out["author"] == "Editor"


def test_photo_fields():
    msg = make_msg(4, media=Media(kind="photo", path="photos/p.jpg", width=800, height=600, size=1000))
    out = message_to_json(msg)
    assert out["photo"] == "photos/p.jpg"
    assert out["photo_file_size"] == 1000
    assert out["width"] == 800 and out["height"] == 600
    assert "media_type" not in out and "file" not in out


def test_video_and_sticker_fields():
    video = message_to_json(make_msg(
        1, media=Media(kind="video_file", path="video_files/v.mp4", thumbnail="video_files/v.mp4_thumb.jpg",
                       mime_type="video/mp4", duration=12, width=640, height=360, file_name="v.mp4", size=99),
    ))
    assert video["file"] == "video_files/v.mp4"
    assert video["thumbnail"] == "video_files/v.mp4_thumb.jpg"
    assert video["media_type"] == "video_file"
    assert video["mime_type"] == "video/mp4"
    assert video["duration_seconds"] == 12
    assert (video["width"], video["height"]) == (640, 360)

    sticker = message_to_json(make_msg(
        2, media=Media(kind="sticker", path="stickers/s.webp", sticker_emoji="😀", width=512, height=512),
    ))
    assert sticker["media_type"] == "sticker"
    assert sticker["sticker_emoji"] == "😀"

    plain_file = message_to_json(make_msg(3, media=Media(kind="file", path="files/a.pdf", file_name="a.pdf")))
    assert "media_type" not in plain_file
    assert plain_file["file_name"] == "a.pdf"


def test_skipped_media_placeholders():
    size = message_to_json(make_msg(1, media=Media(kind="video_file", skipped="size")))
    assert size["file"] == "(File exceeds maximum size. Change data exporting settings to download.)"
    off = message_to_json(make_msg(2, media=Media(kind="photo", skipped="type")))
    assert off["photo"] == "(File not included. Change data exporting settings to download.)"
    failed = message_to_json(make_msg(3, media=Media(kind="file", skipped="failed")))
    assert failed["file"].startswith("(File unavailable")


def test_poll_contact_location():
    poll = {"question": "Q", "closed": True, "total_voters": 1, "answers": [{"text": "A", "voters": 1, "chosen": True}]}
    assert message_to_json(make_msg(1, poll=poll))["poll"] == poll

    contact = {"first_name": "Ann", "last_name": "", "phone_number": "+1555"}
    assert message_to_json(make_msg(2, contact=contact))["contact_information"] == contact

    loc = message_to_json(make_msg(
        3, location={"latitude": 41.3, "longitude": 69.2, "live_period": 900},
        venue={"title": "Cafe", "address": "Main st"},
    ))
    assert loc["location_information"] == {"latitude": 41.3, "longitude": 69.2}
    assert loc["live_location_period_seconds"] == 900
    assert loc["place_name"] == "Cafe" and loc["address"] == "Main st"


def test_service_message():
    msg = make_msg(
        6, type="service", from_name=None, from_id=None, text="",
        action="invite_members", actor="Alice", actor_id="user1", action_data={"members": ["Bob"]},
    )
    out = message_to_json(msg)
    assert out["type"] == "service"
    assert out["actor"] == "Alice"
    assert out["actor_id"] == "user1"
    assert out["action"] == "invite_members"
    assert out["members"] == ["Bob"]
    assert out["text"] == "" and out["text_entities"] == []
    assert "from" not in out


def test_pin_service_message_id():
    msg = make_msg(7, type="service", action="pin_message", actor="A", actor_id="user1",
                   action_data={"message_id": 3}, text="")
    assert message_to_json(msg)["message_id"] == 3


def test_unicode_is_not_escaped(tmp_path, chat):
    path = write_json(tmp_path, chat, [make_msg(1, text="Привет 👋")])
    assert "Привет 👋" in path.read_text(encoding="utf-8")
