"""Main window: dark Win11 Notepad layout, tabs, find/replace, preview."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QEnterEvent,
    QFont,
    QIcon,
    QKeySequence,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
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
from typing_extensions import override

from morgul.find import (
    FindError,
    FindOptions,
    Match,
    find_all,
    replace_all,
    replace_one,
)
from morgul.highlight import highlight_ranges, spans_in_line
from morgul.icons import close_icon, close_icon_hover, new_tab_icon
from morgul.render import to_html

if TYPE_CHECKING:
    from collections.abc import Callable

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
        self.dirty = False
        self.wrap_on = True
        self.preview_on = True

        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setTabStopDistance(32)
        self.editor.setFont(_editor_font())

        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(True)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([1, 1])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        # Keep a reference so the highlighter is not GC'd.
        self._highlighter = MarkdownHighlighter(self.editor.document())
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.refresh_preview)

        self.editor.textChanged.connect(self._on_text_changed)

    def tab_label(self) -> str:
        """Short name for the tab bar (with dirty star).

        Returns:
            Filename or ``Untitled``, prefixed with ``*`` when dirty.
        """
        name = self.path.name if self.path is not None else "Untitled"
        return f"*{name}" if self.dirty else name

    def _on_text_changed(self) -> None:
        if not self.dirty:
            self.dirty = True
            self.meta_changed.emit()
        self._preview_timer.start()

    def refresh_preview(self) -> None:
        """Push current Markdown into the HTML preview if visible."""
        if self.preview.isVisible():
            self.preview.setHtml(to_html(self.editor.toPlainText()))

    def load_text(self, text: str, path: Path | None) -> None:
        """Replace contents without leaving a dirty flag behind."""
        self.editor.setPlainText(text)
        self.path = path
        self.dirty = False
        self.refresh_preview()

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
        self.editor.setExtraSelections(selections)

    def clear_find_highlights(self) -> None:
        """Remove find ExtraSelections."""
        self.editor.setExtraSelections([])

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
        """Build an empty window with one untitled tab."""
        super().__init__()

        self._tabs = EditorTabStrip()
        self._tabs.new_tab_requested.connect(self._new_tab)
        self._tabs.current_changed.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)

        self._pos_label = QLabel("Ln 1, Col 1")
        self._meta_label = QLabel("UTF-8  |  Markdown")
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
        self._new_tab()
        self.resize(1000, 680)
        self._set_title()

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

    def _new_tab(self) -> EditorTab:
        tab = EditorTab()
        tab.editor.cursorPositionChanged.connect(self._update_status)
        tab.meta_changed.connect(self.tab_meta_changed)
        index = self._tabs.add_tab(tab, tab.tab_label())
        self._install_close_button(index, tab)
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
        tab = self.current_tab()
        if tab is None:
            return
        if self._wrap_action is not None:
            with QSignalBlocker(self._wrap_action):
                self._wrap_action.setChecked(tab.wrap_on)
        if self._preview_action is not None:
            with QSignalBlocker(self._preview_action):
                self._preview_action.setChecked(tab.preview_on)
        self._set_title()
        self._update_status()
        tab.editor.setFocus()

    def _update_status(self) -> None:
        tab = self.current_tab()
        if tab is None:
            self._pos_label.setText("")
            return
        cursor = tab.editor.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.positionInBlock() + 1
        self._pos_label.setText(f"Ln {line}, Col {col}")

    def _toggle_preview(self, *, checked: bool) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.set_preview(on=checked)

    def _toggle_wrap(self, *, checked: bool) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.set_wrap(on=checked)

    def _undo(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.undo()

    def _redo(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.redo()

    def _cut(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.cut()

    def _copy(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.copy()

    def _paste(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.editor.paste()

    def _select_all(self) -> None:
        tab = self.current_tab()
        if tab is not None:
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
        widget.deleteLater()
        if self._tabs.count() == 0:
            self._new_tab()

    def _close_current(self) -> None:
        index = self._tabs.current_index()
        if index >= 0:
            self._close_tab_at(index)

    def _open(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open",
            "",
            "Markdown (*.md *.markdown *.mdown *.txt);;All files (*.*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        # Reuse a blank untitled tab when possible; otherwise open a new one.
        tab = self.current_tab()
        if (
            tab is not None
            and tab.path is None
            and not tab.dirty
            and not tab.editor.toPlainText()
        ):
            target = tab
        else:
            target = self._new_tab()
        target.load_text(path.read_text(encoding="utf-8"), path=path)
        self.tab_meta_changed()

    def _save(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.path is None:
            self._save_as()
            return
        tab.path.write_text(
            tab.editor.toPlainText(),
            encoding="utf-8",
            newline="\n",
        )
        tab.dirty = False
        self.tab_meta_changed()

    def _save_as(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            str(tab.path) if tab.path is not None else "Untitled.md",
            "Markdown (*.md);;All files (*.*)",
        )
        if not path_str:
            return
        tab.path = Path(path_str)
        self._save()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        """Confirm every dirty tab before quitting."""
        for index in range(self._tabs.count()):
            widget = self._tabs.widget(index)
            if isinstance(widget, EditorTab) and not self._confirm_discard(widget):
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
