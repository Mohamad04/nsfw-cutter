"""Atomic, non-overwriting JSON writes: readers see either no file or the complete file."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def write_atomic(path: Path, value, *, serialized: str | None = None):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    text = serialized if serialized is not None else json.dumps(value, indent=2, ensure_ascii=False,
                                                                allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise FileExistsError(path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
