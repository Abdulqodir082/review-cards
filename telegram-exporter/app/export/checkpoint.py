"""On-disk checkpoint so an interrupted export can be resumed with /resume.

Layout (inside ``EXPORT_DIR/.state``):
  job.json       – chat, options, output folder, counters
  records.jsonl  – one converted ExportMessage per line, appended in order
A message is appended only after its media finished downloading, so the last
line is always a fully processed message; a torn final line is discarded.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .models import ChatInfo, ExportMessage, ExportOptions

log = logging.getLogger(__name__)


@dataclass
class JobSpec:
    chat: ChatInfo
    options: ExportOptions
    output_dir: str
    created_at: int
    counters: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chat": asdict(self.chat),
            "options": self.options.to_dict(),
            "output_dir": self.output_dir,
            "created_at": self.created_at,
            "counters": self.counters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobSpec":
        return cls(
            chat=ChatInfo(**data["chat"]),
            options=ExportOptions.from_dict(data["options"]),
            output_dir=data["output_dir"],
            created_at=data["created_at"],
            counters=data.get("counters", {}),
        )


class Checkpoint:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.job_path = state_dir / "job.json"
        self.records_path = state_dir / "records.jsonl"
        self._fh = None
        self._since_sync = 0

    # -- job --
    def exists(self) -> bool:
        return self.job_path.exists()

    def start(self, job: JobSpec) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.records_path.write_text("", encoding="utf-8")
        self.save_job(job)

    def save_job(self, job: JobSpec) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.job_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.job_path)

    def load_job(self) -> JobSpec:
        return JobSpec.from_dict(json.loads(self.job_path.read_text(encoding="utf-8")))

    # -- records --
    def repair(self) -> None:
        """Drop a partially written trailing line (crash mid-write)."""
        if not self.records_path.exists():
            return
        data = self.records_path.read_bytes()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            with self.records_path.open("r+b") as fh:
                fh.truncate(cut)
            log.warning("checkpoint: dropped torn trailing record", extra={"bytes": len(data) - cut})

    def append(self, msg: ExportMessage) -> None:
        if self._fh is None:
            self._fh = self.records_path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")
        self._fh.flush()
        self._since_sync += 1
        if self._since_sync >= 200:
            os.fsync(self._fh.fileno())
            self._since_sync = 0

    def close(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            self._fh = None

    def iter_records(self) -> Iterator[ExportMessage]:
        if not self.records_path.exists():
            return
        with self.records_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield ExportMessage.from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError) as exc:
                    log.warning("checkpoint: skipping unreadable record", extra={"error": str(exc)})

    def summary(self) -> tuple[int, int]:
        """(record count, last message id)."""
        count, last_id = 0, 0
        for rec in self.iter_records():
            count += 1
            last_id = rec.id
        return count, last_id

    def clear(self) -> None:
        self.close()
        if self.state_dir.exists():
            shutil.rmtree(self.state_dir, ignore_errors=True)


class RecordStore:
    """Re-iterable view over the checkpointed records (the writers read it twice)."""

    def __init__(self, checkpoint: Checkpoint):
        self.checkpoint = checkpoint

    def __iter__(self) -> Iterator[ExportMessage]:
        return self.checkpoint.iter_records()
