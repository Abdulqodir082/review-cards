#!/usr/bin/env python3
"""Create the user (MTProto) session interactively in the terminal.

Run once:  python login.py        (or: docker compose run --rm exporter python login.py)
Log out:   python login.py --logout

Login is deliberately NOT possible through the bot: Telegram invalidates login
codes that are forwarded inside Telegram messages, and typing your 2FA password
into a chat would leave it in message history.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from telethon import TelegramClient, errors

from app.config import ConfigError, load_user_config

REPO_ROOT = Path(__file__).resolve().parent


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


async def login(logout: bool) -> int:
    try:
        api_id, api_hash, session_dir = load_user_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if _inside_repo(session_dir):
        print(
            f"Refusing to store the session inside the repository ({session_dir}).\n"
            "Set SESSION_DIR to a directory outside the project (default: ~/.tg-exporter).",
            file=sys.stderr,
        )
        return 2
    session_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(session_dir, 0o700)

    session_path = session_dir / "user"
    session_file = Path(f"{session_path}.session")
    client = TelegramClient(str(session_path), api_id, api_hash, device_model="Chat Exporter")

    if logout:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
            print("Logged out and session revoked.")
        else:
            await client.disconnect()
            session_file.unlink(missing_ok=True)
            print("No active session.")
        return 0

    try:
        await client.start(
            phone=lambda: input("Phone number (international format, e.g. +15551234567): ").strip(),
            code_callback=lambda: input("Login code (from the Telegram app): ").strip(),
            password=lambda: getpass.getpass("Two-step verification password: "),
        )
    except errors.PhoneNumberInvalidError:
        print("That phone number is not valid.", file=sys.stderr)
        return 1
    except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
        print("The code was wrong or expired. Run login.py again.", file=sys.stderr)
        return 1
    except errors.FloodWaitError as exc:
        print(f"Too many attempts. Telegram asks to wait {exc.seconds} seconds.", file=sys.stderr)
        return 1

    me = await client.get_me()
    await client.disconnect()
    os.chmod(session_file, 0o600)
    name = " ".join(x for x in (me.first_name, me.last_name) if x)
    print(f"\nLogged in as {name} (@{me.username or '-'}).")
    print(f"Session saved to {session_file} (mode 600). Keep it secret: it grants full account access.")
    print(f"Your Telegram user ID is {me.id} — put OWNER_ID={me.id} in .env")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--logout", action="store_true", help="log out and revoke the session")
    args = parser.parse_args()
    sys.exit(asyncio.run(login(args.logout)))


if __name__ == "__main__":
    main()
