# Instagram poster

Posts to the Otvizcards Instagram account with Meta's free official API
(Instagram Graph API; system-user token via Unified login, or Instagram Login). Runs in GitHub Actions
(`.github/workflows/instagram.yml`), Python standard library only.

First-time setup for Ali: [SETUP.md](SETUP.md).

## How a post goes live

1. Someone (usually Claude) opens a **pull request** that adds a folder to `instagram/queue/`.
2. The PR check runs `publish.py validate` (file types, caption length, hashtags).
3. **Ali reviews the PR and merges it. Merging is the approval.** Nothing in the
   queue may be pushed straight to `main`.
4. On merge, the workflow waits for GitHub Pages to serve the media, publishes
   it, then moves the folder to `instagram/posted/<name>/` with a `result.json`
   holding the post id and link.

Posts with `publish_at` in the future stay in the queue and go out at the first
hourly run after that time.

## Post folder format

```
instagram/queue/2026-11-10-reel-launch/
  post.json
  caption.txt     (optional, multi-line caption; wins over "caption" in post.json)
  ad.mp4
  cover.jpg       (optional, reels only)
```

`post.json`:

```json
{
  "type": "reel",
  "media": "ad.mp4",
  "cover": "cover.jpg",
  "share_to_feed": true,
  "publish_at": "2026-11-10T19:00"
}
```

| Field | Notes |
|---|---|
| `type` | `image`, `reel` or `carousel` |
| `media` | one file name; a list of 2–10 for `carousel` |
| `caption` | or use `caption.txt`. Max 2200 chars, 30 hashtags, 20 @mentions |
| `cover` | reels only, `.jpg` |
| `thumb_offset_ms` | reels only, frame to use as cover if no `cover` |
| `share_to_feed` | reels only, default `true` |
| `publish_at` | optional. No timezone = Tashkent time (UTC+5) |

Media rules from Instagram: images must be **JPEG** (4:5 to 1.91:1, 1080 px wide
is best). Reels: **MP4/MOV, H.264 + AAC, 9:16, 1080×1920, 3 s–15 min**, keep
files under 50 MB so GitHub accepts them. See `example-post/` for a sample.

## Manual runs

Actions → **Instagram poster** → Run workflow:

- `check`: test the token and show the account name.
- `publish`: publish whatever is due in the queue now.
- `refresh-token`: renew the 60-day token now.

Locally: `python3 instagram/publish.py validate`.

## Secrets

| Secret | Needed | What |
|---|---|---|
| `IG_ACCESS_TOKEN` | yes | system-user token (`EAA...`, never expires) or Instagram-Login token (`IG...`, 60 days); SETUP.md |
| `GH_SECRETS_PAT` | optional | fine-grained token with Secrets read/write on this repo, so the renewed token is saved automatically |
| `IG_USER_ID` | optional | only if the account id cannot be read from the token |
