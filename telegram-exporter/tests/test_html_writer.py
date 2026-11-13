import re

from app.export.html_writer import (
    HtmlWriter,
    entities_to_html,
    media_view,
    page_file_name,
    safe_href,
    write_html,
)
from app.export.models import Media

from .conftest import make_msg


def _write(tmp_path, chat, messages, per_page=1000):
    pages = write_html(tmp_path, chat, messages, per_page=per_page)
    return pages, [p.read_text(encoding="utf-8") for p in pages]


def test_writes_page_and_static_assets(tmp_path, chat, sample_messages):
    pages, (html,) = _write(tmp_path, chat, sample_messages)
    assert [p.name for p in pages] == ["messages.html"]
    assert (tmp_path / "css" / "style.css").exists()
    assert (tmp_path / "js" / "script.js").exists()
    assert (tmp_path / "images" / "media_photo.svg").exists()
    assert '<link href="css/style.css" rel="stylesheet"/>' in html
    assert "Test &lt;Chat&gt;" in html  # chat name escaped


def test_every_message_has_anchor(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    for msg in sample_messages:
        assert f'id="message{msg.id}"' in html


def test_joined_messages(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert 'class="message default clearfix joined" id="message2"' in html
    assert 'class="message default clearfix" id="message1"' in html
    assert 'class="message default clearfix" id="message3"' in html  # different sender
    # message 4 is from the same sender as 3, within 15 minutes
    assert 'class="message default clearfix joined" id="message4"' in html


def test_no_join_after_15_minutes_or_forward(tmp_path, chat):
    msgs = [make_msg(1, 0), make_msg(2, 16 * 60), make_msg(3, 16 * 60 + 5, forwarded_from="X")]
    _, (html,) = _write(tmp_path, chat, msgs)
    assert "joined" not in html.split('id="message2"')[0].split('id="message1"')[1]
    assert 'clearfix" id="message2"' in html
    assert 'clearfix" id="message3"' in html


def test_date_separators(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert ">1 March 2024<" in html
    assert ">2 March 2024<" in html
    assert 'id="message-1"' in html and 'id="message-2"' in html


def test_reply_preview_links_to_original(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert 'href="#go_to_message1" onclick="return GoToMessage(1)"' in html
    block = html.split('id="message3"')[1].split('id="message4"')[0]
    assert "reply_preview" in block
    assert "Alice Smith" in block
    assert "Hello **world**" in block  # snippet of the original


def test_reply_to_missing_message(tmp_path, chat):
    _, (html,) = _write(tmp_path, chat, [make_msg(1, reply_to_message_id=999)])
    assert "In reply to a message outside this export" in html


def test_pagination_1000_per_page_and_cross_page_reply(tmp_path, chat):
    msgs = [make_msg(i, i) for i in range(1, 2502)]
    msgs[-1].reply_to_message_id = 5
    pages, htmls = _write(tmp_path, chat, msgs)
    assert [p.name for p in pages] == ["messages.html", "messages2.html", "messages3.html"]
    assert htmls[0].count('class="message default') == 1000
    assert htmls[2].count('class="message default') == 501
    assert 'href="messages2.html">Next messages' in htmls[0]
    assert "Previous messages" not in htmls[0]
    assert 'href="messages.html">Previous messages' in htmls[1]
    assert 'href="messages3.html">Next messages' in htmls[1]
    assert "Next messages" not in htmls[2]
    assert 'href="messages.html#go_to_message5"' in htmls[2]


def test_small_page_size(tmp_path, chat):
    pages, _ = _write(tmp_path, chat, [make_msg(i, i) for i in range(1, 6)], per_page=2)
    assert len(pages) == 3


def test_empty_export(tmp_path, chat):
    pages, (html,) = _write(tmp_path, chat, [])
    assert pages[0].name == "messages.html"
    assert "No messages" in html


def test_forwarded_header(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert "Forwarded from News Channel" in html
    assert 'class="forwarded body"' in html


def test_inline_photo_thumbnail(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert '<a class="photo_wrap clearfix pull_left" href="photos/photo_4@01-03-2024_10-03-00.jpg">' in html
    m = re.search(r'<img class="photo" src="photos/photo_4[^"]+" style="width: (\d+)px; height: (\d+)px"', html)
    assert m and (int(m.group(1)), int(m.group(2))) == (260, 195)


def test_skipped_media_placeholder(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert "File exceeds maximum size. Change data exporting settings to download." in html
    assert "media_video_file" in html


def test_file_link_and_voice(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert 'href="voice_messages/audio_10.ogg"' in html
    assert "Voice message" in html


def test_service_message_text(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert "Alice Smith invited Carol" in html
    assert 'class="message service" id="message6"' in html


def test_pin_service_links_message(tmp_path, chat):
    msgs = [make_msg(1), make_msg(2, 5, type="service", action="pin_message", actor="Bob", actor_id="user2",
                                  action_data={"message_id": 1}, text="", from_name=None, from_id=None)]
    _, (html,) = _write(tmp_path, chat, msgs)
    assert 'Bob pinned <a href="#go_to_message1" onclick="return GoToMessage(1)">this message</a>' in html


def test_poll_reactions_edited(tmp_path, chat, sample_messages):
    _, (html,) = _write(tmp_path, chat, sample_messages)
    assert "Lunch?" in html and "2 votes, chosen vote" in html and "3 votes" in html
    assert '<span class="emoji">👍</span><span class="count">2</span>' in html
    assert ">edited</span>" in html


def test_entities_to_html_formatting():
    text = "bold italic code link @user spoiler"
    ents = [
        {"type": "bold", "offset": 0, "length": 4},
        {"type": "italic", "offset": 5, "length": 6},
        {"type": "code", "offset": 12, "length": 4},
        {"type": "text_link", "offset": 17, "length": 4, "href": "https://example.com/?a=1&b=2"},
        {"type": "mention", "offset": 22, "length": 5},
        {"type": "spoiler", "offset": 28, "length": 7},
    ]
    html = str(entities_to_html(text, ents))
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://example.com/?a=1&amp;b=2">link</a>' in html
    assert '<a href="https://t.me/user">@user</a>' in html
    assert '<span class="spoiler hidden" onclick="ShowSpoiler(this)"><span aria-hidden="true">spoiler</span></span>' in html


def test_nested_entities_and_pre():
    html = str(entities_to_html("ab", [
        {"type": "bold", "offset": 0, "length": 2},
        {"type": "italic", "offset": 1, "length": 1},
    ]))
    assert html == "<strong>a</strong><strong><em>b</em></strong>"
    pre = str(entities_to_html("a\nb", [{"type": "pre", "offset": 0, "length": 3, "language": "py"}]))
    assert pre == '<pre class="language-py">a\nb</pre>'


def test_text_is_escaped_and_newlines_kept():
    html = str(entities_to_html("<script>alert(1)</script>\nline2", []))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<br>line2" in html


def test_unsafe_links_are_neutralised():
    assert safe_href("javascript:alert(1)") is None
    assert safe_href("example.com") == "http://example.com"
    assert safe_href("https://t.me/x") == "https://t.me/x"
    html = str(entities_to_html("click", [{"type": "text_link", "offset": 0, "length": 5, "href": "javascript:alert(1)"}]))
    assert "javascript" not in html


def test_media_view_variants():
    assert media_view(Media(kind="sticker", path="stickers/s.webp", width=512, height=512))["display"] == "sticker"
    assert media_view(Media(kind="sticker", path="stickers/s.tgs"))["display"] == "block"
    video = media_view(Media(kind="video_file", path="v.mp4", thumbnail="v.mp4_thumb.jpg", width=1920, height=1080, duration=65))
    assert video["display"] == "video" and video["duration"] == "01:05"
    assert (video["width"], video["height"]) == (260, 146)
    assert media_view(Media(kind="video_message", path="r.mp4", thumbnail="r.jpg"))["display"] == "round"
    skipped = media_view(Media(kind="photo", skipped="type"))
    assert skipped["status"] == "File not included. Change data exporting settings to download."
    audio = media_view(Media(kind="audio_file", path="files/a.mp3", performer="Band", title="Song"))
    assert audio["title"] == "Band – Song"


def test_page_file_names():
    assert page_file_name(0) == "messages.html"
    assert page_file_name(1) == "messages2.html"
    assert page_file_name(9) == "messages10.html"


def test_writer_accepts_reiterable_store(tmp_path, chat):
    class Store:
        def __init__(self, items):
            self.items = items
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return iter(self.items)

    store = Store([make_msg(1), make_msg(2, 10)])
    HtmlWriter(tmp_path, chat).write(store)
    assert store.iterations == 2
