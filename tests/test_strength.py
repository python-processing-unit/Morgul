"""zxcvbn-backed password strength scoring tests."""

from __future__ import annotations

from morgul.strength import STRENGTH_LABELS, score_password


def test_empty_password_is_score_zero() -> None:
    s = score_password("")
    assert s.score == 0
    assert s.label == STRENGTH_LABELS[0]
    assert not s.warning
    assert s.suggestions == ()


def test_common_password_scores_low() -> None:
    s = score_password("password")
    assert s.score <= 1
    assert s.warning  # zxcvbn flags common passwords


def test_strong_password_scores_high() -> None:
    s = score_password("correct-horse-battery-staple-9zX!morgul")
    assert s.score >= 3


def test_score_in_valid_range() -> None:
    for pw in ("", "a", "Tr0ub4dor&3", "x" * 40, "correct-horse-battery-staple"):
        assert 0 <= score_password(pw).score <= 4


def test_label_matches_score_index() -> None:
    for pw in ("", "password", "Tr0ub4dor&3", "correct-horse-battery-staple"):
        s = score_password(pw)
        assert s.label == STRENGTH_LABELS[s.score]
