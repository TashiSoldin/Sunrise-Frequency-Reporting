"""Which months become tabs, and how many trading days each one has.

These are pure functions of the last invoiced day, so they need no database,
no exports and no fixtures. They would have caught "July 26 missing" on
1 August rather than waiting for Christine to spot it, and they catch the
financial-year rollover on 1 March 2027 seven months before it happens.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "revenue_reports"))

from build_dashboard import (  # noqa: E402
    MONTHS_FY, cal_year, fy_label, fy_start_year, month_trading_days, month_win,
)


def completed(as_of: date):
    """Mirror of the selection in build(): months finished on or before as_of."""
    fy = fy_start_year(as_of)
    return [m for m in MONTHS_FY if month_win(cal_year(fy, m), m)[1] <= as_of]


class TestFinancialYear:
    @pytest.mark.parametrize("d, fy", [
        (date(2026, 3, 1), 2026),    # first day of FY27
        (date(2026, 7, 31), 2026),
        (date(2027, 2, 28), 2026),   # last day of FY27
        (date(2027, 3, 1), 2027),    # rolls to FY28
        (date(2026, 1, 15), 2025),   # Jan belongs to the FY that opened last March
    ])
    def test_start_year(self, d, fy):
        assert fy_start_year(d) == fy

    def test_label(self):
        assert fy_label(2026) == "FY27"
        assert fy_label(2027) == "FY28"

    def test_jan_feb_fall_in_the_following_calendar_year(self):
        assert cal_year(2026, 3) == 2026
        assert cal_year(2026, 12) == 2026
        assert cal_year(2026, 1) == 2027
        assert cal_year(2026, 2) == 2027


class TestCompletedMonths:
    def test_mid_july_is_the_reference_workbook_shape(self):
        # Larry's 28 Jul reference: Mar-Jun complete, July still running.
        assert completed(date(2026, 7, 24)) == [3, 4, 5, 6]

    def test_end_of_july_completes_july(self):
        # 3 Aug, data through 31 Jul - this is the case Christine reported.
        assert completed(date(2026, 7, 31)) == [3, 4, 5, 6, 7]

    def test_part_way_through_august_leaves_august_open(self):
        assert completed(date(2026, 8, 12)) == [3, 4, 5, 6, 7]

    def test_full_year(self):
        assert completed(date(2027, 2, 28)) == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]

    def test_first_month_of_a_new_fy_has_nothing_complete(self):
        assert completed(date(2027, 3, 10)) == []


class TestTradingDays:
    def test_matches_larrys_reference_workbook(self):
        """The five values read out of the reference's own assumption cells.

        Plain Mon-Fri with public holidays left in. Weekdays minus SA public
        holidays would give Apr 19 / May 20 / Jun 21, which is a different
        report - see the Questions for Larry note before changing this.
        """
        assert [month_trading_days(2026, m) for m in (3, 4, 5, 6, 7)] == [22, 22, 21, 22, 23]

    def test_ytd_to_june_is_87(self):
        assert sum(month_trading_days(2026, m) for m in (3, 4, 5, 6)) == 87

    def test_holidays_are_not_deducted(self):
        # April 2026 contains Good Friday (3rd), Family Day (6th) and Freedom
        # Day (27th). All three still count.
        assert month_trading_days(2026, 4) == 22

    def test_every_fy_month_is_plausible(self):
        for m in MONTHS_FY:
            assert 18 <= month_trading_days(2026, m) <= 23
