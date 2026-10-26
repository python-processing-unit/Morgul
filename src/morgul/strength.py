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
    """Represent a normalized zxcvbn password-strength result.

    Attributes:
        score (int): zxcvbn score from 0 (terrible) to 4 (great).
        label (str): Short human-readable label for the score.
        warning (str): Contextual zxcvbn warning, or an empty string if there is none.
        suggestions (tuple[str, ...]): zxcvbn improvement suggestions, ordered by
            relevance.
    """

    score: int
    label: str
    warning: str
    suggestions: tuple[str, ...]


def score_password(password: str) -> PasswordStrength:
    """Score a password using zxcvbn.

    An empty password receives score 0, the corresponding strength label, and no warning
        or suggestions. For a non-empty password, the score and feedback are derived
        from zxcvbn's result.

    Args:
        password (str): The password to score.

    Returns:
        PasswordStrength: The score, corresponding label, warning, and suggestions.
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
