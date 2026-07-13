"""Single-host leader election for commands received by every bot process."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path


class ProcessLeaderLock:
    def __init__(self, path: str | None = None) -> None:
        lock_path = Path(path or os.getenv(
            "CACHE_COMMAND_LOCK_FILE", "/tmp/gallery-image-relay-cache-command.lock"
        ))
        self._file = lock_path.open("a+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_leader = True
        except BlockingIOError:
            self.is_leader = False

    def try_acquire(self) -> bool:
        if self.is_leader:
            return True
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.is_leader = True
        except BlockingIOError:
            return False
        return True

    def close(self) -> None:
        if self._file.closed:
            return
        if self.is_leader:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
