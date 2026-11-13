"""Tests for the non-network helpers: zipper, checkpoint, options, progress."""
import asyncio
import zipfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.export.checkpoint import Checkpoint, JobSpec, RecordStore
from app.export.models import ChatInfo, ExportOptions, Media, parse_custom_range
from app.utils.progress import Progress
from app.utils.zipper import make_archive, split_file

from .conftest import make_msg


def test_make_archive_single(tmp_path):
    src = tmp_path / "ChatExport_2024-03-01"
    (src / "photos").mkdir(parents=True)
    (src / "messages.html").write_text("<html></html>")
    (src / "photos" / "a.jpg").write_bytes(b"x" * 100)
    (src / "photos" / "partial.jpg.part").write_bytes(b"x")
    parts = make_archive(src, tmp_path / "out", 10 * 1024 * 1024)
    assert len(parts) == 1 and parts[0].suffix == ".zip"
    with zipfile.ZipFile(parts[0]) as zf:
        names = sorted(zf.namelist())
    assert names == ["ChatExport_2024-03-01/messages.html", "ChatExport_2024-03-01/photos/a.jpg"]


def test_split_and_rejoin(tmp_path):
    src = tmp_path / "ChatExport_x"
    src.mkdir()
    import os
    (src / "big.bin").write_bytes(os.urandom(250_000))
    parts = make_archive(src, tmp_path / "out", 100_000)
    assert [p.name for p in parts] == ["ChatExport_x.zip.001", "ChatExport_x.zip.002", "ChatExport_x.zip.003"]
    assert all(p.stat().st_size <= 100_000 for p in parts)
    joined = tmp_path / "joined.zip"
    joined.write_bytes(b"".join(p.read_bytes() for p in parts))
    with zipfile.ZipFile(joined) as zf:
        assert zf.read("ChatExport_x/big.bin") == (src / "big.bin").read_bytes()


def test_split_exact_multiple(tmp_path):
    f = tmp_path / "a.zip"
    f.write_bytes(b"x" * 300)
    parts = split_file(f, 100)
    assert len(parts) == 3 and not f.exists()


def test_checkpoint_roundtrip_and_torn_line(tmp_path):
    cp = Checkpoint(tmp_path / ".state")
    job = JobSpec(ChatInfo(1, 1, "Chat", "personal_chat"), ExportOptions(), str(tmp_path / "out"), 0)
    cp.start(job)
    cp.append(make_msg(1, media=Media(kind="photo", path="photos/a.jpg")))
    cp.append(make_msg(2))
    cp.close()
    with cp.records_path.open("a") as fh:
        fh.write('{"id": 3, "type": "mess')  # simulated crash mid-write
    cp.repair()
    records = list(RecordStore(cp))
    assert [r.id for r in records] == [1, 2]
    assert records[0].media.path == "photos/a.jpg"
    assert cp.summary() == (2, 2)
    assert cp.load_job().chat.name == "Chat"
    cp.clear()
    assert not cp.exists()


def test_parse_custom_range():
    assert parse_custom_range("2024-01-01 2024-02-01") == ("2024-01-01", "2024-02-01")
    with pytest.raises(ValueError):
        parse_custom_range("2024-02-01 2024-01-01")
    with pytest.raises(ValueError):
        parse_custom_range("yesterday")


def test_date_range_custom_is_inclusive_in_local_tz():
    opts = ExportOptions(date_preset="custom", date_from="2024-01-01", date_to="2024-01-31")
    start, end = opts.date_range(ZoneInfo("Asia/Tashkent"))
    assert start == datetime(2023, 12, 31, 19, 0, tzinfo=timezone.utc)
    assert end == datetime(2024, 1, 31, 19, 0, tzinfo=timezone.utc)
    now = datetime(2024, 5, 10, tzinfo=timezone.utc)
    assert ExportOptions(date_preset="7d").date_range(timezone.utc, now)[0] == datetime(2024, 5, 3, tzinfo=timezone.utc)
    assert ExportOptions().date_range(timezone.utc) == (None, None)


def test_progress_is_throttled():
    edits = []

    async def edit(text, stop):
        edits.append((text, stop))

    async def scenario():
        p = Progress("Chat", edit, min_interval=0.2)
        await p.update()
        p.processed = 5
        await p.update()  # within the interval: skipped
        assert len(edits) == 1
        await asyncio.sleep(0.25)
        await p.update()
        assert len(edits) == 2 and "Messages: 5" in edits[-1][0]
        p.waiting = 30
        await p.update(force=True)  # waits for the window instead of skipping
        assert "waiting 30s (Telegram rate limit)" in edits[-1][0]
        await p.finish("done")
        assert edits[-1] == ("done", False)

    asyncio.run(scenario())
