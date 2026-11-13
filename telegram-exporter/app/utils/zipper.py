"""Zip an export folder and split it into numbered volumes if it is too big.

Volumes are named ``<name>.zip.001``, ``.002`` …  They are a byte-split of a
single zip archive: 7-Zip, WinRAR, ZArchiver (Android) and Keka (macOS) open
``.001`` directly; on Linux/macOS ``cat name.zip.0* > name.zip`` rejoins them.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Callable

# Already-compressed formats are stored instead of deflated (much faster, same size).
STORED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".mkv", ".webm",
    ".ogg", ".oga", ".opus", ".mp3", ".m4a", ".aac", ".zip", ".rar", ".7z",
    ".gz", ".xz", ".bz2", ".tgs", ".heic", ".avi", ".flac",
}

CHUNK = 4 * 1024 * 1024


def zip_directory(src: Path, zip_path: Path, on_progress: Callable[[int, int], None] | None = None) -> Path:
    """Zip ``src`` so that the archive contains ``src.name/`` as its root folder."""
    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.endswith(".part"))
    total = len(files)
    tmp = zip_path.with_name(zip_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as zf:
        for i, path in enumerate(files, start=1):
            arcname = f"{src.name}/{path.relative_to(src).as_posix()}"
            method = zipfile.ZIP_STORED if path.suffix.lower() in STORED_EXTENSIONS else zipfile.ZIP_DEFLATED
            zf.write(path, arcname, compress_type=method)
            if on_progress:
                on_progress(i, total)
    os.replace(tmp, zip_path)
    return zip_path


def split_file(path: Path, part_size: int) -> list[Path]:
    """Split ``path`` into ``path.001``, ``path.002`` … of at most ``part_size`` bytes."""
    if part_size <= 0:
        raise ValueError("part_size must be positive")
    if path.stat().st_size <= part_size:
        return [path]
    parts: list[Path] = []
    with path.open("rb") as src:
        index = 0
        while True:
            index += 1
            part_path = path.with_name(f"{path.name}.{index:03d}")
            written = 0
            with part_path.open("wb") as dst:
                while written < part_size:
                    chunk = src.read(min(CHUNK, part_size - written))
                    if not chunk:
                        break
                    dst.write(chunk)
                    written += len(chunk)
            if written == 0:
                part_path.unlink()
                break
            parts.append(part_path)
            if written < part_size:
                break
    path.unlink()
    return parts


def make_archive(src: Path, dest_dir: Path, part_size: int,
                 on_progress: Callable[[int, int], None] | None = None) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dest_dir / f"{src.name.replace(' ', '_')}.zip"
    zip_directory(src, zip_path, on_progress)
    return split_file(zip_path, part_size)
