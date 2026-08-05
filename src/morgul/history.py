"""Serializable undo/redo stacks for session restore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EditFrame:
    """One document snapshot for undo/redo."""

    text: str
    cursor: int


@dataclass
class EditHistory:
    """Full-text undo/redo (serializable; replaces Qt's opaque stack)."""

    undo: list[EditFrame] = field(default_factory=list)
    redo: list[EditFrame] = field(default_factory=list)
    current: EditFrame = field(default_factory=lambda: EditFrame("", 0))
    max_steps: int = 200

    def seed(self, text: str, cursor: int = 0) -> None:
        """Reset stacks around *text* (load / unlock)."""
        self.undo.clear()
        self.redo.clear()
        self.current = EditFrame(text, max(0, cursor))

    def record(self, text: str, cursor: int) -> None:
        """Push previous state when *text* changed (skip no-ops)."""
        cursor = max(0, cursor)
        if text == self.current.text:
            self.current = EditFrame(text, cursor)
            return
        self.undo.append(self.current)
        if len(self.undo) > self.max_steps:
            del self.undo[0 : len(self.undo) - self.max_steps]
        self.redo.clear()
        self.current = EditFrame(text, cursor)

    def can_undo(self) -> bool:
        """Whether undo has a prior frame.

        Returns:
            True when :meth:`undo_step` would succeed.
        """
        return bool(self.undo)

    def can_redo(self) -> bool:
        """Whether redo has a frame.

        Returns:
            True when :meth:`redo_step` would succeed.
        """
        return bool(self.redo)

    def undo_step(self) -> EditFrame | None:
        """Pop undo and make that frame current.

        Returns:
            The restored frame, or ``None`` if the stack is empty.
        """
        if not self.undo:
            return None
        self.redo.append(self.current)
        self.current = self.undo.pop()
        return self.current

    def redo_step(self) -> EditFrame | None:
        """Pop redo and make that frame current.

        Returns:
            The restored frame, or ``None`` if the stack is empty.
        """
        if not self.redo:
            return None
        self.undo.append(self.current)
        self.current = self.redo.pop()
        return self.current

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly snapshot including current text.

        Returns:
            A dict suitable for :meth:`from_dict`.
        """

        def _frames(items: list[EditFrame]) -> list[dict[str, Any]]:
            return [{"text": f.text, "cursor": f.cursor} for f in items]

        return {
            "text": self.current.text,
            "cursor": self.current.cursor,
            "undo": _frames(self.undo),
            "redo": _frames(self.redo),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditHistory:
        """Rebuild stacks from :meth:`to_dict` output.

        Returns:
            A new history instance.
        """

        def _load(items: object) -> list[EditFrame]:
            if not isinstance(items, list):
                return []
            out: list[EditFrame] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    continue
                raw_c = item.get("cursor", 0)
                cursor = raw_c if isinstance(raw_c, int) else 0
                out.append(EditFrame(text, max(0, cursor)))
            return out

        hist = cls()
        text = data.get("text", "")
        if not isinstance(text, str):
            text = ""
        raw_c = data.get("cursor", 0)
        cursor = raw_c if isinstance(raw_c, int) else 0
        hist.current = EditFrame(text, max(0, cursor))
        hist.undo = _load(data.get("undo"))
        hist.redo = _load(data.get("redo"))
        return hist
