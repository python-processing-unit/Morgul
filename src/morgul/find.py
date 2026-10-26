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
    """Configure matching behavior for one search or replace pass.

    Attributes:
        pattern (str): Text or regular expression to match.
        case_sensitive (bool): Whether matching is case-sensitive.
        whole_word (bool): Whether matches must be whole words.
        regex (bool): Whether to interpret the pattern as a regular expression.
        in_selection (bool): Whether to limit matches to the range from selection_start
            to selection_end.
        in_highlight (bool): Whether to limit matches to ranges fully inside a highlight
            span.
    """

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
    """Represent a match as a half-open span in the full document string.

    Attributes:
        start (int): Inclusive start index of the match.
        end (int): Exclusive end index of the match.
    """

    start: int
    end: int


class FindError(ValueError):
    """Represent an error caused by a bad search pattern."""


def compile_pattern(options: FindOptions) -> Pattern[str]:
    """Compile the search pattern according to the find options.

    Escape the pattern unless regex mode is enabled, apply case sensitivity, and
        optionally require whole-word matches.

    Args:
        options (FindOptions): Search options containing the pattern and matching
            settings.

    Returns:
        Pattern[str]: The compiled regular expression.

    Raises:
        FindError: If the pattern is empty or contains an invalid regular expression.
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
    """Check whether the interval [start, end) is contained in any range.

    Args:
        start (int): Start of the interval to check.
        end (int): End of the interval to check.
        ranges (list[tuple[int, int]]): Ranges to check, each represented by a start and
            end pair.

    Returns:
        bool: True if any range contains the interval; otherwise, False.
    """
    return any(start >= r0 and end <= r1 for r0, r1 in ranges)


def find_all(
    text: str,
    options: FindOptions,
    *,
    selection: tuple[int, int] | None = None,
    highlight_ranges: list[tuple[int, int]] | None = None,
) -> list[Match]:
    """Find all non-empty matches in the text that satisfy the search options.

    When selection filtering is enabled, search only the specified selection and return
        no matches if it is missing or empty. When highlight filtering is enabled,
        include only matches contained in a highlight range. Returned match offsets are
        relative to the original text.

    Args:
        text (str): Full document text to search.
        options (FindOptions): Search options controlling the search and filtering.
        selection (tuple[int, int] | None): Selection bounds used when selection
            filtering is enabled.
        highlight_ranges (list[tuple[int, int]] | None): Highlight ranges used when
            highlight filtering is enabled.

    Returns:
        list[Match]: Non-empty matches in document order, with non-overlapping spans.
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
    """Replace every match found in the text.

    Args:
        text (str): Text to search and update.
        options (FindOptions): Options used to find matches and determine whether
            replacement is regex-based.
        replacement (str): Text to use for each replacement.
        selection (tuple[int, int] | None): Optional selection range passed to the
            search.
        highlight_ranges (list[tuple[int, int]] | None): Optional highlight ranges
            passed to the search.

    Returns:
        tuple[str, int]: The updated text and the number of matches replaced.
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
    """Replace one known match in the text.

    Args:
        text (str): The full text containing the match.
        options (FindOptions): Options that determine whether the replacement uses a
            regular expression.
        replacement (str): The replacement text.
        hit (Match): The match to replace.

    Returns:
        str: The full text with the match replaced.
    """
    if options.regex:
        pattern = compile_pattern(options)
        piece = text[hit.start : hit.end]
        new_piece = pattern.sub(replacement, piece, count=1)
    else:
        new_piece = replacement
    return text[: hit.start] + new_piece + text[hit.end :]
