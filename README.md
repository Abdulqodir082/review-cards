# Review Cards

Reusable QR/NFC review cards. Every physical card points at one redirect page
(`r.html?id=NNN`). The redirect looks the card's id up in `mapping.json` and
forwards the visitor to whatever review link that card is currently assigned to.

Because the destination lives in `mapping.json` — not in the QR — you can hand a
card to a business today, and reassign it to a different business next month
**without reprinting anything**. You just edit the mapping from your phone.

```
QR / NFC on card  →  https://<user>.github.io/<repo>/r.html?id=001
                                      │
                                      ▼
                          r.html reads mapping.json
                                      │
                          "001": "https://g.page/..."   →  redirect
```

## Files

| File              | What it does                                                        |
|-------------------|---------------------------------------------------------------------|
| `r.html`          | Redirect page every card points to. `r.html?id=001` → destination.  |
| `mapping.json`    | The card → review-link lookup table (10 demo cards to start).        |
| `admin.html`      | Phone-friendly panel to assign/reassign any card. Commits via GitHub.|
| `generate_qr.py`  | Generates the QR PNGs once you know your real Pages URL.             |

## Deploy (one time)

1. Create a **public** GitHub repo named `review-cards`.
2. Push all of these files to the `main` branch (root of the repo).
3. Repo → **Settings → Pages** → Source: **Deploy from a branch** → `main` / `/ (root)` → Save.
4. Wait ~1 min. Your site is `https://<username>.github.io/review-cards/`.
   - Redirect page: `https://<username>.github.io/review-cards/r.html?id=001`
   - Admin panel:   `https://<username>.github.io/review-cards/admin.html`

> If you have Claude Code installed, it can do steps 1–3 for you on your machine
> (where you're logged into GitHub). See the prompt in the chat.

## Make the QR codes

```bash
pip install "qrcode[pil]"
# edit GITHUB_USER / REPO_NAME at the top of generate_qr.py
python generate_qr.py     # writes qr_codes/card_001.png … card_100.png
```

Send the PNGs to your card printer.

## Assign a card to a business

1. Open `admin.html` on your phone (bookmark it).
2. Enter your GitHub username, repo (`review-cards`), and a **fine-grained token**.
3. **Connect & load cards**, edit the destination URL for a card, **Save changes**.

Live cards pick up the new link within a minute (the redirect page cache-busts,
so it's usually instant).

### The token `admin.html` needs

Create a **fine-grained personal access token** limited to this one repo:

- GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- **Repository access:** Only select repositories → `review-cards`
- **Permissions → Repository permissions → Contents: Read and write**
- Set an expiration you're comfortable with; regenerate when it lapses.

The token is stored only in your phone's browser (and only if you tap
“Remember on this phone”). It's sent directly to GitHub and nowhere else.
Revoke it anytime from the same settings page.

## Notes

- Cards for businesses that haven't said yes yet can point anywhere (a demo page,
  your own site). Assign the real review link the moment they're on board.
- `error_correction=M` in `generate_qr.py` tolerates minor print smudging. Bump
  to `H` if cards will be laminated/handled heavily.
