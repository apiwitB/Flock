from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    queue_url: str
    image_root: Path
    session_ttl: timedelta
    cookie_secure: bool
    writer_name: str

    @classmethod
    def from_env(cls) -> Settings:
        def need(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise SystemExit(f"ต้องตั้งค่า environment variable {name}")
            return value

        return cls(
            database_url=need("FLOCK_DATABASE_URL"),
            queue_url=need("FLOCK_QUEUE_URL"),
            image_root=Path(os.environ.get("FLOCK_IMAGE_ROOT", "/data/images")),
            session_ttl=timedelta(hours=float(os.environ.get("FLOCK_SESSION_HOURS", "8"))),
            cookie_secure=os.environ.get("FLOCK_COOKIE_SECURE", "true").lower() != "false",
            writer_name=os.environ.get("FLOCK_WRITER_NAME", socket.gethostname()),
        )
