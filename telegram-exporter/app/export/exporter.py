"""Fetches chat history through the user client and downloads media."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from telethon import TelegramClient, errors, functions, utils
from telethon.tl import types

from ..config import Config
from ..utils.progress import Progress
from .checkpoint import Checkpoint, JobSpec, RecordStore
from .html_writer import write_html
from .json_writer import write_json
from .models import (
    MEDIA_KINDS,
    SKIP_FAILED,
    SKIP_SIZE,
    SKIP_TYPE,
    ChatInfo,
    ExportMessage,
    ExportOptions,
    Media,
)

log = logging.getLogger(__name__)

T = TypeVar("T")
DOWNLOAD_ATTEMPTS = 3


# --- generic flood-wait helper ------------------------------------------

async def flood_retry(
    func: Callable[[], Awaitable[T]],
    on_wait: Callable[[int], Awaitable[None]] | None = None,
    max_rounds: int = 10,
) -> T:
    """Run ``func`` and transparently sleep through FloodWaitError."""
    for _ in range(max_rounds):
        try:
            return await func()
        except errors.FloodWaitError as exc:
            seconds = int(exc.seconds) + 1
            log.warning("flood wait", extra={"seconds": seconds})
            if on_wait:
                await on_wait(seconds)
            else:
                await asyncio.sleep(seconds)
    return await func()


# --- chat helpers -------------------------------------------------------

def desktop_chat_type(entity: Any, me_id: int | None = None) -> str:
    if isinstance(entity, types.User):
        if entity.is_self or (me_id is not None and entity.id == me_id):
            return "saved_messages"
        return "bot_chat" if entity.bot else "personal_chat"
    if isinstance(entity, types.Chat):
        return "private_group"
    if isinstance(entity, types.Channel):
        public = bool(entity.username or getattr(entity, "usernames", None))
        if entity.megagroup or getattr(entity, "gigagroup", False):
            return "public_supergroup" if public else "private_supergroup"
        return "public_channel" if public else "private_channel"
    return "personal_chat"


def display_name(entity: Any) -> str:
    if entity is None:
        return "Deleted Account"
    if isinstance(entity, types.User) and entity.is_self:
        return utils.get_display_name(entity) or "Saved Messages"
    return utils.get_display_name(entity) or "Deleted Account"


def chat_info(entity: Any, me_id: int | None = None) -> ChatInfo:
    return ChatInfo(
        id=entity.id,
        peer_id=utils.get_peer_id(entity),
        name=display_name(entity),
        type=desktop_chat_type(entity, me_id),
    )


def peer_string(entity: Any = None, peer: Any = None) -> str | None:
    if isinstance(entity, types.User):
        return f"user{entity.id}"
    if isinstance(entity, types.Channel):
        return f"channel{entity.id}"
    if isinstance(entity, (types.Chat, types.ChatForbidden)):
        return f"chat{entity.id}"
    if isinstance(peer, types.PeerUser):
        return f"user{peer.user_id}"
    if isinstance(peer, types.PeerChannel):
        return f"channel{peer.channel_id}"
    if isinstance(peer, types.PeerChat):
        return f"chat{peer.chat_id}"
    return None


# --- entity conversion --------------------------------------------------

_ENTITY_MAP: dict[type, str] = {
    types.MessageEntityBold: "bold",
    types.MessageEntityItalic: "italic",
    types.MessageEntityUnderline: "underline",
    types.MessageEntityStrike: "strikethrough",
    types.MessageEntityCode: "code",
    types.MessageEntityPre: "pre",
    types.MessageEntityTextUrl: "text_link",
    types.MessageEntityUrl: "link",
    types.MessageEntityMention: "mention",
    types.MessageEntityMentionName: "mention_name",
    types.InputMessageEntityMentionName: "mention_name",
    types.MessageEntityHashtag: "hashtag",
    types.MessageEntityCashtag: "cashtag",
    types.MessageEntityBotCommand: "bot_command",
    types.MessageEntityEmail: "email",
    types.MessageEntityPhone: "phone",
    types.MessageEntitySpoiler: "spoiler",
    types.MessageEntityBlockquote: "blockquote",
    types.MessageEntityCustomEmoji: "custom_emoji",
    types.MessageEntityBankCard: "bank_card",
}


def convert_entities(entities: list[Any] | None) -> list[dict[str, Any]]:
    result = []
    for ent in entities or []:
        item: dict[str, Any] = {
            "type": _ENTITY_MAP.get(type(ent), "unknown"),
            "offset": ent.offset,
            "length": ent.length,
        }
        if isinstance(ent, types.MessageEntityTextUrl):
            item["href"] = ent.url
        elif isinstance(ent, types.MessageEntityPre):
            item["language"] = ent.language or ""
        elif isinstance(ent, types.MessageEntityMentionName):
            item["user_id"] = ent.user_id
        elif isinstance(ent, types.InputMessageEntityMentionName):
            item["user_id"] = getattr(ent.user_id, "user_id", None)
        elif isinstance(ent, types.MessageEntityCustomEmoji):
            item["document_id"] = str(ent.document_id)
        elif isinstance(ent, types.MessageEntityBlockquote) and getattr(ent, "collapsed", False):
            item["collapsed"] = True
        result.append(item)
    return result


def convert_reactions(reactions: Any) -> list[dict[str, Any]]:
    out = []
    for rc in getattr(reactions, "results", None) or []:
        reaction = rc.reaction
        if isinstance(reaction, types.ReactionEmoji):
            out.append({"type": "emoji", "count": rc.count, "emoji": reaction.emoticon})
        elif isinstance(reaction, types.ReactionCustomEmoji):
            out.append({"type": "custom_emoji", "count": rc.count, "document_id": str(reaction.document_id)})
        else:
            out.append({"type": "paid", "count": rc.count})
    return out


def _text_of(value: Any) -> str:
    """Poll questions/answers are TextWithEntities on newer layers, str on older."""
    if value is None:
        return ""
    return value if isinstance(value, str) else getattr(value, "text", str(value))


def convert_poll(media: types.MessageMediaPoll) -> dict[str, Any]:
    poll, results = media.poll, media.results
    voters_by_option: dict[bytes, Any] = {}
    for r in getattr(results, "results", None) or []:
        voters_by_option[r.option] = r
    answers = []
    for answer in poll.answers:
        r = voters_by_option.get(answer.option)
        answers.append(
            {
                "text": _text_of(answer.text),
                "voters": getattr(r, "voters", 0) or 0,
                "chosen": bool(getattr(r, "chosen", False)),
            }
        )
    return {
        "question": _text_of(poll.question),
        "closed": bool(poll.closed),
        "total_voters": getattr(results, "total_voters", 0) or 0,
        "answers": answers,
    }


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


_DISCARD_REASONS = {
    types.PhoneCallDiscardReasonMissed: "missed",
    types.PhoneCallDiscardReasonBusy: "busy",
    types.PhoneCallDiscardReasonHangup: "hangup",
    types.PhoneCallDiscardReasonDisconnect: "disconnect",
}


def classify_media(msg: Any) -> str | None:
    """Return the media kind of a message (see models.MEDIA_KINDS) or None."""
    media = msg.media
    if isinstance(media, types.MessageMediaPhoto):
        return "photo" if media.photo else None
    if not isinstance(media, types.MessageMediaDocument) or not isinstance(media.document, types.Document):
        return None
    attrs = media.document.attributes
    if any(isinstance(a, types.DocumentAttributeSticker) for a in attrs):
        return "sticker"
    if any(isinstance(a, types.DocumentAttributeAnimated) for a in attrs):
        return "animation"
    video = next((a for a in attrs if isinstance(a, types.DocumentAttributeVideo)), None)
    if video is not None:
        return "video_message" if video.round_message else "video_file"
    audio = next((a for a in attrs if isinstance(a, types.DocumentAttributeAudio)), None)
    if audio is not None:
        return "voice_message" if audio.voice else "audio_file"
    return "file"


_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    name = _FILENAME_BAD.sub("_", name).strip(" .")
    return name[:180] or "file"


# --- exporter -----------------------------------------------------------

class Exporter:
    def __init__(self, client: TelegramClient, cfg: Config, checkpoint: Checkpoint, progress: Progress):
        self.client = client
        self.cfg = cfg
        self.checkpoint = checkpoint
        self.progress = progress
        self.tz = cfg.timezone
        self.entity: Any = None
        self.chat: ChatInfo | None = None
        self.options: ExportOptions | None = None
        self.out_dir: Path | None = None
        self.used_paths: set[str] = set()
        self._entity_cache: dict[int, Any] = {}

    # -- flood handling with progress display --
    async def _on_flood(self, seconds: int) -> None:
        deadline = time.monotonic() + seconds
        while True:
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                break
            self.progress.waiting = remaining
            await self.progress.update()
            await asyncio.sleep(min(3, remaining))
        self.progress.waiting = 0
        await self.progress.update()

    async def _call(self, func: Callable[[], Awaitable[T]]) -> T:
        return await flood_retry(func, self._on_flood)

    # -- entry point --
    async def run(self, job: JobSpec, resume: bool = False) -> Path:
        self.chat, self.options = job.chat, job.options
        self.out_dir = Path(job.output_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.entity = await self._call(lambda: self.client.get_entity(job.chat.peer_id))

        start, end = self.options.date_range(self.tz)
        last_id = 0
        if resume:
            self.checkpoint.repair()
            done, last_id = 0, 0
            for rec in self.checkpoint.iter_records():
                done += 1
                last_id = rec.id
                if rec.media and rec.media.path:
                    self.used_paths.add(rec.media.path)
                if rec.media and rec.media.thumbnail:
                    self.used_paths.add(rec.media.thumbnail)
            self.progress.processed = done
            for key in ("media_downloaded", "media_skipped", "media_failed", "bytes"):
                setattr(self.progress, key, job.counters.get(key, 0))
            log.info("resuming export", extra={"chat": self.chat.name, "done": done, "last_id": last_id})

        self.progress.phase = "Counting messages"
        await self.progress.update(force=True)
        self.progress.total = await self._estimate_total(start, end)

        self.progress.phase = "Fetching messages"
        await self.progress.update(force=True)
        try:
            await self._fetch(job, start, end, last_id)
        finally:
            self.checkpoint.close()
            self._save_counters(job)

        store = RecordStore(self.checkpoint)
        if self.options.write_json:
            self.progress.phase = "Writing result.json"
            await self.progress.update(force=True)
            await asyncio.to_thread(write_json, self.out_dir, self.chat, store, self.tz)
        if self.options.write_html:
            self.progress.phase = "Writing HTML pages"
            await self.progress.update(force=True)
            await asyncio.to_thread(write_html, self.out_dir, self.chat, store, self.tz)
        log.info("export written", extra={"chat": self.chat.name, "dir": str(self.out_dir)})
        return self.out_dir

    def _save_counters(self, job: JobSpec) -> None:
        job.counters = {
            "media_downloaded": self.progress.media_downloaded,
            "media_skipped": self.progress.media_skipped,
            "media_failed": self.progress.media_failed,
            "bytes": self.progress.bytes,
        }
        self.checkpoint.save_job(job)

    async def _estimate_total(self, start: datetime | None, end: datetime | None) -> int | None:
        try:
            if start is None and end is None:
                result = await self._call(lambda: self.client.get_messages(self.entity, limit=0))
                return int(result.total)
            request = functions.messages.SearchRequest(
                peer=self.entity,
                q="",
                filter=types.InputMessagesFilterEmpty(),
                min_date=start,
                max_date=end,
                offset_id=0,
                add_offset=0,
                limit=0,
                max_id=0,
                min_id=0,
                hash=0,
            )
            result = await self._call(lambda: self.client(request))
            return int(getattr(result, "count", len(getattr(result, "messages", []))))
        except Exception:  # noqa: BLE001 - estimate is best effort
            log.exception("could not estimate message count")
            return None

    async def _fetch(self, job: JobSpec, start: datetime | None, end: datetime | None, last_id: int) -> None:
        processed_since_save = 0
        while True:
            kwargs: dict[str, Any] = {"reverse": True, "wait_time": 0}
            if last_id:
                kwargs["min_id"] = last_id
            elif start is not None:
                kwargs["offset_date"] = start
            try:
                async for msg in self.client.iter_messages(self.entity, **kwargs):
                    if not isinstance(msg, (types.Message, types.MessageService)):
                        continue
                    if end is not None and msg.date >= end:
                        return
                    if start is not None and msg.date < start:
                        continue
                    record = await self.convert(msg)
                    self.checkpoint.append(record)
                    last_id = msg.id
                    self.progress.processed += 1
                    processed_since_save += 1
                    if processed_since_save >= 100:
                        self._save_counters(job)
                        processed_since_save = 0
                    await self.progress.update()
                return
            except errors.FloodWaitError as exc:
                log.warning("flood wait during history fetch", extra={"seconds": exc.seconds, "last_id": last_id})
                await self._on_flood(int(exc.seconds) + 1)

    # -- message conversion --
    async def convert(self, msg: Any) -> ExportMessage:
        sender = msg.sender
        if sender is None and msg.sender_id is not None:
            sender = await self._entity_cached(msg.sender_id)
        if sender is None and msg.post:
            sender = self.entity
        name = display_name(sender)
        from_id = peer_string(sender, msg.from_id)
        if from_id is None and msg.sender_id is not None:
            real_id, peer_cls = utils.resolve_id(msg.sender_id)
            from_id = f"{'user' if peer_cls is types.PeerUser else 'channel'}{real_id}"

        record = ExportMessage(
            id=msg.id,
            type="message",
            date=int(msg.date.timestamp()),
            edited=int(msg.edit_date.timestamp())
            if getattr(msg, "edit_date", None) and not getattr(msg, "edit_hide", False)
            else None,
            from_name=name,
            from_id=from_id,
            text=msg.message or "",
            entities=convert_entities(getattr(msg, "entities", None)),
            reply_to_message_id=getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None,
            reactions=convert_reactions(getattr(msg, "reactions", None)),
        )

        if isinstance(msg, types.MessageService) or getattr(msg, "action", None) is not None:
            record.type = "service"
            record.actor, record.actor_id = name, from_id
            record.action, record.action_data = await self._convert_action(msg)
            record.from_name = record.from_id = None
            record.edited = None
            return record

        if getattr(msg, "post_author", None):
            record.author = msg.post_author
        if msg.fwd_from:
            record.forwarded_from = await self._forward_name(msg)
        if msg.via_bot_id:
            bot = msg.via_bot or await self._safe(lambda: self.client.get_entity(msg.via_bot_id))
            if bot is not None and getattr(bot, "username", None):
                record.via_bot = "@" + bot.username

        media = msg.media
        if isinstance(media, types.MessageMediaPoll):
            record.poll = convert_poll(media)
        elif isinstance(media, types.MessageMediaContact):
            record.contact = {
                "first_name": media.first_name or "",
                "last_name": media.last_name or "",
                "phone_number": media.phone_number or "",
            }
        elif isinstance(media, (types.MessageMediaGeo, types.MessageMediaGeoLive, types.MessageMediaVenue)):
            geo = media.geo
            if isinstance(geo, types.GeoPoint):
                record.location = {"latitude": geo.lat, "longitude": geo.long}
                if isinstance(media, types.MessageMediaGeoLive):
                    record.location["live_period"] = media.period
            if isinstance(media, types.MessageMediaVenue):
                record.venue = {"title": media.title or "", "address": media.address or ""}
        elif isinstance(media, types.MessageMediaDice):
            record.dice = {"emoji": media.emoticon, "value": media.value}
        else:
            kind = classify_media(msg)
            if kind:
                record.media = await self._process_media(msg, kind)
        return record

    async def _safe(self, func: Callable[[], Awaitable[T]]) -> T | None:
        try:
            return await self._call(func)
        except Exception:  # noqa: BLE001 - names are cosmetic, never fail the export
            return None

    async def _entity_cached(self, peer_id: int) -> Any:
        if peer_id not in self._entity_cache:
            self._entity_cache[peer_id] = await self._safe(lambda: self.client.get_entity(peer_id))
        return self._entity_cache[peer_id]

    async def _user_name(self, user_id: int) -> str:
        return display_name(await self._entity_cached(user_id))

    async def _forward_name(self, msg: Any) -> str:
        fwd = msg.forward
        entity = getattr(fwd, "sender", None) or getattr(fwd, "chat", None)
        if entity is not None:
            return display_name(entity)
        if msg.fwd_from.from_name:
            return msg.fwd_from.from_name
        peer = msg.fwd_from.from_id
        if peer is not None:
            entity = await self._safe(lambda: self.client.get_entity(peer))
            if entity is not None:
                return display_name(entity)
        return "Unknown"

    async def _members(self, msg: Any, ids: list[int]) -> list[str]:
        known = {e.id: display_name(e) for e in (getattr(msg, "action_entities", None) or []) if e is not None}
        return [known.get(uid) or await self._user_name(uid) for uid in ids]

    async def _convert_action(self, msg: Any) -> tuple[str, dict[str, Any]]:
        a = msg.action
        t = types
        if isinstance(a, t.MessageActionChatCreate):
            return "create_group", {"title": a.title, "members": await self._members(msg, a.users)}
        if isinstance(a, t.MessageActionChatEditTitle):
            return "edit_group_title", {"title": a.title}
        if isinstance(a, t.MessageActionChatEditPhoto):
            return "edit_group_photo", {}
        if isinstance(a, t.MessageActionChatDeletePhoto):
            return "delete_group_photo", {}
        if isinstance(a, t.MessageActionChatAddUser):
            return "invite_members", {"members": await self._members(msg, a.users)}
        if isinstance(a, t.MessageActionChatDeleteUser):
            return "remove_members", {"members": await self._members(msg, [a.user_id])}
        if isinstance(a, t.MessageActionChatJoinedByLink):
            return "join_group_by_link", {"inviter": await self._user_name(a.inviter_id)}
        if isinstance(a, t.MessageActionChatJoinedByRequest):
            return "join_group_by_request", {}
        if isinstance(a, t.MessageActionChannelCreate):
            return "create_channel", {"title": a.title}
        if isinstance(a, t.MessageActionChatMigrateTo):
            return "migrate_to_supergroup", {}
        if isinstance(a, t.MessageActionChannelMigrateFrom):
            return "migrate_from_group", {"title": a.title}
        if isinstance(a, t.MessageActionPinMessage):
            target = getattr(msg.reply_to, "reply_to_msg_id", None) if msg.reply_to else None
            return "pin_message", {"message_id": target}
        if isinstance(a, t.MessageActionHistoryClear):
            return "clear_history", {}
        if isinstance(a, t.MessageActionGameScore):
            return "score_in_game", {"game_message_id": getattr(msg.reply_to, "reply_to_msg_id", None), "score": a.score}
        if isinstance(a, t.MessageActionPhoneCall):
            data: dict[str, Any] = {}
            if a.duration:
                data["duration_seconds"] = a.duration
            if a.reason is not None:
                data["discard_reason"] = _DISCARD_REASONS.get(type(a.reason), "unknown")
            return "phone_call", data
        if isinstance(a, t.MessageActionScreenshotTaken):
            return "take_screenshot", {}
        if isinstance(a, t.MessageActionCustomAction):
            return "custom_action", {"message": a.message}
        if isinstance(a, t.MessageActionBotAllowed):
            return "allow_sending_messages", {}
        if isinstance(a, t.MessageActionContactSignUp):
            return "joined_telegram", {}
        if isinstance(a, t.MessageActionGroupCall):
            return "group_call", ({"duration_seconds": a.duration} if a.duration else {})
        if isinstance(a, t.MessageActionInviteToGroupCall):
            return "invite_to_group_call", {"members": await self._members(msg, a.users)}
        if isinstance(a, t.MessageActionGroupCallScheduled):
            return "group_call_scheduling", {"schedule_date": int(a.schedule_date.timestamp())}
        if isinstance(a, t.MessageActionSetMessagesTTL):
            return "set_messages_ttl", {"period_seconds": a.period}
        if isinstance(a, t.MessageActionSetChatTheme):
            return "edit_chat_theme", {"emoticon": getattr(a, "emoticon", None)}
        if isinstance(a, t.MessageActionTopicCreate):
            return "topic_created", {"title": a.title}
        if isinstance(a, t.MessageActionTopicEdit):
            return "topic_edit", ({"title": a.title} if a.title else {})
        if isinstance(a, t.MessageActionPaymentSent):
            return "send_payment", {"amount": a.total_amount / 100, "currency": a.currency}
        if isinstance(a, t.MessageActionGiftPremium):
            return "send_premium_gift", {"months": a.months, "amount": a.amount, "currency": a.currency}
        name = type(a).__name__.removeprefix("MessageAction") or "Unknown"
        return _snake(name), {}

    # -- media --
    def _unique_path(self, folder: str, name: str) -> str:
        stem, ext = os.path.splitext(name)
        candidate = f"{folder}/{name}"
        n = 1
        while candidate in self.used_paths:
            n += 1
            candidate = f"{folder}/{stem} ({n}){ext}"
        self.used_paths.add(candidate)
        return candidate

    def _file_name(self, msg: Any, kind: str) -> str:
        stamp = msg.date.astimezone(self.tz).strftime("%d-%m-%Y_%H-%M-%S")
        f = msg.file
        ext = (f.ext if f and f.ext else "") or ""
        if kind == "photo":
            return f"photo_{msg.id}@{stamp}.jpg"
        if kind == "voice_message":
            return f"audio_{msg.id}@{stamp}{ext or '.ogg'}"
        if kind == "video_message":
            return f"file_{msg.id}@{stamp}{ext or '.mp4'}"
        if kind == "sticker":
            return f"sticker_{msg.id}{ext or '.webp'}"
        if f and f.name:
            return sanitize_filename(f.name)
        prefix = {"video_file": "video", "animation": "animation", "audio_file": "audio"}.get(kind, "file")
        return f"{prefix}_{msg.id}@{stamp}{ext}"

    def _media_metadata(self, msg: Any, kind: str) -> Media:
        f = msg.file
        media = Media(kind=kind)
        if kind == "photo":
            sizes = [s for s in msg.media.photo.sizes if getattr(s, "w", None)]
            if sizes:
                biggest = max(sizes, key=lambda s: s.w * s.h)
                media.width, media.height = biggest.w, biggest.h
            media.size = f.size if f else None
            return media
        if f is not None:
            media.mime_type = f.mime_type
            media.size = f.size
            media.file_name = f.name
            media.width = f.width
            media.height = f.height
            dur = f.duration
            media.duration = int(round(dur)) if dur else None
            if kind == "sticker":
                media.sticker_emoji = f.emoji
            if kind == "audio_file":
                media.performer = f.performer
                media.title = f.title
        if kind in ("photo", "sticker", "voice_message", "video_message"):
            media.file_name = None
        return media

    async def _process_media(self, msg: Any, kind: str) -> Media:
        media = self._media_metadata(msg, kind)
        assert self.options is not None and self.out_dir is not None
        _, folder, option_key = MEDIA_KINDS[kind]
        if not self.options.media.get(option_key, False):
            media.skipped = SKIP_TYPE
            self.progress.media_skipped += 1
            return media
        limit = self.options.size_limit_bytes
        if limit is not None and media.size is not None and media.size > limit:
            media.skipped = SKIP_SIZE
            self.progress.media_skipped += 1
            return media

        rel = self._unique_path(folder, self._file_name(msg, kind))
        ok, msg = await self._download(msg, rel)
        if not ok:
            media.skipped = SKIP_FAILED
            self.used_paths.discard(rel)
            self.progress.media_failed += 1
            return media
        media.path = rel
        self.progress.media_downloaded += 1
        self.progress.bytes += (self.out_dir / rel).stat().st_size

        if kind in ("video_file", "animation", "video_message") and getattr(msg.media.document, "thumbs", None):
            thumb_rel = f"{rel}_thumb.jpg"
            self.used_paths.add(thumb_rel)
            ok, msg = await self._download(msg, thumb_rel, thumb=-1, attempts=2)
            if ok:
                media.thumbnail = thumb_rel
                self.progress.bytes += (self.out_dir / thumb_rel).stat().st_size
            else:
                self.used_paths.discard(thumb_rel)
        return media

    async def _download(self, msg: Any, rel: str, thumb: int | None = None, attempts: int = DOWNLOAD_ATTEMPTS):
        """Download into ``rel``; returns (success, possibly refreshed message)."""
        assert self.out_dir is not None
        target = self.out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        failures = 0
        while failures < attempts:
            try:
                result = await self.client.download_media(msg, file=str(part), thumb=thumb)
                if not result:
                    raise RuntimeError("download returned nothing")
                os.replace(result, target)
                return True, msg
            except errors.FloodWaitError as exc:
                await self._on_flood(int(exc.seconds) + 1)  # does not count as a failure
            except (errors.FileReferenceExpiredError, errors.FileReferenceInvalidError):
                failures += 1
                log.info("file reference expired, refetching", extra={"msg_id": msg.id})
                fresh = await self._safe(lambda: self.client.get_messages(self.entity, ids=msg.id))
                if fresh is not None:
                    msg = fresh
            except asyncio.CancelledError:
                part.unlink(missing_ok=True)
                raise
            except Exception as exc:  # noqa: BLE001 - retried, then reported as failed
                failures += 1
                log.warning(
                    "media download failed",
                    extra={"msg_id": msg.id, "file": rel, "attempt": failures, "error": repr(exc)},
                )
                if failures < attempts:
                    await asyncio.sleep(2 ** failures)
        part.unlink(missing_ok=True)
        log.error("media download gave up", extra={"msg_id": msg.id, "file": rel})
        return False, msg


def new_output_dir(export_dir: Path, now: datetime | None = None) -> Path:
    """ChatExport_YYYY-MM-DD, or 'ChatExport_YYYY-MM-DD (2)' if it already exists."""
    now = now or datetime.now(timezone.utc)
    base = f"ChatExport_{now:%Y-%m-%d}"
    candidate = export_dir / base
    n = 1
    while candidate.exists():
        n += 1
        candidate = export_dir / f"{base} ({n})"
    return candidate
