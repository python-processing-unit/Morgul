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


class _PasswordField(QWidget):
    """Single line edit with show/hide eye toggle (masked by default)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the field and eye button."""
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

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self._edit, 1)
        row.addWidget(self._eye)

    def _toggle_echo(self, *, checked: bool) -> None:
        if checked:
            self._edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._eye.setIcon(eye_open_icon(size=16))
            self._eye.setToolTip("Hide password")
        else:
            self._edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._eye.setIcon(eye_off_icon(size=16))
            self._eye.setToolTip("Show password")

    def text(self) -> str:
        """Return the current password text."""
        return self._edit.text()

    def set_text(self, value: str) -> None:
        """Replace the field contents."""
        self._edit.setText(value)

    def set_focus(self) -> None:
        """Focus the line edit."""
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._edit.selectAll()

    @property
    def line_edit(self) -> QLineEdit:
        """Underlying line edit (for returnPressed hooks)."""
        return self._edit


class SetPasswordDialog(QDialog):
    """Set or clear the encryption password for the current document."""

    def __init__(self, parent: QWidget | None = None, *, has_password: bool) -> None:
        """Build the dialog; *has_password* only affects the hint label."""
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
        """Return the accepted password, empty string to clear, or None if cancelled."""
        return self._result_password


class ConfirmPasswordDialog(QDialog):
    """Require the user to retype *expected* before continuing."""

    def __init__(self, parent: QWidget | None, *, expected: str) -> None:
        """Build the confirmation field."""
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
    """Ask for the password to open an encrypted MORGUL file."""

    def __init__(self, parent: QWidget | None = None, *, filename: str = "") -> None:
        """Build the unlock field."""
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
        self._result_password = self._field.text()
        self.accept()

    def password(self) -> str | None:
        """Return the entered password, or ``None`` if cancelled."""
        return self._result_password
