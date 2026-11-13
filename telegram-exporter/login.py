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

from telethon import TelegramClient, errors, functions
from telethon.tl import types

from app.config import ConfigError, load_user_config

REPO_ROOT = Path(__file__).resolve().parent


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def describe_code(sent) -> str:
    """Explain in plain words where Telegram sent the login code."""
    t = getattr(sent, "type", None)
    name = type(t).__name__
    if name == "SentCodeTypeApp":
        where = (
            "as a MESSAGE in the Telegram app: open the chat named \"Telegram\" (blue checkmark)\n"
            "  on any device where you are already logged in (check Archived Chats too)"
        )
    elif name in ("SentCodeTypeSms", "SentCodeTypeSmsWord", "SentCodeTypeSmsPhrase", "SentCodeTypeFirebaseSms"):
        where = "by SMS to your phone"
    elif name == "SentCodeTypeFragmentSms":
        where = f"via fragment.com ({getattr(t, 'url', '')})"
    elif name == "SentCodeTypeCall":
        where = "by a PHONE CALL — a voice will read the code"
    elif name == "SentCodeTypeFlashCall":
        where = "by a short phone call — the code is the caller's number"
    elif name == "SentCodeTypeMissedCall":
        where = f"by a missed call — the code is the last {getattr(t, 'length', '?')} digits of the caller's number"
    elif name == "SentCodeTypeEmailCode":
        where = f"by EMAIL to {getattr(t, 'email_pattern', 'your login email')}"
    elif name == "SentCodeTypeSetUpEmailRequired":
        where = "nowhere yet: Telegram requires a login email on this account (see below)"
    else:
        where = f"by an unknown method ({name})"
    text = f"Telegram sent the code {where}."
    nxt = getattr(sent, "next_type", None)
    if nxt is not None:
        how = {
            "CodeTypeSms": "SMS",
            "CodeTypeCall": "a phone call",
            "CodeTypeFlashCall": "a flash call",
            "CodeTypeMissedCall": "a missed call",
            "CodeTypeFragmentSms": "fragment.com",
        }.get(type(nxt).__name__, type(nxt).__name__)
        wait = getattr(sent, "timeout", None)
        text += f"\nNot received? Type r to resend it by {how}" + (f" (possible after ~{wait}s)." if wait else ".")
    else:
        text += "\nNo other delivery method is offered for this account."
    return text


async def _interactive_sign_in(client: TelegramClient) -> int:
    phone = input("Phone number (international format, e.g. +15551234567): ").strip()
    try:
        sent = await client.send_code_request(phone)
    except errors.PhoneNumberInvalidError:
        print("That phone number is not valid.", file=sys.stderr)
        return 1
    except errors.PhoneNumberBannedError:
        print("Telegram reports this phone number as banned.", file=sys.stderr)
        return 1
    except errors.FloodWaitError as exc:
        print(f"Too many attempts. Telegram asks to wait {exc.seconds} seconds.", file=sys.stderr)
        return 1

    if isinstance(sent, types.auth.SentCodeSuccess):
        return 0
    if isinstance(sent, types.auth.SentCodePaymentRequired):
        print("Telegram requires a paid/Premium step to send a login code to this number.", file=sys.stderr)
        return 1

    print("\n" + describe_code(sent) + "\n")
    if type(sent.type).__name__ == "SentCodeTypeSetUpEmailRequired":
        print(
            "Open Telegram > Settings > Privacy and Security > Login Email, add an email,\n"
            "then run login.py again.",
            file=sys.stderr,
        )
        return 1

    code_hash = sent.phone_code_hash
    while True:
        code = input("Login code (r = resend another way, q = quit): ").strip()
        if code.lower() == "q":
            return 1
        if code.lower() == "r":
            try:
                sent = await client(functions.auth.ResendCodeRequest(phone, code_hash))
                code_hash = sent.phone_code_hash
                print("\n" + describe_code(sent) + "\n")
            except errors.SendCodeUnavailableError:
                print("Telegram has no other way to send the code right now. Wait a few minutes and run login.py again.")
            except errors.FloodWaitError as exc:
                print(f"Too many attempts. Telegram asks to wait {exc.seconds} seconds.")
            except errors.RPCError as exc:
                print(f"Resend not possible yet: {exc.__class__.__name__}. Wait the time shown above and try again.")
            continue
        if not code:
            continue
        try:
            await client.sign_in(phone, code, phone_code_hash=code_hash)
            return 0
        except errors.SessionPasswordNeededError:
            while True:
                try:
                    await client.sign_in(password=getpass.getpass("Two-step verification password: "))
                    return 0
                except errors.PasswordHashInvalidError:
                    print("Wrong password, try again.")
        except errors.PhoneCodeInvalidError:
            print("That code is wrong — try again.")
        except errors.PhoneCodeExpiredError:
            print("That code has expired. Type r to get a new one, or q and run login.py again.")


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

    await client.connect()
    if not await client.is_user_authorized():
        result = await _interactive_sign_in(client)
        if result != 0:
            await client.disconnect()
            return result

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
