#!/usr/bin/env python3
"""
Generate one QR-code PNG per card, each pointing at the redirect page:

    https://<USER>.github.io/<REPO>/r.html?id=001

Every card is physically different (different id in the QR), but where each card
sends people is controlled entirely by mapping.json — so you can reassign a card
to a new business anytime from admin.html without reprinting.

Setup once:
    pip install "qrcode[pil]"

Then edit the three CONFIG values below and run:
    python generate_qr.py
"""

import csv
import os
import qrcode

# ---------------------------------------------------------------------------
# CONFIG — set these, then run `python generate_qr.py` (no arguments needed).
# ---------------------------------------------------------------------------
GITHUB_USER = "Abdulqodir082"  # GitHub username that owns the Pages site
GITHUB_REPO = "review-cards"  # the repo you deploy to GitHub Pages
NUM_CARDS   = 200             # how many cards to generate
START_AT    = 1               # first card number
# ---------------------------------------------------------------------------

OUT_DIR = "qr_codes"


def base_url() -> str:
    return f"https://{GITHUB_USER}.github.io/{GITHUB_REPO}/r.html"


def main() -> None:
    if not GITHUB_USER:
        raise SystemExit(
            "Set GITHUB_USER at the top of this file to your GitHub username, "
            "then run `python generate_qr.py` again."
        )

    os.makedirs(OUT_DIR, exist_ok=True)

    rows = []  # (card_id, png_filename, url) for the supplier CSV
    for n in range(START_AT, START_AT + NUM_CARDS):
        card_id = f"{n:03d}"                       # 001, 002, …
        url = f"{base_url()}?id={card_id}"

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=12,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        filename = f"card_{card_id}.png"
        img.save(os.path.join(OUT_DIR, filename))
        rows.append((card_id, filename, url))

    csv_path = os.path.join(OUT_DIR, "card_urls_for_supplier.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["card_id", "png_file", "url"])
        writer.writerows(rows)

    print(f"Done. {NUM_CARDS} QR codes written to ./{OUT_DIR}/")
    print(f"Supplier sheet: ./{OUT_DIR}/card_urls_for_supplier.csv")
    print(f"Each encodes: {base_url()}?id=NNN")


if __name__ == "__main__":
    main()
