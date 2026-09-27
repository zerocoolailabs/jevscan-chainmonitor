"""The local workspace: where caches, indexes, collections and the spending ledger live, and how files are written
there. Credentials come only from the process environment; no .env file is read."""

import json
import os
import tempfile
from pathlib import Path


def data_directory() -> Path:
    """JEVSCAN_DATA_DIR, read each time, so a program can set it after importing the package."""
    value = os.environ.get("JEVSCAN_DATA_DIR")
    return Path(value).expanduser().resolve() if value else Path.home() / ".local/share/jevscan-chainmonitor"


def cache_directory() -> Path:
    """Raw provider responses, the label index and the mixer index."""
    return data_directory() / "cache"


def atomic_json(path: Path, value: object, *, overwrite: bool = True) -> None:
    """Owner-only temporary file and atomic replacement in the same directory."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
