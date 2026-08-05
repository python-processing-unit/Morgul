"""Tab session persistence under ``~/.morgul``."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from morgul.format import looks_like_morgul, pack, unpack
from morgul.history import EditHistory

SESSION_VERSION = 1


def session_root() -> Path:
    """Return ``~/.morgul``.

    Returns:
        The session root directory path.
    """
    return Path.home() / ".morgul"


def tabs_dir() -> Path:
    """Return ``~/.morgul/tabs``.

    Returns:
        Directory that holds per-tab payload blobs.
    """
    return session_root() / "tabs"


def session_file() -> Path:
    """Return ``~/.morgul/session.json``.

    Returns:
        Path to the session index file.
    """
    return session_root() / "session.json"


def tab_blob_path(tab_id: str) -> Path:
    """Path for one tab's payload blob.

    Returns:
        ``~/.morgul/tabs/<id>.tab``.
    """
    return tabs_dir() / f"{tab_id}.tab"


def new_tab_id() -> str:
    """Allocate a unique tab id for session files.

    Returns:
        A hex UUID string.
    """
    return uuid.uuid4().hex


@dataclass(slots=True)
class TabMeta:
    """One row in the session index (no secrets, no body)."""

    id: str
    path: str | None
    encrypted: bool
    wrap_on: bool
    preview_on: bool
    dirty: bool


@dataclass(slots=True)
class SessionIndex:
    """Ordered open tabs + active index."""

    version: int
    active: int
    tabs: list[TabMeta]


@dataclass(slots=True)
class TabPayload:
    """In-memory tab body + undo history (before encrypt/write)."""

    history: EditHistory
    path: str | None
    dirty: bool
    wrap_on: bool
    preview_on: bool
    scroll: int = 0

    def to_json(self) -> str:
        """Serialize as UTF-8 JSON text (packable as MORGUL payload).

        Returns:
            Compact JSON string.
        """
        body: dict[str, Any] = {
            "v": SESSION_VERSION,
            "path": self.path,
            "dirty": self.dirty,
            "wrap_on": self.wrap_on,
            "preview_on": self.preview_on,
            "scroll": self.scroll,
            **self.history.to_dict(),
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> TabPayload:
        """Parse :meth:`to_json` output.

        Returns:
            Restored payload.

        Raises:
            TypeError: Top-level value is not an object.
        """
        data = json.loads(text)
        if not isinstance(data, dict):
            msg = "Tab payload is not an object."
            raise TypeError(msg)
        path = data.get("path")
        if path is not None and not isinstance(path, str):
            path = None
        dirty = bool(data.get("dirty", False))
        wrap_on = bool(data.get("wrap_on", True))
        preview_on = bool(data.get("preview_on", True))
        raw_scroll = data.get("scroll", 0)
        scroll = raw_scroll if isinstance(raw_scroll, int) else 0
        return cls(
            history=EditHistory.from_dict(data),
            path=path,
            dirty=dirty,
            wrap_on=wrap_on,
            preview_on=preview_on,
            scroll=max(0, scroll),
        )


def encode_tab_blob(payload: TabPayload, password: str | None) -> bytes:
    """Encode *payload*; encrypt with *password* when set (same as .morgul files).

    Returns:
        Plain UTF-8 JSON bytes, or a MORGUL blob when *password* is set.
    """
    raw = payload.to_json()
    if password:
        return pack(raw, password)
    return raw.encode("utf-8")


def decode_tab_blob(blob: bytes, password: str | None) -> TabPayload:
    """Decode a tab blob; *password* required when the blob is MORGUL-packed.

    Returns:
        The decoded tab payload.

    Raises:
        ValueError: Corrupt plain JSON or encrypted blob without password.
    """
    if looks_like_morgul(blob):
        if not password:
            msg = "Password required for encrypted tab."
            raise ValueError(msg)
        return TabPayload.from_json(unpack(blob, password))
    try:
        return TabPayload.from_json(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        msg = "Corrupt tab session data."
        raise ValueError(msg) from exc


def blob_is_encrypted(blob: bytes) -> bool:
    """True when *blob* is a MORGUL container.

    Returns:
        Whether *blob* looks like a MORGUL file.
    """
    return looks_like_morgul(blob)


def ensure_session_dirs() -> None:
    """Create ``~/.morgul/tabs`` if needed."""
    tabs_dir().mkdir(parents=True, exist_ok=True)


def _parse_meta(item: object) -> TabMeta | None:
    if not isinstance(item, dict):
        return None
    tab_id = item.get("id")
    if not isinstance(tab_id, str) or not tab_id:
        return None
    path_s = item.get("path")
    if path_s is not None and not isinstance(path_s, str):
        path_s = None
    return TabMeta(
        id=tab_id,
        path=path_s,
        encrypted=bool(item.get("encrypted", False)),
        wrap_on=bool(item.get("wrap_on", True)),
        preview_on=bool(item.get("preview_on", True)),
        dirty=bool(item.get("dirty", False)),
    )


def load_index() -> SessionIndex | None:
    """Read session index, or None if missing/invalid.

    Returns:
        Parsed index, or ``None`` when nothing usable is on disk.
    """
    path = session_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != SESSION_VERSION:
        return None
    raw_tabs = data.get("tabs")
    if not isinstance(raw_tabs, list):
        return None
    tabs = [m for item in raw_tabs if (m := _parse_meta(item)) is not None]
    if not tabs:
        return None
    raw_active = data.get("active", 0)
    active = raw_active if isinstance(raw_active, int) else 0
    active = max(0, min(active, len(tabs) - 1))
    return SessionIndex(version=SESSION_VERSION, active=active, tabs=tabs)


def save_index(index: SessionIndex) -> None:
    """Write session index atomically-ish."""
    ensure_session_dirs()
    body = {
        "version": SESSION_VERSION,
        "active": index.active,
        "tabs": [
            {
                "id": t.id,
                "path": t.path,
                "encrypted": t.encrypted,
                "wrap_on": t.wrap_on,
                "preview_on": t.preview_on,
                "dirty": t.dirty,
            }
            for t in index.tabs
        ],
    }
    path = session_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def read_tab_blob(tab_id: str) -> bytes | None:
    """Return raw tab bytes, or None if missing.

    Returns:
        File contents, or ``None`` on missing/IO error.
    """
    path = tab_blob_path(tab_id)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def write_tab_blob(tab_id: str, blob: bytes) -> None:
    """Write one tab payload blob."""
    ensure_session_dirs()
    path = tab_blob_path(tab_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def prune_tab_blobs(keep_ids: set[str]) -> None:
    """Delete tab files whose ids are not in *keep_ids*."""
    root = tabs_dir()
    if not root.is_dir():
        return
    for path in root.glob("*.tab"):
        if path.stem not in keep_ids:
            path.unlink(missing_ok=True)


def clear_session() -> None:
    """Remove index and all tab blobs."""
    idx = session_file()
    if idx.is_file():
        idx.unlink(missing_ok=True)
    root = tabs_dir()
    if root.is_dir():
        for path in root.glob("*.tab"):
            path.unlink(missing_ok=True)
