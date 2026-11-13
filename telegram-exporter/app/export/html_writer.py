"""Renders messages.html, messages2.html, ... in the style of Telegram Desktop."""
from __future__ import annotations

import html
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from ..utils.fmt import day_title, duration, full_datetime, human_size, initials
from .entities import Segment, plain_snippet, split_segments
from .models import SKIP_TEXT, ChatInfo, ExportMessage, Media

MESSAGES_PER_PAGE = 1000
JOIN_WINDOW_SECONDS = 15 * 60
THUMB_MAX = 260
STICKER_MAX = 256

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

_SAFE_SCHEMES = ("http://", "https://", "tg://", "mailto:", "tel:", "ftp://")


def page_file_name(page_index: int) -> str:
    return "messages.html" if page_index == 0 else f"messages{page_index + 1}.html"


def safe_href(url: str) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    lowered = url.lower()
    if lowered.startswith(_SAFE_SCHEMES):
        return url
    if re.match(r"^[a-z][a-z0-9+.-]*:", lowered):
        return None  # javascript:, data:, etc.
    return "http://" + url


# --- text entities -> HTML ----------------------------------------------

def _escape_text(text: str, in_pre: bool) -> str:
    escaped = html.escape(text, quote=False)
    return escaped if in_pre else escaped.replace("\n", "<br>")


def _open_close(ent: dict[str, Any], seg_text: str) -> tuple[str, str]:
    kind = ent.get("type")
    if kind == "bold":
        return "<strong>", "</strong>"
    if kind == "italic":
        return "<em>", "</em>"
    if kind == "underline":
        return "<u>", "</u>"
    if kind == "strikethrough":
        return "<s>", "</s>"
    if kind == "code":
        return "<code>", "</code>"
    if kind == "pre":
        lang = ent.get("language")
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        return f"<pre{cls}>", "</pre>"
    if kind == "blockquote":
        return "<blockquote>", "</blockquote>"
    if kind == "spoiler":
        return '<span class="spoiler hidden" onclick="ShowSpoiler(this)"><span aria-hidden="true">', "</span></span>"
    href: str | None = None
    if kind == "text_link":
        href = safe_href(ent.get("href", ""))
    elif kind == "link":
        href = safe_href(seg_text)
    elif kind == "email":
        href = "mailto:" + seg_text.strip()
    elif kind == "phone":
        href = "tel:" + re.sub(r"[^\d+]", "", seg_text)
    elif kind == "mention":
        href = "https://t.me/" + seg_text.lstrip("@").strip()
    elif kind == "mention_name" and ent.get("user_id"):
        href = f"tg://user?id={int(ent['user_id'])}"
    elif kind in ("hashtag", "cashtag", "bot_command"):
        return f'<span class="{kind}">', "</span>"
    if href:
        return f'<a href="{html.escape(href, quote=True)}">', "</a>"
    return "", ""


def entities_to_html(text: str, entities: list[dict[str, Any]] | None) -> Markup:
    parts: list[str] = []
    for seg in split_segments(text, entities):
        parts.append(_segment_html(seg))
    return Markup("".join(parts))


def _segment_html(seg: Segment) -> str:
    in_pre = any(e.get("type") == "pre" for e in seg.entities)
    body = _escape_text(seg.text, in_pre)
    for ent in reversed(seg.entities):  # innermost first, so outermost ends up outside
        open_tag, close_tag = _open_close(ent, seg.text)
        body = f"{open_tag}{body}{close_tag}"
    return body


# --- service messages ----------------------------------------------------

