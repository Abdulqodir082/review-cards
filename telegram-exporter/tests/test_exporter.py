"""Runs the Exporter end to end against a fake Telethon client built from real TL objects."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import errors
from telethon.tl import types

from app.config import Config
from app.export.checkpoint import Checkpoint, JobSpec
from app.export.exporter import Exporter, classify_media, convert_entities
from app.export.models import ChatInfo, ExportOptions
from app.utils.progress import Progress

T0 = datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc)
PEER = types.PeerUser(555)
ALICE = types.User(id=555, first_name="Alice", last_name="Smith", access_hash=1)


def _doc(attrs, size=1000, mime="application/octet-stream", thumbs=None):
    return types.MessageMediaDocument(
        document=types.Document(
            id=1, access_hash=1, file_reference=b"", date=T0, mime_type=mime, size=size,
            dc_id=2, attributes=attrs, thumbs=thumbs,
        )
    )


def _photo():
    return types.MessageMediaPhoto(
        photo=types.Photo(
            id=2, access_hash=1, file_reference=b"", date=T0, dc_id=2,
            sizes=[types.PhotoSize(type="x", w=1280, h=960, size=5000)],
        )
    )


def _msg(id, minutes, text="", media=None, **kw):
    m = types.Message(id=id, peer_id=PEER, date=T0 + timedelta(minutes=minutes), message=text,
                      media=media, from_id=PEER, **kw)
    m._sender = ALICE
    return m


class FakeClient:
    def __init__(self, messages, flood_once=False, fail_media_ids=()):
        self.messages = messages
        self.flood_once = flood_once
        self.fail_media_ids = set(fail_media_ids)
        self.download_calls = 0
        self.iter_kwargs = []

    async def get_entity(self, peer):
        return ALICE

    async def get_messages(self, entity, limit=None, ids=None):
        if ids is not None:
            return next(m for m in self.messages if m.id == ids)

        class R:
            total = len(self.messages)
        return R()

    def iter_messages(self, entity, reverse=True, min_id=0, offset_date=None, wait_time=0):
        self.iter_kwargs.append({"min_id": min_id, "offset_date": offset_date})
        client = self

        async def gen():
            for m in client.messages:
                if m.id <= min_id or (offset_date and m.date <= offset_date):
                    continue
                if client.flood_once and m.id == 3:
                    client.flood_once = False
                    raise errors.FloodWaitError(request=None, capture=0)
                yield m
        return gen()

    async def download_media(self, msg, file, thumb=None):
        self.download_calls += 1
        if msg.id in self.fail_media_ids:
            raise ConnectionError("boom")
        Path(file).write_bytes(b"data" * 10)
        return file


def _cfg(tmp_path):
    return Config(
        api_id=1, api_hash="x", bot_token="t", owner_id=1, export_dir=tmp_path, session_dir=tmp_path,
        max_part_size_mb=10, keep_exports=False, log_dir=tmp_path, log_level="INFO", timezone=timezone.utc,
    )


def _messages():
    return [
        _msg(1, 0, "Hello bold", entities=[types.MessageEntityBold(offset=6, length=4)]),
        _msg(2, 1, media=_photo()),
        _msg(3, 2, "voice", media=_doc([types.DocumentAttributeAudio(duration=3, voice=True)], mime="audio/ogg")),
        _msg(4, 3, "huge", media=_doc([types.DocumentAttributeFilename("big.iso")], size=10**9)),
        _msg(5, 4, "sticker", media=_doc([types.DocumentAttributeSticker(alt="😀", stickerset=types.InputStickerSetEmpty()),
                                          types.DocumentAttributeFilename("s.webp")], mime="image/webp")),
        _msg(6, 5, "reply", reply_to=types.MessageReplyHeader(reply_to_msg_id=1)),
        types.MessageService(id=7, peer_id=PEER, date=T0 + timedelta(minutes=6), from_id=PEER,
                             action=types.MessageActionScreenshotTaken()),
    ]


def _run(tmp_path, client, options, resume=False, job=None):
    cfg = _cfg(tmp_path)
    cp = Checkpoint(cfg.state_dir)
    if job is None:
        job = JobSpec(ChatInfo(555, 555, "Alice Smith", "personal_chat"), options, str(tmp_path / "ChatExport_2024-03-01"), 0)
        cp.start(job)
    progress = Progress("Alice", None)
    out = asyncio.run(Exporter(client, cfg, cp, progress).run(job, resume=resume))
    return out, progress, cp, job


def test_classify_media():
    assert classify_media(_msg(1, 0, media=_photo())) == "photo"
    assert classify_media(_msg(1, 0, media=_doc([types.DocumentAttributeVideo(duration=1, w=1, h=1, round_message=True)]))) == "video_message"
    assert classify_media(_msg(1, 0, media=_doc([types.DocumentAttributeAnimated(), types.DocumentAttributeVideo(duration=1, w=1, h=1)]))) == "animation"
    assert classify_media(_msg(1, 0, media=_doc([types.DocumentAttributeAudio(duration=1, title="t")]))) == "audio_file"
    assert classify_media(_msg(1, 0)) is None


def test_convert_entities():
    ents = convert_entities([
        types.MessageEntityTextUrl(offset=0, length=3, url="https://a.b"),
        types.MessageEntityPre(offset=4, length=2, language="py"),
        types.MessageEntityMentionName(offset=7, length=2, user_id=9),
    ])
    assert ents[0] == {"type": "text_link", "offset": 0, "length": 3, "href": "https://a.b"}
    assert ents[1]["language"] == "py"
    assert ents[2]["user_id"] == 9


def test_full_export(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    client = FakeClient(_messages(), flood_once=True)
    out, progress, cp, _ = _run(tmp_path, client, ExportOptions(size_limit_mb=8))

    data = json.loads((out / "result.json").read_text())
    msgs = {m["id"]: m for m in data["messages"]}
    assert len(msgs) == 7
    assert msgs[1]["text"] == ["Hello ", {"type": "bold", "text": "bold"}]
    assert msgs[1]["from"] == "Alice Smith" and msgs[1]["from_id"] == "user555"
    assert msgs[2]["photo"].startswith("photos/photo_2@01-03-2024_10-01-00") and msgs[2]["width"] == 1280
    assert msgs[3]["media_type"] == "voice_message" and msgs[3]["file"].startswith("voice_messages/")
    assert msgs[4]["file"] == "(File exceeds maximum size. Change data exporting settings to download.)"
    assert msgs[5]["sticker_emoji"] == "😀" and msgs[5]["file"].startswith("stickers/")
    assert msgs[6]["reply_to_message_id"] == 1
    assert msgs[7]["type"] == "service" and msgs[7]["action"] == "take_screenshot"
    assert (out / msgs[2]["photo"]).exists()
    assert (out / "messages.html").exists() and (out / "css" / "style.css").exists()
    assert progress.processed == 7
    assert progress.media_downloaded == 3 and progress.media_skipped == 1
    # flood wait restarted the iterator after message 2
    assert client.iter_kwargs[1]["min_id"] == 2


def test_disabled_type_and_failed_download(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    opts = ExportOptions()
    opts.media["photos"] = False
    client = FakeClient(_messages(), fail_media_ids={3})
    out, progress, _, _ = _run(tmp_path, client, opts)
    msgs = {m["id"]: m for m in json.loads((out / "result.json").read_text())["messages"]}
    assert msgs[2]["photo"] == "(File not included. Change data exporting settings to download.)"
    assert msgs[3]["file"].startswith("(File unavailable")
    assert progress.media_failed == 1
    assert not list((out / "voice_messages").glob("*.part"))


def test_resume_continues_after_last_record(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    all_msgs = _messages()
    first = FakeClient(all_msgs[:3])
    out, _, cp, job = _run(tmp_path, first, ExportOptions(format="json"))
    assert cp.summary() == (3, 3)

    second = FakeClient(all_msgs)
    out, progress, cp, _ = _run(tmp_path, second, job.options, resume=True, job=job)
    assert second.iter_kwargs[0]["min_id"] == 3
    ids = [m["id"] for m in json.loads((out / "result.json").read_text())["messages"]]
    assert ids == [1, 2, 3, 4, 5, 6, 7]
    assert progress.processed == 7
    assert not (out / "messages.html").exists()  # JSON-only export


def test_date_range_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    opts = ExportOptions(date_preset="custom", date_from="2024-03-01", date_to="2024-03-01")
    msgs = _messages() + [_msg(8, 60 * 24, "next day")]
    client = FakeClient(msgs)
    out, _, _, _ = _run(tmp_path, client, opts)
    ids = [m["id"] for m in json.loads((out / "result.json").read_text())["messages"]]
    assert ids == [1, 2, 3, 4, 5, 6, 7]


_real_sleep = asyncio.sleep


async def _no_sleep(seconds, *a, **k):
    await _real_sleep(0)
