"""Find / replace over plain text (no Qt).

Supports case, whole-word, regex, selection scope, and “only inside
syntax-highlighted zones” (caller supplies those ranges).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern


@dataclass(frozen=True, slots=True)
class FindOptions:
    """Knob cluster for one search or replace pass."""

    pattern: str
    case_sensitive: bool = False
    whole_word: bool = False
    regex: bool = False
    # Limit hits to [selection_start, selection_end).
    in_selection: bool = False
    # Limit hits to ranges that sit fully inside a highlight span.
    in_highlight: bool = False


@dataclass(frozen=True, slots=True)
class Match:
    """One hit: ``[start, end)`` in the full document string."""

    start: int
    end: int


class FindError(ValueError):
    """Bad pattern (usually an invalid regular expression)."""


def compile_pattern(options: FindOptions) -> Pattern[str]:
    """Build the regex used for find/replace.

    Returns:
        A compiled pattern ready for ``finditer`` / ``sub``.

    Raises:
        FindError: If *options.pattern* is empty or not a valid regex.
    """
    raw = options.pattern
    if not raw:
        msg = "Search pattern is empty."
        raise FindError(msg)

    flags = 0 if options.case_sensitive else re.IGNORECASE
    try:
        body = raw if options.regex else re.escape(raw)
        if options.whole_word:
            # Non-capturing group keeps replace-group numbers stable for regex mode.
            body = rf"\b(?:{body})\b"
        return re.compile(body, flags)
    except re.error as exc:
        msg = f"Invalid regular expression: {exc}"
        raise FindError(msg) from exc


def _in_any_range(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """Return True when [start, end) sits fully inside one of *ranges*."""
    return any(start >= r0 and end <= r1 for r0, r1 in ranges)


def find_all(
    text: str,
    options: FindOptions,
    *,
    selection: tuple[int, int] | None = None,
    highlight_ranges: list[tuple[int, int]] | None = None,
) -> list[Match]:
    """Return every match in *text* honouring *options*.

    Args:
        text: Full document text.
        options: Search knobs.
        selection: ``(start, end)`` used when ``options.in_selection``.
        highlight_ranges: Syntax spans used when ``options.in_highlight``.

    Returns:
        Matches in document order (non-overlapping, leftmost-longest via finditer).
    """
    pattern = compile_pattern(options)

    if options.in_selection:
        if selection is None:
            return []
        sel_lo, sel_hi = selection
        if sel_hi < sel_lo:
            sel_lo, sel_hi = sel_hi, sel_lo
        if sel_lo == sel_hi:
            return []
        search_text = text[sel_lo:sel_hi]
        base = sel_lo
    else:
        search_text = text
        base = 0

    zones = highlight_ranges if options.in_highlight else None
    hits: list[Match] = []
    for match in pattern.finditer(search_text):
        start = base + match.start()
        end = base + match.end()
        if start == end:
            # Zero-width regex matches (e.g. ``(?=x)``) — skip to avoid loops.
            continue
        if zones is not None and not _in_any_range(start, end, zones):
            continue
        hits.append(Match(start, end))
    return hits


def replace_all(
    text: str,
    options: FindOptions,
    replacement: str,
    *,
    selection: tuple[int, int] | None = None,
    highlight_ranges: list[tuple[int, int]] | None = None,
) -> tuple[str, int]:
    """Replace every match.

    Returns:
        ``(new_text, count)`` where *count* is how many hits were replaced.
    """
    hits = find_all(
        text,
        options,
        selection=selection,
        highlight_ranges=highlight_ranges,
    )
    if not hits:
        return text, 0

    pattern = compile_pattern(options)
    # Walk right-to-left so earlier offsets stay valid.
    out = text
    for hit in reversed(hits):
        piece = out[hit.start : hit.end]
        if options.regex:
            new_piece = pattern.sub(replacement, piece, count=1)
        else:
            new_piece = replacement
        out = out[: hit.start] + new_piece + out[hit.end :]
    return out, len(hits)


def replace_one(
    text: str,
    options: FindOptions,
    replacement: str,
    hit: Match,
) -> str:
    """Replace a single known *hit*.

    Returns:
        The new full document text.
    """
    if options.regex:
        pattern = compile_pattern(options)
        piece = text[hit.start : hit.end]
        new_piece = pattern.sub(replacement, piece, count=1)
    else:
        new_piece = replacement
    return text[: hit.start] + new_piece + text[hit.end :]
