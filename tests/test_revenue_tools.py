"""Revenue tools — guards, matching and shaping logic, no database.

The query runner is injected (a FakeDB that answers each SQL shape from
fixture rows, applying the extraction filters the way Firebird would —
including the case-sensitive exact-ACCNUM match). The rules under test:

- customer matching resolves exact account / exact unique name and otherwise
  returns CANDIDATES, never a silent best guess;
- future dates are refused, never answered;
- a day still being captured / still being invoiced is warned about or
  refused, never returned as a confident partial;
- default date bases come from last_trading_day, never a max over the column;
- filtered extracts feed inline answers only — workbook paths always fetch
  the unfiltered FY extract;
- the shared SQL (day counts, credits) passes the SELECT-only guard.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "revenue_reports"))

from extract_revenue import DB_COLS, day_counts_sql

from mcp_server import revenue
from mcp_server.revenue import InputError
from mcp_server.sql_guard import assert_select_only

FETCH = [*DB_COLS, "RECEIPT_USERNAME", "WB_TOTSURCHARGE"]

CREDIT_COLS = [
    "RECEIPT",
    "ACCNUM",
    "CUSTNAME",
    "RECDATE",
    "AMOUNT",
    "DISCOUNT",
    "REFERENCE",
    "RECTYPE",
    "REASON",
    "ALLOCATED",
    "COMMENT",
    "AIF",
    "USERNAME",
    "EXPORT",
    "VAT",
    "VATTYPE",
    "BRANCHNAME",
    "BANK",
    "CUSTOMSVAT",
    "CUSTOMSDUTIES",
    "REPNAME",
    "COSTCNTRNAME",
    "CREDCONTROLLER",
]

# "Today" is pinned through revenue._today so the fixtures are deterministic
# forever — not correct-until-next-March. All test dates derive from it.
TODAY = date(2026, 8, 17)


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr(revenue, "_today", lambda: TODAY)


def D(n: int) -> date:
    return TODAY - timedelta(days=n)


def wb_row(**fields) -> tuple:
    ix = {c: i for i, c in enumerate(FETCH)}
    row = [None] * len(FETCH)
    defaults = {
        "WAYBILL": "SLJNB100001",
        "WAYDATE": D(5),
        "SERVICE": "ON",
        "CUSTNAME": "TOMMY PDY LIMITED",
        "ACCNUM": "TOM001",
        "ORIGHUB": "JNB",
        "SUBTOTAL": Decimal("100.00"),
        "CHARGEMASS": Decimal("10.00"),
        "STATUS": "Invoiced",
    }
    for k, v in {**defaults, **fields}.items():
        row[ix[k]] = v
    return tuple(row)


def credit_row(**fields) -> tuple:
    ix = {c: i for i, c in enumerate(CREDIT_COLS)}
    row = [None] * len(CREDIT_COLS)
    defaults = {
        "RECEIPT": -100,
        "ACCNUM": "TOM001",
        "CUSTNAME": "TOMMY PDY LIMITED",
        "RECDATE": D(5),
        "AMOUNT": Decimal("115.00"),
        "VAT": Decimal("15.00"),
        "RECTYPE": "N",  # Credit Note
        "REASON": "Rate query",
    }
    for k, v in {**defaults, **fields}.items():
        row[ix[k]] = v
    return tuple(row)


class FakeDB:
    """Answers each SQL shape from fixture rows, filtering the way the live
    query would — including case-sensitive ACCNUM equality."""

    def __init__(
        self,
        customers=(),
        rows=(),
        credit_rows=(),
        wb_counts=(),
        inv_counts=(),
    ):
        self.customers = list(customers)
        self.rows = list(rows)
        self.credit_rows = list(credit_rows)
        self.wb_counts = list(wb_counts)
        self.inv_counts = list(inv_counts)
        self.calls = []

    def __call__(self, sql, params=(), max_rows=1000):
        assert_select_only(sql)  # everything the tools emit must pass the guard
        self.calls.append((sql, params, max_rows))
        if "FROM CUSTOMER WHERE ACCNUM = ?" in sql:
            return ["ACCNUM", "CUSTNAME"], [
                c for c in self.customers if c[0] == params[0]
            ]
        if "FROM CUSTOMER" in sql:
            return ["ACCNUM", "CUSTNAME"], list(self.customers)
        if "GROUP BY" in sql:
            counts = self.wb_counts if "wba.WAYDATE" in sql else self.inv_counts
            return ["DAY_D", "N_WAYBILLS", "SUBTOTAL_SUM", "N_INVOICED"], list(counts)
        if "FROM RECEIPT r" in sql:
            return CREDIT_COLS, list(self.credit_rows)
        if "FROM VIEW_WBANALYSE wba" in sql:
            return FETCH, self._extract(sql, params)
        raise AssertionError(f"unexpected SQL: {sql}")

    def _extract(self, sql, params):
        date_col = "WAYDATE" if "wba.WAYDATE >= ?" in sql else "INVDATE"
        di = FETCH.index(date_col)
        wi, ai, si = (
            FETCH.index("WAYBILL"),
            FETCH.index("ACCNUM"),
            FETCH.index("STATUS"),
        )
        i = 2
        account = d_from = d_to = None
        if "wba.ACCNUM = ?" in sql:
            account = params[i]
            i += 1
        if sql.count(f"wba.{date_col} >= ?") == 2:
            d_from = params[i]
            i += 1
        if f"wba.{date_col} <= ?" in sql:
            d_to = params[i]
        out = []
        for r in self.rows:
            d = r[di]
            if not isinstance(d, date) or not (params[0] <= d < params[1]):
                continue
            if "~" in str(r[wi] or "") or str(r[si]) == "Cancelled":
                continue
            if account is not None and r[ai] != account:  # case-sensitive
                continue
            if d_from is not None and d < d_from:
                continue
            if d_to is not None and d > d_to:
                continue
            out.append(r)
        return out


# Fully-invoiced history through D(3); D(1)-D(2) shipped but not invoiced.
WB_COUNTS = [(D(n), 700, 70000.0, 700) for n in range(3, 12)] + [
    (D(2), 700, 70000.0, 0),
    (D(1), 650, 65000.0, 0),
]
INV_COUNTS = [(D(n), 700, 70000.0, 700) for n in range(3, 12)]
FRONTIER = D(2)  # first not-yet-invoiced day


class TestMatchCustomer:
    def test_exact_account_code_is_uppercased_before_the_query(self):
        db = FakeDB(customers=[("TOM001", "TOMMY PDY LIMITED")])
        m = revenue.match_customer("tom001", run=db)
        assert m["resolved"] and m["account"] == "TOM001"
        assert m["via"] == "exact account code"
        assert db.calls[0][1] == ("TOM001",)  # contract: never lowercased

    def test_exact_unique_name_resolves_and_says_how(self):
        db = FakeDB(customers=[("TOM001", "TOMMY PDY LIMITED"), ("B35", "BIDVEST 35")])
        m = revenue.match_customer("Tommy PDY Limited", run=db)
        assert m["resolved"] and m["account"] == "TOM001"
        assert m["via"] == "exact name match"

    def test_ambiguous_name_returns_candidates_never_a_pick(self):
        db = FakeDB(
            customers=[
                ("TOM001", "TOMMY PDY LIMITED"),
                ("TOM002", "TOMMY PDY (CAPE) LIMITED"),
            ]
        )
        m = revenue.match_customer("Tommy PDY", run=db)
        assert m["resolved"] is False
        assert len(m["candidates"]) == 2
        assert "ask" in m["message"].lower()

    def test_no_match_says_nothing_was_assumed(self):
        db = FakeDB(customers=[("B35", "BIDVEST 35")])
        m = revenue.match_customer("Completely Unknown Trading", run=db)
        assert m["resolved"] is False and m["candidates"] == []
        assert "Nothing was assumed" in m["message"]

    def test_empty_customer_refused_before_any_query(self):
        db = FakeDB()
        with pytest.raises(InputError):
            revenue.match_customer("   ", run=db)
        assert db.calls == []


def _sales_db(**kw):
    rows = [
        wb_row(WAYBILL="A1", INVDATE=D(40), SUBTOTAL=Decimal("100.00")),
        wb_row(WAYBILL="A2", INVDATE=D(40), SUBTOTAL=Decimal("50.00")),
        wb_row(WAYBILL="A3", INVDATE=D(5), SUBTOTAL=Decimal("200.00")),
        wb_row(WAYBILL="B1", INVDATE=D(5), ACCNUM="B35", CUSTNAME="BIDVEST 35"),
    ]
    return FakeDB(
        customers=[("TOM001", "TOMMY PDY LIMITED"), ("B35", "BIDVEST 35")],
        rows=rows,
        credit_rows=[credit_row(RECDATE=D(5))],  # Subtotal 100.00
        wb_counts=WB_COUNTS,
        inv_counts=INV_COUNTS,
        **kw,
    )


class TestSalesReport:
    def test_fully_future_period_is_refused(self):
        r = revenue.sales_report(
            "TOM001", date_from=(TODAY + timedelta(days=3)).isoformat(), run=_sales_db()
        )
        assert r["ok"] is False and r["refused"] is True
        assert "future" in r["reason"]

    def test_future_date_to_is_clamped_with_a_warning(self):
        r = revenue.sales_report(
            "TOM001", date_to=(TODAY + timedelta(days=3)).isoformat(), run=_sales_db()
        )
        assert r["ok"] is True
        assert r["period"]["to"] == TODAY.isoformat()
        assert any("clamped to today" in w for w in r["warnings"])

    def test_period_reaching_the_frontier_warns_still_being_invoiced(self):
        r = revenue.sales_report("TOM001", run=_sales_db())
        assert any("still being invoiced" in w for w in r["warnings"])

    def test_account_filter_is_bound_uppercase_never_interpolated(self):
        db = _sales_db()
        revenue.sales_report("tom001", run=db)
        extract_calls = [
            (sql, params)
            for sql, params, _ in db.calls
            if "FROM VIEW_WBANALYSE wba" in sql and "GROUP BY" not in sql
        ]
        assert extract_calls, "no filtered extract was queried"
        sql, params = extract_calls[0]
        assert "wba.ACCNUM = ?" in sql and "TOM001" in params
        assert "tom001" not in sql and "TOM001" not in sql  # bound, not inlined

    def test_totals_months_credits_and_net(self):
        r = revenue.sales_report("TOM001", run=_sales_db())
        assert r["waybills"] == 3  # B35's row filtered out by account
        assert r["gross_revenue"] == 350.0
        assert r["credit_notes"] == {
            "count": 1,
            "total": 100.0,
            "types_counted": "Credit Note + Journal Credit only",
        }
        assert r["net_revenue"] == 250.0
        assert len(r["by_month"]) == 2
        assert sum(m["gross_revenue"] for m in r["by_month"]) == 350.0

    def test_disambiguation_is_surfaced_not_guessed(self):
        db = _sales_db()
        db.customers.append(("TOM002", "TOMMY PDY (CAPE) LIMITED"))
        r = revenue.sales_report("Tommy PDY", run=db)
        assert r["ok"] is False and r["needs"] == "customer_disambiguation"
        assert len(r["candidates"]) == 2


class TestRevenueSummary:
    def test_default_day_skips_a_quiet_trap_day(self):
        # A near-dead day carrying a handful of waybills must not be picked
        # just because it is the newest date present.
        counts = [(D(n), 700, 70000.0, 700) for n in range(2, 12)] + [
            (D(1), 6, 400.0, 0)  # the trap: newest, nearly empty
        ]
        db = FakeDB(
            rows=[wb_row(WAYDATE=D(2), INVDATE=D(2))],
            wb_counts=counts,
            inv_counts=counts,
        )
        r = revenue.revenue_summary(run=db)
        assert r["shipped"]["day"] == D(2).isoformat()

    def test_future_day_is_refused(self):
        db = FakeDB(wb_counts=WB_COUNTS, inv_counts=INV_COUNTS)
        r = revenue.revenue_summary((TODAY + timedelta(days=1)).isoformat(), run=db)
        assert r["ok"] is False and "future" in r["reason"]

    def test_day_past_the_frontier_warns_instead_of_confident_partial(self):
        db = FakeDB(
            rows=[wb_row(WAYDATE=D(1), INVDATE=None, STATUS="Ready for Approval")],
            wb_counts=WB_COUNTS,
            inv_counts=INV_COUNTS,
        )
        r = revenue.revenue_summary(D(1).isoformat(), run=db)
        assert r["ok"] is True
        assert any("has not finished" in w for w in r["warnings"])
        assert r["billing_frontier"] == FRONTIER.isoformat()


def _unbilled_rows():
    rows = []
    # D(6): fully invoiced day (establishes the frontier at D(5))
    rows += [
        wb_row(WAYBILL=f"INV{i:03d}", WAYDATE=D(6), INVDATE=D(5)) for i in range(25)
    ]
    # D(6): three genuinely unbilled waybills (before the frontier)
    rows += [
        wb_row(
            WAYBILL=f"UNB{i}",
            WAYDATE=D(6),
            INVDATE=None,
            STATUS="Ready for Approval",
            SUBTOTAL=Decimal("10.00"),
        )
        for i in range(3)
    ]
    # D(2): a fresh day, shipped but not yet invoiced — billing lag, NOT
    # unbilled (the 4 Aug R731k lesson)
    rows += [
        wb_row(
            WAYBILL=f"NEW{i:03d}",
            WAYDATE=D(2),
            INVDATE=None,
            STATUS="Ready for Approval",
        )
        for i in range(25)
    ]
    return rows


class TestUnbilledReport:
    def test_fresh_days_are_billing_lag_not_unbilled(self):
        db = FakeDB(rows=_unbilled_rows())
        r = revenue.unbilled_report(run=db)
        assert r["billing_frontier"] == D(5).isoformat()
        assert r["unbilled_waybills"] == 3
        assert r["unbilled_value"] == 30.0
        assert r["by_status"] == {"Ready for Approval": 3}

    def test_workbook_path_uses_the_unfiltered_extract(self, tmp_path, monkeypatch):
        monkeypatch.setattr(revenue, "ONDEMAND_DIR", tmp_path)
        db = FakeDB(rows=_unbilled_rows())
        r = revenue.unbilled_report(workbook=True, run=db)
        assert Path(r["workbook"]["path"]).exists()
        extract_calls = [
            (sql, params)
            for sql, params, _ in db.calls
            if "FROM VIEW_WBANALYSE wba" in sql and "GROUP BY" not in sql
        ]
        # one fetch serving both the inline answer and the workbook, and it
        # carries only the two FY bounds — no account or date filters
        assert len(extract_calls) == 1
        assert len(extract_calls[0][1]) == 2


class TestCreditNotes:
    def _db(self):
        m0 = D(40).replace(day=1)
        return FakeDB(
            credit_rows=[
                credit_row(RECEIPT=-1, RECDATE=D(5)),
                credit_row(RECEIPT=-2, RECDATE=D(5), RECTYPE="J"),
                credit_row(RECEIPT=-3, RECDATE=D(5), RECTYPE="B"),  # Bad Debt: out
                credit_row(RECEIPT=-4, RECDATE=m0),  # earlier month
            ],
            wb_counts=WB_COUNTS,
            inv_counts=INV_COUNTS,
        )

    def test_only_credit_note_and_journal_credit_count(self):
        r = revenue.credit_notes(
            month=f"{D(5).year:04d}-{D(5).month:02d}", run=self._db()
        )
        assert r["credit_notes"] == 2
        assert r["total_value"] == 200.0
        assert "Bad Debt" in r["types_counted"]

    def test_future_month_is_refused(self):
        nxt = (TODAY.replace(day=1) + timedelta(days=32)).replace(day=1)
        r = revenue.credit_notes(
            month=f"{nxt.year:04d}-{nxt.month:02d}", run=self._db()
        )
        assert r["ok"] is False and "future" in r["reason"]

    def test_default_month_follows_the_last_invoiced_trading_day(self):
        r = revenue.credit_notes(run=self._db())
        inv_day = D(3)  # newest fully-invoiced day in INV_COUNTS
        assert r["month"] == f"{inv_day.year:04d}-{inv_day.month:02d}"

    def test_open_month_is_flagged_mtd(self):
        r = revenue.credit_notes(
            month=f"{TODAY.year:04d}-{TODAY.month:02d}", run=self._db()
        )
        assert any("month-to-date" in w for w in r["warnings"])


class TestDailyReport:
    def test_unknown_report_is_refused_before_any_query(self):
        db = FakeDB()
        with pytest.raises(InputError):
            revenue.daily_report("sales", run=db)
        assert db.calls == []

    def test_flash_for_today_is_refused_still_being_captured(self):
        db = FakeDB(wb_counts=WB_COUNTS, inv_counts=INV_COUNTS)
        r = revenue.daily_report("flash", day=TODAY.isoformat(), run=db)
        assert r["ok"] is False and "still being captured" in r["reason"]

    def test_flash_for_the_future_is_refused(self):
        db = FakeDB(wb_counts=WB_COUNTS)
        r = revenue.daily_report(
            "flash", day=(TODAY + timedelta(days=2)).isoformat(), run=db
        )
        assert r["ok"] is False and "future" in r["reason"]

    def test_billing_detail_past_the_frontier_is_refused_not_partial(self):
        db = FakeDB(wb_counts=WB_COUNTS, inv_counts=INV_COUNTS)
        r = revenue.daily_report("billing_detail", day=D(1).isoformat(), run=db)
        assert r["ok"] is False
        assert "has not finished" in r["reason"]
        assert r["last_fully_invoiced_day"] == D(3).isoformat()


class TestSharedSqlPassesTheGuard:
    def test_day_counts_sql(self):
        for basis in ("wb", "inv"):
            sql, params = day_counts_sql(basis, date(2026, 3, 1))
            assert_select_only(sql)
            assert params == [date(2026, 3, 1), date(2027, 3, 1)]

    def test_frontier_arithmetic_is_shared_not_rewritten(self):
        # the one-early-invoice scenario, straight on the hoisted function
        from day_guards import frontier_from_day_counts

        per_day = {D(5): (700, 700), D(2): (1, 807)}
        assert frontier_from_day_counts(per_day) == D(4)

    def test_account_validation_enforces_the_case_contract(self):
        with pytest.raises(InputError):
            revenue._validate_account("b35")
        with pytest.raises(InputError):
            revenue._validate_account("TOOLONG7")
        assert revenue._validate_account(" B35 ") == "B35"
