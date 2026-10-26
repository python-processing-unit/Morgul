"""Password entry dialogs for MORGUL encryption."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from morgul.icons import eye_off_icon, eye_open_icon
from morgul.strength import score_password


class PasswordStrengthMeter(QWidget):
    """Display password strength as a bar, a label, and an optional warning.

    The meter updates from an object with `score`, `label`, and `warning` attributes.
        Missing attributes default to a score of 0 and empty label and warning text.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the meter's bar, label, and warning widgets.

        Args:
            parent (QWidget | None): Optional parent widget.
        """
        super().__init__(parent)
        self._bars = [self._make_bar() for _ in range(4)]
        self._label = QLabel()
        self._warning = QLabel()
        self._warning.setWordWrap(True)
        self._warning.setObjectName("passwordWarningLabel")
        self._warning.setVisible(False)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(3)
        for bar in self._bars:
            bar_row.addWidget(bar)
        bar_row.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        root.addLayout(bar_row)
        root.addWidget(self._label)
        root.addWidget(self._warning)

    @staticmethod
    def _make_bar() -> QLabel:
        """Create an empty password-strength bar.

        Returns:
            QLabel: A 6-pixel-high label named `passwordStrengthBar` with its strength
                property set to 0.
        """
        bar = QLabel()
        bar.setFixedHeight(6)
        bar.setObjectName("passwordStrengthBar")
        bar.setProperty("strength", 0)
        return bar

    def show_strength(self, strength: object) -> None:
        """Update the strength bars, label, and warning.

        Read `score`, `label`, and `warning` attributes from `strength`, defaulting to
            `0`, `""`, and `""` when they are absent. Fill bars according to the score,
            set the label text, and show the warning only when it is nonempty.

        Args:
            strength (object): Object providing `score`, `label`, and `warning`
                attributes.

        Returns:
            None: This method does not return a value.
        """
        score = int(getattr(strength, "score", 0))
        label = str(getattr(strength, "label", ""))
        warning = str(getattr(strength, "warning", ""))
        for i, bar in enumerate(self._bars):
            filled = i < score
            bar.setProperty("strength", score if filled else 0)
            bar.setProperty("filled", filled)
            bar.style().unpolish(bar)
            bar.style().polish(bar)
        self._label.setText(label)
        if warning:
            self._warning.setText(warning)
            self._warning.setVisible(True)
        else:
            self._warning.setVisible(False)


class _PasswordField(QWidget):
    """Provide a password field with a show/hide toggle and an optional strength meter.

    Attributes:
        line_edit (QLineEdit): The underlying line edit, available for connecting
            signals such as ``returnPressed``.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the password field, visibility toggle, and hidden strength meter.

        Args:
            parent (QWidget | None): The optional parent widget.
        """
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setMinimumWidth(260)

        self._eye = QToolButton()
        self._eye.setObjectName("passwordEyeButton")
        self._eye.setAutoRaise(True)
        self._eye.setCheckable(True)
        self._eye.setChecked(False)
        self._eye.setIcon(eye_off_icon(size=16))
        self._eye.setIconSize(QSize(16, 16))
        self._eye.setToolTip("Show password")
        self._eye.toggled.connect(lambda on: self._toggle_echo(checked=on))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self._edit, 1)
        row.addWidget(self._eye)

        self._meter = PasswordStrengthMeter()
        self._meter.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addLayout(row)
        outer.addWidget(self._meter)

        self._edit.textChanged.connect(self._update_meter)

    def enable_strength_meter(self, *, enabled: bool) -> None:
        """Show or hide the strength meter and refresh it when shown.

        Args:
            enabled (bool): Whether to show the strength meter.

        Returns:
            None: This method does not return a value.
        """
        self._meter_shown = enabled
        self._meter.setVisible(enabled)
        if enabled:
            self._update_meter(self._edit.text())

    def _update_meter(self, text: str) -> None:
        """Update the password-strength meter when it is shown.

        Args:
            text (str): The password text to score.

        Returns:
            None: This method does not return a value.
        """
        if not getattr(self, "_meter_shown", False):
            return
        self._meter.show_strength(score_password(text))

    def _toggle_echo(self, *, checked: bool) -> None:
        """Toggle password visibility based on the checked state.

        Args:
            checked (bool): Whether to show the password.
        """
        if checked:
            self._edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._eye.setIcon(eye_open_icon(size=16))
            self._eye.setToolTip("Hide password")
        else:
            self._edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye.setIcon(eye_off_icon(size=16))
            self._eye.setToolTip("Show password")

    def text(self) -> str:
        """Return the text currently entered in the password field."""
        return self._edit.text()

    def set_text(self, value: str) -> None:
        """Set the field contents to the given value.

        Args:
            value (str): The text to display in the field.

        Returns:
            None.
        """
        self._edit.setText(value)

    def set_focus(self) -> None:
        """Focus the line edit and select all of its text."""
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._edit.selectAll()

    @property
    def line_edit(self) -> QLineEdit:
        """The underlying line edit widget.

        Returns:
            QLineEdit: The line edit widget.
        """
        return self._edit


class SetPasswordDialog(QDialog):
    """Configure a password for document encryption.

    Accept an empty password to remove existing encryption or leave the document
        unencrypted. A non-empty password must be confirmed before the dialog accepts
        it. Use password() to retrieve the accepted password, an empty string if no
        password was selected, or None if the dialog was cancelled.
    """

    def __init__(self, parent: QWidget | None = None, *, has_password: bool) -> None:
        """Initialize the modal password dialog and its controls.

        Args:
            parent (QWidget | None): Parent widget for the dialog.
            has_password (bool): Selects the hint shown for setting or removing a
                password.
        """
        super().__init__(parent)
        self.setWindowTitle("Password")
        self.setModal(True)
        self._result_password: str | None = None

        hint = (
            "Enter a new password for this file, or leave blank to remove encryption."
            if has_password
            else "Enter a password to encrypt this file, or leave blank for none."
        )
        self._field = _PasswordField()
        self._field.line_edit.returnPressed.connect(self._accept)
        self._field.enable_strength_meter(enabled=True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(hint))
        root.addWidget(self._field)
        root.addWidget(buttons)
        self._field.set_focus()

    def _accept(self) -> None:
        """Accept the password or return focus to the password field.

        If the password is empty, clear the result password and accept the dialog.
            Otherwise, request confirmation; save the password and accept the dialog if
            confirmation succeeds, or return focus to the password field if it does not.
        """
        password = self._field.text()
        if not password:
            self._result_password = ""
            self.accept()
            return
        confirm = ConfirmPasswordDialog(self, expected=password)
        if confirm.exec() == QDialog.DialogCode.Accepted:
            self._result_password = password
            self.accept()
        else:
            self._field.set_focus()

    def password(self) -> str | None:
        """Return the password result.

        Returns:
            str | None: The accepted password, an empty string to clear it, or None if
                cancelled.
        """
        return self._result_password


class ConfirmPasswordDialog(QDialog):
    """Require the user to re-enter a password before accepting the dialog.

    Accept the dialog when the entered password matches the expected value; otherwise,
        show a warning and return focus to the password field.
    """

    def __init__(self, parent: QWidget | None, *, expected: str) -> None:
        """Initialize the modal password confirmation dialog.

        Args:
            parent (QWidget | None): Parent widget for the dialog.
            expected (str): Password that the entered value is expected to match.
        """
        super().__init__(parent)
        self.setWindowTitle("Confirm password")
        self.setModal(True)
        self._expected = expected
        self._field = _PasswordField()
        self._field.line_edit.returnPressed.connect(self._accept)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Re-enter the password to confirm:"))
        root.addWidget(self._field)
        root.addWidget(buttons)
        self._field.set_focus()

    def _accept(self) -> None:
        """Validate the entered password and accept the dialog if it matches.

        If the password does not match, show a warning and return focus to the password
            field.
        """
        if self._field.text() != self._expected:
            QMessageBox.warning(
                self,
                "Password",
                "Passwords do not match.",
            )
            self._field.set_focus()
            return
        self.accept()


class UnlockPasswordDialog(QDialog):
    """Display a modal dialog for entering the password to open an encrypted file.

    The prompt includes the filename when one is provided. Retrieve the entered password
        with `password()`, which returns `None` if the dialog is cancelled.
    """

    def __init__(self, parent: QWidget | None = None, *, filename: str = "") -> None:
        """Initialize a modal dialog for entering a file password.

        Args:
            parent (QWidget | None): Parent widget for the dialog.
            filename (str): Filename to include in the prompt, or an empty string for a
                generic prompt.
        """
        super().__init__(parent)
        self.setWindowTitle("Open encrypted file")
        self.setModal(True)
        self._result_password: str | None = None
        label = (
            f"Enter the password for '{filename}':"
            if filename
            else "Enter the file password:"
        )
        self._field = _PasswordField()
        self._field.line_edit.returnPressed.connect(self._accept)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(label))
        root.addWidget(self._field)
        root.addWidget(buttons)
        self._field.set_focus()

    def _accept(self) -> None:
        """Store the entered password and accept the dialog."""
        self._result_password = self._field.text()
        self.accept()

    def password(self) -> str | None:
        """Return the stored password result.

        Returns:
            str | None: The entered password, or `None` if no password is available.
        """
        return self._result_password
