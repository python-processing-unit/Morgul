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

# Max entries remembered in the File → Open Recent list.
RECENT_LIMIT = 10


def session_root() -> Path:
    """Return the path to the Morgul session directory.

    Returns:
        Path: Path to the `.morgul` directory in the user's home directory.
    """
    return Path.home() / ".morgul"


def tabs_dir() -> Path:
    """Return the path to the tabs directory.

    Returns:
        Path: The path formed by appending "tabs" to the session root.
    """
    return session_root() / "tabs"


def session_file() -> Path:
    """Return the path to the session index file.

    Returns:
        Path to ``session.json`` inside the session root.
    """
    return session_root() / "session.json"


def tab_blob_path(tab_id: str) -> Path:
    """Return the payload blob path for a tab.

    Args:
        tab_id (str): Identifier used to name the tab's blob file.

    Returns:
        Path: Path to the tab's `.tab` payload blob.
    """
    return tabs_dir() / f"{tab_id}.tab"


def new_tab_id() -> str:
    """Generate a unique hexadecimal tab identifier.

    Returns:
        A hexadecimal UUID string.
    """
    return uuid.uuid4().hex


@dataclass(slots=True)
class TabMeta:
    """Represent one session-index row without secrets or message body.

    Attributes:
        id (str): Session identifier.
        path (str | None): Path associated with the session, if available.
        encrypted (bool): Whether the session is encrypted.
        wrap_on (bool): Whether text wrapping is enabled.
        preview_on (bool): Whether preview is enabled.
        spellcheck_on (bool): Whether spellchecking is enabled.
        dirty (bool): Whether the session has unsaved changes.
    """

    id: str
    path: str | None
    encrypted: bool
    wrap_on: bool
    preview_on: bool
    spellcheck_on: bool
    dirty: bool


@dataclass(slots=True)
class SessionIndex:
    """Represent ordered open tabs and the index of the active tab.

    Attributes:
        version (int): Version value for this session index.
        active (int): Index of the active tab in `tabs`.
        tabs (list[TabMeta]): Open tabs in order.
    """

    version: int
    active: int
    tabs: list[TabMeta]


@dataclass(slots=True)
class TabPayload:
    """Store a tab's in-memory editing state and undo history.

    Attributes:
        history (EditHistory): The tab's editing history.
        path (str | None): The tab's file path, if one is set.
        dirty (bool): Whether the tab has unsaved changes.
        wrap_on (bool): Whether text wrapping is enabled.
        preview_on (bool): Whether preview is enabled.
        spellcheck_on (bool): Whether spellchecking is enabled.
        scroll (int): The tab's scroll position.
    """

    history: EditHistory
    path: str | None
    dirty: bool
    wrap_on: bool
    preview_on: bool
    spellcheck_on: bool = True
    scroll: int = 0

    def to_json(self) -> str:
        """Serialize the tab payload as compact JSON text.

        Returns:
            str: The payload encoded as a JSON string.
        """
        body: dict[str, Any] = {
            "v": SESSION_VERSION,
            "path": self.path,
            "dirty": self.dirty,
            "wrap_on": self.wrap_on,
            "preview_on": self.preview_on,
            "spellcheck_on": self.spellcheck_on,
            "scroll": self.scroll,
            **self.history.to_dict(),
        }
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> TabPayload:
        """Restore a tab payload from its JSON representation.

        Invalid or non-string paths are replaced with None. Boolean fields are converted
            to bool, and scroll is reset to 0 if it is not an integer or is negative.
            Invalid JSON propagates the `json.JSONDecodeError` raised by the decoder.

        Args:
            text (str): JSON text representing a tab payload.

        Returns:
            TabPayload: The restored payload.

        Raises:
            TypeError: If the decoded top-level value is not an object.
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
        spellcheck_on = bool(data.get("spellcheck_on", True))
        raw_scroll = data.get("scroll", 0)
        scroll = raw_scroll if isinstance(raw_scroll, int) else 0
        return cls(
            history=EditHistory.from_dict(data),
            path=path,
            dirty=dirty,
            wrap_on=wrap_on,
            preview_on=preview_on,
            spellcheck_on=spellcheck_on,
            scroll=max(0, scroll),
        )


def encode_tab_blob(payload: TabPayload, password: str | None) -> bytes:
    """Encode a tab payload as UTF-8 JSON or a password-protected blob.

    Args:
        payload (TabPayload): The tab payload to serialize.
        password (str | None): The password used to pack the serialized payload when
            non-empty.

    Returns:
        bytes: The serialized payload as UTF-8 JSON bytes when password is empty or
            None, or as a packed blob otherwise.
    """
    raw = payload.to_json()
    if password:
        return pack(raw, password)
    return raw.encode("utf-8")


def decode_tab_blob(blob: bytes, password: str | None) -> TabPayload:
    """Decode a tab blob into a payload.

    Args:
        blob (bytes): Serialized tab data.
        password (str | None): Password used to unpack a MORGUL-packed blob, if needed.

    Returns:
        TabPayload: The decoded tab payload.

    Raises:
        ValueError: If the blob is MORGUL-packed and no password is provided, or if
            plain tab data cannot be decoded.
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
    """Check whether the blob looks like a MORGUL container.

    Args:
        blob (bytes): The data to check.

    Returns:
        bool: Whether the blob looks like a MORGUL container.
    """
    return looks_like_morgul(blob)


