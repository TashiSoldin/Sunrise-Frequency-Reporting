"""South African public-holiday calendar and trading-day arithmetic.

Single home for "which days count as trading days" — used by the dashboard's
projection/expected/day-target divisors. Hoisted here per the project rule
that a guard written three times gets shared on the fourth.

Definition (Larry, 13 Aug 2026, by email re the 12 Aug flash): public
holidays come OUT of the day count — "Monday was a public holiday so we
should be on day 6" (Mon 10 Aug 2026, Women's Day observed, mid-August).
This supersedes the holidays-left-in reading of his 28 Jul reference
workbook: that reference only ever exercised completed months (elapsed =
period, so the choice cancels) and July, which had no weekday holiday —
August 2026 was the first month where the two readings diverge, and Larry
picked holidays-out. It also matches the reporting system's own behaviour:
the flash day-selection already rolls back over public holidays as
non-trading days.

Trading day = Monday-Friday, not an SA public holiday, adjusted by the
exception lists below.

Sources: Public Holidays Act 36 of 1994 (fixed dates + the Sunday rule:
a public holiday falling on a Sunday makes the following Monday a public
holiday) and the Easter computus for Good Friday / Family Day.

One-off proclaimed holidays (e.g. election days) are NOT derivable from the
Act — add them to EXTRA_HOLIDAYS as they are proclaimed. A worked Saturday
or a company shutdown day goes in EXTRA_WORKDAYS / EXTRA_HOLIDAYS likewise.
"""

from datetime import date, timedelta
from functools import cache

# ---------------------------------------------------------------- exceptions
# One-off proclaimed public holidays (election days, special holidays) and
# company-specific closures. Larry-notified; keep dated comments.
EXTRA_HOLIDAYS: set[date] = set()

# Days that WOULD be excluded but which the business worked and wants counted
# (e.g. a worked Saturday). Weekend days added here are counted as trading.
EXTRA_WORKDAYS: set[date] = set()


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (Anonymous/Meeus computus)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@cache
def public_holidays(year: int) -> frozenset[date]:
    """All SA public holidays observed in a calendar year, Sunday rule applied."""
    easter = _easter(year)
    fixed = [
        date(year, 1, 1),  # New Year's Day
        date(year, 3, 21),  # Human Rights Day
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Family Day
        date(year, 4, 27),  # Freedom Day
        date(year, 5, 1),  # Workers' Day
        date(year, 6, 16),  # Youth Day
        date(year, 8, 9),  # National Women's Day
        date(year, 9, 24),  # Heritage Day
        date(year, 12, 16),  # Day of Reconciliation
        date(year, 12, 25),  # Christmas Day
        date(year, 12, 26),  # Day of Goodwill
    ]
    observed = set(fixed)
    for h in fixed:
        if h.weekday() == 6:  # Sunday -> following Monday is a public holiday
            observed.add(h + timedelta(days=1))
    # Observance shifted into an adjacent year stays put (can't happen with
    # the current list — 31 Dec is not a holiday — but keep the filter honest).
    observed = {d for d in observed if d.year == year}
    observed |= {d for d in EXTRA_HOLIDAYS if d.year == year}
    return frozenset(observed)


def is_trading_day(d: date) -> bool:
    """Mon-Fri, not a public holiday; EXTRA_WORKDAYS force-counts a day."""
    if d in EXTRA_WORKDAYS:
        return True
    return d.weekday() < 5 and d not in public_holidays(d.year)


def trading_days_between(a: date, b: date) -> int:
    """Trading days in the inclusive window [a, b]."""
    n, d = 0, a
    while d <= b:
        if is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def nth_trading_day(y: int, m: int, n: int) -> date:
    """The n-th trading day of a calendar month (for like-for-like windows)."""
    d = date(y, m, 1)
    k = 0
    while True:
        if is_trading_day(d):
            k += 1
            if k == n:
                return d
        d += timedelta(days=1)
