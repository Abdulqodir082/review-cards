#!/usr/bin/env python3
"""Otvizcards Instagram poster (free, official Meta API).

Publishes the posts waiting in instagram/queue/ to the Instagram professional
account that IG_ACCESS_TOKEN belongs to, then moves each one to
instagram/posted/ with a result.json (post id + link).

Uses only the Python standard library, so GitHub Actions needs no installs.

Commands:
  python3 instagram/publish.py validate        check every queued post (no token needed)
  python3 instagram/publish.py check           test the token, print the account name
  python3 instagram/publish.py publish         publish every queued post that is due
  python3 instagram/publish.py refresh-token   renew the 60-day token, write it to $NEW_TOKEN_FILE

Environment:
  IG_ACCESS_TOKEN   long-lived token (GitHub secret). Required for check/publish/refresh.
  IG_USER_ID        optional; looked up from the token when empty.
  IG_GRAPH_HOST     optional; picked from the token when empty:
                    "IG..." tokens (Instagram Login) use graph.instagram.com,
                    "EAA..." tokens (Unified / Facebook Login, system-user
                    tokens) use graph.facebook.com.
  IG_API_VERSION    optional; default v23.0.
  PUBLIC_BASE_URL   where the repo files are publicly served.
                    Default https://abdulqodir082.github.io/review-cards
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "instagram" / "queue"
POSTED = ROOT / "instagram" / "posted"

def _pick_host() -> str:
    if os.environ.get("IG_GRAPH_HOST"):
        return os.environ["IG_GRAPH_HOST"]
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    return "graph.instagram.com" if tok.startswith("IG") else "graph.facebook.com"


GRAPH_HOST = _pick_host()
API_VERSION = os.environ.get("IG_API_VERSION") or "v23.0"
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL")
                   or "https://abdulqodir082.github.io/review-cards").rstrip("/")

IMAGE_EXT = {".jpg", ".jpeg"}          # the API only accepts JPEG images
VIDEO_EXT = {".mp4", ".mov"}
MAX_CAPTION = 2200
MAX_HASHTAGS = 30
MAX_MENTIONS = 20
MAX_CAROUSEL = 10
WARN_SIZE_MB = 50                       # GitHub warns above 50 MB, refuses above 100 MB


class PostError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Reading a queued post
# --------------------------------------------------------------------------- #

def load_post(folder: Path) -> dict:
    """Read post.json (+ caption.txt) from a queue folder and check it."""
    meta_file = folder / "post.json"
    if not meta_file.exists():
        raise PostError("missing post.json")
    try:
        post = json.loads(meta_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PostError(f"post.json is not valid JSON: {e}")

    caption_file = folder / "caption.txt"
    if caption_file.exists():
        post["caption"] = caption_file.read_text(encoding="utf-8").strip()
    post.setdefault("caption", "")

    kind = post.get("type")
    if kind not in ("image", "reel", "carousel"):
        raise PostError('"type" must be "image", "reel" or "carousel"')

    media = post.get("media")
    files = media if isinstance(media, list) else [media]
    if not files or not all(isinstance(f, str) and f for f in files):
        raise PostError('"media" must be a file name (or a list for carousel)')
    if kind == "carousel":
        if not isinstance(media, list) or not 2 <= len(media) <= MAX_CAROUSEL:
            raise PostError(f"carousel needs 2-{MAX_CAROUSEL} files in a list")
    elif isinstance(media, list):
        raise PostError(f'"{kind}" takes one file, not a list')

    for name in files:
        path = folder / name
        if not path.is_file():
            raise PostError(f"media file not found: {name}")
        ext = path.suffix.lower()
        if kind == "image" and ext not in IMAGE_EXT:
            raise PostError(f"{name}: images must be .jpg/.jpeg (Instagram API rule)")
        if kind == "reel" and ext not in VIDEO_EXT:
            raise PostError(f"{name}: reels must be .mp4 or .mov")
        if kind == "carousel" and ext not in IMAGE_EXT | VIDEO_EXT:
            raise PostError(f"{name}: carousel items must be .jpg or .mp4/.mov")
        size_mb = path.stat().st_size / 1_000_000
        if size_mb > 95:
            raise PostError(f"{name}: {size_mb:.0f} MB is too big for GitHub (keep under 50 MB)")
        if size_mb > WARN_SIZE_MB:
            print(f"  ! warning: {name} is {size_mb:.0f} MB; try to keep media under {WARN_SIZE_MB} MB")

    cover = post.get("cover")
    if cover is not None:
        if kind != "reel":
            raise PostError('"cover" only works for reels')
        if not (folder / cover).is_file() or Path(cover).suffix.lower() not in IMAGE_EXT:
            raise PostError(f"cover must be an existing .jpg file: {cover}")

    caption = post["caption"]
    if len(caption) > MAX_CAPTION:
        raise PostError(f"caption is {len(caption)} characters (max {MAX_CAPTION})")
    if len(re.findall(r"#\w", caption)) > MAX_HASHTAGS:
        raise PostError(f"caption has more than {MAX_HASHTAGS} hashtags")
    if len(re.findall(r"@\w", caption)) > MAX_MENTIONS:
        raise PostError(f"caption has more than {MAX_MENTIONS} @mentions")

    when = post.get("publish_at")
    if when is not None:
        post["_publish_at"] = parse_time(when)

    post["_files"] = files
    return post


def parse_time(value: str) -> dt.datetime:
    """ISO time; without a timezone it is read as Tashkent time (UTC+5)."""
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise PostError(f'publish_at "{value}" is not a time like 2026-11-10T19:00')
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone(dt.timedelta(hours=5)))
    return t


def queued_folders() -> list[Path]:
    if not QUEUE.exists():
        return []
    return sorted(p for p in QUEUE.iterdir() if p.is_dir())


# --------------------------------------------------------------------------- #
# Graph API helpers
# --------------------------------------------------------------------------- #

def token() -> str:
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not tok:
        sys.exit("IG_ACCESS_TOKEN is not set. Add it under repo Settings > "
                 "Secrets and variables > Actions (see instagram/SETUP.md).")
    return tok


def api(method: str, path: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    params["access_token"] = token()
    url = f"https://{GRAPH_HOST}/{API_VERSION}/{path.lstrip('/')}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            err = json.loads(body).get("error", {})
            msg = err.get("error_user_msg") or err.get("message") or body
        except json.JSONDecodeError:
            msg = body
        raise PostError(f"Instagram API {e.code} on {path}: {msg}") from None


def account() -> tuple[str, str]:
    """Return (ig_user_id, username) for the token."""
    if GRAPH_HOST == "graph.instagram.com":
        me = api("GET", "me", {"fields": "user_id,username"})
        uid = os.environ.get("IG_USER_ID") or me.get("user_id") or me.get("id")
        return str(uid), me.get("username", "?")
    uid = os.environ.get("IG_USER_ID", "").strip()
    if not uid:
        # Find the Instagram account through the Facebook Pages the token can see.
        pages = api("GET", "me/accounts",
                    {"fields": "name,instagram_business_account{id,username}"}).get("data", [])
        found = [p["instagram_business_account"] for p in pages if p.get("instagram_business_account")]
        if len(found) != 1:
            names = ", ".join("@" + f.get("username", "?") for f in found) or "none"
            sys.exit(f"Could not pick the Instagram account automatically (found: {names}). "
                     "Add the IG_USER_ID secret (see instagram/SETUP.md).")
        return str(found[0]["id"]), found[0].get("username", "?")
    me = api("GET", uid, {"fields": "username"})
    return uid, me.get("username", "?")


def public_url(folder: Path, name: str) -> str:
    rel = (folder / name).relative_to(ROOT).as_posix()
    return f"{PUBLIC_BASE_URL}/{urllib.parse.quote(rel)}"


def wait_until_public(url: str, local: Path, timeout: int = 900) -> None:
    """GitHub Pages needs a minute or two after a push. Wait for the file."""
    want = local.stat().st_size
    deadline = time.time() + timeout
    while True:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=30) as r:
                size = int(r.headers.get("Content-Length") or -1)
                if r.status == 200 and size in (-1, want):
                    return
        except urllib.error.URLError:
            pass
        if time.time() > deadline:
            raise PostError(f"file never became public at {url} (is GitHub Pages on?)")
        print("  waiting for GitHub Pages to serve", url)
        time.sleep(20)


def wait_for_container(cid: str, timeout: int = 900) -> None:
    deadline = time.time() + timeout
    while True:
        st = api("GET", cid, {"fields": "status_code,status"})
        code = st.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise PostError(f"Instagram could not process the media: {st.get('status')}")
        if time.time() > deadline:
            raise PostError("Instagram took too long to process the media")
        print(f"  Instagram is processing ({code})...")
        time.sleep(15)


def create_container(uid: str, params: dict) -> str:
    res = api("POST", f"{uid}/media", params)
    if "id" not in res:
        raise PostError(f"no container id returned: {res}")
    return res["id"]


def publish_post(uid: str, folder: Path, post: dict) -> dict:
    kind = post["type"]
    files = post["_files"]
    for name in files + ([post["cover"]] if post.get("cover") else []):
        wait_until_public(public_url(folder, name), folder / name)

    if kind == "image":
        cid = create_container(uid, {"image_url": public_url(folder, files[0]),
                                     "caption": post["caption"]})
    elif kind == "reel":
        params = {"media_type": "REELS",
                  "video_url": public_url(folder, files[0]),
                  "caption": post["caption"],
                  "share_to_feed": "true" if post.get("share_to_feed", True) else "false"}
        if post.get("cover"):
            params["cover_url"] = public_url(folder, post["cover"])
        if post.get("thumb_offset_ms") is not None:
            params["thumb_offset"] = str(int(post["thumb_offset_ms"]))
        cid = create_container(uid, params)
    else:  # carousel
        children = []
        for name in files:
            if Path(name).suffix.lower() in VIDEO_EXT:
                p = {"media_type": "VIDEO", "video_url": public_url(folder, name)}
            else:
                p = {"image_url": public_url(folder, name)}
            p["is_carousel_item"] = "true"
            child = create_container(uid, p)
            wait_for_container(child)
            children.append(child)
        cid = create_container(uid, {"media_type": "CAROUSEL",
                                     "children": ",".join(children),
                                     "caption": post["caption"]})

    wait_for_container(cid)
    media_id = api("POST", f"{uid}/media_publish", {"creation_id": cid})["id"]
    try:
        link = api("GET", media_id, {"fields": "permalink"}).get("permalink")
    except PostError:
        link = None
    return {"media_id": media_id, "permalink": link}


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_validate() -> int:
    folders = queued_folders()
    if not folders:
        print("Queue is empty.")
        return 0
    bad = 0
    for f in folders:
        try:
            post = load_post(f)
            when = post.get("_publish_at")
            print(f"OK   {f.name}: {post['type']}, {len(post['_files'])} file(s), "
                  f"{len(post['caption'])} caption chars"
                  + (f", publish at {when.isoformat()}" if when else ", publish on merge"))
        except PostError as e:
            bad += 1
            print(f"FAIL {f.name}: {e}")
    return 1 if bad else 0


def cmd_check() -> int:
    uid, name = account()
    print(f"Connected to Instagram @{name} (id {uid}). Ready to post.")
    return 0


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def cmd_publish(commit: bool) -> int:
    folders = queued_folders()
    if not folders:
        print("Queue is empty, nothing to post.")
        return 0
    uid, name = account()
    print(f"Posting as @{name}")
    now = dt.datetime.now(dt.timezone.utc)
    failed = 0
    for f in folders:
        try:
            post = load_post(f)
        except PostError as e:
            failed += 1
            print(f"SKIP {f.name}: {e}")
            continue
        when = post.get("_publish_at")
        if when and when > now:
            print(f"WAIT {f.name}: scheduled for {when.isoformat()}")
            continue
        print(f"POST {f.name} ({post['type']})")
        try:
            result = publish_post(uid, f, post)
        except PostError as e:
            failed += 1
            print(f"FAIL {f.name}: {e}")
            continue
        result.update({"posted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                       "account": name, "type": post["type"]})
        print(f"DONE {f.name}: {result.get('permalink') or result['media_id']}")
        dest = POSTED / f.name
        if dest.exists():
            dest = POSTED / f"{f.name}-{int(time.time())}"
        POSTED.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), str(dest))
        (dest / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if commit:
            # Commit right away so a later failure can never post the same thing twice.
            git("add", "-A", "instagram")
            git("commit", "-m", f"instagram: posted {f.name}")
            git("pull", "--rebase", "origin", "main")
            git("push", "origin", "HEAD:main")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as s:
                s.write(f"- Posted **{f.name}**: {result.get('permalink') or result['media_id']}\n")
    return 1 if failed else 0


def cmd_refresh() -> int:
    if GRAPH_HOST != "graph.instagram.com":
        print("This token type does not expire (or is renewed by Meta), nothing to do.")
        return 0
    res = urllib.request.urlopen(
        "https://graph.instagram.com/refresh_access_token?"
        + urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token()}),
        timeout=60)
    data = json.loads(res.read().decode())
    new = data["access_token"]
    days = int(data.get("expires_in", 0)) // 86400
    print(f"Token renewed, valid for about {days} more days.")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{new}")
    out = os.environ.get("NEW_TOKEN_FILE")
    if out:
        Path(out).write_text(new, encoding="utf-8")
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if cmd == "validate":
        return cmd_validate()
    if cmd == "check":
        return cmd_check()
    if cmd == "publish":
        return cmd_publish(commit="--commit" in sys.argv)
    if cmd == "refresh-token":
        return cmd_refresh()
    sys.exit(__doc__)


if __name__ == "__main__":
    sys.exit(main())
