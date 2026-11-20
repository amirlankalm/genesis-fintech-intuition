"""Deterministic, runnable versions of the tutoring prompts."""

from __future__ import annotations

from .core import Bank, Question, SessionResult, check, render_markdown, run_session


def banks() -> dict[str, Bank]:
    """All question banks by prompt letter."""
    from . import bank_a, bank_c, bank_d

    return {"A": bank_a.BANK, "C": bank_c.BANK, "D": bank_d.BANK}


__all__ = ["Bank", "Question", "SessionResult", "banks", "check", "render_markdown", "run_session"]
