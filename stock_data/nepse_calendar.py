"""
NEPSE trading calendar helpers.

Nepal's trading week is not fixed and has changed more than once:

- Before 2026-04-06 the exchange traded **Sunday-Thursday**, with **Friday and Saturday**
  as the weekend. Fridays were open for odd-lot trading only, not regular trading.
- From 2026-04-06 the exchange trades **Monday-Friday**, with **Saturday and Sunday** as
  the weekend. The Cabinet declared Saturday and Sunday weekly public holidays and the
  NEPSE board (meeting Chait 22 BS, 2026-04-05) resolved to align with the new schedule.

The 2026-04-06 cutoff also covers the transition week correctly. Sunday 2026-04-05 was
still the final day of the old Sunday-Thursday week, and Friday 2026-04-10 traded as part
of a six-day transition week; regular Monday-Friday trading began 2026-04-13.

Limitation: Nepali public holidays (Dashain, Tihar, Prithvi Jayanti, ...) follow the
Bikram Sambat calendar and are published per-year by NEPSE. They are **not** modeled here,
so `is_trading_day()` over-reports on holidays. Callers must tolerate empty results for
those dates, as they did before this module existed.
"""
from datetime import date, timedelta

# First trading day of the Monday-Friday schedule. Dates on or after this use the
# Saturday/Sunday weekend; earlier dates use the Friday/Saturday weekend.
NEPSE_MON_FRI_START = date(2026, 4, 6)

# datetime.date.weekday() indices, Monday=0 .. Sunday=6
_WED_FRI = (4, 5)
_WED_SAT_SUN = (5, 6)


def weekend_weekdays(d: date) -> tuple:
    """
    Return the `date.weekday()` indices that fall on the weekend for the given date.

    Returns (4, 5) Friday/Saturday before 2026-04-06, (5, 6) Saturday/Sunday after.
    """
    return _WED_SAT_SUN if d >= NEPSE_MON_FRI_START else _WED_FRI


def is_trading_day(d: date) -> bool:
    """
    Return True if the date is a NEPSE trading day with respect to weekends only.

    Does not account for Nepali public holidays.
    """
    return d.weekday() not in weekend_weekdays(d)


def next_trading_day(d: date, n: int = 1) -> date:
    """
    Return the date `n` trading days after `d` (excluding `d` itself).

    Negative values walk backwards. Returns `d` unchanged when n is 0.
    """
    if n == 0:
        return d

    step = 1 if n > 0 else -1
    remaining = abs(n)
    current = d

    while remaining > 0:
        current += timedelta(days=step)
        if is_trading_day(current):
            remaining -= 1

    return current


def today_or_clamp(d: date) -> date:
    """
    Return `d` if it is today or in the past, otherwise today.

    Used to stop date-range scrapers walking into the future, where every request is
    guaranteed to come back empty.
    """
    today = date.today()
    return d if d <= today else today