def _names(values: list[str] | None) -> str:
    names = [str(escape(v)) for v in (values or []) if v]
    if not names:
        return "someone"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def service_html(msg: ExportMessage, link_for) -> Markup:
    actor = str(escape(msg.actor or "Someone"))
    d = msg.action_data
    title = str(escape(d.get("title", "")))
    action = msg.action or ""
    if action == "create_group":
        text = f"{actor} created group «{title}»"
    elif action == "edit_group_title":
        text = f"{actor} changed group title to «{title}»"
    elif action == "edit_group_photo":
        text = f"{actor} changed group photo"
    elif action == "delete_group_photo":
        text = f"{actor} removed group photo"
    elif action == "invite_members":
        members = d.get("members") or []
        text = f"{actor} joined group" if members == [msg.actor] else f"{actor} invited {_names(members)}"
    elif action == "remove_members":
        members = d.get("members") or []
        text = f"{actor} left group" if members == [msg.actor] else f"{actor} removed {_names(members)}"
    elif action == "join_group_by_link":
        text = f"{actor} joined group by link from {escape(d.get('inviter') or 'an invite link')}"
    elif action == "join_group_by_request":
        text = f"{actor} was accepted into the group"
    elif action == "create_channel":
        text = f"Channel «{title}» created"
    elif action == "migrate_to_supergroup":
        text = f"{actor} converted this group to a supergroup"
    elif action == "migrate_from_group":
        text = f"{actor} converted the basic group «{title}» to this supergroup"
    elif action == "pin_message":
        target = d.get("message_id") or msg.reply_to_message_id
        link = link_for(target) if target else None
        if link:
            text = f'{actor} pinned <a href="{link[0]}"{link[1]}>this message</a>'
        else:
            text = f"{actor} pinned a message"
    elif action == "clear_history":
        text = "History cleared"
    elif action == "score_in_game":
        text = f"{actor} scored {escape(d.get('score', 0))}"
    elif action == "phone_call":
        secs = d.get("duration_seconds")
        reason = d.get("discard_reason")
        if reason == "missed":
            text = f"Missed call from {actor}"
        elif reason == "busy":
            text = f"Declined call ({actor})"
        else:
            text = f"{actor} made a call" + (f" ({duration(secs)})" if secs else "")
    elif action == "group_call":
        secs = d.get("duration_seconds")
        text = f"Voice chat ended ({duration(secs)})" if secs else f"{actor} started a voice chat"
    elif action == "invite_to_group_call":
        text = f"{actor} invited {_names(d.get('members'))} to the voice chat"
    elif action == "group_call_scheduling":
        text = f"{actor} scheduled a voice chat"
    elif action == "take_screenshot":
        text = f"{actor} took a screenshot"
    elif action == "allow_sending_messages":
        text = "You allowed this bot to message you"
    elif action == "joined_telegram":
        text = f"{actor} joined Telegram"
    elif action == "set_messages_ttl":
        period = d.get("period_seconds") or 0
        text = (
            f"{actor} set messages to auto-delete in {_ttl(period)}"
            if period
            else f"{actor} disabled the auto-delete timer"
        )
    elif action == "edit_chat_theme":
        emoticon = d.get("emoticon")
        text = f"{actor} changed the chat theme to {escape(emoticon)}" if emoticon else f"{actor} disabled the chat theme"
    elif action == "topic_created":
        text = f"{actor} created topic «{title}»"
    elif action == "topic_edit":
        text = f"{actor} edited the topic" + (f" «{title}»" if title else "")
    elif action == "send_payment":
        text = f"Payment of {escape(d.get('amount', ''))} {escape(d.get('currency', ''))} sent"
    elif action == "send_premium_gift":
        text = f"{actor} sent a Telegram Premium gift"
    elif action == "custom_action":
        text = str(escape(d.get("message", "")))
    else:
        text = f"{actor}: {escape(action.replace('_', ' '))}"
    return Markup(text)


