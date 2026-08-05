"""Pure-logic tests (no Qt display needed)."""

from __future__ import annotations

import pytest

from morgul.find import FindError, FindOptions, find_all, replace_all, replace_one
from morgul.format import (
    CURRENT_VERSION,
    FORMATS,
    MorgulFormatError,
    looks_like_morgul,
    pack,
    unpack,
)
from morgul.highlight import highlight_ranges, spans_in_line
from morgul.history import EditHistory
from morgul.render import to_html
from morgul.session import (
    TabPayload,
    blob_is_encrypted,
    decode_tab_blob,
    encode_tab_blob,
)
from morgul.syncmap import preview_pos_to_source, source_pos_to_preview


def test_to_html_wraps_heading() -> None:
    html = to_html("# Hello")
    assert "<h1>" in html
    assert "Hello" in html
    assert "<!DOCTYPE html>" in html
    # Dark preview permanently.
    assert "#1e1e1e" in html


def test_to_html_renders_table() -> None:
    html = to_html("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
    assert "<table>" in html
    assert "<th>" in html
    assert "<td>" in html


def test_to_html_renders_task_lists() -> None:
    html = to_html("- [x] Done\n- [ ] Todo\n")
    # Unicode ballot boxes — QTextBrowser strips <input type="checkbox">.
    assert "\u2611" in html  # ☑
    assert "\u2610" in html  # ☐
    assert "Done" in html
    assert "Todo" in html
    assert 'type="checkbox"' not in html


def test_to_html_accepts_loose_empty_task_box() -> None:
    # People often type ``[]`` without the GFM-required space.
    html = to_html("- [] To-do\n")
    assert "\u2610" in html
    assert "To-do" in html
    assert "[]" not in html

    assert 'type="checkbox"' not in html


def test_to_html_allows_img_tag() -> None:
    html = to_html('<img src="pic.png" alt="photo">')
    assert '<img src="pic.png" alt="photo">' in html


def test_to_html_allows_br_and_inline_html() -> None:
    html = to_html("line<br>break")
    assert "<br>" in html
    html = to_html("Hello <b>bold</b> and <i>italic</i>")
    assert "<b>bold</b>" in html
    assert "<i>italic</i>" in html


def test_to_html_tagfilter_blocks_script() -> None:
    html = to_html("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "</script>" not in html
    # Only `<` is replaced; `>` passes through.
    assert "&lt;script>alert(1)&lt;/script>" in html


def test_to_html_tagfilter_blocks_style_iframe() -> None:
    # Check body content only (the document head has its own <style>).
    body = to_html("<style>body{}</style>").split("<body>")[1].split("</body>")[0]
    assert "<style>" not in body
    assert "&lt;style>" in body
    body = to_html("<iframe src=x></iframe>").split("<body>")[1].split("</body>")[0]
    assert "<iframe" not in body
    assert "&lt;iframe" in body


def test_to_html_renders_strikethrough() -> None:
    html = to_html("~~deleted~~")
    assert "<s>deleted</s>" in html


def test_heading_span() -> None:
    spans, fence = spans_in_line("# Title", in_fence=False)
    assert fence is False
    assert any(s.kind == "heading" for s in spans)


def test_fence_toggles_state() -> None:
    open_spans, inside = spans_in_line("```python", in_fence=False)
    assert inside is True
    assert open_spans[0].kind == "fence"

    body_spans, still = spans_in_line("x = 1", in_fence=True)
    assert still is True
    assert body_spans[0].kind == "code"

    close_spans, after = spans_in_line("```", in_fence=True)
    assert after is False
    assert close_spans[0].kind == "fence"


def test_inline_code_and_bold() -> None:
    spans, _ = spans_in_line("use `x` and **bold**", in_fence=False)
    kinds = {s.kind for s in spans}
    assert "code" in kinds
    assert "bold" in kinds


def test_find_plain_and_case() -> None:
    text = "Foo foo FOO"
    hits = find_all(text, FindOptions("foo"))
    assert len(hits) == 3
    hits_cs = find_all(text, FindOptions("foo", case_sensitive=True))
    assert len(hits_cs) == 1
    assert text[hits_cs[0].start : hits_cs[0].end] == "foo"


def test_find_whole_word() -> None:
    text = "cat catalog cat"
    hits = find_all(text, FindOptions("cat", whole_word=True))
    assert len(hits) == 2
    assert text[hits[0].start : hits[0].end] == "cat"
    assert text[hits[1].start : hits[1].end] == "cat"


def test_find_regex() -> None:
    text = "a1 b22 c3"
    hits = find_all(text, FindOptions(r"\w(\d+)", regex=True))
    assert len(hits) == 3


def test_find_in_selection() -> None:
    text = "one two one"
    hits = find_all(
        text,
        FindOptions("one", in_selection=True),
        selection=(4, 11),  # "two one"
    )
    assert len(hits) == 1
    assert hits[0].start == 8


def test_find_in_highlight_zones() -> None:
    text = "# Title\nplain Title\n"
    zones = highlight_ranges(text)
    hits = find_all(
        text,
        FindOptions("Title", in_highlight=True),
        highlight_ranges=zones,
    )
    # Only the heading line is highlighted for "Title".
    assert len(hits) == 1
    assert hits[0].start == text.index("Title")


def test_find_bad_regex() -> None:
    with pytest.raises(FindError):
        find_all("abc", FindOptions("(", regex=True))


def test_replace_all_and_one() -> None:
    text = "a a a"
    new, count = replace_all(text, FindOptions("a"), "b")
    assert new == "b b b"
    assert count == 3
    hits = find_all(text, FindOptions("a"))
    one = replace_one(text, FindOptions("a"), "x", hits[1])
    assert one == "a x a"


def test_replace_regex_groups() -> None:
    text = "name=Ada"
    new, count = replace_all(
        text,
        FindOptions(r"name=(\w+)", regex=True),
        r"user=\1",
    )
    assert count == 1
    assert new == "user=Ada"


def test_syncmap_italics_round_trip() -> None:
    source = "*italics*"
    preview = "italics"
    # Caret after the word in the preview → just before the closing marker.
    assert preview_pos_to_source(source, preview, len(preview)) == 8
    # Caret on the first visible letter → that letter in the source.
    assert preview_pos_to_source(source, preview, 0) == 1
    # Source caret after the closing star → end of preview.
    assert source_pos_to_preview(source, preview, 9) == len(preview)
    # Typing at end of preview inserts before closing ``*``, not after it.
    at = preview_pos_to_source(source, preview, len(preview))
    assert source[:at] + "x" + source[at:] == "*italicsx*"


def test_syncmap_plain_identity() -> None:
    source = "hello world"
    preview = "hello world"
    for index in range(len(preview) + 1):
        assert preview_pos_to_source(source, preview, index) == index
        assert source_pos_to_preview(source, preview, index) == index


def test_syncmap_qt_paragraph_separator() -> None:
    # QTextBrowser.toPlainText() uses U+2029 between blocks.
    source = "a\nb"
    preview = "a\u2029b"
    assert preview_pos_to_source(source, preview, 0) == 0
    assert preview_pos_to_source(source, preview, 2) == 2
    assert source_pos_to_preview(source, preview, 2) == 2


def test_syncmap_identical_is_identity() -> None:
    # Incomplete constructs like ``*foo`` render as raw text — carets must match.
    source = "*foo"
    preview = "*foo"
    for index in range(len(source) + 1):
        assert source_pos_to_preview(source, preview, index) == index
        assert preview_pos_to_source(source, preview, index) == index


def test_syncmap_trailing_block_break() -> None:
    # Preview plain text often ends with an extra block separator.
    source = "*foo"
    preview = "*foo\n"
    assert source_pos_to_preview(source, preview, 4) == 4
    assert source_pos_to_preview(source, preview, 0) == 0


def test_morgul_pack_unpack_round_trip() -> None:
    md = "# Hello\n\n**bold** and a table:\n\n| a | b |\n| - | - |\n| 1 | 2 |\n"
    blob = pack(md, "s3cret-password")
    assert blob[0] == CURRENT_VERSION
    assert looks_like_morgul(blob)
    assert unpack(blob, "s3cret-password") == md


def test_morgul_wrong_password() -> None:
    blob = pack("secret notes", "correct horse")
    with pytest.raises(MorgulFormatError, match="Incorrect password"):
        unpack(blob, "wrong battery")


def test_morgul_unknown_version() -> None:
    blob = bytearray(pack("x", "pw"))
    blob[0] = 0xFF
    with pytest.raises(MorgulFormatError, match="Unknown MORGUL"):
        unpack(bytes(blob), "pw")


def test_morgul_format_table_has_rev0() -> None:
    assert CURRENT_VERSION in FORMATS
    cfg = FORMATS[CURRENT_VERSION]
    assert cfg.nonce_len == 24
    assert cfg.argon2_hash_len == 32


def test_edit_history_undo_redo_round_trip() -> None:
    hist = EditHistory()
    hist.seed("a", 1)
    hist.record("ab", 2)
    hist.record("abc", 3)
    assert hist.undo_step() is not None
    assert hist.current.text == "ab"
    assert hist.redo_step() is not None
    assert hist.current.text == "abc"
    data = hist.to_dict()
    restored = EditHistory.from_dict(data)
    assert restored.current.text == "abc"
    assert [f.text for f in restored.undo] == ["a", "ab"]


def test_session_tab_blob_plain_and_encrypted() -> None:
    hist = EditHistory()
    hist.seed("note")
    hist.record("note!", 5)
    payload = TabPayload(
        history=hist,
        path=r"C:\docs\x.md",
        dirty=True,
        wrap_on=False,
        preview_on=True,
        scroll=12,
    )
    plain = encode_tab_blob(payload, None)
    assert not blob_is_encrypted(plain)
    back = decode_tab_blob(plain, None)
    assert back.history.current.text == "note!"
    assert back.history.undo[0].text == "note"
    assert back.path == r"C:\docs\x.md"
    assert back.dirty is True
    assert back.wrap_on is False
    assert back.scroll == 12

    enc = encode_tab_blob(payload, "s3cret")
    assert blob_is_encrypted(enc)
    assert looks_like_morgul(enc)
    assert decode_tab_blob(enc, "s3cret").history.current.text == "note!"
    with pytest.raises(MorgulFormatError):
        decode_tab_blob(enc, "wrong")
