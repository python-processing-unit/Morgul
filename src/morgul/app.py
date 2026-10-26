"""Main window: dark Win11 Notepad layout, tabs, find/replace, preview."""

from __future__ import annotations

import contextlib
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import xxhash
from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QPoint,
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
    QContextMenuEvent,
    QDrag,
    QDropEvent,
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
    QPixmap,
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
from spellchecker import SpellChecker
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
    RECENT_LIMIT,
    SESSION_VERSION,
    SessionIndex,
    TabMeta,
    TabPayload,
    blob_is_encrypted,
    clear_recent,
    clear_session,
    decode_tab_blob,
    encode_tab_blob,
    load_index,
    load_recent,
    new_tab_id,
    prune_tab_blobs,
    read_tab_blob,
    save_index,
    save_recent,
    write_tab_blob,
)
from morgul.syncmap import preview_pos_to_source, source_pos_to_preview

if TYPE_CHECKING:
    from collections.abc import Callable


class _UserCancelledError(Exception):
    """Signal that the user dismissed a required password prompt."""


# MIME type used to drag a tab between windows (carries the tab's session id).
_TAB_MIME = "application/x-morgul-tab"

# Every open :class:`MainWindow`, used to resolve cross-window tab drops.
_WINDOWS: list[MainWindow] = []


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
    """Highlight Markdown syntax and merge spell-check underlines into each block.

    Track fenced-block state across blocks so Markdown formatting and spell-check
        underlines can be applied by the same highlighter.
    """

    def __init__(self, document: QTextDocument, spell: SpellHighlighter) -> None:
        """Attach the highlighter to a document and store its spell highlighter.

        Args:
            document (QTextDocument): The document to attach the highlighter to.
            spell (SpellHighlighter): The spell highlighter to store.
        """
        super().__init__(document)
        self._spell = spell
        self._formats = {kind: _make_format(color) for kind, color in _COLORS.items()}
        self._formats["heading"].setFontWeight(QFont.Weight.Bold)
        self._formats["bold"].setFontWeight(QFont.Weight.Bold)
        self._formats["italic"].setFontItalic(True)

    @override
    def highlightBlock(self, text: str) -> None:
        """Highlight Markdown spans in the current text block.

        Apply formats to the spans found in the line, update the block state to reflect
            whether a code fence remains open, and apply spellcheck formatting.

        Args:
            text (str): The text in the current block.

        Returns:
            None: This method updates the current block's formatting and state.
        """
        in_fence = self.previousBlockState() == _STATE_FENCE
        spans, still_fenced = spans_in_line(text, in_fence=in_fence)
        for span in spans:
            self.setFormat(span.start, span.end - span.start, self._formats[span.kind])
        self.setCurrentBlockState(_STATE_FENCE if still_fenced else _STATE_NORMAL)
        self._apply_spellcheck(text)

    def _apply_spellcheck(self, text: str) -> None:
        """Apply spellcheck underlining to misspelled ranges.

        Args:
            text (str): Text to check for misspelled ranges.

        Returns:
            None: This method does not return a value.
        """
        if not self._spell.is_enabled:
            return
        underline = self._spell.underline_format
        for start, end in self._spell.misspelled_ranges(text):
            index = start
            while index < end:
                base = self.format(index)
                run_end = index + 1
                while run_end < end and self.format(run_end) == base:
                    run_end += 1
                merged = QTextCharFormat(base)
                merged.merge(underline)
                self.setFormat(index, run_end - index, merged)
                index = run_end


def _make_format(color: str) -> QTextCharFormat:
    """Create a character format with the specified foreground color.

    Args:
        color (str): The foreground color to apply.

    Returns:
        QTextCharFormat: The character format with the specified foreground color.
    """
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    return fmt


def _editor_font() -> QFont:
    """Create the editor font.

    Prefer Consolas, falling back to Cascadia Mono when it is unavailable.

    Returns:
        QFont: An 11-point Consolas or Cascadia Mono font.
    """
    font = QFont("Consolas")
    if not font.exactMatch():
        font = QFont("Cascadia Mono")
    font.setPointSize(11)
    return font


def _doc_end_position(document: QTextDocument) -> int:
    """Return the cursor position at the end of the document.

    Args:
        document (QTextDocument): The document whose end position to retrieve.

    Returns:
        int: The position at the document end, suitable for QTextCursor.setPosition.
    """
    cursor = QTextCursor(document)
    cursor.movePosition(QTextCursor.MoveOperation.End)
    return cursor.position()


