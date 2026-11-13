# Telegram Chat Exporter (bot-controlled)

A self-hosted copy of Telegram Desktop's **Export chat history**, controlled from
your phone through your own Telegram bot. The result is the same folder Desktop
produces (`messages.html`, `result.json`, `photos/`, `video_files/`, …), zipped
and sent to you in the bot chat.

```
 your phone ──► your bot (Bot API token)  ─┐
                                           ├─ one Python process (asyncio)
 your account ◄── user client (MTProto) ───┘      reads history, downloads media
```

Bots cannot read your private chats, so the process runs **two Telethon clients**:

| Client | Logged in as | Used for |
|---|---|---|
| user client | **your account** (session from `login.py`) | listing dialogs, reading history, downloading media |
| bot client | the bot from @BotFather | the buttons and messages you use on your phone |

The bot answers **only `OWNER_ID`**. Messages from anyone else are silently ignored.

---

## Setup

### 1. Get `API_ID` and `API_HASH`

1. Open <https://my.telegram.org> and log in with your phone number.
2. Click **API development tools**.
3. Create an application (any title and short name, e.g. `chatexport`; platform: *Other*).
4. Copy **App api_id** → `API_ID` and **App api_hash** → `API_HASH`.

Keep these private: together with a session they identify your app.

### 2. Create the bot

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a name and a username ending in `bot`.
3. Copy the token (`123456789:AA…`) → `BOT_TOKEN`.
4. Open your new bot and press **Start**. A bot can only message you after you've started it.

### 3. Find your `OWNER_ID`

Either:
- run `login.py` (step 5): it prints `Your Telegram user ID is …`, or
- message **@userinfobot** and copy the number it replies with.

### 4. Configure

```bash
git clone <this repo> && cd telegram-exporter
cp .env.example .env
nano .env        # fill API_ID, API_HASH, BOT_TOKEN, OWNER_ID
```

| Variable | Default | Meaning |
|---|---|---|
| `API_ID`, `API_HASH` | — | from my.telegram.org |
| `BOT_TOKEN` | — | from @BotFather |
| `OWNER_ID` | — | your numeric user id; the only user the bot answers |
| `EXPORT_DIR` | `./exports` | exports, checkpoints (`.state/`) and logs (`logs/`) |
| `MAX_PART_SIZE_MB` | `1900` | zips larger than this are split into volumes (max 2000, the bot upload limit) |
| `KEEP_EXPORTS` | `false` | keep the folder and zip on the server after sending |
| `SESSION_DIR` | `~/.tg-exporter` | where the user session lives (**must be outside the repo**) |
| `TZ` | `UTC` | timezone for dates in the export and for custom ranges |
| `LOG_LEVEL` | `INFO` | `DEBUG` for more detail |

### 5. Log in your account (once)

Login happens **only in the terminal**, never through the bot. Telegram
invalidates login codes that are forwarded inside Telegram messages, and typing a
2FA password into a chat would leave it in history.

**With Docker (recommended on a VPS):**

```bash
mkdir -p exports && sudo chown 1000:1000 exports   # the container runs as uid 1000
docker compose build
docker compose run --rm exporter python login.py
```

**Without Docker:**

```bash
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python login.py
```

You'll be asked for your phone number, the code Telegram sends to your app, and
your two-step verification password if you have one. The session is saved as
`$SESSION_DIR/user.session` with mode `600` (in Docker, in the named volume
`session`). `login.py` refuses to save it inside the project folder, and
`*.session` is in `.gitignore`.

> ⚠️ The session file gives **full access to your account**. Never share or
> commit it. To revoke it: `python login.py --logout`, or Telegram → Settings →
> Devices → terminate "Chat Exporter".

### 6. Run

```bash
docker compose up -d
docker compose logs -f        # "running — send /start to the bot from your account"
```

Without Docker: `python -m app.main`.

Updating later: `git pull && docker compose up -d --build`. The session volume is kept.

---

## Using the bot

| Command | What it does |
|---|---|
| `/start`, `/help` | short help |
| `/chats` | your dialogs, 10 per page, with icons 👤 private · 👥 group · 📢 channel · 🤖 bot · ⭐ saved |
| `/search <text>` | find a dialog by name or `@username` |
| `/status` | progress of the current job, or info about an unfinished one |
| `/cancel` | stop the current export (progress is kept) |
| `/resume` | continue an interrupted or stopped export |
| `/discard` | delete an unfinished export and its checkpoint |

After you pick a chat you get Desktop-style toggles:

- **Media:** Photos · Videos · Voice messages · Video messages · Stickers · GIFs · Files
- **Max file size:** 8 MB · 50 MB · 500 MB · No limit
- **Period:** All time · 7 days · 30 days · Custom… (then send `2024-01-01 2024-03-31`; both days inclusive, in `TZ`)
- **Format:** HTML · JSON · Both
- **▶️ Start export** / **✖️ Cancel**

