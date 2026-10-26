"""Serializable undo/redo stacks for session restore."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EditFrame:
    """Represent one document snapshot for undo and redo.

    Attributes:
        text (str): The document text.
        cursor (int): The cursor position within the document.
    """

    text: str
    cursor: int


@dataclass
class EditHistory:
    """Maintain serializable undo and redo history for text edits.

    Track the current text and cursor position alongside stacks of prior and redoable
        frames. Recording a changed text adds the previous frame to the undo stack,
        trims that stack to `max_steps`, and clears the redo stack; recording unchanged
        text only updates the current cursor.

    Attributes:
        undo (list[EditFrame]): Prior frames available for undo.
        redo (list[EditFrame]): Frames available for redo.
        current (EditFrame): The current text and cursor position.
        max_steps (int): Maximum number of undo frames retained when recording a changed
            text.
    """

    undo: list[EditFrame] = field(default_factory=list)
    redo: list[EditFrame] = field(default_factory=list)
    current: EditFrame = field(default_factory=lambda: EditFrame("", 0))
    max_steps: int = 200

    def seed(self, text: str, cursor: int = 0) -> None:
        """Reset the edit history to a frame containing the given text.

        Clear the undo and redo stacks, then set the current frame. Clamp the cursor
            position to zero or greater.

        Args:
            text (str): Text to store in the current frame.
            cursor (int): Cursor position to store, clamped to zero or greater.

        Returns:
            None: This method does not return a value.
        """
        self.undo.clear()
        self.redo.clear()
        self.current = EditFrame(text, max(0, cursor))

    def record(self, text: str, cursor: int) -> None:
        """Record a text state and update the undo history.

        If the text matches the current state, update only the current cursor.
            Otherwise, save the current state to the undo history, trim the history to
            the maximum number of steps, clear the redo history, and set the new current
            state. Clamp the cursor to zero or greater.

        Args:
            text (str): The text for the new current state.
            cursor (int): The cursor position for the new current state.

        Returns:
            None: This method does not return a value.
        """
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
        """Return whether the undo history is nonempty.

        Returns:
            bool: Whether the undo history contains at least one frame.
        """
        return bool(self.undo)

    def can_redo(self) -> bool:
        """Return whether the redo history contains a frame.

        Returns:
            bool: True if the redo history is nonempty.
        """
        return bool(self.redo)

    def undo_step(self) -> EditFrame | None:
        """Restore the most recent frame from the undo stack.

        Returns:
            EditFrame | None: The restored frame, or `None` if the undo stack is empty.
        """
        if not self.undo:
            return None
        self.redo.append(self.current)
        self.current = self.undo.pop()
        return self.current

    def redo_step(self) -> EditFrame | None:
        """Restore the most recently undone frame and make it current.

        Returns:
            EditFrame | None: The restored frame, or None if the redo stack is empty.
        """
        if not self.redo:
            return None
        self.undo.append(self.current)
        self.current = self.redo.pop()
        return self.current

    def to_dict(self) -> dict[str, Any]:
        """Create a JSON-friendly snapshot of the current state and edit history.

        Returns:
            dict[str, Any]: A mapping with the current text and cursor, plus undo and
                redo lists of frames containing text and cursor values.
        """

        def _frames(items: list[EditFrame]) -> list[dict[str, Any]]:
            """Convert edit frames to dictionaries.

            Args:
                items (list[EditFrame]): The edit frames to convert.

            Returns:
                list[dict[str, Any]]: Dictionaries containing each frame's text and
                    cursor.
            """
            return [{"text": f.text, "cursor": f.cursor} for f in items]

        return {
            "text": self.current.text,
            "cursor": self.current.cursor,
            "undo": _frames(self.undo),
            "redo": _frames(self.redo),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditHistory:
        """Rebuild an edit history from serialized data.

        Non-string current text defaults to an empty string, and non-integer or negative
            cursors default to zero or are clamped to zero. Undo and redo entries are
            loaded only from lists; entries that are not dictionaries or do not contain
            string text are skipped.

        Args:
            data (dict[str, Any]): Serialized history data containing the current frame
                and optional undo and redo stacks.

        Returns:
            EditHistory: A new history populated with the valid data.
        """

        def _load(items: object) -> list[EditFrame]:
            """Load valid edit frames from a list of serialized items.

            Args:
                items (object): Value to inspect for serialized edit frames.

            Returns:
                list[EditFrame]: Frames created from dictionary items with string text;
                    invalid items are skipped, and cursors default to zero and are
                    clamped to nonnegative values. Returns an empty list if items is not
                    a list.
            """
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
