"""Where files live.

``Storage`` is the only place that touches the file system for downloads. The
pipeline talks to this interface, so a cloud version (for example S3 or Azure
Blob) can be added later as another class with the same three methods, without
changing the ingest code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    """The three operations the pipeline needs from any storage backend."""

    def write_bytes(self, key: str, data: bytes) -> str:
        """Save ``data`` under ``key`` and return a reference to where it was saved."""

    def read_bytes(self, key: str) -> bytes:
        """Return the bytes stored under ``key``."""

    def exists(self, key: str) -> bool:
        """Return True if something is stored under ``key``."""


class LocalStorage:
    """Stores files in a folder on this computer."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key

    def write_bytes(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def sha256_of(data: bytes) -> str:
    """Return the SHA-256 fingerprint of ``data`` as a hex string.

    The fingerprint changes if even one byte of the file changes, which lets
    the pipeline detect a file it has already loaded (and skip it) or one that
    has changed (and flag it).
    """
    return hashlib.sha256(data).hexdigest()
