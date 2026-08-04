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


class TestExtractionIsBoundedAtBothEnds:
    """The manual export names a date RANGE; this query only had a floor.

    Parcel Perfect holds waybills with mis-keyed dates — 340 in the FY27 pull
    on 4 Aug 2026, years 2520 to 9473, the two Invoiced ones on records
    captured in October 2008. With no ceiling they all read as FY27. Larry's
    own export never showed one: a waybill dated 9473 is outside March26-Feb27.
    """

    def test_both_bounds_are_in_the_query(self):
        from extract_revenue import extraction_sql
        sql = extraction_sql("wb", date(2026, 3, 1))
        assert "wba.WAYDATE >= DATE '2026-03-01'" in sql
        assert "wba.WAYDATE < DATE '2027-03-01'" in sql

    def test_the_ceiling_closes_the_financial_year_that_start_opens(self):
        from extract_revenue import fy_end
        assert fy_end(date(2026, 3, 1)) == date(2027, 3, 1)
        assert fy_end(date(2025, 3, 1)) == date(2026, 3, 1)

    def test_invoice_basis_is_bounded_the_same_way(self):
        from extract_revenue import extraction_sql
        sql = extraction_sql("inv", date(2026, 3, 1))
        assert "wba.INVDATE >= DATE '2026-03-01'" in sql
        assert "wba.INVDATE < DATE '2027-03-01'" in sql


class TestBillingFrontierIsNotAPlainMax:
    """One invoice must not decide that a day is billed.

    On 4 Aug 2026 invoicing had not run for August at all — 0 of 807 waybills
    dated the 3rd were invoiced in the 07:13 export. By 10:40 a single early
    invoice carrying a 3 Aug waybill date had moved max() from 31 Jul to 3 Aug,
    which reclassified all of Monday's freight as unbilled and took the report
    from R41k to R731k. Nothing about the day had changed.

    Fixing the extract's date range does not help here: this row is real,
    current and correctly dated. Only judging a day by the SHARE invoiced does.
    """

    IX = {"Waybill Date": 0, "Status": 1}

    @staticmethod
    def _norm(v):
        return v

    def _rows(self, aug3_invoiced: int):
        """July fully invoiced, August not — plus however many early invoices
        happen to carry a 3 August waybill date."""
        rows = []
        for day in (30, 31):
            rows += [[date(2026, 7, day), "Invoiced"] for _ in range(700)]
            rows += [[date(2026, 7, day), "Ready for Approval"] for _ in range(10)]
        rows += [[date(2026, 8, 3), "Invoiced"] for _ in range(aug3_invoiced)]
        rows += [[date(2026, 8, 3), "Ready for Approval"]
                 for _ in range(807 - aug3_invoiced)]
        return rows

    def _frontier(self, rows):
        import build_unbilled
        return build_unbilled.billing_frontier(rows, self.IX, self._norm)

    def test_one_early_invoice_does_not_move_the_frontier(self):
        assert self._frontier(self._rows(aug3_invoiced=1)) == date(2026, 8, 1)

    def test_nor_does_a_handful(self):
        assert self._frontier(self._rows(aug3_invoiced=40)) == date(2026, 8, 1)

    def test_the_frontier_moves_once_the_day_is_actually_invoiced(self):
        assert self._frontier(self._rows(aug3_invoiced=500)) == date(2026, 8, 4)

    def test_a_future_dated_invoice_is_still_rejected(self):
        """The year-9473 case, kept from the earlier fix."""
        rows = self._rows(aug3_invoiced=0)
        rows += [[date(9473, 7, 5), "Invoiced"]] * 50
        assert self._frontier(rows) == date(2026, 8, 1)

    def test_a_quiet_day_is_too_small_to_judge(self):
        """A Saturday carrying three waybills, all invoiced, is not evidence
        that invoicing has reached Saturday."""
        rows = self._rows(aug3_invoiced=0)
        rows += [[date(2026, 8, 8), "Invoiced"]] * 3
        assert self._frontier(rows) == date(2026, 8, 1)
