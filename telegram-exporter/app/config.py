"""Application configuration loaded from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when a required setting is missing or invalid."""


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required setting {name} (see .env.example)")
    return value


def _int(name: str, default: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        if default is None:
            raise ConfigError(f"Missing required setting {name} (see .env.example)")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Setting {name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Setting {name} must be true/false, got {raw!r}")


DEFAULT_SESSION_DIR = Path.home() / ".tg-exporter"


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    owner_id: int
    export_dir: Path
    session_dir: Path
    max_part_size_mb: int
    keep_exports: bool
    log_dir: Path
    log_level: str
    timezone: ZoneInfo

    @property
    def user_session_path(self) -> Path:
        # Telethon appends ".session" itself.
        return self.session_dir / "user"

    @property
    def bot_session_path(self) -> Path:
        return self.session_dir / "bot"

    @property
    def state_dir(self) -> Path:
        return self.export_dir / ".state"

    @property
    def max_part_size_bytes(self) -> int:
        return self.max_part_size_mb * 1024 * 1024


def load_user_config(env_file: str | None = None) -> tuple[int, str, Path]:
    """Minimal settings needed by login.py (no bot token / owner required)."""
    load_dotenv(env_file)
    session_dir = Path(os.getenv("SESSION_DIR", "") or DEFAULT_SESSION_DIR).expanduser()
    return _int("API_ID"), _require("API_HASH"), session_dir


def load_config(env_file: str | None = None) -> Config:
    load_dotenv(env_file)
    tz_name = os.getenv("TZ", "").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 - zoneinfo raises several types
        raise ConfigError(f"Unknown timezone TZ={tz_name!r}") from exc

    max_part = _int("MAX_PART_SIZE_MB", 1900)
    if not 1 <= max_part <= 2000:
        raise ConfigError("MAX_PART_SIZE_MB must be between 1 and 2000 (bot upload limit is 2 GB)")

    export_dir = Path(os.getenv("EXPORT_DIR", "") or "./exports").expanduser().resolve()
    return Config(
        api_id=_int("API_ID"),
        api_hash=_require("API_HASH"),
        bot_token=_require("BOT_TOKEN"),
        owner_id=_int("OWNER_ID"),
        export_dir=export_dir,
        session_dir=Path(os.getenv("SESSION_DIR", "") or DEFAULT_SESSION_DIR).expanduser().resolve(),
        max_part_size_mb=max_part,
        keep_exports=_bool("KEEP_EXPORTS", False),
        log_dir=Path(os.getenv("LOG_DIR", "") or export_dir / "logs").expanduser().resolve(),
        log_level=(os.getenv("LOG_LEVEL", "") or "INFO").upper(),
        timezone=tz,
    )
