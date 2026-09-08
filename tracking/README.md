# Review tracking (Google Places API)

Automated daily snapshots of each business's Google **rating** and **review count**,
using Google's official Places API (New) — no scraping. Results append to
`tracking-history.json` at the repo root so the dashboard can chart growth over time.

## Files
| File | Purpose |
|---|---|
| `businesses.json` | The list of businesses to track (name, card id, Place ID). |
| `snapshot.mjs` | Calls Places API, appends one record per business per day. |
| `find-place-id.mjs` | Helper: turn a business name into a Place ID. |
| `../tracking-history.json` | The growing array of snapshots. |
| `../.github/workflows/daily-snapshot.yml` | Runs `snapshot.mjs` daily and commits results. |

---

## 1. Get a Google Cloud API key (do this once)

Google requires a billing account even for free usage, but this volume (a handful
of businesses × once a day) stays comfortably inside the free tier.

1. Go to **https://console.cloud.google.com/** and sign in.
2. **Create a project:** top bar → project dropdown → **New Project** → name it
   `otvizcards` → **Create**. Make sure it's selected in the top bar afterward.
3. **Enable billing** (required, but you won't be charged at this volume):
   left menu (☰) → **Billing** → **Link a billing account** → add a card if you
   don't have one. *(You add the card yourself — never share it with anyone.)*
4. **Enable the API:** ☰ → **APIs & Services** → **Library** → search
   **“Places API (New)”** → click it → **Enable**.
5. **Create the key:** ☰ → **APIs & Services** → **Credentials** →
   **+ Create credentials** → **API key**. Copy the key it shows.
6. **Restrict the key** (recommended): on that key → **Edit** →
   - *API restrictions* → **Restrict key** → check **Places API (New)** → Save.
   - (Optional) leave *Application restrictions* as **None** — GitHub Actions runs
     from changing IPs, so IP restriction won't work here.

Keep the key private. It goes into a GitHub **Secret** (next section), never into
the code or any committed file.

---

## 2. Add the key to GitHub (so the daily job can use it)

1. In the repo on GitHub: **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret** → Name: `GOOGLE_MAPS_API_KEY` → Value: *(paste the key)* → **Add secret**.

---

## 3. Add your businesses

For each business you need its **Place ID**. Find it from the name:

```bash
GOOGLE_MAPS_API_KEY=your_key_here node tracking/find-place-id.mjs "O'zbegim Lavash, Sho'rchi"
```

Copy the correct Place ID into `tracking/businesses.json`:

```json
{
  "businesses": [
    { "card_id": "019", "name": "O'zbegim Lavash", "place_id": "ChIJ..." }
  ]
}
```

Commit that change.

---

## 4. Run it

- **Automatically:** the workflow runs every day at 06:00 UTC and commits the new
  snapshot. Nothing to do.
- **On demand:** GitHub → **Actions** → **Daily review snapshot** → **Run workflow**.
- **Locally (to test):**
  ```bash
  GOOGLE_MAPS_API_KEY=your_key_here node tracking/snapshot.mjs
  ```
- **Plumbing test without a key** (writes fake data — reset the file afterward):
  ```bash
  SNAPSHOT_FAKE=1 node tracking/snapshot.mjs
  ```

Each record looks like:
```json
{ "card_id":"019","business_name":"O'zbegim Lavash","place_id":"ChIJ...",
  "date":"2026-09-08","collected_at":"2026-09-08T06:00:12Z",
  "rating":4.6,"review_count":128 }
```

Running twice in one day won't create duplicates — same business + same date is skipped.
