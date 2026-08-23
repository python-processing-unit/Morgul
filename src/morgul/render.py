"""Markdown → safe HTML for the preview pane.

Kept free of Qt so pytest can exercise it without a display.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from mdit_py_plugins.gfm import gfm_plugin

# GFM preset: tables, strikethrough, autolinks, task lists, footnotes.
# HTML enabled so <img>, <br>, <b>, etc. pass through; tagfilter blocks
# the dangerous tags per GFM spec §6.12.
# ponytail: single shared parser; rebuild if you ever need per-call options.
_PARSER = MarkdownIt("commonmark", {"html": True, "linkify": False}).use(
    gfm_plugin,
)

# GFM "Disallowed Raw HTML" tagfilter (spec §6.12).
# Escapes the opening `<` of dangerous tags; all other HTML passes through.
_DISALLOWED_TAGS = re.compile(
    r"<(/?)(title|textarea|style|xmp|iframe|noembed|noframes|script|plaintext)\b",
    re.IGNORECASE,
)


def _tagfilter(html: str) -> str:
    """Apply GFM tagfilter: escape disallowed raw HTML tags.

    Returns:
        HTML with ``<`` replaced by ``&lt;`` for blocked tag names.
    """
    return _DISALLOWED_TAGS.sub(r"&lt;\1\2", html)


# Loose task syntax people type: ``- [] foo`` (GFM needs a space inside).
_LOOSE_EMPTY_BOX = re.compile(
    r"^(\s*(?:[-*+]|\d+[.)])\s+)\[\](\s+)",
    re.MULTILINE,
)

# QTextBrowser drops <input type="checkbox">. Inject real glyphs instead of
# relying on Qt's flaky li.checked / li.unchecked markers.
_CHECKED_ITEM = re.compile(
    r'<li class="task-list-item[^"]*">\s*'
    r'<input[^>]*\bchecked\b[^>]*type="checkbox"[^>]*>\s*',
    re.IGNORECASE,
)
_UNCHECKED_ITEM = re.compile(
    r'<li class="task-list-item[^"]*">\s*'
    r'<input[^>]*type="checkbox"[^>]*>\s*',
    re.IGNORECASE,
)

_CHECK_ON = "\u2611\u00a0"  # ☑ + nbsp
_CHECK_OFF = "\u2610\u00a0"  # ☐ + nbsp

# Permanent dark preview — matches the editor chrome.
_CSS = """
body {
  font-family: "Segoe UI", "Segoe UI Variable", sans-serif;
  font-size: 14px;
  line-height: 1.5;
  color: #e6e6e6;
  background: #1e1e1e;
  margin: 12px 16px;
}
pre, code {
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: 13px;
  background: #2d2d2d;
  color: #f0a0a0;
}
pre {
  padding: 10px 12px;
  overflow-x: auto;
  border-radius: 4px;
  line-height: normal;
}
code { padding: 1px 4px; border-radius: 3px; }
pre code { padding: 0; background: transparent; }
h1, h2, h3, h4, h5, h6 {
  font-weight: 600;
  line-height: 1.25;
  color: #79b8ff;
}
a { color: #58a6ff; }
blockquote {
  margin-left: 0;
  padding-left: 12px;
  border-left: 3px solid #484848;
  color: #9a9a9a;
}
table { border-collapse: collapse; margin: 0.5em 0; }
th, td { border: 1px solid #484848; padding: 6px 10px; }
th { background: #2d2d2d; font-weight: 600; }
tr:nth-child(even) td { background: #252526; }
hr { border: none; border-top: 1px solid #484848; }
img { max-width: 100%; height: auto; }
/* Hide the default bullet; the ☑/☐ glyph is the marker. */
ul.contains-task-list { list-style: none; padding-left: 0.35em; }
ul.contains-task-list > li { margin: 0.15em 0; }
"""


def _normalize_task_markdown(source: str) -> str:
    """Coerce common near-GFM task boxes into real GFM ``[ ]`` / ``[x]``.

    Returns:
        Source with bare ``[]`` task boxes expanded to ``[ ]``.
    """
    return _LOOSE_EMPTY_BOX.sub(r"\1[ ]\2", source)


def _qtify_tasklists(html: str) -> str:
    """Replace checkbox ``<input>`` tags with Unicode ballot boxes.

    Returns:
        HTML QTextBrowser can actually paint (no form controls).
    """
    # Checked first so the second pattern does not steal them.
    html = _CHECKED_ITEM.sub(f"<li>{_CHECK_ON}", html)
    return _UNCHECKED_ITEM.sub(f"<li>{_CHECK_OFF}", html)


def to_html(source: str) -> str:
    """Render Markdown *source* to a full HTML document string.

    Returns:
        A self-contained HTML page suitable for ``QTextBrowser.setHtml``.
    """
    rendered = _PARSER.render(_normalize_task_markdown(source))
    body = _qtify_tasklists(_tagfilter(rendered))
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )
