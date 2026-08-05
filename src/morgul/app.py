"""Main window: dark Win11 Notepad layout, tabs, find/replace, preview."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEvent,
    QObject,
    QRect,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QEnterEvent,
    QFont,
    QIcon,
    QImage,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid
from typing_extensions import override

from morgul.find import (
    FindError,
    FindOptions,
    Match,
    find_all,
    replace_all,
    replace_one,
)
from morgul.format import (
    MorgulFormatError,
    is_morgul_path,
    looks_like_morgul,
    pack,
    unpack,
)
from morgul.highlight import highlight_ranges, spans_in_line
from morgul.history import EditFrame, EditHistory
from morgul.icons import close_icon, close_icon_hover, new_tab_icon
from morgul.password_ui import SetPasswordDialog, UnlockPasswordDialog
from morgul.render import to_html
from morgul.session import (
    SESSION_VERSION,
    SessionIndex,
    TabMeta,
    TabPayload,
    blob_is_encrypted,
    clear_session,
    decode_tab_blob,
    encode_tab_blob,
    load_index,
    new_tab_id,
    prune_tab_blobs,
    read_tab_blob,
    save_index,
    write_tab_blob,
)
from morgul.syncmap import preview_pos_to_source, source_pos_to_preview

if TYPE_CHECKING:
    from collections.abc import Callable


class _UserCancelledError(Exception):
    """User dismissed a required password prompt."""


# Dark syntax colours (GitHub-dark adjacent, easy on the eyes).
_COLORS: dict[str, str] = {
    "heading": "#79b8ff",
    "bold": "#e6edf3",
    "italic": "#8b949e",
    "code": "#ff7b72",
    "fence": "#d2a8ff",
    "link": "#58a6ff",
    "quote": "#8b949e",
    "list": "#ffa657",
}

_STATE_NORMAL = 0
_STATE_FENCE = 1

# App-wide dark chrome. One stylesheet, no light toggle.
_DARK_QSS = """
QWidget {
  background-color: #1e1e1e;
  color: #e6e6e6;
  selection-background-color: #264f78;
  selection-color: #ffffff;
}
QMainWindow, QDialog, QStatusBar, QMenuBar, QMenu {
  background-color: #1e1e1e;
  color: #e6e6e6;
}
QMenuBar::item:selected, QMenu::item:selected {
  background-color: #2d2d2d;
}
QPlainTextEdit, QTextBrowser, QLineEdit {
  background-color: #1e1e1e;
  color: #e6e6e6;
  border: 1px solid #3c3c3c;
  selection-background-color: #264f78;
}
QPlainTextEdit, QTextBrowser { border: none; }
QTabBar::tab {
  background: #252526;
  color: #cccccc;
  padding: 6px 28px 6px 12px;
  border: none;
  margin-right: 1px;
}
QTabBar::tab:selected {
  background: #1e1e1e;
  color: #ffffff;
  border-bottom: 2px solid #0078d4;
}
QTabBar::tab:hover { background: #2d2d2d; }
QWidget#tabStrip { background: #1e1e1e; }
QFrame#tabStripRule { background: #3c3c3c; border: none; max-height: 1px; }
/* Hide the default (often emoji-ish) close decoration; we install SVG buttons. */
QTabBar::close-button { image: none; width: 0; height: 0; }
QToolButton#tabCloseButton, QToolButton#newTabButton {
  background: transparent;
  border: none;
  border-radius: 3px;
  padding: 2px;
}
QToolButton#tabCloseButton:hover, QToolButton#newTabButton:hover {
  background: #3c3c3c;
}
QToolButton#newTabButton {
  margin-left: 2px;
}
QToolButton#passwordEyeButton {
  background: transparent;
  border: none;
  border-radius: 3px;
  padding: 2px;
}
QToolButton#passwordEyeButton:hover {
  background: #3c3c3c;
}
QLabel#passwordStrengthBar {
  background: #2d2d2d;
  border: 1px solid #3c3c3c;
  border-radius: 2px;
}
QLabel#passwordStrengthBar[filled="true"][strength="0"] {
  background: #c43c3c; border-color: #c43c3c;
}
QLabel#passwordStrengthBar[filled="true"][strength="1"] {
  background: #d98b2b; border-color: #d98b2b;
}
QLabel#passwordStrengthBar[filled="true"][strength="2"] {
  background: #c8c831; border-color: #c8c831;
}
QLabel#passwordStrengthBar[filled="true"][strength="3"] {
  background: #5fa83f; border-color: #5fa83f;
}
QLabel#passwordStrengthBar[filled="true"][strength="4"] {
  background: #2faa5e; border-color: #2faa5e;
}
QLabel#passwordWarningLabel {
  color: #d98b2b;
}
QPushButton {
  background-color: #2d2d2d;
  border: 1px solid #3c3c3c;
  padding: 4px 12px;
  border-radius: 3px;
}
QPushButton:hover { background-color: #3c3c3c; }
QPushButton:default { border-color: #0078d4; }
QCheckBox { spacing: 6px; }
QStatusBar { border-top: 1px solid #3c3c3c; }
QSplitter::handle { background: #3c3c3c; width: 1px; height: 1px; }
QMessageBox { background-color: #1e1e1e; }
"""


class MarkdownHighlighter(QSyntaxHighlighter):
    """Colour one block at a time; fence state rides on ``previousBlockState``."""

    def __init__(self, document: QTextDocument) -> None:
        """Attach to *document* and build the colour table once."""
        super().__init__(document)
        self._formats = {kind: _make_format(color) for kind, color in _COLORS.items()}
        self._formats["heading"].setFontWeight(QFont.Weight.Bold)
        self._formats["bold"].setFontWeight(QFont.Weight.Bold)
        self._formats["italic"].setFontItalic(True)

    @override
    def highlightBlock(self, text: str) -> None:
        """Apply Markdown spans to the current block (Qt override)."""
        in_fence = self.previousBlockState() == _STATE_FENCE
        spans, still_fenced = spans_in_line(text, in_fence=in_fence)
        for span in spans:
            self.setFormat(span.start, span.end - span.start, self._formats[span.kind])
        self.setCurrentBlockState(_STATE_FENCE if still_fenced else _STATE_NORMAL)


def _make_format(color: str) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    return fmt


def _editor_font() -> QFont:
    font = QFont("Consolas")
    if not font.exactMatch():
        font = QFont("Cascadia Mono")
    font.setPointSize(11)
    return font


def _doc_end_position(document: QTextDocument) -> int:
    """Return the caret position at the end of *document*.

    Returns:
        Position suitable for ``QTextCursor.setPosition`` (not
        ``characterCount() - 1``, which is often one too early).
    """
    cursor = QTextCursor(document)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    return cursor.position()


class _LineNumberArea(QWidget):
    """Narrow gutter that paints line numbers for :class:`SourceEditor`."""

    def __init__(self, editor: SourceEditor) -> None:
        """Bind to *editor*."""
        super().__init__(editor)
        self._editor = editor

    @override
    def sizeHint(self) -> QSize:
        """Return the preferred gutter width.

        Returns:
            Width from the editor's digit metrics; height unused by layout.
        """
        return QSize(self._editor.line_number_area_width(), 0)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Delegate painting to the owning editor."""
        self._editor.paint_line_numbers(event)


class SourceEditor(QPlainTextEdit):
    """Markdown source editor with a line-number gutter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the editor and its gutter."""
        super().__init__(parent)
        # Session-persisted undo lives on EditorTab; Qt's stack is not serializable.
        self.setUndoRedoEnabled(False)
        self._gutter = _LineNumberArea(self)
        self._overlays: list[QTextEdit.ExtraSelection] = []
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width(0)
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        """Width in pixels needed for the current last line number.

        Returns:
            Gutter width including padding.
        """
        digits = max(1, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def set_overlay_selections(self, overlays: list[QTextEdit.ExtraSelection]) -> None:
        """Set non-line overlays (e.g. find hits) and rebuild extras."""
        self._overlays = overlays
        self._highlight_current_line()

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        """Paint visible line numbers into the gutter."""
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor("#252526"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        color = QColor("#858585")
        current = QColor("#c6c6c6")
        current_block = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(current if block_number == current_block else color)
                painter.drawText(
                    0,
                    top,
                    self._gutter.width() - 6,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    def _update_gutter_width(self, _block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def _highlight_current_line(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        if not self.isReadOnly():
            line = QTextEdit.ExtraSelection()
            line.format.setBackground(QColor("#2a2d2e"))
            line.format.setProperty(
                QTextFormat.Property.FullWidthSelection,
                1,  # Qt treats non-zero as true for FullWidthSelection
            )
            line.cursor = self.textCursor()
            line.cursor.clearSelection()
            selections.append(line)
        selections.extend(self._overlays)
        self.setExtraSelections(selections)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Keep the gutter docked to the left of the viewport."""
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._gutter.setGeometry(
            contents.left(),
            contents.top(),
            self.line_number_area_width(),
            contents.height(),
        )

    def _main_window(self) -> MainWindow | None:
        win = self.window()
        return win if isinstance(win, MainWindow) else None

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Type normally, or overtype when replace mode is on (Ins toggles)."""
        mods = event.modifiers()
        no_mods = mods in {
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        }
        if event.key() == Qt.Key.Key_Insert and no_mods:
            host = self._main_window()
            if host is not None:
                host.toggle_replace_mode()
            return

        text = event.text()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        host = self._main_window()
        replace_on = host is not None and host.replace_mode
        if replace_on and text and text.isprintable() and not ctrl:
            cursor = self.textCursor()
            if not cursor.hasSelection() and not cursor.atEnd():
                # Select the single character under the caret to overtype it.
                cursor.movePosition(
                    QTextCursor.MoveOperation.NextCharacter,
                    QTextCursor.MoveMode.KeepAnchor,
                )
                self.setTextCursor(cursor)
            self.textCursor().insertText(text)
            return

        super().keyPressEvent(event)


class _InactiveCaret(QObject):
    """Draw a solid caret on a text pane even when it does not have focus."""

    def __init__(self, pane: QPlainTextEdit | QTextBrowser) -> None:
        """Attach to *pane* (source editor or preview)."""
        super().__init__(pane)
        self._pane: QPlainTextEdit | QTextBrowser | None = pane
        self._viewport = pane.viewport()
        self._enabled = True
        self._viewport.installEventFilter(self)
        pane.cursorPositionChanged.connect(self._request_repaint)
        pane.selectionChanged.connect(self._request_repaint)
        # Tear down before Qt deletes the pane (tab close / last-tab replace).
        pane.destroyed.connect(self.dispose)

    def dispose(self, *_args: object) -> None:
        """Remove filters/signals so late paints cannot touch a dead pane."""
        if not self._enabled and self._pane is None:
            return
        self._enabled = False
        pane = self._pane
        viewport = self._viewport
        self._pane = None
        if pane is not None and isValid(pane):
            with contextlib.suppress(RuntimeError):
                pane.cursorPositionChanged.disconnect(self._request_repaint)
            with contextlib.suppress(RuntimeError):
                pane.selectionChanged.disconnect(self._request_repaint)
        if viewport is not None and isValid(viewport):
            with contextlib.suppress(RuntimeError):
                viewport.removeEventFilter(self)

    def _request_repaint(self) -> None:
        pane = self._pane
        if not self._enabled or pane is None or not isValid(pane):
            return
        with contextlib.suppress(RuntimeError):
            pane.viewport().update()

    def schedule_repaint(self) -> None:
        """Repaint after the event loop lays out the document (post-setHtml)."""
        if self._enabled:
            QTimer.singleShot(0, self._request_repaint)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """After the viewport paints, draw our caret if the pane is unfocused.

        Returns:
            True when this filter handled the paint event.
        """
        pane = self._pane
        if (
            not self._enabled
            or pane is None
            or not isValid(pane)
            or event.type() != QEvent.Type.Paint
        ):
            return False
        try:
            viewport = pane.viewport()
        except RuntimeError:
            return False
        if watched is not viewport:
            return False
        watched.removeEventFilter(self)
        QApplication.sendEvent(watched, event)
        if self._enabled and isValid(watched):
            watched.installEventFilter(self)
            self._paint_caret()
        return True

    def _paint_caret(self) -> None:
        pane = self._pane
        if pane is None or not isValid(pane):
            return
        try:
            focused = pane.hasFocus()
            cursor = pane.textCursor()
            rect = pane.cursorRect(cursor)
            viewport = pane.viewport()
            palette_color = pane.palette().color(pane.foregroundRole())
        except RuntimeError:
            return
        if focused or cursor.hasSelection():
            return
        # Reject empty/stale rects (common right after setHtml, before layout).
        min_caret_height = 2
        if rect.height() < min_caret_height or rect.width() < 0:
            return
        if not viewport.rect().intersects(rect.adjusted(-1, 0, 1, 0)):
            return
        painter = QPainter(viewport)
        color = palette_color
        color.setAlpha(230)
        pen = QPen(color)
        pen.setWidth(1)
        painter.setPen(pen)
        x = rect.x()
        painter.drawLine(x, rect.y(), x, rect.y() + rect.height() - 1)
        painter.end()


class PreviewPane(QTextBrowser):
    """Rendered Markdown with a caret; typing edits the source editor."""

    # Movement is applied to the *source* editor, not the rendered plain text.
    _MOVE_KEYS = frozenset({
        Qt.Key.Key_Left,
        Qt.Key.Key_Right,
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_PageDown,
    })
    _MOD_KEYS = frozenset({
        Qt.Key.Key_Shift,
        Qt.Key.Key_Control,
        Qt.Key.Key_Alt,
        Qt.Key.Key_Meta,
        Qt.Key.Key_CapsLock,
        Qt.Key.Key_NumLock,
    })
    _PREVIEW_ONLY_KEYS = frozenset({Qt.Key.Key_A, Qt.Key.Key_C})

    def __init__(self, tab: EditorTab) -> None:
        """Bind to the owning *tab* (source editor + refresh)."""
        super().__init__()
        self._tab = tab
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setCursorWidth(1)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
        )

    def set_preview_html(self, html: str, *, base_dir: Path | None) -> None:
        """Load *html* with a file base URL and scale images to the viewport.

        QTextBrowser ignores CSS ``max-width`` / percentage ``width`` on
        ``<img>``, so large screenshots stay at intrinsic size and look
        cropped/off-center. After parse, clamp every image to the pane width.
        """
        root = (base_dir if base_dir is not None else Path.cwd()).resolve()
        base = QUrl.fromLocalFile(str(root) + "/")
        self.document().setBaseUrl(base)
        self.setHtml(html)
        self.fit_images()

    def fit_images(self) -> None:
        """Clamp embedded images to the viewport width (keep aspect ratio)."""
        doc = self.document()
        max_w = max(float(self.viewport().width() - 8), 32.0)
        # Skip no-op format writes when size already matches within half a pixel.
        eps = 0.5
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    img_fmt = frag.charFormat().toImageFormat()
                    image = self._image_for_format(img_fmt)
                    if image is not None and not image.isNull() and image.width() > 0:
                        iw = float(image.width())
                        ih = float(image.height())
                        # Honor explicit pixel widths when they already fit.
                        cur_w = img_fmt.width()
                        if cur_w > 0 and cur_w <= max_w:
                            new_w = cur_w
                        else:
                            new_w = min(iw, max_w)
                        new_h = ih * (new_w / iw)
                        if (
                            abs(img_fmt.width() - new_w) >= eps
                            or abs(img_fmt.height() - new_h) >= eps
                        ):
                            img_fmt.setWidth(new_w)
                            img_fmt.setHeight(new_h)
                            cur = QTextCursor(doc)
                            cur.setPosition(frag.position())
                            cur.setPosition(
                                frag.position() + frag.length(),
                                QTextCursor.MoveMode.KeepAnchor,
                            )
                            cur.setCharFormat(img_fmt)
                it += 1
            block = block.next()

    def _image_for_format(self, img_fmt: QTextImageFormat) -> QImage | None:
        """Resolve a ``QTextImageFormat`` to a ``QImage`` via base URL or path.

        Returns:
            The loaded image, or ``None`` when the resource cannot be resolved.
        """
        name = img_fmt.name()
        url = QUrl(name)
        if url.isRelative():
            url = self.document().baseUrl().resolved(url)
        if url.isLocalFile():
            image = QImage(url.toLocalFile())
            if not image.isNull():
                return image
        res = self.document().resource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(name),
        )
        if isinstance(res, QImage):
            return res
        return None

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-fit images when the preview pane width changes."""
        super().resizeEvent(event)
        self.fit_images()

    def _source_range_for_preview_selection(self) -> tuple[int, int]:
        """Map the current preview selection (or caret) onto source offsets.

        Returns:
            ``(start, end)`` indices into the Markdown source string.
        """
        source = self._tab.editor.toPlainText()
        plain = self.toPlainText()
        cursor = self.textCursor()
        start = preview_pos_to_source(source, plain, cursor.selectionStart())
        end = preview_pos_to_source(source, plain, cursor.selectionEnd())
        if end < start:
            start, end = end, start
        return start, end

    def _sync_editor_caret(self) -> None:
        """Copy the mapped preview selection onto the source editor caret."""
        start, end = self._source_range_for_preview_selection()
        cursor = self._tab.editor.textCursor()
        cursor.setPosition(start)
        if end != start:
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._tab.editor.setTextCursor(cursor)
        self._tab.editor.viewport().update()

    def _navigate_in_source(self, event: QKeyEvent) -> None:
        """Apply a movement key to the source editor, then mirror the caret here."""
        editor = self._tab.editor
        # Keep focus on the preview so typing continues here; only the caret moves.
        QApplication.sendEvent(editor, event)
        self._tab.mirror_source_caret_to_preview()
        self.ensureCursorVisible()
        self.viewport().update()
        editor.viewport().update()

    def _replace_source(self, start: int, end: int, text: str) -> None:
        """Replace ``source[start:end]`` with *text* (same as typing in the editor)."""
        self._tab.apply_source_edit(start, end, text)

    def _edit_from_key(self, key: int, *, ctrl: bool, text: str) -> bool:
        """Apply a source edit for *key*.

        Uses the **source** caret (kept in sync on click/arrows), not a fresh
        preview→source remap, so multi-character typing does not drift.

        Returns:
            True when the key was handled as a source edit.
        """
        editor_cursor = self._tab.editor.textCursor()
        start = editor_cursor.selectionStart()
        end = editor_cursor.selectionEnd()
        source = self._tab.editor.toPlainText()
        host = self.window()
        replace_on = isinstance(host, MainWindow) and host.replace_mode
        action = _preview_key_action(
            key,
            ctrl=ctrl,
            text=text,
            start=start,
            end=end,
            source_len=len(source),
            replace_mode=replace_on,
        )
        if action is None:
            return False
        delete_start, delete_end, replacement, do_cut = action
        if do_cut and delete_start != delete_end:
            QApplication.clipboard().setText(source[delete_start:delete_end])
        if replacement is not None:
            self._replace_source(delete_start, delete_end, replacement)
        return True

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """After a click, align the source caret with the preview caret."""
        super().mouseReleaseEvent(event)
        self._sync_editor_caret()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Navigate/edit as if the caret lived in the Markdown source editor."""
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if key in self._MOD_KEYS:
            return
        if key == Qt.Key.Key_Insert and not ctrl:
            host = self.window()
            if isinstance(host, MainWindow):
                host.toggle_replace_mode()
            return
        if ctrl and key in self._PREVIEW_ONLY_KEYS:
            super().keyPressEvent(event)
            return
        if key in self._MOVE_KEYS:
            # Arrows/Home/End/Page* move by source lines/chars, not rendered text.
            self._navigate_in_source(event)
            return
        if self._edit_from_key(key, ctrl=ctrl, text=event.text()):
            return
        super().keyPressEvent(event)


def _preview_key_action(  # ruff: ignore[complex-structure, too-many-return-statements, too-many-arguments, too-many-branches]
    key: int,
    *,
    ctrl: bool,
    text: str,
    start: int,
    end: int,
    source_len: int,
    replace_mode: bool = False,
) -> tuple[int, int, str | None, bool] | None:
    """Translate a preview key into a source edit.

    Returns:
        ``(del_start, del_end, replacement, cut)`` or ``None`` if the key is
        not a source edit. ``replacement is None`` means no document change
        (still handled). ``cut`` means copy the deleted span to the clipboard.
    """
    if ctrl and key == Qt.Key.Key_V:
        return start, end, QApplication.clipboard().text(), False
    if ctrl and key == Qt.Key.Key_X:
        if start == end:
            return start, end, None, False
        return start, end, "", True
    if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
        return start, end, "\n", False
    if key == Qt.Key.Key_Tab:
        return start, end, "\t", False
    if key == Qt.Key.Key_Backspace:
        if start != end:
            return start, end, "", False
        if start > 0:
            return start - 1, start, "", False
        return start, end, None, False
    if key == Qt.Key.Key_Delete:
        if start != end:
            return start, end, "", False
        if start < source_len:
            return start, start + 1, "", False
        return start, end, None, False
    if text and not ctrl and text.isprintable():
        # Overtype: with no selection, consume the next character(s).
        if replace_mode and start == end and start < source_len:
            end = min(start + max(1, len(text)), source_len)
        return start, end, text, False
    return None


class _SvgToolButton(QToolButton):
    """Tool button that swaps between two icons on hover."""

    def __init__(
        self,
        *,
        normal: QIcon,
        hover: QIcon | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Build with a normal icon and optional hover icon."""
        super().__init__(parent)
        self._normal = normal
        self._hover = hover if hover is not None else normal
        self.setIcon(self._normal)
        self.setAutoRaise(True)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Show the hover glyph."""
        self.setIcon(self._hover)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Restore the normal glyph."""
        self.setIcon(self._normal)
        super().leaveEvent(event)


class EditorTabStrip(QWidget):
    """Tab titles + trailing SVG ``+`` + stacked editor pages.

    Uses a real ``QHBoxLayout`` so the new-tab control sits immediately after
    the last tab and cannot be clipped the way a free child of ``QTabBar`` is.
    """

    current_changed = Signal(int)
    new_tab_requested = Signal()
    tab_bar_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the strip, plus button, and page stack."""
        super().__init__(parent)
        self._bar = QTabBar()
        self._bar.setExpanding(False)
        self._bar.setDrawBase(False)
        self._bar.setMovable(True)
        self._bar.setDocumentMode(True)
        self._bar.currentChanged.connect(self._on_current_changed)
        self._bar.tabMoved.connect(self._on_tab_moved)
        self._bar.tabBarClicked.connect(self.tab_bar_clicked.emit)

        self._new_btn = _SvgToolButton(normal=new_tab_icon(size=16))
        self._new_btn.setObjectName("newTabButton")
        self._new_btn.setIconSize(QSize(16, 16))
        self._new_btn.setFixedSize(28, 24)
        self._new_btn.setToolTip("New tab (Ctrl+N)")
        self._new_btn.clicked.connect(self.new_tab_requested.emit)

        strip = QWidget()
        strip.setObjectName("tabStrip")
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self._bar, 0)
        row.addWidget(self._new_btn, 0)
        row.addStretch(1)

        rule = QFrame()
        rule.setObjectName("tabStripRule")
        rule.setFrameShape(QFrame.Shape.HLine)
        rule.setFixedHeight(1)

        self._stack = QStackedWidget()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(strip)
        root.addWidget(rule)
        root.addWidget(self._stack, 1)

    def _on_current_changed(self, index: int) -> None:
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
        self.current_changed.emit(index)

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        widget = self._stack.widget(from_index)
        if widget is None:
            return
        self._stack.removeWidget(widget)
        self._stack.insertWidget(to_index, widget)
        self._stack.setCurrentIndex(self._bar.currentIndex())

    def add_tab(self, page: QWidget, title: str) -> int:
        """Append *page* and a matching title tab.

        Returns:
            Index of the new tab.
        """
        index = self._stack.addWidget(page)
        self._bar.addTab(title)
        return index

    def remove_tab(self, index: int) -> None:
        """Drop the title and page at *index* (does not delete the page)."""
        page = self._stack.widget(index)
        if page is not None:
            self._stack.removeWidget(page)
        self._bar.removeTab(index)

    def set_tab_text(self, index: int, title: str) -> None:
        """Update the title label for *index*."""
        self._bar.setTabText(index, title)

    def set_tab_close_button(self, index: int, button: QWidget) -> None:
        """Install a custom close control on the title tab."""
        self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def current_index(self) -> int:
        """Return the active tab index, or ``-1`` when empty."""
        return self._bar.currentIndex()

    def set_current_index(self, index: int) -> None:
        """Select *index* on both the bar and the stack."""
        self._bar.setCurrentIndex(index)
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)

    def current_widget(self) -> QWidget | None:
        """Return the active page widget, if any."""
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget | None:
        """Return the page at *index*, if any."""
        return self._stack.widget(index)

    def index_of(self, page: QWidget) -> int:
        """Return the index of *page*, or ``-1``."""
        return self._stack.indexOf(page)

    def count(self) -> int:
        """Return how many pages are open."""
        return self._stack.count()


class EditorTab(QWidget):
    """One document: editor + preview split, path, dirty flag."""

    meta_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build a blank untitled page."""
        super().__init__(parent)
        self.path: Path | None = None
        self.password: str | None = None  # session key; None = plaintext file
        self.dirty = False
        self.wrap_on = True
        self.preview_on = True
        self.session_id = new_tab_id()
        self.history = EditHistory()
        # Locked encrypted session tab: blob kept until unlock; never auto-closed.
        self.locked = False
        self.locked_blob: bytes | None = None
        self._applying_history = False
        self._restore_scroll = 0

        self.editor = SourceEditor()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setTabStopDistance(32)
        self.editor.setFont(_editor_font())
        self.editor.setCursorWidth(1)

        self.preview = PreviewPane(self)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([1, 1])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        # Keep a reference so the highlighter is not GC'd.
        self._highlighter = MarkdownHighlighter(self.editor.document())
        # Carets stay visible on the unfocused pane too.
        self._editor_caret = _InactiveCaret(self.editor)
        self._preview_caret = _InactiveCaret(self.preview)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.refresh_preview)
        self._sync_preview_from_source = True

        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._sync_preview_caret_from_editor)
        self.history.seed("")

    def dispose(self) -> None:
        """Drop caret filters before Qt deletes nested editor widgets."""
        self._preview_timer.stop()
        self._editor_caret.dispose()
        self._preview_caret.dispose()

    def tab_label(self) -> str:
        """Short name for the tab bar (with dirty star).

        Returns:
            Filename or ``Untitled``, prefixed with ``*`` when dirty.
        """
        name = self.path.name if self.path is not None else "Untitled"
        if self.locked:
            name = f"{name} (locked)"
        return f"*{name}" if self.dirty else name

    def _sync_preview_caret_from_editor(self) -> None:
        """Mirror the source caret into the preview when the editor is driving."""
        if not self.preview.isVisible() or self.preview.hasFocus():
            return
        self.mirror_source_caret_to_preview()

    def mirror_source_caret_to_preview(self) -> None:
        """Place the preview caret/selection from the source editor caret."""
        if not self.preview.isVisible():
            return
        source = self.editor.toPlainText()
        plain = self.preview.toPlainText()
        editor_cursor = self.editor.textCursor()
        preview_cursor = self.preview.textCursor()
        # Clamp against the live Qt document end (MoveOperation.End — not
        # characterCount()-1, which sits one code unit early in QTextBrowser).
        doc_end = _doc_end_position(self.preview.document())

        def _clamp(pos: int) -> int:
            return min(max(pos, 0), doc_end)

        if editor_cursor.hasSelection():
            start = _clamp(
                source_pos_to_preview(source, plain, editor_cursor.selectionStart())
            )
            end = _clamp(
                source_pos_to_preview(source, plain, editor_cursor.selectionEnd())
            )
            preview_cursor.setPosition(start)
            preview_cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        else:
            pos = _clamp(source_pos_to_preview(source, plain, editor_cursor.position()))
            preview_cursor.setPosition(pos)
        with QSignalBlocker(self.preview):
            self.preview.setTextCursor(preview_cursor)
        self.preview.ensureCursorVisible()
        self.preview.viewport().update()
        self.editor.viewport().update()
        # Layout finishes after setHtml/setTextCursor returns — repaint caret then.
        self._preview_caret.schedule_repaint()
        self._editor_caret.schedule_repaint()

    def _on_text_changed(self) -> None:
        if not self._applying_history and not self.locked:
            self.history.record(
                self.editor.toPlainText(),
                self.editor.textCursor().position(),
            )
        if not self.dirty:
            self.dirty = True
            self.meta_changed.emit()
        if self._sync_preview_from_source:
            self._preview_timer.start()

    def apply_history_frame(self, frame: EditFrame) -> None:
        """Replace editor text/cursor from an undo/redo frame."""
        self._applying_history = True
        try:
            self.editor.setPlainText(frame.text)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(max(frame.cursor, 0), len(frame.text)))
            self.editor.setTextCursor(cursor)
        finally:
            self._applying_history = False
        self.dirty = True
        self.meta_changed.emit()
        self.refresh_preview()

    def apply_source_edit(self, start: int, end: int, text: str) -> None:
        """Apply a source edit as if it were typed in the Markdown editor.

        Used by the preview pane so keystrokes land in the same document.
        """
        source = self.editor.toPlainText()
        start = max(0, min(start, len(source)))
        end = max(start, min(end, len(source)))
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        # Immediate re-render so the caret can follow the edit.
        self._preview_timer.stop()
        self.refresh_preview(follow_source_caret=True)

    def refresh_preview(self, *, follow_source_caret: bool = False) -> None:
        """Push current Markdown into the HTML preview if visible.

        Args:
            follow_source_caret: Unused (kept for call-site compatibility).
                The source caret is always the position source of truth.
        """
        del follow_source_caret  # source caret always wins
        if not self.preview.isVisible():
            return
        old_scroll = self.preview.verticalScrollBar().value()
        source = self.editor.toPlainText()
        source_pos = self.editor.textCursor().position()

        base_dir = self.path.parent if self.path is not None else None
        self.preview.set_preview_html(to_html(source), base_dir=base_dir)
        plain_after = self.preview.toPlainText()
        new_pos = source_pos_to_preview(source, plain_after, source_pos)

        cursor = self.preview.textCursor()
        doc_end = _doc_end_position(self.preview.document())
        cursor.setPosition(min(max(new_pos, 0), doc_end))
        # Restore selection from the source editor when present.
        editor_cursor = self.editor.textCursor()
        if editor_cursor.hasSelection():
            start = min(
                max(
                    source_pos_to_preview(
                        source, plain_after, editor_cursor.selectionStart()
                    ),
                    0,
                ),
                doc_end,
            )
            end = min(
                max(
                    source_pos_to_preview(
                        source, plain_after, editor_cursor.selectionEnd()
                    ),
                    0,
                ),
                doc_end,
            )
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        with QSignalBlocker(self.preview):
            self.preview.setTextCursor(cursor)
        self.preview.verticalScrollBar().setValue(old_scroll)
        self.preview.ensureCursorVisible()
        self.preview.viewport().update()
        self.editor.viewport().update()
        self._preview_caret.schedule_repaint()
        self._editor_caret.schedule_repaint()

    def load_text(
        self, text: str, path: Path | None, *, password: str | None = None
    ) -> None:
        """Replace contents without leaving a dirty flag behind."""
        self.locked = False
        self.locked_blob = None
        self.editor.setReadOnly(False)
        self.editor.setPlaceholderText("")
        self._applying_history = True
        try:
            self.editor.setPlainText(text)
        finally:
            self._applying_history = False
        self.path = path
        self.password = password
        self.dirty = False
        self.history.seed(text, self.editor.textCursor().position())
        self.refresh_preview()

    def apply_payload(self, payload: TabPayload, *, password: str | None) -> None:
        """Restore a session payload (text, history, view flags)."""
        self.locked = False
        self.locked_blob = None
        self.editor.setReadOnly(False)
        self.editor.setPlaceholderText("")
        self.history = payload.history
        self.path = Path(payload.path) if payload.path else None
        self.password = password
        self.dirty = payload.dirty
        self.set_wrap(on=payload.wrap_on)
        self.set_preview(on=payload.preview_on)
        self._restore_scroll = payload.scroll
        frame = self.history.current
        self._applying_history = True
        try:
            self.editor.setPlainText(frame.text)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(max(frame.cursor, 0), len(frame.text)))
            self.editor.setTextCursor(cursor)
        finally:
            self._applying_history = False
        self.refresh_preview()
        QTimer.singleShot(0, self._apply_restore_scroll)

    def _apply_restore_scroll(self) -> None:
        self.editor.verticalScrollBar().setValue(self._restore_scroll)

    def set_locked(self, blob: bytes, *, path: Path | None, dirty: bool) -> None:
        """Show a locked encrypted session tab; body stays ciphertext until unlock."""
        self.locked = True
        self.locked_blob = blob
        self.path = path
        self.password = None
        self.dirty = dirty
        self.history.seed("")
        self._applying_history = True
        try:
            self.editor.setPlainText("")
        finally:
            self._applying_history = False
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("Password required — switch here to unlock.")
        self.preview.setHtml("")

    def to_payload(self) -> TabPayload:
        """Snapshot unlocked tab state for session write.

        Returns:
            Serializable tab body including undo/redo history.
        """
        # Keep history.current aligned with the live buffer/cursor.
        text = self.editor.toPlainText()
        cursor = self.editor.textCursor().position()
        if text != self.history.current.text:
            self.history.record(text, cursor)
        else:
            self.history.current = EditFrame(text, cursor)
        return TabPayload(
            history=self.history,
            path=str(self.path) if self.path is not None else None,
            dirty=self.dirty,
            wrap_on=self.wrap_on,
            preview_on=self.preview_on,
            scroll=self.editor.verticalScrollBar().value(),
        )

    def set_wrap(self, *, on: bool) -> None:
        """Toggle word wrap for this tab's editor."""
        self.wrap_on = on
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if on
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.editor.setLineWrapMode(mode)

    def set_preview(self, *, on: bool) -> None:
        """Show or hide the preview pane."""
        self.preview_on = on
        self.preview.setVisible(on)
        if on:
            self.refresh_preview()

    def apply_find_highlights(self, matches: list[Match], current: int) -> None:
        """Paint find hits with ExtraSelections; *current* index is brighter."""
        dim = QColor("#3a4a20")
        bright = QColor("#6b8c2a")
        selections: list[QTextEdit.ExtraSelection] = []
        for index, hit in enumerate(matches):
            sel = QTextEdit.ExtraSelection()
            cursor = self.editor.textCursor()
            cursor.setPosition(hit.start)
            cursor.setPosition(hit.end, QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            fmt = QTextCharFormat()
            fmt.setBackground(bright if index == current else dim)
            sel.format = fmt
            selections.append(sel)
        self.editor.set_overlay_selections(selections)

    def clear_find_highlights(self) -> None:
        """Remove find ExtraSelections."""
        self.editor.set_overlay_selections([])

    def reveal_match(self, hit: Match) -> None:
        """Select *hit* and scroll it into view."""
        cursor = self.editor.textCursor()
        cursor.setPosition(hit.start)
        cursor.setPosition(hit.end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()


class FindReplaceDialog(QDialog):
    """Modeless find/replace sheet shared across tabs."""

    def __init__(self, main: MainWindow) -> None:
        """Wire controls to *main*'s active tab."""
        super().__init__(main)
        self._main = main
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        self.setMinimumWidth(420)

        self._find_edit = QLineEdit()
        self._replace_edit = QLineEdit()
        self._case = QCheckBox("Match &case")
        self._word = QCheckBox("Whole &word")
        self._regex = QCheckBox("Regular e&xpression")
        self._in_sel = QCheckBox("In &selection")
        self._in_hi = QCheckBox("In &highlighted zones only")
        self._status = QLabel("")
        self._status.setWordWrap(True)

        form = QFormLayout()
        form.addRow("&Find:", self._find_edit)
        form.addRow("Rep&lace:", self._replace_edit)

        opts = QVBoxLayout()
        for box in (
            self._case,
            self._word,
            self._regex,
            self._in_sel,
            self._in_hi,
        ):
            opts.addWidget(box)

        buttons = QHBoxLayout()
        find_next_btn = QPushButton("Find &Next")
        find_prev_btn = QPushButton("Find &Previous")
        replace_btn = QPushButton("&Replace")
        replace_all_btn = QPushButton("Replace &All")
        find_next_btn.setDefault(True)
        find_next_btn.clicked.connect(self._find_next)
        find_prev_btn.clicked.connect(self._find_prev)
        replace_btn.clicked.connect(self._replace_one)
        replace_all_btn.clicked.connect(self._replace_all)
        buttons.addWidget(find_next_btn)
        buttons.addWidget(find_prev_btn)
        buttons.addWidget(replace_btn)
        buttons.addWidget(replace_all_btn)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.close)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(opts)
        root.addLayout(buttons)
        root.addWidget(self._status)
        root.addWidget(close_box)

        self._matches: list[Match] = []
        self._index = -1
        self._find_edit.returnPressed.connect(self._find_next)
        self._find_edit.textChanged.connect(self._invalidate)

        for box in (self._case, self._word, self._regex, self._in_sel, self._in_hi):
            box.toggled.connect(self._invalidate)

    def open_for_find(self) -> None:
        """Show dialog focused on the find field (Ctrl+F)."""
        tab = self._main.current_tab()
        if tab is not None:
            selected = tab.editor.textCursor().selectedText().replace("\u2029", "\n")
            if selected and "\n" not in selected:
                self._find_edit.setText(selected)
        self.show()
        self.raise_()
        self.activateWindow()
        self._find_edit.setFocus()
        self._find_edit.selectAll()

    def open_for_replace(self) -> None:
        """Show dialog focused on replace (Ctrl+H)."""
        self.open_for_find()
        self._replace_edit.setFocus()

    def _options(self) -> FindOptions:
        return FindOptions(
            pattern=self._find_edit.text(),
            case_sensitive=self._case.isChecked(),
            whole_word=self._word.isChecked(),
            regex=self._regex.isChecked(),
            in_selection=self._in_sel.isChecked(),
            in_highlight=self._in_hi.isChecked(),
        )

    @staticmethod
    def _selection_bounds(tab: EditorTab) -> tuple[int, int] | None:
        cursor = tab.editor.textCursor()
        if not cursor.hasSelection():
            return None
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        return (start, end)

    def _recompute(self, tab: EditorTab) -> bool:
        text = tab.editor.toPlainText()
        options = self._options()
        selection = self._selection_bounds(tab) if options.in_selection else None
        zones = highlight_ranges(text) if options.in_highlight else None
        try:
            self._matches = find_all(
                text,
                options,
                selection=selection,
                highlight_ranges=zones,
            )
        except FindError as exc:
            self._matches = []
            self._index = -1
            tab.clear_find_highlights()
            self._status.setText(str(exc))
            return False
        return True

    def _invalidate(self) -> None:
        self._matches = []
        self._index = -1
        tab = self._main.current_tab()
        if tab is not None:
            tab.clear_find_highlights()
        self._status.clear()

    def _paint(self, tab: EditorTab) -> None:
        tab.apply_find_highlights(self._matches, self._index)
        if 0 <= self._index < len(self._matches):
            tab.reveal_match(self._matches[self._index])
            self._status.setText(f"{self._index + 1} of {len(self._matches)}")
        elif self._matches:
            self._status.setText(f"{len(self._matches)} matches")
        else:
            self._status.setText("No matches")

    def find_next(self) -> None:
        """Public Find Next (menu / F3)."""
        self._find_next()

    def find_prev(self) -> None:
        """Public Find Previous (Shift+F3)."""
        self._find_prev()

    def _find_next(self) -> None:
        tab = self._main.current_tab()
        if tab is None:
            return
        if not self._recompute(tab):
            return
        if not self._matches:
            self._paint(tab)
            return
        if self._index < 0:
            self._index = 0
        else:
            self._index = (self._index + 1) % len(self._matches)
        self._paint(tab)

    def _find_prev(self) -> None:
        tab = self._main.current_tab()
        if tab is None:
            return
        if not self._recompute(tab):
            return
        if not self._matches:
            self._paint(tab)
            return
        if self._index < 0:
            self._index = len(self._matches) - 1
        else:
            self._index = (self._index - 1) % len(self._matches)
        self._paint(tab)

    def _replace_one(self) -> None:
        tab = self._main.current_tab()
        if tab is None:
            return
        if not self._recompute(tab):
            return
        if not self._matches:
            self._paint(tab)
            return
        self._index = max(self._index, 0)
        # Clamp in case the document shrank.
        self._index = min(self._index, len(self._matches) - 1)
        hit = self._matches[self._index]
        options = self._options()
        text = tab.editor.toPlainText()
        replacement = self._replace_edit.text()
        try:
            new_text = replace_one(text, options, replacement, hit)
        except FindError as exc:
            self._status.setText(str(exc))
            return
        # Cursor lands just after the inserted replacement text.
        new_end = hit.start + (len(new_text) - len(text) + (hit.end - hit.start))
        tab.editor.setPlainText(new_text)
        c = tab.editor.textCursor()
        c.setPosition(min(max(new_end, 0), len(new_text)))
        tab.editor.setTextCursor(c)
        if not self._recompute(tab):
            return
        if self._matches:
            self._index = min(self._index, len(self._matches) - 1)
        else:
            self._index = -1
        self._paint(tab)

    def _replace_all(self) -> None:
        tab = self._main.current_tab()
        if tab is None:
            return
        options = self._options()
        text = tab.editor.toPlainText()
        selection = self._selection_bounds(tab) if options.in_selection else None
        zones = highlight_ranges(text) if options.in_highlight else None
        try:
            new_text, count = replace_all(
                text,
                options,
                self._replace_edit.text(),
                selection=selection,
                highlight_ranges=zones,
            )
        except FindError as exc:
            self._status.setText(str(exc))
            return
        if count:
            tab.editor.setPlainText(new_text)
        self._matches = []
        self._index = -1
        tab.clear_find_highlights()
        self._status.setText(f"Replaced {count} occurrence(s)")

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Clear find paint when the sheet goes away."""
        tab = self._main.current_tab()
        if tab is not None:
            tab.clear_find_highlights()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Notepad shell: tab strip, menus, shared find dialog, status bar."""

    def __init__(self) -> None:
        """Build the window and restore the previous tab session if any."""
        super().__init__()
        self._replace_mode = False
        self._restoring_session = False
        # Set when the restored active tab is encrypted; unlock after first show.
        self._prompt_active_unlock = False

        self._tabs = EditorTabStrip()
        self._tabs.new_tab_requested.connect(self._new_tab)
        self._tabs.current_changed.connect(self._on_tab_changed)
        self._tabs.tab_bar_clicked.connect(self._on_tab_bar_clicked)
        self.setCentralWidget(self._tabs)

        self._pos_label = QLabel("Ln 1, Col 1")
        self._meta_label = QLabel("INS  |  UTF-8  |  Markdown")
        status = QStatusBar()
        status.addWidget(self._pos_label, 1)
        right = QWidget()
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 8, 0)
        right_layout.addWidget(self._meta_label)
        status.addPermanentWidget(right)
        self.setStatusBar(status)

        self._find_dialog = FindReplaceDialog(self)
        self._wrap_action: QAction | None = None
        self._preview_action: QAction | None = None

        self._build_menus()
        if not self._restore_session():
            self._new_tab()
        self.resize(1000, 680)
        self._set_title()

    @property
    def replace_mode(self) -> bool:
        """True when overtype/replace mode is active (Ins toggles)."""
        return self._replace_mode

    def toggle_replace_mode(self) -> None:
        """Flip insert/overtype mode and refresh the status bar."""
        self._replace_mode = not self._replace_mode
        self._update_status()

    def current_tab(self) -> EditorTab | None:
        """Active editor page, or ``None`` if the strip is empty.

        Returns:
            The current :class:`EditorTab`, if any.
        """
        widget = self._tabs.current_widget()
        return widget if isinstance(widget, EditorTab) else None

    def tab_meta_changed(self) -> None:
        """Refresh tab label + window title after dirty/path changes."""
        tab = self.current_tab()
        if tab is None:
            return
        index = self._tabs.current_index()
        self._tabs.set_tab_text(index, tab.tab_label())
        self._set_title()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(
            self._act("&New Tab", QKeySequence.StandardKey.New, self._new_tab)
        )
        file_menu.addAction(
            self._act("&Open...", QKeySequence.StandardKey.Open, self._open)
        )
        file_menu.addAction(
            self._act("&Save", QKeySequence.StandardKey.Save, self._save)
        )
        file_menu.addAction(
            self._act("Save &As...", QKeySequence.StandardKey.SaveAs, self._save_as)
        )
        export_menu = file_menu.addMenu("E&xport")
        export_menu.addAction("Markdown...").triggered.connect(self._export_markdown)
        export_menu.addAction("HTML...").triggered.connect(self._export_html)
        file_menu.addAction(
            self._act("Close &Tab", QKeySequence.StandardKey.Close, self._close_current)
        )
        file_menu.addSeparator()
        file_menu.addAction(
            self._act("E&xit", QKeySequence.StandardKey.Quit, self.close)
        )

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(
            self._act("&Undo", QKeySequence.StandardKey.Undo, self._undo)
        )
        edit_menu.addAction(
            self._act("&Redo", QKeySequence.StandardKey.Redo, self._redo)
        )
        edit_menu.addSeparator()
        edit_menu.addAction(self._act("Cu&t", QKeySequence.StandardKey.Cut, self._cut))
        edit_menu.addAction(
            self._act("&Copy", QKeySequence.StandardKey.Copy, self._copy)
        )
        edit_menu.addAction(
            self._act("&Paste", QKeySequence.StandardKey.Paste, self._paste)
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._act(
                "Select &All",
                QKeySequence.StandardKey.SelectAll,
                self._select_all,
            )
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._act(
                "&Find...",
                QKeySequence.StandardKey.Find,
                self._find_dialog.open_for_find,
            )
        )
        edit_menu.addAction(
            self._act(
                "Find &Next",
                QKeySequence.StandardKey.FindNext,
                self._find_dialog.find_next,
            )
        )
        edit_menu.addAction(
            self._act(
                "Find Pre&vious",
                QKeySequence.StandardKey.FindPrevious,
                self._find_dialog.find_prev,
            )
        )
        edit_menu.addAction(
            self._act(
                "&Replace...",
                QKeySequence.StandardKey.Replace,
                self._find_dialog.open_for_replace,
            )
        )

        view_menu = self.menuBar().addMenu("&View")
        self._preview_action = QAction("&Preview pane", self)
        self._preview_action.setCheckable(True)
        self._preview_action.setChecked(True)
        self._preview_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self._preview_action.toggled.connect(
            lambda on: self._toggle_preview(checked=on)
        )
        view_menu.addAction(self._preview_action)

        self._wrap_action = QAction("&Word wrap", self)
        self._wrap_action.setCheckable(True)
        self._wrap_action.setChecked(True)
        self._wrap_action.toggled.connect(lambda on: self._toggle_wrap(checked=on))
        view_menu.addAction(self._wrap_action)

        # Top-level action sits to the right of View (menu-bar "button").
        self._password_action = QAction("Pass&word", self)
        self._password_action.triggered.connect(self._set_password)
        self.menuBar().addAction(self._password_action)

    def _act(
        self,
        text: str,
        shortcut: QKeySequence.StandardKey,
        slot: Callable[[], object],
    ) -> QAction:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.triggered.connect(slot)
        return action

    def _set_title(self) -> None:
        tab = self.current_tab()
        if tab is None:
            self.setWindowTitle("Morgul")
            return
        name = tab.path.name if tab.path is not None else "Untitled"
        mark = "*" if tab.dirty else ""
        self.setWindowTitle(f"{mark}{name} - Morgul")
        if hasattr(self, "_password_action"):
            self._password_action.setText(
                "Pass&word •" if tab.password else "Pass&word"
            )

    def _install_close_button(self, index: int, tab: EditorTab) -> None:
        """Put an SVG X on the tab instead of the platform default mark."""
        btn = _SvgToolButton(
            normal=close_icon(size=12),
            hover=close_icon_hover(size=12),
            parent=self._tabs,
        )
        btn.setObjectName("tabCloseButton")
        btn.setIconSize(QSize(12, 12))
        btn.setFixedSize(18, 18)
        btn.setToolTip("Close tab")
        btn.clicked.connect(lambda: self._close_tab_widget(tab))
        self._tabs.set_tab_close_button(index, btn)

    def _new_tab(self, *_args: object, select: bool = True) -> EditorTab:
        tab = EditorTab()
        tab.editor.cursorPositionChanged.connect(self._update_status)
        tab.meta_changed.connect(self.tab_meta_changed)
        index = self._tabs.add_tab(tab, tab.tab_label())
        self._install_close_button(index, tab)
        if select:
            self._tabs.set_current_index(index)
            tab.editor.setFocus()
            self._set_title()
            self._update_status()
        return tab

    def _close_tab_widget(self, tab: EditorTab) -> None:
        """Close by widget identity so tab indices cannot go stale."""
        index = self._tabs.index_of(tab)
        if index >= 0:
            self._close_tab_at(index)

    def _on_tab_changed(self, _index: int) -> None:
        if self._restoring_session:
            return
        tab = self.current_tab()
        if tab is None:
            return
        self._sync_view_for_tab(tab)

    def _on_tab_bar_clicked(self, index: int) -> None:
        """Prompt for password only when the user opens that tab."""
        if self._restoring_session:
            return
        widget = self._tabs.widget(index)
        if isinstance(widget, EditorTab) and widget.locked:
            self._try_unlock_tab(widget)
            self._sync_view_for_tab(widget)

    def _sync_view_for_tab(self, tab: EditorTab) -> None:
        if self._wrap_action is not None:
            with QSignalBlocker(self._wrap_action):
                self._wrap_action.setChecked(tab.wrap_on)
        if self._preview_action is not None:
            with QSignalBlocker(self._preview_action):
                self._preview_action.setChecked(tab.preview_on)
        self._set_title()
        self._update_status()
        index = self._tabs.index_of(tab)
        if index >= 0:
            self._tabs.set_tab_text(index, tab.tab_label())
        tab.editor.setFocus()

    def _try_unlock_tab(self, tab: EditorTab) -> None:
        """Prompt for password and decrypt a locked session tab in place.

        Failures leave the tab open and locked so the user can switch away.
        """
        if not tab.locked or tab.locked_blob is None:
            return
        name = tab.path.name if tab.path is not None else "Untitled"
        dialog = UnlockPasswordDialog(self, filename=name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        password = dialog.password()
        if password is None:
            return
        try:
            payload = decode_tab_blob(tab.locked_blob, password)
        except (MorgulFormatError, ValueError) as exc:
            QMessageBox.warning(self, "Morgul", str(exc))
            return
        tab.apply_payload(payload, password=password)
        self.tab_meta_changed()

    def _update_status(self) -> None:
        tab = self.current_tab()
        mode = "OVR" if self._replace_mode else "INS"
        self._meta_label.setText(f"{mode}  |  UTF-8  |  Markdown")
        if tab is None:
            self._pos_label.setText("")
            return
        cursor = tab.editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        self._pos_label.setText(f"Ln {line}, Col {col}")

    def _toggle_preview(self, *, checked: bool) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.set_preview(on=checked)

    def _toggle_wrap(self, *, checked: bool) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.set_wrap(on=checked)

    def _undo(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        frame = tab.history.undo_step()
        if frame is not None:
            tab.apply_history_frame(frame)

    def _redo(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        frame = tab.history.redo_step()
        if frame is not None:
            tab.apply_history_frame(frame)

    def _restore_session(self) -> bool:
        """Reload tabs from ``~/.morgul``.

        Returns:
            True when at least one tab was restored.
        """
        index = load_index()
        if index is None:
            return False
        self._restoring_session = True
        try:
            opened = self._load_session_tabs(index)
        finally:
            self._restoring_session = False
        if opened == 0:
            return False
        active = max(0, min(index.active, opened - 1))
        self._tabs.set_current_index(active)
        self._finish_session_restore()
        return True

    def _load_session_tabs(self, index: SessionIndex) -> int:
        """Materialize tabs from *index*; encrypted tabs stay locked.

        Returns:
            Number of tabs successfully opened.
        """
        opened = 0
        for meta in index.tabs:
            blob = read_tab_blob(meta.id)
            if blob is None:
                continue
            tab = self._new_tab(select=False)
            tab.session_id = meta.id
            path = Path(meta.path) if meta.path else None
            if meta.encrypted or blob_is_encrypted(blob):
                tab.set_locked(blob, path=path, dirty=meta.dirty)
                tab.set_wrap(on=meta.wrap_on)
                tab.set_preview(on=meta.preview_on)
            else:
                try:
                    payload = decode_tab_blob(blob, None)
                except ValueError:
                    self._drop_tab_widget(tab)
                    continue
                tab.apply_payload(payload, password=None)
            self._tabs.set_tab_text(self._tabs.index_of(tab), tab.tab_label())
            opened += 1
        return opened

    def _drop_tab_widget(self, tab: EditorTab) -> None:
        """Remove a half-built tab from the strip without discard prompts."""
        idx = self._tabs.index_of(tab)
        if idx >= 0:
            self._tabs.remove_tab(idx)
        tab.dispose()
        tab.deleteLater()

    def _finish_session_restore(self) -> None:
        """Sync chrome after restore; defer active-tab unlock until after show."""
        active_tab = self.current_tab()
        if active_tab is None:
            return
        self._prompt_active_unlock = active_tab.locked
        if self._wrap_action is not None:
            with QSignalBlocker(self._wrap_action):
                self._wrap_action.setChecked(active_tab.wrap_on)
        if self._preview_action is not None:
            with QSignalBlocker(self._preview_action):
                self._preview_action.setChecked(active_tab.preview_on)
        active_tab.editor.setFocus()
        self._set_title()
        self._update_status()

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """After the window is on screen, unlock the restored active tab if needed."""
        super().showEvent(event)
        if self._prompt_active_unlock:
            self._prompt_active_unlock = False
            # Next event-loop tick so the main window paints before the dialog.
            QTimer.singleShot(0, self._unlock_active_if_locked)

    def _unlock_active_if_locked(self) -> None:
        """Prompt for the active tab's password (startup path only)."""
        tab = self.current_tab()
        if tab is not None and tab.locked:
            self._try_unlock_tab(tab)
            self._sync_view_for_tab(tab)

    def _save_session(self) -> None:
        """Persist all tabs (encrypted bodies use the document password)."""
        count = self._tabs.count()
        if count == 0:
            clear_session()
            return
        metas: list[TabMeta] = []
        keep: set[str] = set()
        for i in range(count):
            widget = self._tabs.widget(i)
            if not isinstance(widget, EditorTab):
                continue
            tab = widget
            keep.add(tab.session_id)
            path_s = str(tab.path) if tab.path is not None else None
            if tab.locked and tab.locked_blob is not None:
                write_tab_blob(tab.session_id, tab.locked_blob)
                encrypted = True
            elif tab.password:
                write_tab_blob(
                    tab.session_id, encode_tab_blob(tab.to_payload(), tab.password)
                )
                encrypted = True
            else:
                write_tab_blob(tab.session_id, encode_tab_blob(tab.to_payload(), None))
                encrypted = False
            metas.append(
                TabMeta(
                    id=tab.session_id,
                    path=path_s,
                    encrypted=encrypted,
                    wrap_on=tab.wrap_on,
                    preview_on=tab.preview_on,
                    dirty=tab.dirty,
                )
            )
        if not metas:
            clear_session()
            return
        active = max(0, min(self._tabs.current_index(), len(metas) - 1))
        save_index(SessionIndex(version=SESSION_VERSION, active=active, tabs=metas))
        prune_tab_blobs(keep)

    def _cut(self) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.cut()

    def _copy(self) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.copy()

    def _paste(self) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.paste()

    def _select_all(self) -> None:
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.selectAll()

    def _confirm_discard(self, tab: EditorTab) -> bool:
        if not tab.dirty:
            return True
        name = tab.path.name if tab.path is not None else "Untitled"
        answer = QMessageBox.question(
            self,
            "Morgul",
            f"'{name}' has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _close_tab_at(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if not isinstance(widget, EditorTab):
            return
        if not self._confirm_discard(widget):
            return
        self._tabs.remove_tab(index)
        widget.dispose()
        widget.deleteLater()
        if self._tabs.count() == 0:
            clear_session()
            self.close()

    def _close_current(self) -> None:
        index = self._tabs.current_index()
        if index >= 0:
            self._close_tab_at(index)

    def _open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open",
            "",
            "Markdown & Morgul (*.md *.markdown *.mdown *.txt *.morgul);;"
            "Morgul (*.morgul);;Markdown (*.md *.markdown *.mdown *.txt);;"
            "All files (*.*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            text, password = self._read_document(path)
        except MorgulFormatError as exc:
            QMessageBox.warning(self, "Morgul", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Morgul", f"Could not open file:\n{exc}")
            return
        except _UserCancelledError:
            return

        tab = self.current_tab()
        if (
            tab is not None
            and tab.path is None
            and not tab.dirty
            and not tab.locked
            and not tab.editor.toPlainText()
        ):
            target = tab
        else:
            target = self._new_tab()
        target.load_text(text, path=path, password=password)
        self.tab_meta_changed()

    def _read_document(self, path: Path) -> tuple[str, str | None]:
        """Load Markdown or MORGUL from *path*.

        Returns:
            ``(markdown, password_or_none)``.

        Raises:
            _UserCancelledError: User aborted the password prompt.
        """
        raw = path.read_bytes()
        encrypted = is_morgul_path(path) or looks_like_morgul(raw)
        if not encrypted:
            return raw.decode("utf-8"), None

        dialog = UnlockPasswordDialog(self, filename=path.name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            raise _UserCancelledError
        password = dialog.password()
        if password is None:
            raise _UserCancelledError
        return unpack(raw, password), password

    @staticmethod
    def _write_document(tab: EditorTab, path: Path) -> None:
        """Write *tab* contents to *path* (MORGUL when a password is set)."""
        text = tab.editor.toPlainText()
        if tab.password:
            path.write_bytes(pack(text, tab.password))
        else:
            path.write_text(text, encoding="utf-8", newline="\n")

    def _save(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        if tab.path is None:
            self._save_as()
            return
        # Password state must match container type.
        if tab.password and not is_morgul_path(tab.path):
            self._save_as()
            return
        if not tab.password and is_morgul_path(tab.path):
            self._save_as()
            return
        try:
            self._write_document(tab, tab.path)
        except OSError as exc:
            QMessageBox.warning(self, "Morgul", f"Could not save file:\n{exc}")
            return
        tab.dirty = False
        self.tab_meta_changed()

    def _save_as(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        if tab.password:
            default = "Untitled.morgul"
            if tab.path is not None:
                default = str(tab.path.with_suffix(".morgul"))
            filters = "Morgul (*.morgul);;All files (*.*)"
        else:
            default = "Untitled.md"
            if tab.path is not None:
                default = str(tab.path.with_suffix(".md"))
            filters = "Markdown (*.md);;All files (*.*)"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            default,
            filters,
        )
        if not path_str:
            return
        path = Path(path_str)
        if tab.password and path.suffix.lower() != ".morgul":
            path = path.with_suffix(".morgul")
        if not tab.password and path.suffix.lower() == ".morgul":
            path = path.with_suffix(".md")
        try:
            self._write_document(tab, path)
        except OSError as exc:
            QMessageBox.warning(self, "Morgul", f"Could not save file:\n{exc}")
            return
        tab.path = path
        tab.dirty = False
        self.tab_meta_changed()

    def _set_password(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.locked:
            self._try_unlock_tab(tab)
            return
        dialog = SetPasswordDialog(self, has_password=bool(tab.password))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = dialog.password()
        if result is None:
            return
        tab.password = result or None
        tab.dirty = True
        self.tab_meta_changed()
        # Encourage saving into the matching container type.
        if tab.password and (tab.path is None or not is_morgul_path(tab.path)):
            QMessageBox.information(
                self,
                "Password",
                "This document is now encrypted. Use Save As to write a .morgul file.",
            )
        elif not tab.password and tab.path is not None and is_morgul_path(tab.path):
            QMessageBox.information(
                self,
                "Password",
                "Encryption removed. Use Save As to write a plain Markdown file.",
            )

    def _export_markdown(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        default = "export.md"
        if tab.path is not None:
            default = str(tab.path.with_suffix(".md"))
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markdown",
            default,
            "Markdown (*.md);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            Path(path_str).write_text(
                tab.editor.toPlainText(),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Morgul", f"Could not export:\n{exc}")

    def _export_html(self) -> None:
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        default = "export.html"
        if tab.path is not None:
            default = str(tab.path.with_suffix(".html"))
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Export HTML",
            default,
            "HTML (*.html *.htm);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            Path(path_str).write_text(
                to_html(tab.editor.toPlainText()),
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Morgul", f"Could not export:\n{exc}")

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Persist tabs under ``~/.morgul`` (Notepad-style; keeps dirty buffers)."""
        try:
            self._save_session()
        except OSError as exc:
            answer = QMessageBox.warning(
                self,
                "Morgul",
                f"Could not save session:\n{exc}\n\nQuit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._find_dialog.close()
        event.accept()


def run() -> None:
    """Create the QApplication and show the main window.

    Raises:
        SystemExit: Always, with the Qt event-loop exit code.
    """
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Morgul")
    app.setOrganizationName("Morgul")
    app.setStyle("Fusion")
    app.setStyleSheet(_DARK_QSS)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
