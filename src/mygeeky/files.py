"""Reading and writing myGeeKy's data files safely.

* A save never leaves a half-written file: the text goes to a temporary file
  next to it first, which then replaces the real one in one step (a crash, a
  power cut or a full disk leaves the old file, not a broken one). Windows'
  antivirus/indexer can hold a file for a moment, so the swap is retried.
* Reading tolerates what really happens to files on people's computers: a
  byte-order mark added by a text editor, a half-written last line, a file
  damaged some other way. A damaged file is kept aside (`<name>.broken-<time>`)
  so nothing is lost, and the caller gets its default instead of an error.

Standard library only (the frozen installer imports config, which uses this).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str, retries: int = 6) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries - 1:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (attempt + 1))


def write_json(path: Path, data: Any, **dumps: Any) -> None:
    write_text_atomic(path, json.dumps(data, **dumps))


def set_aside(path: Path) -> Path | None:
    """Keep a damaged file under another name (never deleted, never synced)."""
    try:
        aside = path.with_name(f"{path.name}.broken-{datetime.now():%Y%m%d-%H%M%S}")
        os.replace(path, aside)
        return aside
    except OSError:
        return None


def read_json(path: Path, default: Any = None) -> Any:
    """The file's JSON, or `default` if it's missing or damaged (a damaged one is set aside)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return default
    except OSError:
        return default
    try:
        return json.loads(text)
    except ValueError:
        set_aside(path)
        return default


def read_jsonl(path: Path) -> list[Any]:
    """Every readable line; a half-written or damaged line is skipped, not fatal."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append_jsonl(path: Path, record: Any) -> None:
    """Add one line. If the file's last line was cut short (a crash mid-write), start a
    new line first, so the new record isn't glued onto the broken one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                needs_newline = fh.read(1) != b"\n"
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(("\n" if needs_newline else "") + json.dumps(record) + "\n")