def _ttl(seconds: int) -> str:
    for unit, size in (("month", 2592000), ("week", 604800), ("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''}"
    return f"{seconds} seconds"


# --- media ---------------------------------------------------------------

def _fit(width: int | None, height: int | None, limit: int) -> tuple[int, int]:
    if not width or not height:
        return limit, limit
    scale = min(1.0, limit / width, limit / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


_KIND_TITLES = {
    "photo": "Photo",
    "video_file": "Video file",
    "voice_message": "Voice message",
    "video_message": "Video message",
    "sticker": "Sticker",
    "animation": "Animation",
    "audio_file": "Audio file",
    "file": "File",
}


def media_view(media: Media) -> dict[str, Any]:
    """Prepare the template context for a media attachment."""
    view: dict[str, Any] = {
        "kind": media.kind,
        "href": media.path,
        "title": _KIND_TITLES.get(media.kind, "File"),
        "status": None,
        "thumb": media.thumbnail,
        "duration": duration(media.duration) if media.duration else None,
        "display": "block",
    }
    if not media.path:
        view["status"] = SKIP_TEXT[media.skipped or "failed"]
        if media.kind == "sticker" and media.sticker_emoji:
            view["title"] = f"Sticker {media.sticker_emoji}"
        if media.kind == "file" and media.file_name:
            view["title"] = media.file_name
        return view

    if media.kind == "photo":
        view["display"] = "photo"
        view["width"], view["height"] = _fit(media.width, media.height, THUMB_MAX)
    elif media.kind == "sticker":
        ext = Path(media.path).suffix.lower()
        if ext in (".webp", ".png", ".jpg", ".jpeg"):
            view["display"] = "sticker"
        elif ext == ".webm":
            view["display"] = "sticker_video"
        view["width"], view["height"] = _fit(media.width or 512, media.height or 512, STICKER_MAX)
        view["title"] = f"Sticker {media.sticker_emoji or ''}".strip()
        view["status"] = human_size(media.size) if media.size else None
    elif media.kind in ("video_file", "animation", "video_message") and media.thumbnail:
        view["display"] = "round" if media.kind == "video_message" else "video"
        limit = 200 if media.kind == "video_message" else THUMB_MAX
        view["width"], view["height"] = _fit(media.width, media.height, limit)
        if media.kind == "video_message":
            view["width"] = view["height"] = 200
    else:
        if media.kind == "audio_file":
            if media.performer or media.title:
                view["title"] = " – ".join(x for x in (media.performer, media.title) if x)
            elif media.file_name:
                view["title"] = media.file_name
        elif media.kind in ("file", "video_file", "animation") and media.file_name:
            view["title"] = media.file_name
        bits = []
        if media.duration:
            bits.append(duration(media.duration))
        if media.size:
            bits.append(human_size(media.size))
        view["status"] = ", ".join(bits) or None
    return view


# --- page model ----------------------------------------------------------

@dataclass
class _IndexEntry:
    page: int
    from_name: str
    snippet: str


def _snippet_for(msg: ExportMessage) -> str:
    if msg.text:
        return plain_snippet(msg.text)
    if msg.media:
        return _KIND_TITLES.get(msg.media.kind, "File")
    if msg.poll:
        return "Poll: " + plain_snippet(msg.poll.get("question", ""))
    if msg.contact:
        return "Contact"
    if msg.location:
        return "Location"
    return "Message"


def _userpic_class(from_id: str | None) -> str:
    digits = re.sub(r"\D", "", from_id or "")
    return f"userpic{(int(digits) % 8) + 1 if digits else 1}"


class HtmlWriter:
    def __init__(self, out_dir: Path, chat: ChatInfo, tz=timezone.utc, per_page: int = MESSAGES_PER_PAGE):
        self.out_dir = out_dir
        self.chat = chat
        self.tz = tz
        self.per_page = per_page
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.index: dict[int, _IndexEntry] = {}
        self.current_page = 0

    # -- helpers --
    def _local(self, ts: int) -> datetime:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(self.tz)

    def link_for(self, message_id: int) -> tuple[str, str] | None:
        """Return (href, extra attributes) linking to a message, or None if not exported."""
        entry = self.index.get(message_id)
        if entry is None:
            return None
        if entry.page == self.current_page:
            return f"#go_to_message{message_id}", f' onclick="return GoToMessage({message_id})"'
        return f"{page_file_name(entry.page)}#go_to_message{message_id}", ""

    def build_index(self, messages: Iterable[ExportMessage]) -> int:
        count = 0
        for count, msg in enumerate(messages, start=1):
            self.index[msg.id] = _IndexEntry(
                page=(count - 1) // self.per_page,
                from_name=msg.from_name or msg.actor or "",
                snippet=_snippet_for(msg),
            )
        return count

    def message_view(self, msg: ExportMessage, prev: ExportMessage | None) -> dict[str, Any]:
        local = self._local(msg.date)
        view: dict[str, Any] = {
            "id": msg.id,
            "service": msg.type == "service",
            "time": local.strftime("%H:%M"),
            "date_title": full_datetime(local),
        }
        if view["service"]:
            view["service_html"] = service_html(msg, self.link_for)
            return view

        joined = (
            prev is not None
            and prev.type != "service"
            and prev.from_id == msg.from_id
            and prev.forwarded_from == msg.forwarded_from
            and msg.date - prev.date < JOIN_WINDOW_SECONDS
            and self._local(prev.date).date() == local.date()
        )
        name = msg.from_name or "Deleted Account"
        view.update(
            joined=joined,
            from_name=name,
            initials=initials(name),
            userpic_class=_userpic_class(msg.from_id),
            author=msg.author,
            via_bot=msg.via_bot,
            forwarded_from=msg.forwarded_from,
            edited_title=full_datetime(self._local(msg.edited)) if msg.edited else None,
            text_html=entities_to_html(msg.text, msg.entities) if msg.text else None,
            media=media_view(msg.media) if msg.media else None,
            poll=msg.poll,
            contact=msg.contact,
            location=msg.location,
            venue=msg.venue,
            dice=msg.dice,
            reactions=msg.reactions,
        )
        if msg.location:
            lat, lon = msg.location["latitude"], msg.location["longitude"]
            view["map_href"] = f"https://maps.google.com/maps?q={lat},{lon}&ll={lat},{lon}&z=16"
        if msg.reply_to_message_id:
            link = self.link_for(msg.reply_to_message_id)
            entry = self.index.get(msg.reply_to_message_id)
            view["reply"] = (
                {
                    "href": link[0],
                    "attrs": Markup(link[1]),
                    "from_name": entry.from_name,
                    "snippet": entry.snippet,
                }
                if link and entry
                else {"missing": True}
            )
        return view

    def _page_items(self, page_messages: list[ExportMessage], date_counter: list[int]) -> Iterator[dict[str, Any]]:
        prev: ExportMessage | None = None
        prev_day = None
        for msg in page_messages:
            day = self._local(msg.date).date()
            if day != prev_day:
                date_counter[0] += 1
                yield {"date_separator": True, "id": -date_counter[0], "title": day_title(self._local(msg.date))}
                prev_day = day
            view = self.message_view(msg, prev)
            yield view
            prev = msg

    def write(self, messages: Iterable[ExportMessage]) -> list[Path]:
        """Write all pages. ``messages`` must be iterable twice (list or re-iterable store)."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.copy_static()
        total = self.build_index(messages)
        pages = max(1, -(-total // self.per_page))
        template = self.env.get_template("page.html.j2")
        written: list[Path] = []
        date_counter = [0]

        def render(page: int, chunk: list[ExportMessage]) -> None:
            self.current_page = page
            html_text = template.render(
                chat_name=self.chat.name,
                items=self._page_items(chunk, date_counter),
                prev_page=page_file_name(page - 1) if page > 0 else None,
                next_page=page_file_name(page + 1) if page + 1 < pages else None,
                empty=total == 0,
            )
            path = self.out_dir / page_file_name(page)
            path.write_text(html_text, encoding="utf-8")
            written.append(path)

        chunk: list[ExportMessage] = []
        page = 0
        for msg in messages:
            chunk.append(msg)
            if len(chunk) == self.per_page:
                render(page, chunk)
                chunk, page = [], page + 1
        if chunk or not written:
            render(page, chunk)
        return written

    def copy_static(self) -> None:
        for sub in ("css", "js", "images"):
            src = STATIC_DIR / sub
            if src.is_dir():
                shutil.copytree(src, self.out_dir / sub, dirs_exist_ok=True)


def write_html(
    out_dir: Path,
    chat: ChatInfo,
    messages: Iterable[ExportMessage],
    tz=timezone.utc,
    per_page: int = MESSAGES_PER_PAGE,
) -> list[Path]:
    return HtmlWriter(out_dir, chat, tz, per_page).write(messages)
