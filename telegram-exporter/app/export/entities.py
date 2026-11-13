"""Text entity handling shared by both writers.

Telegram entity offsets/lengths are measured in UTF-16 code units, so the
text is sliced on its UTF-16 encoding.  Overlapping or nested entities are
flattened into consecutive segments, each carrying the list of entities that
cover it (outermost first).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Desktop JSON entity type names.
ENTITY_TYPES = {
    "plain", "bold", "italic", "underline", "strikethrough", "code", "pre",
    "text_link", "link", "mention", "mention_name", "hashtag", "cashtag",
    "bot_command", "email", "phone", "spoiler", "blockquote", "custom_emoji",
    "bank_card", "unknown",
}

# Extra attributes carried by some entity types.
ENTITY_EXTRAS = ("href", "user_id", "language", "document_id", "collapsed")


@dataclass
class Segment:
    text: str
    entities: list[dict[str, Any]] = field(default_factory=list)

    @property
    def innermost(self) -> dict[str, Any] | None:
        return self.entities[-1] if self.entities else None


def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le", "surrogatepass")


def _from_utf16(raw: bytes) -> str:
    return raw.decode("utf-16-le", "surrogatepass")


def split_segments(text: str, entities: list[dict[str, Any]] | None) -> list[Segment]:
    if not text:
        return []
    if not entities:
        return [Segment(text)]

    raw = _utf16(text)
    total = len(raw) // 2
    valid = []
    for ent in entities:
        start = max(0, int(ent.get("offset", 0)))
        end = min(total, start + max(0, int(ent.get("length", 0))))
        if end > start:
            valid.append((start, end, ent))
    if not valid:
        return [Segment(text)]

    bounds = {0, total}
    for start, end, _ in valid:
        bounds.add(start)
        bounds.add(end)
    points = sorted(bounds)

    segments: list[Segment] = []
    for a, b in zip(points, points[1:]):
        active = [ent for start, end, ent in sorted(valid, key=lambda v: (v[0], -v[1])) if start <= a and end >= b]
        chunk = _from_utf16(raw[a * 2 : b * 2])
        if segments and [id(e) for e in segments[-1].entities] == [id(e) for e in active]:
            segments[-1].text += chunk
        else:
            segments.append(Segment(chunk, active))
    return segments


def to_desktop_entities(text: str, entities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Build Desktop's ``text_entities`` list (every piece of text, typed)."""
    result = []
    for seg in split_segments(text, entities):
        ent = seg.innermost
        item: dict[str, Any] = {"type": ent["type"] if ent else "plain", "text": seg.text}
        if ent:
            for key in ENTITY_EXTRAS:
                if ent.get(key) is not None:
                    item[key] = ent[key]
            # A link inside bold text is still a link: keep the href of any covering text_link.
            if "href" not in item:
                for outer in seg.entities:
                    if outer.get("href") and outer["type"] == "text_link":
                        item["type"], item["href"] = "text_link", outer["href"]
        result.append(item)
    return result


def to_desktop_text(text: str, entities: list[dict[str, Any]] | None) -> str | list[Any]:
    """Desktop's ``text`` field: a plain string, or a mixed array of strings and objects."""
    items = to_desktop_entities(text, entities)
    if not items:
        return ""
    if all(item["type"] == "plain" for item in items):
        return "".join(item["text"] for item in items)
    return [item["text"] if item["type"] == "plain" else item for item in items]


def plain_snippet(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"
