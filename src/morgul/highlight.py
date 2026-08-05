"""Tiny Markdown span finder for syntax colours.

Qt's highlighter calls into :func:`spans_in_line` once per visible line.
Multi-line fenced code is tracked with a simple on/off state bit
(see :class:`morgul.app.MarkdownHighlighter`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern

# Order matters: first match wins for a given character range when we merge.
_RULES: list[tuple[str, Pattern[str]]] = [
    # Fenced code opener/closer on its own line (body handled via block state).
    ("fence", re.compile(r"^```.*$")),
    # ATX headings.
    ("heading", re.compile(r"^#{1,6}(?:\s+.*)?$")),
    # Indented or flush blockquote marker runs.
    ("quote", re.compile(r"^>\s?.*$")),
    # Unordered / ordered list markers at line start.
    ("list", re.compile(r"^\s{0,3}(?:[-*+]|\d+\.)\s+")),
    # Inline code, then bold/italic, then links — greed-safe enough for a notepad.
    ("code", re.compile(r"`+[^`\n]+`+")),
    ("bold", re.compile(r"(\*\*|__)(?=\S).+?(?<=\S)\1")),
    (
        "italic",
        re.compile(
            r"(?<!\*)\*(?!\*)(?=\S).+?(?<=\S)\*(?!\*)"
            r"|(?<!_)_(?!_)(?=\S).+?(?<=\S)_(?!_)"
        ),
    ),
    ("link", re.compile(r"\[[^\]\n]+\]\([^)\n]+\)")),
]


@dataclass(frozen=True, slots=True)
class Span:
    """A coloured slice of one line: ``[start, end)`` in line-local offsets."""

    start: int
    end: int
    kind: str


def spans_in_line(line: str, *, in_fence: bool) -> tuple[list[Span], bool]:
    """Return highlight spans for *line* and the fence state after the line.

    Args:
        line: One editor line (no trailing newline).
        in_fence: Whether we are already inside a ``` fence from prior lines.

    Returns:
        ``(spans, in_fence_after)``. Inside a fence the whole line is ``code``.
    """
    stripped = line  # keep offsets aligned with the real line
    if in_fence:
        # Closing fence ends the block; the fence line itself stays code-coloured.
        if _RULES[0][1].match(stripped) is not None:
            return [Span(0, len(stripped), "fence")], False
        return [Span(0, len(stripped), "code")], True

    if _RULES[0][1].match(stripped) is not None:
        return [Span(0, len(stripped), "fence")], True

    # Whole-line styles first (heading / quote), then inline overlays.
    found: list[Span] = []
    covered = bytearray(len(stripped))  # 0/1 mask so inline skips taken ranges

    for kind, pattern in _RULES[1:4]:
        match = pattern.match(stripped)
        if match is not None:
            start, end = match.span()
            found.append(Span(start, end, kind))
            covered[start:end] = b"\x01" * (end - start)
            break

    for kind, pattern in _RULES[4:]:
        for match in pattern.finditer(stripped):
            start, end = match.span()
            if any(covered[start:end]):
                continue
            found.append(Span(start, end, kind))
            covered[start:end] = b"\x01" * (end - start)

    return found, False


def highlight_ranges(text: str) -> list[tuple[int, int]]:
    """Document-absolute ``[start, end)`` ranges covered by syntax colours.

    Used by find-in-highlight so search can stay inside Markdown structure
    (headings, code, links, …) without talking to Qt.

    Returns:
        Non-overlapping-ish ranges in document order (may abut or nest lightly).
    """
    ranges: list[tuple[int, int]] = []
    offset = 0
    in_fence = False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        spans, in_fence = spans_in_line(body, in_fence=in_fence)
        ranges.extend((offset + span.start, offset + span.end) for span in spans)
        offset += len(line)
    return ranges