def ensure_session_dirs() -> None:
    """Create the session tabs directory and any missing parent directories."""
    tabs_dir().mkdir(parents=True, exist_ok=True)


def _parse_meta(item: object) -> TabMeta | None:
    """Parse a metadata item into a tab record.

    Return `None` if the item is not a dictionary or does not contain a nonempty string
        ID. Non-string paths are treated as `None`, and boolean fields are converted
        with `bool()`.

    Args:
        item (object): Value to parse.

    Returns:
        TabMeta | None: Parsed tab metadata, or `None` if the item is invalid.
    """
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
        spellcheck_on=bool(item.get("spellcheck_on", True)),
        dirty=bool(item.get("dirty", False)),
    )


def load_index() -> SessionIndex | None:
    """Load the session index from disk.

    Return None if the file is missing, unreadable, invalid, or contains no parseable
        tabs. The active tab index is clamped to the available tabs.

    Returns:
        SessionIndex | None: The parsed session index, or None if no usable index is
            available.
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
    """Write the session index to disk through a temporary file.

    Serialize the index as indented UTF-8 JSON, then replace the session index file with
        the temporary file.

    Args:
        index (SessionIndex): Session index containing the active session and tabs.

    Returns:
        None
    """
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
    """Read the tab blob and return its raw bytes.

    Args:
        tab_id (str): Identifier used to locate the tab blob.

    Returns:
        bytes | None: The blob contents, or None if the path is not a file or reading
            raises OSError.
    """
    path = tab_blob_path(tab_id)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def write_tab_blob(tab_id: str, blob: bytes) -> None:
    """Write a tab's binary payload to its session file.

    Ensure the session directories exist, write the payload to a temporary file, and
        replace the tab's existing blob with it.

    Args:
        tab_id (str): Identifier of the tab whose blob is written.
        blob (bytes): Binary payload to write.

    Returns:
        None
    """
    ensure_session_dirs()
    path = tab_blob_path(tab_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def prune_tab_blobs(keep_ids: set[str]) -> None:
    """Remove tab files whose IDs are not in `keep_ids`.

    Args:
        keep_ids (set[str]): IDs of tab files to retain.

    Returns:
        None: This function does not return a value.
    """
    root = tabs_dir()
    if not root.is_dir():
        return
    for path in root.glob("*.tab"):
        if path.stem not in keep_ids:
            path.unlink(missing_ok=True)


def clear_session() -> None:
    """Remove the session index file and matching tab files.

    The index file is removed if it exists as a file, and files matching `*.tab` in the
        tabs directory are removed if that directory exists.
    """
    idx = session_file()
    if idx.is_file():
        idx.unlink(missing_ok=True)
    root = tabs_dir()
    if root.is_dir():
        for path in root.glob("*.tab"):
            path.unlink(missing_ok=True)


def recent_file() -> Path:
    """Return the path to the recent-files list.

    Returns:
        Path to ``recent.json`` in the session root.
    """
    return session_root() / "recent.json"


def load_recent() -> list[str]:
    """Load and filter the saved recent-files list.

    Returns:
        list[str]: String entries from the saved list, in their original order, limited
            to `RECENT_LIMIT`; returns an empty list if the file is missing, unreadable,
            invalid JSON, or does not contain a list.
    """
    path = recent_file()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [s for s in data if isinstance(s, str)][:RECENT_LIMIT]


def save_recent(files: list[str]) -> None:
    """Save recent file paths to the session's recent-files JSON file.

    Write at most RECENT_LIMIT paths from the beginning of `files`, preserving their
        order, as indented UTF-8 JSON.

    Args:
        files (list[str]): Recent file paths, ordered newest first.

    Returns:
        None
    """
    ensure_session_dirs()
    path = recent_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(files[:RECENT_LIMIT], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    tmp.replace(path)


def clear_recent() -> None:
    """Remove the recent-files file if it exists."""
    recent_file().unlink(missing_ok=True)
