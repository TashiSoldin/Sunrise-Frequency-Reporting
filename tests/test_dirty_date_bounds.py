"""The last two unbounded max()-over-a-date-column sites, pinned.

18 Aug 2026 sweep (the 'Sweep for other max()/min() over dirty date columns'
task): the scheduled path is safe everywhere — run_daily passes --month to
build_credit_notes and --inv-asof/--wb-asof to build_dashboard, both derived
from last_trading_day. But both builders' HAND-RUN defaults took a plain
max() over a date column, the project's recorded failure mode (dead-Sunday
flash, run-date credit notes, year-9473 frontier):

- build_credit_notes with no --month picked the newest FY27-or-later date in
  the file, unbounded above — one year-9473 mis-key and the report is built
  for a month nobody traded.
- build_dashboard with no as-of caps let the newest raw date decide the
  financial year and current month.

Both now cap at today (the upper bound of day_guards.plausible_window).
Parcel Perfect carries mis-keyed future years as a matter of course.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "revenue_reports"))

import build_credit_notes
from build_dashboard import latest_data_day

CREDIT_HDR = [
    "Receipt",
    "Account",
    "Customer Name",
    "Date",
    "Subtotal",
    "Reference",
    "Type",
    "Rep",
    "Reason",
    "Branch",
    "Credit Controller",
]


def note_row(d, value=-1000.0, receipt=-1.0):
    return [
        receipt,
        "ABC001",
        "Test Customer",
        d,
        value,
        "CN123",
        "Credit Note",
        "REP",
        "Damaged",
        "JHB",
        "Ctrl",
    ]


class TestCreditNotesDefaultMonth:
    def test_future_miskey_does_not_pick_the_month(self, tmp_path):
        """One year-9473 row must not outvote a real July note."""
        data = (
            CREDIT_HDR,
            [note_row(date(2026, 7, 14)), note_row(date(9473, 1, 2))],
        )
        out = build_credit_notes.build(
            "unused.xls", str(tmp_path), month=None, data=data
        )
        assert "Jul 2026" in out
        assert "9473" not in out

    def test_explicit_month_still_wins(self, tmp_path):
        data = (CREDIT_HDR, [note_row(date(2026, 6, 10))])
        out = build_credit_notes.build(
            "unused.xls", str(tmp_path), month=date(2026, 6, 1), data=data
        )
        assert "Jun 2026" in out

    def test_only_implausible_dates_refuses_rather_than_guessing(self, tmp_path):
        """All-future file: refuse with a plain message, never build for 9473."""
        data = (CREDIT_HDR, [note_row(date(9473, 1, 2))])
        with pytest.raises(ValueError, match="--month"):
            build_credit_notes.build("unused.xls", str(tmp_path), month=None, data=data)


class TestDashboardLatestDataDay:
    def test_asof_cap_still_applies(self):
        pools = {"A": {date(2026, 8, 14): 1, date(2026, 8, 17): 1}}
        assert latest_data_day(pools, date(2026, 8, 14)) == date(2026, 8, 14)

    def test_future_miskey_cannot_decide_the_fy_when_uncapped(self):
        """No as-of (a hand run): cap at today, not the raw max."""
        pools = {"A": {date(2026, 8, 14): 1, date(9473, 1, 2): 1}}
        assert latest_data_day(pools, None) == date(2026, 8, 14)

    def test_plain_newest_day_survives(self):
        pools = {"A": {date(2026, 8, 13): 1}, "B": {date(2026, 8, 14): 1}}
        assert latest_data_day(pools, None) == date(2026, 8, 14)
