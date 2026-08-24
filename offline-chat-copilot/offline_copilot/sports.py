"""Dated sports/small-talk lines. Banter follows the calendar, not a frozen slogan."""

from __future__ import annotations

from datetime import date

UFC_NIGHT = (date(2026, 8, 22), date(2026, 8, 23))


def sports_banter(today: date | None = None) -> list[str]:
    day = today or date.today()
    lines: list[str] = [
        "I've been flipping between MLB games whenever I get a spare minute.",
        "NFL pre-season has been on in the background here.",
    ]
    start, end = UFC_NIGHT
    if start <= day <= end:
        lines.append("I've been looking forward to UFC Fight Night this weekend.")
    elif date(2026, 8, 20) <= day <= date(2026, 8, 24):
        lines.append("I've been thinking about that UFC Fight Night from this weekend.")
    else:
        lines.append("I like keeping up with fight nights when they pop up.")
    return lines
