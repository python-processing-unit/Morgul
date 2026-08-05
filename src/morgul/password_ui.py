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
    """Four-segment bar + label + optional warning, driven by zxcvbn scores."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the empty meter (score 0, no label)."""
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
        bar = QLabel()
        bar.setFixedHeight(6)
        bar.setObjectName("passwordStrengthBar")
        bar.setProperty("strength", 0)
        return bar

    def show_strength(self, strength: object) -> None:
        """Update bars/label/warning from a :class:`PasswordStrength`.

        *strength* is typed ``object`` to avoid an import cycle for callers that
        only need the duck-typed attributes (``score``, ``label``, ``warning``).
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
        """Show or hide the live strength meter under the field."""
        self._meter_shown = enabled
        self._meter.setVisible(enabled)
        if enabled:
            self._update_meter(self._edit.text())

    def _update_meter(self, text: str) -> None:
        if not getattr(self, "_meter_shown", False):
            return
        self._meter.show_strength(score_password(text))

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
