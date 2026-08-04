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


class TestUnbilledBillingFrontier:
    """The same class of bug on the unbilled report, found 4 Aug 2026.

    build_unbilled derives its billing frontier from the newest INVOICED
    waybill date, so that freight still waiting for a normal invoice run is
    not reported as unbilled. Capture typos put a few waybills in years 2803,
    3000 and 9473, and two of them are marked Invoiced — so a plain max() put
    the frontier in the year 9473, excluded nothing, and reported 1,050
    waybills worth R3.07m against 35-85 and R10-265k in Larry's own reports.

    A waybill cannot be invoiced before it ships, so future dates are rejected.
    """

    HEADERS = ["Waybill", "Waybill Date", "Account", "Customer", "Service",
               "Status", "Subtotal"]

    def _build(self, tmp_path, rows):
        import openpyxl
        import xlsxwriter

        import build_unbilled
        tmp_path.mkdir(parents=True, exist_ok=True)
        src = tmp_path / "wb.xlsx"
        w = xlsxwriter.Workbook(str(src))
        sh = w.add_worksheet()
        dfmt = w.add_format({"num_format": "yyyy-mm-dd"})
        for c, h in enumerate(self.HEADERS):
            sh.write(0, c, h)
        for r, vals in enumerate(rows, start=1):
            for c, v in enumerate(vals):
                if isinstance(v, date):
                    sh.write_datetime(r, c, v, dfmt)
                else:
                    sh.write(r, c, v)
        w.close()
        out = build_unbilled.build(str(src), str(tmp_path))
        return openpyxl.load_workbook(out, data_only=True)

    def _rows(self, typo: bool):
        """Freight invoiced to 31 Jul, one older genuinely-unbilled waybill,
        and one still awaiting its invoice run."""
        rows = [
            ["SL1", date(2026, 7, 30), "A1", "C1", "RDF", "Invoiced", 100],
            ["SL2", date(2026, 7, 31), "A1", "C1", "RDF", "Invoiced", 100],
            ["SL3", date(2026, 7, 29), "A2", "C2", "RDF", "Ready for Approval", 500],
            ["SL4", date(2026, 8, 3), "A3", "C3", "RDF", "Ready for Approval", 9000],
        ]
        if typo:
            # a real one from the export: an Invoiced waybill keyed to year 9473
            rows.append(["SL5", date(9473, 7, 5), "A4", "C4", "RDF", "Invoiced", 100])
        return rows

    def _headline(self, wb):
        ws = wb["Overview"]
        for r in range(1, 12):
            if str(ws.cell(r, 1).value or "").startswith("Unbilled value"):
                return ws.cell(r, 3).value

    def test_future_dated_invoiced_waybill_does_not_disable_the_frontier(self, tmp_path):
        clean = self._headline(self._build(tmp_path / "a", self._rows(typo=False)))
        typo = self._headline(self._build(tmp_path / "b", self._rows(typo=True)))
        assert clean == typo == 500, (
            "the 3 Aug waybill is normal billing lag and must stay excluded; "
            "a year-9473 Invoiced row must not move the frontier"
        )

    def test_the_lagging_waybill_is_what_gets_excluded(self, tmp_path):
        """Guards the assertion above against passing for the wrong reason."""
        wb = self._build(tmp_path, self._rows(typo=True))
        detail = wb["Unbilled Detail"]
        listed = {detail.cell(r, 2).value for r in range(2, detail.max_row + 1)}
        assert "SL3" in listed and "SL4" not in listed