class _LineNumberArea(QWidget):
    """Display line numbers in a narrow gutter beside a `SourceEditor`."""

    def __init__(self, editor: SourceEditor) -> None:
        """Initialize the line-number area for an editor.

        Args:
            editor (SourceEditor): The editor to use as the line-number area's parent
                and reference.
        """
        super().__init__(editor)
        self._editor = editor

    @override
    def sizeHint(self) -> QSize:
        """Return the preferred size of the line-number gutter.

        Returns:
            QSize: A size with the editor's line-number area width and a height of 0.
        """
        return QSize(self._editor.line_number_area_width(), 0)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint the line-number area by delegating to the owning editor.

        Args:
            event (QPaintEvent): The paint event to pass to the editor.
        """
        self._editor.paint_line_numbers(event)


class SpellHighlighter:
    """Highlight words absent from the spellchecker's dictionary.

    Match ASCII words with an optional apostrophe, and expose the highlighting state and
        underline format.

    Attributes:
        is_enabled (bool): Whether spell highlighting is enabled.
        underline_format (QTextCharFormat): The underline format used for misspelled
            words.
    """

    def __init__(self) -> None:
        """Initialize spell-checking state and underline formatting.

        Returns:
            None.
        """
        self._spellchecker = SpellChecker()
        self._enabled = True
        self._fmt = QTextCharFormat()
        self._fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self._fmt.setUnderlineColor(QColor("#ff6b6b"))
        self._word_re = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

    def set_enabled(self, *, enabled: bool) -> None:
        """Set whether spell highlighting is enabled.

        Args:
            enabled (bool): Whether to enable spell highlighting.
        """
        self._enabled = enabled

    @property
    def is_enabled(self) -> bool:
        """Report whether spell highlighting is enabled.

        Returns:
            bool: Whether spell highlighting is enabled.
        """
        return self._enabled

    @property
    def underline_format(self) -> QTextCharFormat:
        """The underline format used for misspellings.

        Returns:
            QTextCharFormat: The character format used for misspelling underlines.
        """
        return self._fmt

    def misspelled_ranges(self, text: str) -> frozenset[tuple[int, int]]:
        """Return the character ranges of misspelled words.

        A word is misspelled when it is absent from the spellchecker's word
        frequency.

        Args:
            text (str): Text to search for words.

        Returns:
            frozenset[tuple[int, int]]: Start-inclusive, end-exclusive character offsets
                of words absent from the spellchecker's word frequency.
        """
        return frozenset(
            (match.start(), match.end())
            for match in self._word_re.finditer(text)
            if match.group() not in self._spellchecker.word_frequency
        )


class SourceEditor(QPlainTextEdit):
    """Provide a Markdown source editor with a line-number gutter.

    Display line numbers and highlight the current line. Support spell-check formatting
        and extra text selections, and use the containing main window for undo, redo,
        and replace-mode input when available.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the source editor and its line-number gutter.

        Configure syntax and spell highlighting, cursor and gutter updates, and disable
            Qt's undo stack.

        Args:
            parent (QWidget | None): The parent widget.
        """
        super().__init__(parent)
        # Session-persisted undo lives on EditorTab; Qt's stack is not serializable.
        self.setUndoRedoEnabled(False)
        self._gutter = _LineNumberArea(self)
        self._overlays: list[QTextEdit.ExtraSelection] = []
        self._spell_highlighter = SpellHighlighter()
        self._highlighter = MarkdownHighlighter(
            self.document(),
            self._spell_highlighter,
        )
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_gutter_width(0)
        self._highlight_current_line()

    def line_number_area_width(self) -> int:
        """Calculate the pixel width needed to display the current line count.

        Returns:
            int: The width in pixels, including 12 pixels of padding.
        """
        digits = max(1, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def set_overlay_selections(self, overlays: list[QTextEdit.ExtraSelection]) -> None:
        """Set non-line text selections and refresh the editor's extra selections.

        Args:
            overlays (list[QTextEdit.ExtraSelection]): Non-line overlays to apply.

        Returns:
            None: This method does not return a value.
        """
        self._overlays = overlays
        self._highlight_current_line()

    def paint_line_numbers(self, event: QPaintEvent) -> None:
        """Paint visible, one-based line numbers in the gutter.

        Args:
            event (QPaintEvent): Paint event whose rectangle bounds the gutter area to
                update.

        Returns:
            None: This method paints the gutter without returning a value.
        """
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
        """Update the viewport's left margin to fit the line-number area.

        Args:
            _block_count (int): The current block count; this method does not use it.

        Returns:
            None: This method does not return a value.
        """
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int) -> None:
        """Update the gutter to reflect viewport changes.

        Args:
            rect (QRect): The rectangle affected by the viewport change.
            dy (int): The vertical scroll displacement; a nonzero value scrolls the
                gutter.

        Returns:
            None: This method does not return a value.
        """
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width(0)

    def _highlight_current_line(self) -> None:
        """Highlight the current line and apply configured overlays.

        Adds a full-width background selection for the current line when the editor is
            editable, then applies the configured overlays.
        """
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

    def set_spellcheck_enabled(self, *, enabled: bool) -> None:
        """Enable or disable spell checking and refresh highlighting.

        Temporarily block this editor's signals during rehighlighting so format-only
            `textChanged` emissions do not disturb the preview or history.

        Args:
            enabled (bool): Whether spell checking should be enabled.
        """
        self._spell_highlighter.set_enabled(enabled=enabled)
        # rehighlight() can emit textChanged (format-only). Block it so it
        # cannot disturb the preview/history.
        with QSignalBlocker(self):
            self._highlighter.rehighlight()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        """Position the gutter along the left edge of the contents area after resizing.

        Args:
            event (QResizeEvent): The resize event.

        Returns:
            None: This method does not return a value.
        """
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._gutter.setGeometry(
            contents.left(),
            contents.top(),
            self.line_number_area_width(),
            contents.height(),
        )

    def _main_window(self) -> MainWindow | None:
        """Return the main window if the current window is a `MainWindow`.

        Returns:
            MainWindow | None: The current window if it is a `MainWindow`; otherwise,
                `None`.
        """
        win = self.window()
        return win if isinstance(win, MainWindow) else None

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle a key press, routing history, replace-mode, and text input.

        Ctrl+Z undoes, Ctrl+Shift+Z and Ctrl+Y redo when a main window is available. An
            unmodified Insert key toggles replace mode when a main window is available
            and is consumed either way. In replace mode, printable text without Ctrl
            overtypes the character at the cursor when there is no selection and the
            cursor is not at the end; otherwise, it inserts the text normally. Keys not
            handled here are passed to the superclass.

        Args:
            event (QKeyEvent): Key press event to handle.

        Returns:
            None: This method does not return a value.
        """
        mods = event.modifiers()
        no_mods = mods in {
            Qt.KeyboardModifier.NoModifier,
            Qt.KeyboardModifier.KeypadModifier,
        }
        # QPlainTextEdit consumes Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z internally (its
        # own undo stack is disabled via setUndoRedoEnabled(False)), which would
        # swallow the app-level Undo/Redo QAction shortcuts. Route them to the
        # session-persisted history ourselves.
        host = self._main_window()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if ctrl and host is not None and event.key() == Qt.Key.Key_Z:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                host._redo()  # ruff: ignore[private-member-access]
            else:
                host._undo()  # ruff: ignore[private-member-access]
            return
        if ctrl and host is not None and event.key() == Qt.Key.Key_Y:
            host._redo()  # ruff: ignore[private-member-access]
            return
        if event.key() == Qt.Key.Key_Insert and no_mods:
            host = self._main_window()
            if host is not None:
                host.toggle_replace_mode()
            return

        text = event.text()
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

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Show the standard context menu with spelling suggestions when applicable.

        Args:
            event (QContextMenuEvent): The context menu event.

        Returns:
            None: This method does not return a value.
        """
        menu = self.createStandardContextMenu()
        cursor = self.cursorForPosition(event.pos())
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        word = cursor.selectedText()
        if (
            word
            and hasattr(self, "_spell_highlighter")
            and self._spell_highlighter._enabled  # ruff: ignore[private-member-access]
            and word not in self._spell_highlighter._spellchecker.word_frequency  # ruff: ignore[private-member-access]
        ):
            suggestions = self._spell_highlighter._spellchecker.candidates(word)  # ruff: ignore[private-member-access]
            if suggestions:
                menu.addSeparator()
                suggestion_menu = menu.addMenu("Spelling Suggestions")
                for suggestion in sorted(suggestions)[:10]:
                    action = suggestion_menu.addAction(suggestion)
                    start = cursor.selectionStart()
                    end = cursor.selectionEnd()
                    action.triggered.connect(
                        lambda _, s=suggestion, start=start, end=end: (
                            self._replace_word(start, end, s)
                        )
                    )
        menu.exec_(event.globalPos())

    def _replace_word(self, start: int, end: int, new_word: str) -> None:
        """Replace the text between two cursor positions.

        Args:
            start (int): The starting cursor position.
            end (int): The ending cursor position.
            new_word (str): The text to insert in place of the selected text.
        """
        cursor = self.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(new_word)
        self.setTextCursor(cursor)


class _InactiveCaret(QObject):
    """Draw a solid caret in a text pane that does not have focus.

    The caret is not drawn when the text pane has a selection. Call `schedule_repaint`
        to request a repaint after document layout, or `dispose` to remove the event
        filter and signal connections.
    """

    def __init__(self, pane: QPlainTextEdit | QTextBrowser) -> None:
        """Initialize the inactive caret for a text pane.

        Attach to the pane's viewport, monitor cursor and selection changes, and dispose
            of the caret when the pane is destroyed.

        Args:
            pane (QPlainTextEdit | QTextBrowser): The source editor or preview pane to
                monitor.
        """
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
        """Disable repaint handling and detach this object from its pane and viewport.

        Args:
            *_args (object): Positional arguments accepted but not used.

        Returns:
            None: This method does not return a value.
        """
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
        """Request a repaint when the caret is enabled and its pane is valid.

        RuntimeError is suppressed in case the pane is already gone.
        """
        pane = self._pane
        if not self._enabled or pane is None or not isValid(pane):
            return
        with contextlib.suppress(RuntimeError):
            pane.viewport().update()

    def schedule_repaint(self) -> None:
        """Schedule a repaint on the next event-loop iteration if enabled."""
        if self._enabled:
            QTimer.singleShot(0, self._request_repaint)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Draw the inactive caret after the pane viewport paints.

        Return False when the filter is disabled, the pane or viewport is invalid or
            unavailable, the event is not a paint event, or the watched object is not
            the pane viewport. For a matching paint event, temporarily remove the
            filter, resend the event, reinstall the filter if still enabled and valid,
            and paint the caret.

        Args:
            watched (QObject): Object receiving the event.
            event (QEvent): Event to filter.

        Returns:
            bool: True if the matching viewport paint event was handled; otherwise,
                False.
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
        """Paint the caret when the pane is eligible.

        Draw a vertical caret using the pane's foreground color when the pane is valid,
            unfocused, and has no text selection, provided its cursor rectangle is
            usable and intersects the viewport. Return without drawing if these
            conditions are not met or if pane access raises RuntimeError.

        Returns:
            None.
        """
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
    """Provide a Markdown preview tied to a Markdown source editor.

    The pane displays rendered HTML, fits embedded images to its viewport, and keeps the
        source editor's caret aligned with preview selections. Movement keys act on the
        source editor, while supported typing and editing keys apply changes to the
        Markdown source. Links and text selection remain available in the preview.
    """

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
        """Initialize the preview pane for its owning editor tab.

        Args:
            tab (EditorTab): The editor tab associated with this pane.
        """
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
        """Load HTML with a file-based base URL and fit images to the pane.

        Args:
            html (str): HTML content to load.
            base_dir (Path | None): Directory to use as the base URL, or None to use the
                current working directory.
        """
        root = (base_dir if base_dir is not None else Path.cwd()).resolve()
        base = QUrl.fromLocalFile(str(root) + "/")
        self.document().setBaseUrl(base)
        self.setHtml(html)
        self.fit_images()

    def fit_images(self) -> None:
        """Fit embedded images within the viewport while preserving their aspect ratios.

        The maximum image width is the viewport width minus 8 pixels, with a minimum of
            32 pixels. Preserve an explicit image width when it is positive and within
            that limit; otherwise, use the smaller of the image's natural width and the
            limit. Update image formatting only when the width or height differs by at
            least 0.5 pixels.

        Returns:
            None.
        """
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
        """Resolve an image format to a QImage.

        Args:
            img_fmt (QTextImageFormat): Image format whose name identifies the image.

        Returns:
            QImage | None: The image loaded from the resolved local file or document
                resource, or None if neither yields a QImage.
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
        """Delegate resize handling to the superclass and re-fit images.

        Args:
            event (QResizeEvent): Event describing the resize.
        """
        super().resizeEvent(event)
        self.fit_images()

    def _source_range_for_preview_selection(self) -> tuple[int, int]:
        """Map the current preview selection or caret to source offsets.

        Returns:
            A pair of ordered start and end indices into the Markdown source.
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
        """Synchronize the source editor caret with the mapped preview selection.

            Set the editor cursor to the mapped source range, preserving a selection
                when the range has distinct endpoints, and update the editor viewport.

        Returns:
            None.
        """
        start, end = self._source_range_for_preview_selection()
        cursor = self._tab.editor.textCursor()
        cursor.setPosition(start)
        if end != start:
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._tab.editor.setTextCursor(cursor)
        self._tab.editor.viewport().update()

    def _navigate_in_source(self, event: QKeyEvent) -> None:
        """Forward a movement key to the source editor and update the preview caret.

        Args:
            event (QKeyEvent): The movement key event to send to the source editor.

        Returns:
            None: This method does not return a value.
        """
        editor = self._tab.editor
        # Keep focus on the preview so typing continues here; only the caret moves.
        QApplication.sendEvent(editor, event)
        self._tab.mirror_source_caret_to_preview()
        self.ensureCursorVisible()
        self.viewport().update()
        editor.viewport().update()

    def _replace_source(self, start: int, end: int, text: str) -> None:
        """Replace a range of source text with the supplied text.

        Args:
            start (int): Start index of the source range to replace.
            end (int): End index of the source range to replace.
            text (str): Text to insert in place of the range.
        """
        self._tab.apply_source_edit(start, end, text)

    def _edit_from_key(self, key: int, *, ctrl: bool, text: str) -> bool:
        """Apply a supported key edit to the source text.

        Use the editor's current selection to determine the edit. When the action is a
            cut, copy the selected source text to the clipboard.

        Args:
            key (int): Key code to process.
            ctrl (bool): Whether the Control key is pressed.
            text (str): Text associated with the key.

        Returns:
            bool: Whether the key was handled as a source edit.
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
        """Forward the mouse release and synchronize the editor caret.

        Args:
            event (QMouseEvent): The mouse release event.
        """
        super().mouseReleaseEvent(event)
        self._sync_editor_caret()

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle key presses using source-editor behavior when applicable.

        Args:
            event (QKeyEvent): The key event to handle.

        Returns:
            None: This method does not return a value.
        """
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
    """Translate a preview key event into a source edit.

    Return the deletion range, replacement text, and cut flag for supported keys, or
        `None` when the key does not represent a source edit. A `None` replacement
        indicates no document change; a true cut flag marks a deleted selection for
        copying to the clipboard.

    Args:
        key (int): Key code to translate.
        ctrl (bool): Whether the Control modifier is pressed.
        text (str): Text produced by the key event.
        start (int): Start of the current selection or cursor position.
        end (int): End of the current selection.
        source_len (int): Length of the source text.
        replace_mode (bool): Whether printable input overwrites following characters
            when there is no selection.

    Returns:
        tuple[int, int, str | None, bool] | None: A tuple of deletion start, deletion
            end, replacement text, and cut flag, or `None` if the key is not handled as
            a source edit.
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
    """Create a tool button that switches icons when hovered.

    Use the normal icon by default and restore it when the pointer leaves. If no hover
        icon is provided, use the normal icon for both states.
    """

    def __init__(
        self,
        *,
        normal: QIcon,
        hover: QIcon | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the button with normal and optional hover icons.

        Args:
            normal (QIcon): Icon displayed normally.
            hover (QIcon | None): Icon displayed on hover; defaults to the normal icon.
            parent (QWidget | None): Parent widget passed to the base class constructor.
        """
        super().__init__(parent)
        self._normal = normal
        self._hover = hover if hover is not None else normal
        self.setIcon(self._normal)
        self.setAutoRaise(True)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        """Show the hover icon and forward the event to the base implementation.

        Args:
            event (QEnterEvent): The enter event.
        """
        self.setIcon(self._hover)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Restore the normal glyph and delegate the leave event to the base class.

        Args:
            event (QEvent): The leave event.
        """
        self.setIcon(self._normal)
        super().leaveEvent(event)


class _DraggableTabBar(QTabBar):
    """Provide a tab bar for initiating tab drags and requesting tab drops.

    Use Qt drag-and-drop events to detect tab drags carrying the configured MIME payload
        and determine the insertion index for a drop. Emit signals so the owning strip
        can handle starting, moving, or reordering tabs.

    Attributes:
        drag_started: Signal emitted with the index of the tab where a drag should
            begin.
        drop_requested: Signal emitted with the dragged tab's session ID and its
            insertion index in this bar.
    """

    drag_started = Signal(int)  # index in this bar where a drag should begin
    drop_requested = Signal(str, int)  # session id, insertion index into this bar

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize a tab bar for custom tab reordering and drag-and-drop.

        Args:
            parent (QWidget | None): Widget that owns this tab bar, if any.
        """
        super().__init__(parent)
        # We drive reordering/drops ourselves so the same code path serves
        # both within-window and cross-window moves.
        self.setMovable(False)
        self.setAcceptDrops(True)
        self._press_index = -1
        self._press_pos = QPoint()

    def _insertion_index_at(self, pos: QPoint) -> int:
        """Return the tab insertion index for a drop position.

        Args:
            pos (QPoint): Drop position; only its x-coordinate is used.

        Returns:
            int: Index of the first tab whose center is to the right of the position, or
                the tab count if none is.
        """
        for i in range(self.count()):
            if pos.x() < self.tabRect(i).center().x():
                return i
        return self.count()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Record the pressed tab for potential drag detection and forward the event.

        Args:
            event (QMouseEvent): The mouse press event to handle.

        Returns:
            None: This method does not return a value.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_index = self.tabAt(event.position().toPoint())
            self._press_pos = event.position().toPoint()
        else:
            self._press_index = -1
        super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Emit the drag-start signal when a left-button drag crosses the threshold.

        Reset the stored press index before emitting the signal; otherwise, pass the
            event to the superclass implementation.

        Args:
            event (QMouseEvent): The mouse-move event to handle.

        Returns:
            None: This method does not return a value.
        """
        point = event.position().toPoint()
        if (
            self._press_index >= 0
            and event.buttons() & Qt.MouseButton.LeftButton
            and (point - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            index = self._press_index
            self._press_index = -1
            self.drag_started.emit(index)
            return
        super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Clear the pending drag state and forward the release event.

        Args:
            event (QMouseEvent): The mouse release event.
        """
        self._press_index = -1
        super().mouseReleaseEvent(event)

    @override
    def dragEnterEvent(self, event: QDropEvent) -> None:
        """Accept the proposed action when the event carries the tab MIME payload.

        Args:
            event (QDropEvent): Drag event to inspect and accept when its MIME data
                contains the tab format.
        """
        if event.mimeData().hasFormat(_TAB_MIME):
            event.acceptProposedAction()

    @override
    def dragMoveEvent(self, event: QDropEvent) -> None:
        """Check for tab MIME data and accept the proposed action when present.

        Args:
            event (QDropEvent): The drag-move event to process.

        Returns:
            None: This method returns no value.
        """
        if event.mimeData().hasFormat(_TAB_MIME):
            self._insertion_index_at(event.position().toPoint())
            event.acceptProposedAction()

    @override
    def dropEvent(self, event: QDropEvent) -> None:
        """Handle a tab drop event.

        If the event contains tab MIME data, decode its session ID, emit a drop request
            with the insertion index, and accept the proposed action; otherwise, ignore
            the event.

        Args:
            event (QDropEvent): The drop event to handle.

        Returns:
            None
        """
        mime = event.mimeData()
        if not mime.hasFormat(_TAB_MIME):
            event.ignore()
            return
        session_id = bytes(mime.data(_TAB_MIME).data()).decode("utf-8")
        self.drop_requested.emit(
            session_id, self._insertion_index_at(event.position().toPoint())
        )
        event.acceptProposedAction()


class EditorTabStrip(QWidget):
    """Manage editor tabs and their corresponding page widgets.

    The strip combines a tab bar, a new-tab button, and a stacked page area. It supports
        reordering tabs and moving them between strips.

    Attributes:
        current_changed: Signal emitted with the current tab index when the tab bar
            selection changes.
        new_tab_requested: Signal emitted when the new-tab button is clicked.
        tab_bar_clicked: Signal emitted with the index of the clicked tab.
        owner (MainWindow | None): Owning window, assigned after construction and used
            for tab-related operations.
    """

    current_changed = Signal(int)
    new_tab_requested = Signal()
    tab_bar_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the tab strip, new-tab button, separator, and page stack.

        Args:
            parent (QWidget | None): Optional parent widget.
        """
        super().__init__(parent)
        # Owning MainWindow, set after construction (used for cross-window moves).
        self.owner: MainWindow | None = None
        self._bar = _DraggableTabBar()
        self._bar.setExpanding(False)
        self._bar.setDrawBase(False)
        self._bar.setDocumentMode(True)
        self._bar.currentChanged.connect(self._on_current_changed)
        self._bar.tabBarClicked.connect(self.tab_bar_clicked.emit)
        self._bar.drag_started.connect(self._on_drag_started)
        self._bar.drop_requested.connect(self._on_drop_requested)

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
        """Update the stacked widget and emit the current index.

        Args:
            index (int): Index to set as current and emit.

        Returns:
            None: This method does not return a value.
        """
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
        self.current_changed.emit(index)

    def _on_drag_started(self, index: int) -> None:
        """Start a move drag for the editor tab at the given index.

        Args:
            index (int): Index of the tab to drag.

        Returns:
            None: Returns without starting a drag if the tab does not contain an
                EditorTab.
        """
        widget = self._stack.widget(index)
        if not isinstance(widget, EditorTab):
            return
        mime = QMimeData()
        mime.setData(_TAB_MIME, str(widget.session_id).encode("utf-8"))
        drag = QDrag(self._bar)
        drag.setMimeData(mime)
        label = self._bar.tabText(index)
        pix = QPixmap(self._bar.width(), self._bar.tabRect(index).height())
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.fillRect(pix.rect(), QColor("#252526"))
        painter.setPen(QColor("#e6e6e6"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, label.strip("*"))
        painter.end()
        drag.setPixmap(pix)
        drag.exec_(Qt.DropAction.MoveAction)

    def _on_drop_requested(self, session_id: str, target_index: int) -> None:
        """Move the requested tab to the target index in this strip.

        If the session is not found in a strip, do nothing. Reorder the tab when it is
            already in this strip, or move it here from another strip.

        Args:
            session_id (str): ID of the session whose tab to move.
            target_index (int): Index where the tab should be placed.

        Returns:
            None: This method does not return a value.
        """
        source = _strip_for_session(session_id)
        if source is None:
            return
        source_index = source.index_of_session(session_id)
        if source_index < 0:
            return
        if source is self:
            if source_index != target_index:
                self._reorder(source_index, target_index)
            return
        _move_tab_across_windows(source, source_index, self, target_index)

    def insert_tab(self, index: int, page: QWidget, title: str) -> int:
        """Insert a page and titled tab at the specified index.

        Args:
            index (int): The position at which to insert the tab.
            page (QWidget): The page to insert into the stack.
            title (str): The title to display in the tab.

        Returns:
            int: The index at which the tab was inserted.
        """
        self._stack.insertWidget(index, page)
        self._bar.insertTab(index, title)
        return index

    def index_of_session(self, session_id: str) -> int:
        """Return the index of the tab for the specified session.

        Args:
            session_id (str): The session ID to find.

        Returns:
            int: The tab's index, or -1 if no matching tab is found.
        """
        for i in range(self._stack.count()):
            widget = self._stack.widget(i)
            if isinstance(widget, EditorTab) and widget.session_id == session_id:
                return i
        return -1

    def index_of_path(self, path: Path) -> int:
        """Find the index of the editor tab matching a path.

        Args:
            path (Path): Path to compare with the paths of the editor tabs.

        Returns:
            int: The matching tab's index, or -1 if no tab matches.
        """
        resolved = path.resolve()
        for i in range(self._stack.count()):
            widget = self._stack.widget(i)
            if (
                isinstance(widget, EditorTab)
                and widget.path is not None
                and widget.path.resolve() == resolved
            ):
                return i
        return -1

    def _reorder(self, source: int, target: int) -> None:
        """Move the tab at the source index to the target index.

        If no widget exists at the source index, leave the strip unchanged. Otherwise,
            update the tab bar and widget stack, and reinstall the close button when an
            owner is present.

        Args:
            source (int): Index of the tab to move.
            target (int): Index at which to insert the tab.

        Returns:
            None: This method does not return a value.
        """
        widget = self._stack.widget(source)
        if widget is None:
            return
        title = self._bar.tabText(source)
        self._stack.removeWidget(widget)
        self._bar.removeTab(source)
        self._stack.insertWidget(target, widget)
        self._bar.insertTab(target, title)
        self._bar.setCurrentIndex(self._bar.currentIndex())
        self._stack.setCurrentIndex(self._bar.currentIndex())
        if self.owner is not None:
            self.owner._install_close_button(target, cast("EditorTab", widget))  # ruff: ignore[private-member-access]

    def add_tab(self, page: QWidget, title: str) -> int:
        """Add a page and matching title tab.

        Args:
            page (QWidget): The page to add.
            title (str): The title for the matching tab.

        Returns:
            int: The index of the added page.
        """
        index = self._stack.addWidget(page)
        self._bar.addTab(title)
        return index

    def remove_tab(self, index: int) -> QWidget | None:
        """Remove the tab and its page from the strip without deleting the page.

        Args:
            index (int): Index of the tab to remove.

        Returns:
            QWidget | None: The removed page widget, or None if no page exists at the
                index.
        """
        page = self._stack.widget(index)
        if page is not None:
            self._stack.removeWidget(page)
        self._bar.removeTab(index)
        return page

    def set_tab_text(self, index: int, title: str) -> None:
        """Set the title of the tab at the given index.

        Args:
            index (int): Index of the tab to update.
            title (str): New title for the tab.
        """
        self._bar.setTabText(index, title)

    def set_tab_close_button(self, index: int, button: QWidget) -> None:
        """Install a custom close control on a tab.

        Args:
            index (int): Index of the tab to update.
            button (QWidget): Widget to display on the tab's right side.

        Returns:
            None
        """
        self._bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)

    def current_index(self) -> int:
        """Return the current index reported by the tab bar.

        Returns:
            int: The current tab index.
        """
        return self._bar.currentIndex()

    def set_current_index(self, index: int) -> None:
        """Set the tab bar index and update the stack index when the index is valid.

        Args:
            index (int): Index to set on the tab bar and, if within the stack's range,
                on the stack.

        Returns:
            None: This method does not return a value.
        """
        self._bar.setCurrentIndex(index)
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)

    def current_widget(self) -> QWidget | None:
        """Return the currently selected page widget, if one exists.

        Returns:
            QWidget | None: The current page widget, or None if no page is selected.
        """
        return self._stack.currentWidget()

    def widget(self, index: int) -> QWidget | None:
        """Return the widget at the given page index.

        Args:
            index (int): Index of the page to retrieve.

        Returns:
            QWidget | None: The widget at the given index, or None if no widget is
                present there.
        """
        return self._stack.widget(index)

    def index_of(self, page: QWidget) -> int:
        """Return the index of the page in the stack, or -1 if it is not present.

        Args:
            page (QWidget): The page to find.

        Returns:
            int: The page's index, or -1 if it is not present.
        """
        return self._stack.indexOf(page)

    def count(self) -> int:
        """Return the number of pages in the tab strip.

        Returns:
            int: The number of pages in the tab strip.
        """
        return self._stack.count()


class EditorTab(QWidget):
    """Represent one document as a source editor and Markdown preview.

    The tab manages the document's editing state, history, preview, and view options.

    Attributes:
        meta_changed (Signal): Emitted when tab metadata changes.
        path (Path | None): Document path, or None for an untitled document.
        password (str | None): Session password, or None for an unencrypted document.
        dirty (bool): Whether the document differs from its saved or loaded state.
        wrap_on (bool): Whether word wrapping is enabled.
        preview_on (bool): Whether the preview pane is visible.
        spellcheck_on (bool): Whether spell checking is enabled.
        session_id: Identifier returned by new_tab_id for this tab.
        history (EditHistory): The document's undo and redo history.
        locked (bool): Whether the tab is a locked encrypted session.
        locked_blob (bytes | None): Encrypted session data retained while the tab is
            locked.
        editor (SourceEditor): The source document editor.
        preview (PreviewPane): The rendered Markdown preview.
        splitter (QSplitter): The horizontal splitter containing the editor and preview.
    """

    meta_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize an empty editor tab with a source editor and preview.

        Args:
            parent (QWidget | None): Optional parent widget.
        """
        super().__init__(parent)
        self.path: Path | None = None
        self.password: str | None = None  # session key; None = plaintext file
        self.dirty = False
        self._baseline_hash: int = 0
        self.wrap_on = True
        self.preview_on = True
        self.spellcheck_on = True
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
        """Stop the preview timer and dispose of the caret filters.

        Run before the nested editor widgets are deleted.
        """
        self._preview_timer.stop()
        self._editor_caret.dispose()
        self._preview_caret.dispose()

    def _hash_state(self, text: str) -> int:
        """Compute a hash of the text and password state.

        Args:
            text (str): Text to include in the hash.

        Returns:
            int: The 64-bit xxHash digest of the UTF-8 encoded text and a marker
                indicating whether a password is set.
        """
        marker = "\x00P" if self.password else "\x00-"
        return xxhash.xxh3_64((text + marker).encode("utf-8")).intdigest()

    def _current_hash(self) -> int:
        """Compute a hash of the current editor text.

        Returns:
            int: The hash produced by `_hash_state` for the editor's plain text.
        """
        return self._hash_state(self.editor.toPlainText())

    def _set_baseline(self, text: str) -> None:
        """Record the hash of the supplied text as the baseline state.

        Args:
            text (str): Text whose hash becomes the baseline.

        Returns:
            None: This method does not return a value.
        """
        self._baseline_hash = self._hash_state(text)

    def _sync_dirty_to_hash(self) -> None:
        """Update the dirty flag from the current and baseline hashes.

        Emit `meta_changed` only when the dirty flag changes.
        """
        current = self._current_hash()
        if current != self._baseline_hash:
            if not self.dirty:
                self.dirty = True
                self.meta_changed.emit()
        elif self.dirty:
            self.dirty = False
            self.meta_changed.emit()

    def tab_label(self) -> str:
        """Return the tab label with status markers.

        Use the filename for file-backed tabs or the trimmed first line of the document,
            truncated to 15 characters. Use ``Untitled`` when the document is empty or
            its first line contains only whitespace. Append `` (locked)`` when locked
            and prefix ``*`` when dirty.

        Returns:
            str: The tab label.
        """
        if self.path is not None:
            name = self.path.name
        else:
            first = self.editor.toPlainText().splitlines()
            name = first[0].strip()[:15] if first and first[0].strip() else "Untitled"
        if self.locked:
            name = f"{name} (locked)"
        return f"*{name}" if self.dirty else name

    def _sync_preview_caret_from_editor(self) -> None:
        """Synchronize the preview caret when the preview is visible and unfocused.

        Returns:
            None: This method does not return a value.
        """
        if not self.preview.isVisible() or self.preview.hasFocus():
            return
        self.mirror_source_caret_to_preview()

    def mirror_source_caret_to_preview(self) -> None:
        """Mirror the source editor's caret or selection in the visible preview.

        If the preview is hidden, leave it unchanged. Otherwise, map the source caret or
            selection positions to the preview, clamp them to the preview document,
            update the preview cursor, and schedule caret repaints for both viewports.

        Returns:
            None.
        """
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
            """Clamp a position to the document bounds.

            Args:
                pos (int): The position to clamp.

            Returns:
                int: The position limited to the range from 0 to `doc_end`.
            """
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
        """Handle changes to the editor text.

        Record the text and cursor position in history and synchronize the dirty state
            when history is not being applied and the tab is unlocked. Emit a metadata
            change for an unlocked untitled tab, and start the preview timer when
            preview synchronization is enabled.
        """
        if not self._applying_history and not self.locked:
            self.history.record(
                self.editor.toPlainText(),
                self.editor.textCursor().position(),
            )
        if not self._applying_history and not self.locked:
            self._sync_dirty_to_hash()
        if self.path is None and not self.locked:
            # Untitled tab: title reflects the first line, so refresh live.
            self.meta_changed.emit()
        if self._sync_preview_from_source:
            self._preview_timer.start()

    def apply_history_frame(self, frame: EditFrame) -> None:
        """Apply a history frame to the editor.

        Set the editor text and restore its cursor position, clamped to the text bounds.
            Then synchronize the dirty state and refresh the preview.

        Args:
            frame (EditFrame): Frame containing the text and cursor position to apply.

        Returns:
            None: This method does not return a value.
        """
        self._applying_history = True
        try:
            self.editor.setPlainText(frame.text)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(max(frame.cursor, 0), len(frame.text)))
            self.editor.setTextCursor(cursor)
        finally:
            self._applying_history = False
        self._sync_dirty_to_hash()
        self.refresh_preview()

    def apply_source_edit(self, start: int, end: int, text: str) -> None:
        """Apply a source edit and refresh the preview.

        Replace the selected range in the editor with the supplied text, clamping the
            range to the current source text. Group the edit into one edit block, then
            refresh the preview with the source caret followed.

        Args:
            start (int): Start position of the range to replace.
            end (int): End position of the range to replace.
            text (str): Text to insert in place of the range.

        Returns:
            None: This method does not return a value.
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
        """Refresh the visible HTML preview from the current Markdown source.

        Preserve the preview's scroll position and synchronize its cursor and selection
            with the source editor. The source caret determines the preview cursor
            position; `follow_source_caret` is ignored.

        Args:
            follow_source_caret (bool): Retained for call-site compatibility and
                ignored.
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
        """Load text into the editor and reset its document state.

        Args:
            text (str): Text to load into the editor.
            path (Path | None): Path associated with the loaded text, or None.
            password (str | None): Password associated with the loaded text, or None.

        Returns:
            None: This method does not return a value.
        """
        self.locked = False
        self.locked_blob = None
        self.editor.setReadOnly(False)
        self.editor.setPlaceholderText("")
        self.path = path
        self.password = password
        self._set_baseline(text)
        self._applying_history = True
        try:
            self.editor.setPlainText(text)
        finally:
            self._applying_history = False
        self.dirty = False
        self.history.seed(text, self.editor.textCursor().position())
        self.refresh_preview()

    def apply_payload(self, payload: TabPayload, *, password: str | None) -> None:
        """Restore this tab's state from a session payload.

        Args:
            payload (TabPayload): Payload containing the tab's history, path, editor
                state, view settings, and scroll position.
            password (str | None): Password to assign to the tab.

        Returns:
            None: This method updates the tab and editor in place.
        """
        self.locked = False
        self.locked_blob = None
        self.editor.setReadOnly(False)
        self.editor.setPlaceholderText("")
        self.history = payload.history
        self.path = Path(payload.path) if payload.path else None
        self.password = password
        self.dirty = payload.dirty
        self._set_baseline(self.history.current.text)
        self.set_wrap(on=payload.wrap_on)
        self.set_preview(on=payload.preview_on)
        self.set_spellcheck(on=payload.spellcheck_on)
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
        """Restore the editor's vertical scroll position."""
        self.editor.verticalScrollBar().setValue(self._restore_scroll)

    def set_locked(self, blob: bytes, *, path: Path | None, dirty: bool) -> None:
        """Mark the tab as locked and clear its displayed content.

        Store the encrypted blob, path, and dirty state; reset the password and history,
            clear the editor and preview, and make the editor read-only with a
            password-required placeholder.

        Args:
            blob (bytes): Encrypted session data to store for the locked tab.
            path (Path | None): Path associated with the tab, if any.
            dirty (bool): Whether the tab has unsaved changes.

        Returns:
            None: This method does not return a value.
        """
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
        self._baseline_hash = self._hash_state("")
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("Password required — switch here to unlock.")
        self.preview.setHtml("")

    def to_payload(self) -> TabPayload:
        """Create a payload from the tab's current state.

        Synchronize the current history frame with the editor's text and cursor before
            creating the payload.

        Returns:
            TabPayload: The tab state, including edit history, path, status flags, and
                vertical scroll position.
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
            spellcheck_on=self.spellcheck_on,
            scroll=self.editor.verticalScrollBar().value(),
        )

    def set_wrap(self, *, on: bool) -> None:
        """Set word wrapping for this tab's editor.

        Args:
            on (bool): Whether to enable word wrapping.
        """
        self.wrap_on = on
        mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if on
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.editor.setLineWrapMode(mode)

    def set_preview(self, *, on: bool) -> None:
        """Set the preview pane's visibility and refresh it when shown.

        Args:
            on (bool): Whether to show the preview pane.

        Returns:
            None: This method does not return a value.
        """
        self.preview_on = on
        self.preview.setVisible(on)
        if on:
            self.refresh_preview()

    def set_spellcheck(self, *, on: bool) -> None:
        """Enable or disable spell checking for this tab's editor.

        Args:
            on (bool): Whether to enable spell checking. Updates the tab's spell-check
                state and the editor's setting.
        """
        self.spellcheck_on = on
        self.editor.set_spellcheck_enabled(enabled=on)

    def apply_find_highlights(self, matches: list[Match], current: int) -> None:
        """Apply find-result highlights to the editor.

        Highlight each match with a dim background, except the match at `current`, which
            uses a brighter background. Replace the editor's overlay selections with the
            generated highlights.

        Args:
            matches (list[Match]): Matches to highlight, with start and end positions.
            current (int): Index of the match to highlight more brightly.

        Returns:
            None: This method does not return a value.
        """
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
        """Clear all overlay selections from the editor."""
        self.editor.set_overlay_selections([])

    def reveal_match(self, hit: Match) -> None:
        """Select the match and center it in the editor view.

        Args:
            hit (Match): Match whose range to select.

        Returns:
            None: This method does not return a value.
        """
        cursor = self.editor.textCursor()
        cursor.setPosition(hit.start)
        cursor.setPosition(hit.end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()


class FindReplaceDialog(QDialog):
    """Provide a modeless find-and-replace dialog for the active editor tab.

    Support searching forward and backward, replacing one or all matches, and filtering
        searches by case, whole-word, regular-expression, selection, or highlighted-zone
        options.
    """

    def __init__(self, main: MainWindow) -> None:
        """Initialize the find-and-replace dialog and connect its controls.

        Args:
            main (MainWindow): Main window associated with the dialog.
        """
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
        """Open the dialog and focus its find field.

        If the current tab has a nonempty single-line selection, use it as the find
            text. Then show and activate the dialog, focus the find field, and select
            its contents.
        """
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
        """Open the find-and-replace dialog and focus its replace field."""
        self.open_for_find()
        self._replace_edit.setFocus()

    def _options(self) -> FindOptions:
        """Build find options from the current dialog controls.

        Returns:
            FindOptions: The options configured by the dialog controls.
        """
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
        """Get the selected text bounds.

        Args:
            tab (EditorTab): The editor tab whose selection bounds to retrieve.

        Returns:
            tuple[int, int] | None: The selection start and end positions, or None if
                there is no selection.
        """
        cursor = tab.editor.textCursor()
        if not cursor.hasSelection():
            return None
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        return (start, end)

    def _recompute(self, tab: EditorTab) -> bool:
        """Recompute find matches for the current editor tab.

        Args:
            tab (EditorTab): The tab whose text and selection are searched.

        Returns:
            bool: Whether recomputing the matches succeeded.
        """
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
        """Clear cached matches and reset the current search state.

        Clear find highlights from the current tab, if one exists, and clear the status
            display.
        """
        self._matches = []
        self._index = -1
        tab = self._main.current_tab()
        if tab is not None:
            tab.clear_find_highlights()
        self._status.clear()

    def _paint(self, tab: EditorTab) -> None:
        """Update find highlights and status for the current matches.

        Args:
            tab (EditorTab): The editor tab to update.
        """
        tab.apply_find_highlights(self._matches, self._index)
        if 0 <= self._index < len(self._matches):
            tab.reveal_match(self._matches[self._index])
            self._status.setText(f"{self._index + 1} of {len(self._matches)}")
        elif self._matches:
            self._status.setText(f"{len(self._matches)} matches")
        else:
            self._status.setText("No matches")

    def find_next(self) -> None:
        """Run the Find Next command.

        This public entry point is used by the menu and F3 shortcut and delegates to
            `_find_next`.
        """
        self._find_next()

    def find_prev(self) -> None:
        """Search for the previous match (Shift+F3)."""
        self._find_prev()

    def _find_next(self) -> None:
        """Find and highlight the next match in the current tab.

        Recompute matches before advancing the selection. Start at the first match when
            no match is currently selected, and wrap to the first match after the last
            one. Paint the tab when there are no matches.

        Returns:
            None.
        """
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
        """Select and display the previous match.

        Recompute matches for the current tab before changing the selection. If there
            are no matches, repaint without changing the index; otherwise, move backward
            with wraparound. Do nothing if there is no current tab or matches cannot be
            recomputed.
        """
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
        """Replace the current match in the active tab.

        Recompute matches before replacing, update the editor text and cursor, then
            refresh the match display. If no tab or match is available, or recomputing
            fails, return without replacing text.

        Returns:
            None.
        """
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
        """Replace all matching text in the current tab.

        Use the configured options and, when requested, restrict replacements to the
            selection or highlighted ranges. Report find errors in the status area;
            after a successful replacement, update the editor if any occurrences were
            replaced, clear find highlights, and reset the match state.
        """
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
        """Clear find highlights on the current tab, then forward the event.

        Args:
            event (QCloseEvent): The close event to handle.
        """
        tab = self._main.current_tab()
        if tab is not None:
            tab.clear_find_highlights()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    """Manage the application's tabbed editor window.

    Coordinate editor tabs, menus, find and replace, status updates, and session
        restoration.

    Attributes:
        replace_mode: Whether overtype mode is active.
    """

    def __init__(self, *, restore_session: bool = True) -> None:
        """Initialize the window and set up its editor interface.

        Attempt to restore a session when requested; create a new tab if no session is
            restored.

        Args:
            restore_session (bool): Whether to attempt to restore a saved session.
                Defaults to True.
        """
        super().__init__()
        self._replace_mode = False
        self._restoring_session = False
        # Set when the restored active tab is encrypted; unlock after first show.
        self._prompt_active_unlock = False

        self._tabs = EditorTabStrip()
        self._tabs.owner = self
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
        self._recent = load_recent()

        self._build_menus()
        if not (restore_session and self._restore_session()):
            self._new_tab()
        self.resize(1000, 680)
        self._set_title()
        _WINDOWS.append(self)

    @property
    def replace_mode(self) -> bool:
        """Whether overtype mode is active.

        Returns:
            bool: True if overtype mode is active; otherwise, False.
        """
        return self._replace_mode

    def toggle_replace_mode(self) -> None:
        """Toggle insert/overtype mode and refresh the status bar."""
        self._replace_mode = not self._replace_mode
        self._update_status()

    def current_tab(self) -> EditorTab | None:
        """Return the current editor tab if the current widget is an editor tab.

        Returns:
            EditorTab | None: The current editor tab, or None if the current widget is
                not an editor tab.
        """
        widget = self._tabs.current_widget()
        return widget if isinstance(widget, EditorTab) else None

    def tab_meta_changed(self) -> None:
        """Refresh the current tab label and window title.

        Returns:
            None: This method does not return a value.
        """
        tab = self.current_tab()
        if tab is None:
            return
        index = self._tabs.current_index()
        self._tabs.set_tab_text(index, tab.tab_label())
        self._set_title()

    def _build_menus(self) -> None:
        """Build the application menus and connect their actions.

        Returns:
            None: This method builds the menus in place.
        """
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(
            self._act("&New Tab", QKeySequence.StandardKey.New, self._new_tab)
        )
        file_menu.addAction(self._new_window_action())
        file_menu.addAction(
            self._act("&Open...", QKeySequence.StandardKey.Open, self._open)
        )
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
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

        self._spellcheck_action = QAction("&Spell check", self)
        self._spellcheck_action.setCheckable(True)
        self._spellcheck_action.setChecked(True)
        self._spellcheck_action.toggled.connect(
            lambda on: self._toggle_spellcheck(checked=on)
        )
        view_menu.addAction(self._spellcheck_action)

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
        """Create an action with the given text, shortcut, and connected slot.

        Args:
            text (str): The action's display text.
            shortcut (QKeySequence.StandardKey): The action's keyboard shortcut.
            slot (Callable[[], object]): The callable connected to the action's
                triggered signal.

        Returns:
            QAction: The configured action.
        """
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.triggered.connect(slot)
        return action

    def _set_title(self) -> None:
        """Set the window title and password action text for the current tab.

        Use the default title when no tab is selected; otherwise include the tab name
            and a dirty marker when applicable. Update the password action text if it
            exists.

        Returns:
            None
        """
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
        """Install a custom SVG close button on a tab.

        Args:
            index (int): Index of the tab where the button is installed.
            tab (EditorTab): Tab to close when the button is clicked.

        Returns:
            None: This method does not return a value.
        """
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

    def _new_window_action(self) -> QAction:
        """Create the action for opening a new window.

        Returns:
            QAction: The action labeled “New Window,” with its shortcut and handler
                configured.
        """
        action = QAction("New &Window", self)
        action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        action.triggered.connect(self._new_window)
        return action

    def _new_window(self) -> None:
        """Open and show a new empty Morgul window offset from this window.

        The new window is positioned 28 pixels right and down from this window, with
            session restoration disabled.

        Returns:
            None.
        """
        win = MainWindow(restore_session=False)
        pos = self.pos()
        win.move(pos.x() + 28, pos.y() + 28)
        win.show()

    def _new_tab(self, *_args: object, select: bool = True) -> EditorTab:
        """Create and attach a new editor tab.

        Args:
            *_args (object): Additional positional arguments, which are ignored.
            select (bool): Whether to select the new tab.

        Returns:
            EditorTab: The newly created tab.
        """
        tab = EditorTab()
        self._attach_tab(tab, select=select)
        return tab

    def _attach_tab(
        self,
        tab: EditorTab,
        *,
        index: int | None = None,
        select: bool = True,
    ) -> int:
        """Attach an editor tab to this window's tab strip.

        Connect the tab's cursor-position and metadata signals, add or insert it at the
            requested index, and install its close button. If `select` is true, select
            and focus the tab and update the window title and status.

        Args:
            tab (EditorTab): The tab to attach.
            index (int | None): The position at which to insert the tab, or `None` to
                add it at the end.
            select (bool): Whether to select and focus the tab after attaching it.

        Returns:
            int: The tab's index in the strip.
        """
        tab.editor.cursorPositionChanged.connect(self._update_status)
        tab.meta_changed.connect(self.tab_meta_changed)
        title = tab.tab_label()
        if index is None:
            index = self._tabs.add_tab(tab, title)
        else:
            index = self._tabs.insert_tab(index, tab, title)
        self._install_close_button(index, tab)
        if select:
            self._tabs.set_current_index(index)
            tab.editor.setFocus()
            self._set_title()
            self._update_status()
        return index

    def _detach_tab(self, tab: EditorTab) -> None:
        """Disconnect this window's signal handlers from the tab being detached.

        Args:
            tab (EditorTab): The tab whose editor cursor-position and metadata-change
                signals to disconnect.
        """
        with contextlib.suppress(RuntimeError):
            tab.editor.cursorPositionChanged.disconnect(self._update_status)
        with contextlib.suppress(RuntimeError):
            tab.meta_changed.disconnect(self.tab_meta_changed)

    def _close_tab_widget(self, tab: EditorTab) -> None:
        """Close the tab associated with the given editor widget.

        Args:
            tab (EditorTab): The editor tab to close.

        Returns:
            None: This method has no return value.
        """
        index = self._tabs.index_of(tab)
        if index >= 0:
            self._close_tab_at(index)

    def _on_tab_changed(self, _index: int) -> None:
        """Synchronize the view with the current tab unless a session is being restored.

        Args:
            _index (int): Index of the tab that changed.

        Returns:
            None: This method does not return a value.
        """
        if self._restoring_session:
            return
        tab = self.current_tab()
        if tab is None:
            return
        self._sync_view_for_tab(tab)

    def _on_tab_bar_clicked(self, index: int) -> None:
        """Handle a tab-bar click and attempt to unlock the selected tab.

        Args:
            index (int): Index of the clicked tab.

        Returns:
            None: This method returns without a value. During session restoration, it
                does nothing; otherwise, it attempts to unlock the selected tab if it is
                a locked editor tab, then synchronizes its view.
        """
        if self._restoring_session:
            return
        widget = self._tabs.widget(index)
        if isinstance(widget, EditorTab) and widget.locked:
            self._try_unlock_tab(widget)
            self._sync_view_for_tab(widget)

    def _sync_view_for_tab(self, tab: EditorTab) -> None:
        """Synchronize the window view with a tab.

        Update available view actions, the window title and status, and the tab label;
            refresh the preview and focus the tab's editor.

        Args:
            tab (EditorTab): The tab whose view state to synchronize.

        Returns:
            None: This method does not return a value.
        """
        if self._wrap_action is not None:
            with QSignalBlocker(self._wrap_action):
                self._wrap_action.setChecked(tab.wrap_on)
        if self._preview_action is not None:
            with QSignalBlocker(self._preview_action):
                self._preview_action.setChecked(tab.preview_on)
        if self._spellcheck_action is not None:
            with QSignalBlocker(self._spellcheck_action):
                self._spellcheck_action.setChecked(tab.spellcheck_on)
        self._set_title()
        self._update_status()
        index = self._tabs.index_of(tab)
        if index >= 0:
            self._tabs.set_tab_text(index, tab.tab_label())
        # Tabs loaded while hidden defer their preview render until selected.
        tab.refresh_preview()
        tab.editor.setFocus()

    def _try_unlock_tab(self, tab: EditorTab) -> None:
        """Unlock a locked tab in place using a password prompt.

        Return without unlocking the tab if it is not locked, has no locked blob, the
            dialog is dismissed, no password is provided, or decoding fails. Show a
            warning when decoding fails.

        Args:
            tab (EditorTab): The tab to unlock.

        Returns:
            None: This method updates the tab in place.
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
        """Update the status labels with the mode, format, and cursor position.

        Clear the position label when no tab is active.
        """
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
        """Toggle preview for the current tab when it exists and is not locked.

        Args:
            checked (bool): Whether to enable preview.
        """
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.set_preview(on=checked)

    def _toggle_wrap(self, *, checked: bool) -> None:
        """Toggle line wrapping for the current tab when it is unlocked.

        Args:
            checked (bool): Whether wrapping should be enabled.
        """
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.set_wrap(on=checked)

    def _toggle_spellcheck(self, *, checked: bool) -> None:
        """Toggle spellchecking for the current unlocked tab.

        Args:
            checked (bool): Whether to enable spellchecking.
        """
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.set_spellcheck(on=checked)

    def _undo(self) -> None:
        """Undo the current tab's latest history step.

        Returns:
            None.
        """
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        frame = tab.history.undo_step()
        if frame is not None:
            tab.apply_history_frame(frame)

    def _redo(self) -> None:
        """Redo the current tab's most recent undone history step."""
        tab = self.current_tab()
        if tab is None or tab.locked:
            return
        frame = tab.history.redo_step()
        if frame is not None:
            tab.apply_history_frame(frame)

    def _restore_session(self) -> bool:
        """Restore session tabs and select the saved active tab.

        Returns:
            Whether at least one session tab was opened. Returns False if no session
                index is available or no tabs were opened.
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
        """Load tabs from a session index.

        Skip tabs whose blobs are missing or whose unencrypted blobs cannot be decoded.
            Keep encrypted tabs locked.

        Args:
            index (SessionIndex): Session index containing the tabs to load.

        Returns:
            int: Number of tabs opened, including tabs left locked.
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
                tab.set_spellcheck(on=meta.spellcheck_on)
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
        """Remove and dispose of a partially built editor tab.

        Remove the tab from the strip if it is present, then dispose of it and schedule
            it for deletion.

        Args:
            tab (EditorTab): The tab to remove and dispose.

        Returns:
            None: This method does not return a value.
        """
        idx = self._tabs.index_of(tab)
        if idx >= 0:
            self._tabs.remove_tab(idx)
        tab.dispose()
        tab.deleteLater()

    def _finish_session_restore(self) -> None:
        """Synchronize the window chrome with the restored active tab.

        If no active tab exists, return without updating the window. Otherwise, set the
            pending unlock prompt from the tab's locked state, synchronize the wrap,
            preview, and spellcheck actions, refresh the preview, focus the editor, and
            update the title and status.

        Returns:
            None.
        """
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
        if self._spellcheck_action is not None:
            with QSignalBlocker(self._spellcheck_action):
                self._spellcheck_action.setChecked(active_tab.spellcheck_on)
        active_tab.refresh_preview()
        active_tab.editor.setFocus()
        self._set_title()
        self._update_status()

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Handle the window becoming visible.

        Call the superclass implementation and, if an active unlock prompt is pending,
            clear the pending flag and schedule the unlock check for the next event-loop
            tick.

        Args:
            event (QShowEvent): The window show event.

        Returns:
            None: This method does not return a value.
        """
        super().showEvent(event)
        if self._prompt_active_unlock:
            self._prompt_active_unlock = False
            # Next event-loop tick so the main window paints before the dialog.
            QTimer.singleShot(0, self._unlock_active_if_locked)

    def _unlock_active_if_locked(self) -> None:
        """Unlock the active tab if it is locked.

        Get the current tab and, if it exists and is locked, attempt to unlock it and
            synchronize its view.

        Returns:
            None.
        """
        tab = self.current_tab()
        if tab is not None and tab.locked:
            self._try_unlock_tab(tab)
            self._sync_view_for_tab(tab)

    def _save_session(self) -> None:
        """Persist the current editor tabs to the session store.

        Save each editor tab's content and metadata, then remove stored blobs for tabs
            that are no longer present. Reuse an existing encrypted blob for locked
            tabs, and encrypt tab content when a password is set. Clear the session if
            there are no editor tabs to save.

        Returns:
            None.
        """
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
                    spellcheck_on=tab.spellcheck_on,
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
        """Cut content from the current tab's editor if the tab is unlocked."""
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.cut()

    def _copy(self) -> None:
        """Copy the selection from the current tab if it is unlocked."""
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.copy()

    def _paste(self) -> None:
        """Paste clipboard contents into the current editor if it is unlocked."""
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.paste()

    def _select_all(self) -> None:
        """Select all text in the current tab when it is unlocked."""
        tab = self.current_tab()
        if tab is not None and not tab.locked:
            tab.editor.selectAll()

    def _confirm_discard(self, tab: EditorTab) -> bool:
        """Confirm whether to discard a tab's unsaved changes.

        Args:
            tab (EditorTab): The tab to check.

        Returns:
            bool: Whether the changes may be discarded. Returns True immediately if the
                tab is not dirty; otherwise, returns True only if the user selects Yes.
        """
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
        """Close the tab at the given index after confirming the discard.

        If the indexed widget is not an EditorTab or discard is not confirmed, leave it
            unchanged. When the last tab is closed, clear the session and close the
            window.

        Args:
            index (int): Index of the tab to close.

        Returns:
            None: This method does not return a value.
        """
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
        """Close the current tab if one is selected."""
        index = self._tabs.current_index()
        if index >= 0:
            self._close_tab_at(index)

    def _open(self) -> None:
        """Open a file selected from the file dialog.

        Return without opening a file if the dialog is canceled; otherwise, pass the
            selected path to `_open_path`.
        """
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
        self._open_path(Path(path_str))

    def _open_path(self, path: Path) -> None:
        """Open a document from the given path.

        If the path is already open, select its tab and add it to recent files.
            Otherwise, read the document and load it into the current tab if that tab is
            empty, clean, unlocked, and has no path; create a new tab in all other
            cases. Show a warning for format or operating-system errors, and return
            without loading if the operation is cancelled.

        Args:
            path (Path): Path of the document to open.

        Returns:
            None
        """
        existing = self._tabs.index_of_path(path)
        if existing >= 0:
            self._tabs.set_current_index(existing)
            self._add_recent(path)
            return
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
        self._add_recent(path)
        self.tab_meta_changed()

    def _rebuild_recent_menu(self) -> None:
        """Rebuild the Open Recent submenu from the stored recent paths.

        Add an action for each recent path, followed by a separator and a Clear Recent
            Files action. If there are no recent paths, add a disabled No recent files
            action instead.

        Returns:
            None.
        """
        self._recent_menu.clear()
        if not self._recent:
            empty = self._recent_menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for path_str in self._recent:
            action = self._recent_menu.addAction(path_str)
            action.triggered.connect(lambda _=False, p=path_str: self._open_recent(p))
        self._recent_menu.addSeparator()
        clear = self._recent_menu.addAction("Clear Recent Files")
        clear.triggered.connect(self._clear_recent)

    def _add_recent(self, path: Path) -> None:
        """Move a path to the front of the recent list.

        Save the list and refresh the recent menu. The list is truncated to the
        recent-item limit, and an OSError while saving the list is ignored.

        Args:
            path (Path): The path to add to the recent list. If already present, its
                existing entry is moved to the front.
        """
        entry = str(path)
        with contextlib.suppress(ValueError):
            self._recent.remove(entry)
        self._recent.insert(0, entry)
        del self._recent[RECENT_LIMIT:]
        with contextlib.suppress(OSError):
            save_recent(self._recent)
        self._rebuild_recent_menu()

    def _clear_recent(self) -> None:
        """Clear recent items and rebuild the recent menu.

        Ignore any OSError raised while clearing recent items with clear_recent().
        """
        self._recent.clear()
        with contextlib.suppress(OSError):
            clear_recent()
        self._rebuild_recent_menu()

    def _open_recent(self, path_str: str) -> None:
        """Open a recent file, dropping it if it is no longer a file.

        Args:
            path_str (str): Path to the file to open.

        Returns:
            None: This method does not return a value.
        """
        path = Path(path_str)
        if not path.is_file():
            QMessageBox.warning(self, "Morgul", f"File not found:\n{path}")
            if path_str in self._recent:
                self._recent.remove(path_str)
                with contextlib.suppress(OSError):
                    save_recent(self._recent)
                self._rebuild_recent_menu()
            return
        self._open_path(path)

    def _read_document(self, path: Path) -> tuple[str, str | None]:
        """Read a Markdown or encrypted MORGUL document from a path.

        Args:
            path (Path): Path to the document to read.

        Returns:
            tuple[str, str | None]: The document content and, for encrypted documents,
                the password used to unlock it; otherwise, `None`.

        Raises:
            _UserCancelledError: If the password prompt is cancelled or provides no
                password.
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
        """Write the editor tab's contents to the specified path.

        If the tab has a password, pack its contents with that password and write the
            resulting bytes. Otherwise, write the contents as UTF-8 text with LF
            newlines.

        Args:
            tab (EditorTab): Editor tab whose contents to write.
            path (Path): Destination path.

        Returns:
            None
        """
        text = tab.editor.toPlainText()
        if tab.password:
            path.write_bytes(pack(text, tab.password))
        else:
            path.write_text(text, encoding="utf-8", newline="\n")

    def _save(self) -> None:
        """Save the current tab to its existing path when possible.

        If there is no current tab or the tab is locked, do nothing. Use the Save As
            flow when the tab has no path or its password state does not match the
            container type. On a successful save, add the path to recent files, update
            the editor baseline, clear the dirty flag, and notify that tab metadata
            changed. Show a warning if writing the document raises an OSError.

        Returns:
            None.
        """
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
        self._add_recent(tab.path)
        tab._set_baseline(tab.editor.toPlainText())  # ruff: ignore[private-member-access]
        tab.dirty = False
        self.tab_meta_changed()

    def _save_as(self) -> None:
        """Save the current tab to a selected path.

        Return without saving if there is no current tab, the tab is locked, or the save
            dialog is canceled. Choose a default filename and file filter based on
            whether the tab has a password, and adjust the selected file extension
            accordingly. If writing fails with an `OSError`, display a warning;
            otherwise, update the tab path, recent files, baseline, and dirty state.
        """
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
        self._add_recent(path)
        tab._set_baseline(tab.editor.toPlainText())  # ruff: ignore[private-member-access]
        tab.dirty = False
        self.tab_meta_changed()

    def _set_password(self) -> None:
        """Set, change, or remove the current tab's password.

        If the current tab is locked, attempt to unlock it instead. Otherwise, show the
            password dialog and update the tab only if the dialog is accepted and
            provides a result. Notify the user when the document's encryption state does
            not match its file type.

        Returns:
            None.
        """
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
        """Export the current unlocked tab as a Markdown file.

        Use the tab's path with a `.md` suffix as the default destination, or
            `export.md` if it has no path. Do nothing if there is no current tab, the
            tab is locked, or the save dialog is canceled. Show a warning if writing the
            file fails.

        Returns:
            None.
        """
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
        """Export the current unlocked tab as an HTML file.

        Use the tab's existing path with an `.html` suffix as the default filename, or
            `export.html` when it has no path. Show a warning if writing the file fails.
        """
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
        """Save the session before closing the window.

        If saving raises an `OSError`, ask whether to quit anyway; ignore the close
            event if the user declines. Otherwise, close the find dialog, remove this
            window from the tracked windows when present, and accept the close event.

        Args:
            event (QCloseEvent): The close event to accept or ignore.
        """
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
        with contextlib.suppress(ValueError):
            _WINDOWS.remove(self)
        event.accept()


def _strip_for_session(session_id: str) -> EditorTabStrip | None:
    """Find the tab strip containing the specified session.

    Args:
        session_id (str): ID of the session to locate.

    Returns:
        EditorTabStrip | None: The tab strip containing the session, or None if no valid
            window contains it.
    """
    for win in _WINDOWS:
        if not isValid(win):
            continue
        strip = win._tabs  # ruff: ignore[private-member-access]
        if strip.index_of_session(session_id) >= 0:
            return strip
    return None


def _move_tab_across_windows(
    source: EditorTabStrip,
    source_index: int,
    target: EditorTabStrip,
    target_index: int,
) -> None:
    """Move an editor tab from one tab strip to another.

    If the indexed widget is not an EditorTab or either strip has no owner, leave both
        strips unchanged. Otherwise, detach the tab from the source window, attach and
        select it in the target window, and close the source window if it has no tabs
        remaining. If tabs remain, update the source window's title and status.

    Args:
        source (EditorTabStrip): Tab strip containing the tab to move.
        source_index (int): Index of the tab in the source strip.
        target (EditorTabStrip): Tab strip that receives the tab.
        target_index (int): Index at which to attach the tab in the target strip.

    Returns:
        None: This function does not return a value.
    """
    widget = source._stack.widget(source_index)  # ruff: ignore[private-member-access]
    if not isinstance(widget, EditorTab):
        return
    source_window = source.owner
    if source_window is None or target.owner is None:
        return

    source.remove_tab(source_index)
    source_window._detach_tab(widget)  # ruff: ignore[private-member-access]
    target.owner._attach_tab(  # ruff: ignore[private-member-access]
        widget, index=target_index, select=True
    )
    if source.count() == 0:
        source_window.close()
    else:
        source_window._set_title()  # ruff: ignore[private-member-access]
        source_window._update_status()  # ruff: ignore[private-member-access]


def run() -> None:
    """Create and display the main application window.

    Configure the Qt application, show the window, and open the first command-line
        argument as a path if one is provided. Run the Qt event loop.

    Raises:
        SystemExit: With the Qt event-loop exit code.
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
    if len(sys.argv) > 1:
        window._open_path(Path(sys.argv[1]))  # ruff: ignore[private-member-access]
    raise SystemExit(app.exec())