While it runs, a single progress message updates at most every 3 seconds: stage,
messages processed / estimated total, media downloaded/skipped/failed, size, and
`⏳ waiting Xs (Telegram rate limit)` during flood waits. It has a **⏹ Stop**
button. Only one export runs at a time; starting another while one is running
(or while an unfinished one exists) is rejected with a hint.

When it's finished you receive the zip as a document. If it's larger than
`MAX_PART_SIZE_MB`, you get numbered volumes `ChatExport_….zip.001`, `.002`, …
Open the `.001` file with 7-Zip / WinRAR (Windows), ZArchiver (Android) or Keka
(macOS), or rejoin with `cat ChatExport_*.zip.0* > export.zip`.

---

## Output format

```
ChatExport_2026-11-13/
├── messages.html, messages2.html, …   1000 messages per page, prev/next links
├── result.json                        Desktop JSON schema
├── css/style.css  js/script.js  images/
├── photos/  video_files/  voice_messages/  round_video_messages/  stickers/  files/
```

**result.json** has the top-level `name`, `type` (`personal_chat`, `bot_chat`,
`saved_messages`, `private_group`, `private_supergroup`, `public_supergroup`,
`private_channel`, `public_channel`), `id`, and `messages[]`. Each message
contains, where they apply: `id`, `type` (`message`/`service`), `date`,
`date_unixtime`, `edited`, `edited_unixtime`, `from`, `from_id`
(`user123`/`channel123`), `author`, `forwarded_from`, `reply_to_message_id`,
`via_bot`, `photo`, `photo_file_size`, `file`, `file_name`, `file_size`,
`thumbnail`, `media_type`, `mime_type`, `duration_seconds`, `width`, `height`,
`sticker_emoji`, `performer`, `title`, `poll`, `contact_information`,
`location_information`, `place_name`, `address`, `reactions`, and always `text`
(a string, or a mixed array of strings and entity objects) plus `text_entities`.
Service messages carry `actor`, `actor_id` and `action`
(`invite_members`, `pin_message`, `phone_call`, …) plus action fields
(`members`, `title`, `message_id`, `duration_seconds`, …).

**HTML** follows Desktop's layout: bubbles with userpic initials, consecutive
messages from the same sender joined (within 15 minutes), date separators,
reply previews that link to the original message (across pages too), forwarded
headers, inline photo/video thumbnails, links to files, polls, reactions, and
formatted entities (bold, italic, underline, strikethrough, code, pre, links,
mentions, spoilers, blockquotes). It also follows the system dark mode.

Media that wasn't downloaded is still listed, with Desktop's wording:
- over the size limit → *File exceeds maximum size. Change data exporting settings to download.*
- type switched off → *File not included. Change data exporting settings to download.*
- still failing after 3 attempts → *File unavailable, please try again later*

---

## Reliability

- **Rate limits:** the user client runs with `flood_sleep_threshold=0`, so every
  `FloodWaitError` reaches the exporter. It shows the countdown in the progress
  message, sleeps, and restarts history iteration from the last saved message.
- **Order and range:** history is read oldest → newest with
  `iter_messages(reverse=True)`, using `offset_date` for the range start and
  `min_id` when resuming; reading stops at the range end.
- **Checkpoints:** each message is appended to `EXPORT_DIR/.state/records.jsonl`
  as soon as its media is on disk (`job.json` holds chat, options and counters).
  After a crash, restart or **Stop**, `/resume` continues after the last saved
  message, and the bot reminds you on startup.
- **Downloads** go to `*.part` and are renamed when complete. Each one gets up to
  3 attempts with backoff, and expired file references are refreshed. If all
  attempts fail, the message is marked failed in the output and the export
  continues.
- **Logging:** readable lines on stdout (`docker compose logs`) and JSON lines in
  `EXPORT_DIR/logs/exporter.log` (rotated, 5 × 10 MB).

---

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover `json_writer` and `html_writer` using fake message objects
(`tests/conftest.py`), the zipper, checkpoints and progress throttling, plus an
end-to-end exporter run against a fake Telethon client built from real TL
objects. That run covers flood wait, resume, size/type skips, failed downloads
and date ranges.

```
app/
  main.py               starts both clients
  config.py             .env settings
  bot/handlers.py       commands + callbacks (owner only)
  bot/keyboards.py      inline keyboards
  bot/states.py         UI state, single-job manager
  bot/jobs.py           export → zip → upload → cleanup
  export/exporter.py    history fetch, Telethon → model conversion, media download
  export/models.py      Telethon-independent message model + options
  export/entities.py    UTF-16 entity splitting shared by both writers
  export/checkpoint.py  resumable on-disk state
  export/json_writer.py result.json
  export/html_writer.py messages*.html
  export/templates/     Jinja2 templates
  export/static/        css, js, images
  utils/progress.py     throttled progress message
  utils/zipper.py       zip + split into volumes
  utils/logging_setup.py
login.py                interactive terminal login
```
