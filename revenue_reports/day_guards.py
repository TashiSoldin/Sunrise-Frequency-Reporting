"""Data-driven day guards — which days in a live extract can be reported on.

Hoisted on the fourth occurrence, per the briefing rule: the same lesson —
ignore what is too small or too sparse to mean anything — was already written
three times (HOLIDAY_GUARD in build_flash, TRADING_GUARD in run_daily,
INVOICED_GUARD in build_unbilled), each time after a max()/min() over a dirty
date column produced a wrong client-facing number. The query interface
(mcp_server/revenue.py) is the fourth consumer, so the shared pieces live
here rather than being written a fourth time.

This module is import-light on purpose: the MCP server needs these guards but
must not import run_daily (logging config, mailer) or a builder (xlsxwriter)
to get them. sa_calendar.py is the *calendar* half — which weekdays count;
this is the *data* half — which days in the data are complete enough to
trust.
"""

import statistics
from datetime import date, timedelta

# A day counts as traded once it clears this fraction of the median day in the
# trailing window. Matches HOLIDAY_GUARD in build_flash.py, which uses the same
# test to keep public holidays out of the typical-weekday benchmark.
TRADING_GUARD = 0.5
TRADING_WINDOW = 28  # days of history the median is taken over


def last_trading_day(pairs, today: date) -> date:
    """Newest day before today that actually traded.

    "Latest date present in the file" is not the same thing. Ten waybills carry
    a Sunday date and two invoices carry a Friday date on which invoicing had
    not yet run — taking the max picked those and produced a flash reporting R0
    and a billing detail of two lines. So walk back to the newest day whose
    value clears half the median of the trailing window, which skips weekends,
    public holidays and days whose invoice run has not happened yet.

    Falls back to the plain newest day if there is no history to compare
    against, so a first run or a sparse file still produces something.
    """
    totals: dict[date, float] = {}
    for d, v in pairs:
        if isinstance(d, date) and d < today:
            totals[d] = totals.get(d, 0.0) + (v or 0)
    if not totals:
        return today
    days = sorted(totals)
    window = [totals[d] for d in days if d > today - timedelta(days=TRADING_WINDOW)]
    if not window:
        return days[-1]
    floor = TRADING_GUARD * statistics.median(window)
    traded = [d for d in days if totals[d] >= floor]
    return traded[-1] if traded else days[-1]


# A waybill date counts as invoiced once this share of its waybills have been.
# One row is not evidence that a day is done.
INVOICED_GUARD = 0.5
MIN_WAYBILLS = 20  # ignore weekend and holiday days carrying a handful


class NoInvoicedDays(ValueError):
    """No invoiced waybills at all — a billing frontier cannot be derived."""


def frontier_from_day_counts(
    per_day: dict[date, tuple[int, int] | list[int]], today: date | None = None
) -> date:
    """First day NOT yet invoiced, judged by the SHARE invoiced per day.

    per_day maps waybill date -> (invoiced count, total count). The full
    story of why this is not `max(invoiced waybill date) + 1` — the year-9473
    frontier and the single 10:40 invoice that reclassified R731k — lives on
    build_unbilled.billing_frontier, which delegates here.

    Days after today are ignored (a waybill cannot be invoiced before it
    ships, and Parcel Perfect carries mis-keyed future years as a matter of
    course); days too small to judge are skipped; and when nothing clears the
    bar the old presence rule is the fallback so a sparse file still yields a
    frontier rather than nothing.
    """
    today = today or date.today()
    counted = {
        d: (inv, tot)
        for d, (inv, tot) in per_day.items()
        if isinstance(d, date) and d <= today
    }
    done = [
        d
        for d, (inv, tot) in counted.items()
        if tot >= MIN_WAYBILLS and inv / tot >= INVOICED_GUARD
    ]
    if done:
        return max(done) + timedelta(days=1)

    any_inv = [d for d, (inv, _) in counted.items() if inv]
    if not any_inv:
        raise NoInvoicedDays(
            "No invoiced waybills found — cannot derive billing frontier."
        )
    return max(any_inv) + timedelta(days=1)
