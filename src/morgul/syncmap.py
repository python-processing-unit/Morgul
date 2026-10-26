"""Map carets between Markdown source and rendered preview plain text.

Preview plain text is roughly the source with markup removed, so a greedy
character alignment beats a raw length ratio (which drifts while typing).
"""

from __future__ import annotations


def normalize_plain(text: str) -> str:
    r"""Normalize Qt and editor newline variants to `\\n`.

    Replace Unicode paragraph separators, Unicode line separators,
        carriage-return/line-feed pairs, and carriage returns with newline characters.

    Args:
        text (str): Text to normalize.

    Returns:
        str: The normalized text.
    """
    # QTextDocument.toPlainText() often emits U+2029 between blocks.
    return (
        text
        .replace("\u2029", "\n")
        .replace("\u2028", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def preview_to_source_map(source: str, preview: str) -> list[int]:
    """Map each normalized preview character to its corresponding source index.

    Normalize both strings, then match preview characters against the source in order.
        Unmatched preview characters map to the current source position, capped at the
        source length, without advancing that position.

    Args:
        source (str): The source text to search.
        preview (str): The text whose characters are mapped to source positions.

    Returns:
        list[int]: Source indices for the normalized preview characters.
    """
    source = normalize_plain(source)
    preview = normalize_plain(preview)
    mapping: list[int] = []
    si = 0
    n = len(source)
    for pc in preview:
        found = source.find(pc, si)
        if found < 0:
            mapping.append(min(si, n))
        else:
            mapping.append(found)
            si = found + 1
    return mapping


def preview_pos_to_source(  # ruff: ignore[too-many-return-statements]
    source: str, preview: str, pos: int
) -> int:
    """Map a preview caret position to a source index.

    Normalize the source and preview text before mapping. If they match, or the
        preview-to-source map is empty, use the nonnegative preview position clamped to
        the source length.

    Args:
        source (str): Source text.
        preview (str): Preview text.
        pos (int): Caret position in the preview.

    Returns:
        int: Source index to insert before, clamped to the source length.
    """
    source = normalize_plain(source)
    preview = normalize_plain(preview)
    pos = max(pos, 0)
    if not source:
        return 0
    # Incomplete Markdown often renders as the raw source — keep 1:1 carets.
    if source == preview:
        return min(pos, len(source))
    if not preview:
        return min(pos, len(source))
    mapping = preview_to_source_map(source, preview)
    if not mapping:
        return min(pos, len(source))
    if pos <= 0:
        return mapping[0]
    if pos >= len(mapping):
        return min(mapping[-1] + 1, len(source))
    return mapping[pos]


def source_pos_to_preview(  # ruff: ignore[too-many-return-statements, complex-structure]
    source: str, preview: str, source_pos: int
) -> int:
    """Map a caret position in source text to the preview position.

    Args:
        source (str): Source text used to determine the caret position.
        preview (str): Preview text in which to place the caret.
        source_pos (int): Caret index in the source text.

    Returns:
        int: Preview index for the caret, clamped to the available mapping. Returns 0 if
            either text is empty or no mapping is available.
    """
    source = normalize_plain(source)
    preview = normalize_plain(preview)
    if not preview:
        return 0
    if not source:
        return 0
    source_pos = min(max(source_pos, 0), len(source))
    # Incomplete Markdown often renders as the raw source — keep 1:1 carets.
    if source == preview:
        return source_pos
    # QTextBrowser usually appends a final block break the source lacks.
    if preview.rstrip("\n") == source:
        return min(source_pos, len(source))
    if source == preview.rstrip("\n"):
        return min(source_pos, len(source))
    mapping = preview_to_source_map(source, preview)
    if not mapping:
        return 0
    if source_pos <= mapping[0]:
        return 0
    for index, src_i in enumerate(mapping):
        if src_i == source_pos:
            return index
        if src_i > source_pos:
            return index
    return len(mapping)
