"""zxcvbn-backed password strength scoring.

A thin wrapper over :func:`zxcvbn.zxcvbn` so the rest of the app (and tests)
talks in terms of a 0-4 score plus a human label, never the raw dict.
"""

from __future__ import annotations

from dataclasses import dataclass

from zxcvbn import zxcvbn

# zxcvbn scores run 0-4; map each to a short label and a bar count (of 4).
STRENGTH_LABELS = (
    "Very weak",
    "Weak",
    "Fair",
    "Strong",
    "Very strong",
)


@dataclass(frozen=True)
class PasswordStrength:
    """Normalised zxcvbn result.

    Attributes:
        score: 0-4, straight from zxcvbn (0 = terrible, 4 = great).
        label: Short human-readable label for the score.
        warning: zxcvbn contextual warning (e.g. "This is a top-10 common password"),
            empty when there is none.
        suggestions: zxcvbn improvement suggestions, ordered most-relevant first.
    """

    score: int
    label: str
    warning: str
    suggestions: tuple[str, ...]


def score_password(password: str) -> PasswordStrength:
    """Score *password* with zxcvbn.

    An empty password is treated as score 0 with no warning/suggestions so the
    meter simply reads "Very weak" while the field is blank rather than erroring
    on zxcvbn's ``""`` input.

    Returns:
        A :class:`PasswordStrength` with zxcvbn's score, label, warning and
        suggestions.
    """
    if not password:
        return PasswordStrength(
            score=0,
            label=STRENGTH_LABELS[0],
            warning="",
            suggestions=(),
        )

    result = zxcvbn(password)
    feedback = result.get("feedback", {})
    return PasswordStrength(
        score=int(result["score"]),
        label=STRENGTH_LABELS[int(result["score"])],
        warning=str(feedback.get("warning", "") or ""),
        suggestions=tuple(feedback.get("suggestions", []) or []),
    )
