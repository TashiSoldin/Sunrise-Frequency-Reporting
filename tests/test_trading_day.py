"""Picking the day a report covers.

"Latest date in the file" is not "last day that traded", and the difference
sent exco a flash reporting R0. On Monday 3 Aug 2026 the waybill export held
ten waybills dated Sunday the 2nd worth nothing at all, and the invoice export
held two lines dated Friday the 31st because that day's invoice run had not
happened yet. Taking the max picked both.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "revenue_reports"))

from run_daily import last_trading_day  # noqa: E402

MON = date(2026, 8, 3)


def week(start: date, values):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


class TestRealCase:
    """The actual figures from 3 August 2026."""

    def test_waybills_roll_back_over_the_weekend(self):
        pairs = week(date(2026, 7, 27), [
            632846,   # Mon 27
            728287,   # Tue 28
            803604,   # Wed 29
            637612,   # Thu 30
            717045,   # Fri 31
            78938,    # Sat 1 Aug — 11% of a normal day
            0,        # Sun 2 Aug — ten waybills, no value
        ])
        assert last_trading_day(pairs, MON) == date(2026, 7, 31)

    def test_invoices_skip_the_day_whose_run_has_not_happened(self):
        pairs = week(date(2026, 7, 27), [
            819559,   # Mon 27
            684551,   # Tue 28
            830847,   # Wed 29
            638341,   # Thu 30
            840,      # Fri 31 — two lines, invoicing not yet run
        ])
        assert last_trading_day(pairs, MON) == date(2026, 7, 30)


class TestOrdinaryDays:
    def test_midweek_picks_yesterday(self):
        pairs = week(date(2026, 7, 27), [600000, 600000, 600000, 620000])
        assert last_trading_day(pairs, date(2026, 7, 31)) == date(2026, 7, 30)

    def test_today_is_never_chosen(self):
        pairs = week(date(2026, 7, 27), [600000, 600000, 600000, 600000, 900000])
        assert last_trading_day(pairs, date(2026, 7, 31)) == date(2026, 7, 30)

    def test_a_quiet_but_real_day_still_counts(self):
        # Half the median is the floor, so a day at 60% is a trading day.
        pairs = week(date(2026, 7, 27), [600000, 600000, 600000, 600000, 360000])
        assert last_trading_day(pairs, MON) == date(2026, 7, 31)

    def test_a_public_holiday_is_skipped(self):
        pairs = week(date(2026, 7, 27), [600000, 600000, 600000, 600000, 12000])
        assert last_trading_day(pairs, MON) == date(2026, 7, 30)


class TestDegenerate:
    def test_empty_input_returns_today(self):
        assert last_trading_day([], MON) == MON

    def test_single_day_of_history_is_used_rather_than_rejected(self):
        assert last_trading_day([(date(2026, 7, 31), 5000)], MON) == date(2026, 7, 31)

    def test_all_days_below_the_floor_falls_back_to_the_newest(self):
        """Never return nothing — a wrong day beats no report at all."""
        pairs = [(date(2026, 7, 30), 0), (date(2026, 7, 31), 0)]
        assert last_trading_day(pairs, MON) == date(2026, 7, 31)

    def test_none_values_are_tolerated(self):
        pairs = [(date(2026, 7, 30), None), (date(2026, 7, 31), 600000)]
        assert last_trading_day(pairs, MON) == date(2026, 7, 31)

    def test_non_dates_are_ignored(self):
        pairs = [("not a date", 999999), (date(2026, 7, 31), 600000)]
        assert last_trading_day(pairs, MON) == date(2026, 7, 31)
