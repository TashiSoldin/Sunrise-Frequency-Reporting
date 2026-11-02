"""revenue_summary's trailing window (maintenance, approved 30 Oct 2026).

Before this change the tool aggregated the whole financial year on both
bases on every call — two silent ~60 s GROUP BYs — only to place the billing
frontier and the last trading day, then read a three-year credits pool for
one day's notes: 143 s on 29 Oct 2026 against the client's 180 s limit. The
four changes pinned here, each against the FakeDB (no database):

1. the day counts are read over a trailing window — max(FY start, today -
   60 days) — through day_counts_sql's own statement with only the lower
   bound moved, and widened to the full FY only when the window holds no
   day the guards accept (then a note says so);
2. the invoice-date counts are not read at all when a day is given — they
   only pick the default billed day;
3. the day's credit notes are read for that day alone, through the verified
   RECEIPT query without its two LIST() link subqueries, and come out
   identical to the pool route;
4. the frontier and last trading day are kept in process for 15 minutes.

The guards in revenue_reports/day_guards.py stay the source of truth: the
window never re-derives what counts as a traded or completed day, it asks
them (frontier_from_day_counts(presence_fallback=False),
is_completed_trading_day), and the equality test below is against the same
guards run over the full year.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "revenue_reports"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from day_guards import (
    NoCompletedDays,
    NoInvoicedDays,
    frontier_from_day_counts,
    last_trading_day,
)
from extract_revenue import CREDITS_SQL, day_counts_sql, fy_end, fy_start
from test_revenue_tools import (
    CREDIT_COLS,
    TODAY,
    D,
    FakeDB,
    credit_row,
    wb_row,
)

from mcp_server import revenue
from mcp_server.sql_guard import assert_select_only

FY0 = fy_start(TODAY)  # 2026-03-01
WINDOW_START = TODAY - timedelta(days=revenue.DAY_COUNTS_WINDOW_DAYS)  # 2026-06-18
assert WINDOW_START > FY0, "the fixtures assume a window strictly inside the FY"


@pytest.fixture(autouse=True)
def _pin_today(monkeypatch):
    monkeypatch.setattr(revenue, "_today", lambda: TODAY)
    revenue.clear_guard_cache()
    yield
    revenue.clear_guard_cache()


class WindowDB(FakeDB):
    """FakeDB that honours the BOUND PARAMETERS of the day-count and credits
    statements — the base fake returns every fixture row regardless, which
    is exactly what the window pins must not be allowed to hide behind."""

    def __call__(self, sql, params=(), max_rows=1000):
        if "GROUP BY" in sql:
            assert_select_only(sql)
            self.calls.append((sql, params, max_rows))
            counts = self.wb_counts if "wba.WAYDATE" in sql else self.inv_counts
            lo, hi = params
            return ["DAY_D", "N_WAYBILLS", "SUBTOTAL_SUM", "N_INVOICED"], [
                c for c in counts if lo <= c[0] < hi
            ]
        if "FROM RECEIPT r" in sql:
            assert_select_only(sql)
            self.calls.append((sql, params, max_rows))
            di = CREDIT_COLS.index("RECDATE")
            lo = params[0]
            hi = params[1] if len(params) > 1 else date.max
            return CREDIT_COLS, [r for r in self.credit_rows if lo <= r[di] < hi]
        return super().__call__(sql, params, max_rows)


def count_calls(db, basis):
    col = {"wb": "wba.WAYDATE", "inv": "wba.INVDATE"}[basis]
    return [(sql, p) for sql, p, _ in db.calls if "GROUP BY" in sql and col in sql]


def credits_calls(db):
    return [(sql, p) for sql, p, _ in db.calls if "FROM RECEIPT r" in sql]


def full_day(d, inv=True):
    return (d, 700, 70000.0, 700 if inv else 0)


# A year of history: every day from the FY start to D(3) fully invoiced,
# D(2) and D(1) shipped but not yet invoiced. The window (D(60)..) and the
# year both hold completed days, so the two must agree.
YEAR_WB = [full_day(FY0 + timedelta(days=i)) for i in range((D(3) - FY0).days + 1)] + [
    (D(2), 700, 70000.0, 0),
    (D(1), 650, 65000.0, 0),
]
YEAR_INV = [full_day(FY0 + timedelta(days=i)) for i in range((D(3) - FY0).days + 1)]


def year_db(**kw):
    return WindowDB(
        rows=[wb_row(WAYDATE=D(3), INVDATE=D(3))],
        wb_counts=YEAR_WB,
        inv_counts=YEAR_INV,
        **kw,
    )


# --- 1. the trailing window ---------------------------------------------------


class TestTrailingWindow:
    def test_day_counts_are_read_from_the_window_start_to_the_fy_end(self):
        db = year_db()
        r = revenue.revenue_summary(run=db)
        assert r["ok"] is True
        ((sql, params),) = count_calls(db, "wb")
        assert params == (WINDOW_START, fy_end(FY0))
        # day_counts_sql's own statement, not a rewrite of it
        assert sql == day_counts_sql("wb", FY0)[0]

    def test_the_window_never_starts_before_the_fy(self, monkeypatch):
        young = date(2026, 3, 20)  # the FY is 19 days old: window == FY
        monkeypatch.setattr(revenue, "_today", lambda: young)
        counts = [full_day(date(2026, 3, 1) + timedelta(days=i)) for i in range(17)]
        db = WindowDB(
            rows=[wb_row(WAYDATE=date(2026, 3, 17), INVDATE=date(2026, 3, 17))],
            wb_counts=counts,
            inv_counts=counts,
        )
        revenue.revenue_summary(run=db)
        ((_, params),) = count_calls(db, "wb")
        assert params[0] == date(2026, 3, 1) == fy_start(young)

    def test_day_counts_refuses_a_start_before_the_fy(self):
        with pytest.raises(ValueError, match="before the FY start"):
            revenue.day_counts("wb", run=year_db(), start=FY0 - timedelta(days=1))

    def test_windowed_frontier_and_trading_day_equal_the_full_year(self):
        """The property the window rests on: with a completed day inside it,
        the newest completed day in the window IS the newest in the year."""
        db = year_db()
        r = revenue.revenue_summary(run=db)
        full_frontier = frontier_from_day_counts(
            {d: (inv, n) for d, n, _, inv in YEAR_WB}, TODAY
        )
        full_wb_day = last_trading_day([(d, s) for d, _, s, _ in YEAR_WB], TODAY)
        full_inv_day = last_trading_day([(d, s) for d, _, s, _ in YEAR_INV], TODAY)
        assert r["billing_frontier"] == full_frontier.isoformat() == D(2).isoformat()
        assert r["shipped"]["day"] == full_wb_day.isoformat() == D(1).isoformat()
        assert r["billed"]["day"] == full_inv_day.isoformat() == D(3).isoformat()
        # and it got there from the window alone — one read per basis
        assert len(count_calls(db, "wb")) == 1
        assert len(count_calls(db, "inv")) == 1
        assert not any("full financial year" in n for n in r["notes"])


class TestFallbackToTheFullYear:
    def test_no_completed_day_in_the_window_widens_the_frontier_read(self):
        # Invoicing stopped two months ago: the window ships but nothing in
        # it is invoiced, so the frontier cannot be judged from it.
        wb = [full_day(D(n)) for n in range(61, 120)] + [
            full_day(D(n), inv=False) for n in range(1, 30)
        ]
        inv = [full_day(D(n)) for n in range(61, 120)]
        db = WindowDB(
            rows=[wb_row(WAYDATE=D(1), INVDATE=None, STATUS="Ready for Approval")],
            wb_counts=wb,
            inv_counts=inv,
        )
        r = revenue.revenue_summary(run=db)
        assert r["ok"] is True
        full_frontier = frontier_from_day_counts(
            {d: (i, n) for d, n, _, i in wb}, TODAY
        )
        assert r["billing_frontier"] == full_frontier.isoformat() == D(60).isoformat()
        calls = count_calls(db, "wb")
        assert [p[0] for _, p in calls] == [WINDOW_START, FY0], (
            "the window first, then the whole FY"
        )
        assert any(
            n.startswith(
                "the waybill-date day counts for the last 60 days held no invoiced day"
            )
            and "billing frontier" in n
            and "full financial year" in n
            for n in r["notes"]
        ), r["notes"]

    def test_no_traded_day_in_the_window_widens_the_billed_read(self):
        # No invoice run for two months: the invoice-date window is EMPTY, so
        # the billed default day is judged over the year (and says so).
        wb = [full_day(D(n)) for n in range(1, 120)]
        inv = [full_day(D(n)) for n in range(61, 120)]
        db = WindowDB(
            rows=[wb_row(WAYDATE=D(1), INVDATE=D(61))], wb_counts=wb, inv_counts=inv
        )
        r = revenue.revenue_summary(run=db)
        assert r["billed"]["day"] == D(61).isoformat()
        assert [p[0] for _, p in count_calls(db, "inv")] == [WINDOW_START, FY0]
        assert len(count_calls(db, "wb")) == 1, "the waybill window answered"
        assert any(
            n.startswith(
                "the invoice-date day counts for the last 60 days held "
                "no completed trading day"
            )
            and "billed last trading day" in n
            for n in r["notes"]
        ), r["notes"]

    def test_a_window_that_is_the_whole_fy_is_never_re_read(self, monkeypatch):
        young = date(2026, 3, 20)
        monkeypatch.setattr(revenue, "_today", lambda: young)
        # nothing invoiced at all in the young FY: NoInvoicedDays either way
        counts = [
            (date(2026, 3, 1) + timedelta(days=i), 700, 70000.0, 0) for i in range(17)
        ]
        db = WindowDB(rows=[], wb_counts=counts, inv_counts=counts)
        with pytest.raises(Exception, match="No invoiced waybills"):
            revenue.revenue_summary(run=db)
        assert len(count_calls(db, "wb")) == 1

    def test_a_window_of_dead_days_is_widened_for_the_frontier(self):
        # The window holds only near-empty days: the trading guard accepts
        # them (they clear their own median), the frontier rule does not
        # (3 waybills a day is too small to judge, MIN_WAYBILLS) -> one
        # basis-wide widening, and both dates come out as the full year's.
        wb = [full_day(D(n)) for n in range(61, 120)] + [
            (D(n), 3, 150.0, 3) for n in range(1, 8)
        ]
        inv = [full_day(D(n)) for n in range(61, 120)]
        db = WindowDB(
            rows=[wb_row(WAYDATE=D(1), INVDATE=D(1))], wb_counts=wb, inv_counts=inv
        )
        r = revenue.revenue_summary(run=db)
        assert [p[0] for _, p in count_calls(db, "wb")] == [WINDOW_START, FY0]
        full_frontier = frontier_from_day_counts(
            {d: (i, n) for d, n, _, i in wb}, TODAY
        )
        full_wb_day = last_trading_day([(d, s) for d, _, s, _ in wb], TODAY)
        assert r["billing_frontier"] == full_frontier.isoformat()
        assert r["shipped"]["day"] == full_wb_day.isoformat() == D(1).isoformat()
        # the note names the guard that triggered — the frontier, not trading
        (note,) = [n for n in r["notes"] if n.startswith("the waybill-date")]
        assert note.startswith(
            "the waybill-date day counts for the last 60 days held "
            "no day with invoicing complete, so"
        ), note
        assert "trading day" not in note.split(", so")[0]


class TestGuardOptOut:
    """day_guards.frontier_from_day_counts(presence_fallback=False): the one
    change to the guard module — the rule is untouched, the fallback can be
    declined."""

    def test_a_completed_day_answers_the_same_either_way(self):
        per_day = {D(5): (700, 700), D(4): (10, 700), D(3): (0, 700)}
        assert frontier_from_day_counts(per_day, TODAY) == D(4)
        assert frontier_from_day_counts(per_day, TODAY, presence_fallback=False) == D(4)

    def test_presence_only_counts_raise_when_the_fallback_is_declined(self):
        per_day = {D(5): (3, 10), D(4): (0, 12)}  # too small to judge
        assert frontier_from_day_counts(per_day, TODAY) == D(4), "the old rule"
        with pytest.raises(NoCompletedDays):
            frontier_from_day_counts(per_day, TODAY, presence_fallback=False)

    def test_nothing_invoiced_raises_no_invoiced_days_either_way(self):
        # the two refusals stay distinct, so the widening note can name the
        # trigger: nothing invoiced at all is NoInvoicedDays, declined
        # fallback or not; NoCompletedDays is for invoiced-but-not-complete
        per_day = {D(5): (0, 700), D(4): (0, 700)}
        with pytest.raises(NoInvoicedDays):
            frontier_from_day_counts(per_day, TODAY)
        with pytest.raises(NoInvoicedDays):
            frontier_from_day_counts(per_day, TODAY, presence_fallback=False)


# --- 2. the invoice-date counts are skipped when a day is given ---------------


class TestSkipInvoiceCountsForAGivenDay:
    def test_a_given_day_reads_only_the_waybill_counts(self):
        db = year_db()
        r = revenue.revenue_summary(D(3).isoformat(), run=db)
        assert r["ok"] is True
        assert len(count_calls(db, "wb")) == 1
        assert count_calls(db, "inv") == []
        assert r["billed"]["day"] == D(3).isoformat()

    def test_no_day_reads_both_bases_once(self):
        db = year_db()
        revenue.revenue_summary(run=db)
        assert len(count_calls(db, "wb")) == 1
        assert len(count_calls(db, "inv")) == 1

    def test_refusals_happen_before_any_read(self):
        db = year_db()
        r = revenue.revenue_summary((TODAY + timedelta(days=1)).isoformat(), run=db)
        assert r["ok"] is False and "future" in r["reason"]
        r = revenue.revenue_summary((FY0 - timedelta(days=1)).isoformat(), run=db)
        assert r["ok"] is False and "before" in r["reason"]
        assert db.calls == []

    def test_the_frontier_warning_still_comes_from_the_waybill_counts(self):
        db = year_db()
        r = revenue.revenue_summary(D(1).isoformat(), run=db)
        assert any("has not finished" in w for w in r["warnings"])
        assert r["billing_frontier"] == D(2).isoformat()


# --- 3. credit notes read for the day alone -----------------------------------

CREDITS = [
    credit_row(RECEIPT=-1, RECDATE=D(3), AMOUNT=115.0, VAT=15.0),  # 100.00
    credit_row(RECEIPT=-2, RECDATE=D(3), AMOUNT=230.0, VAT=30.0),  # 200.00
    credit_row(RECEIPT=-3, RECDATE=D(3), AMOUNT=1150.0, VAT=150.0, RECTYPE="J"),
    credit_row(
        RECEIPT=-4, RECDATE=D(3), AMOUNT=575.0, VAT=75.0, RECTYPE="B"
    ),  # Bad Debt
    credit_row(RECEIPT=-5, RECDATE=D(4), AMOUNT=115.0, VAT=15.0),  # the day before
    credit_row(RECEIPT=-6, RECDATE=D(2), AMOUNT=115.0, VAT=15.0),  # the day after
]


class TestCreditNotesForTheDay:
    def test_the_direct_read_matches_the_pool_route(self):
        db = WindowDB(credit_rows=CREDITS)
        direct = revenue.credit_notes_direct(D(3), D(3), run=db)
        pooled = revenue._credit_notes_between(D(3), D(3), run=db)
        key = lambda n: n["receipt"]
        assert sorted(direct, key=key) == sorted(pooled, key=key)
        assert [n["receipt"] for n in sorted(direct, key=key)] == [-3, -2, -1]
        assert round(sum(n["value"] for n in direct), 2) == 1300.00

    def test_the_statement_is_bounded_to_the_day_and_carries_no_list(self):
        db = WindowDB(credit_rows=CREDITS)
        revenue.credit_notes_direct(D(3), D(3), run=db)
        ((sql, params),) = credits_calls(db)
        assert params == (D(3), D(2)), "RECDATE >= day AND RECDATE < day + 1"
        assert "LIST(" not in sql and "RECALLOC" not in sql
        assert "WHERE r.RECDATE >= ? AND r.RECDATE < ?" in sql
        assert "AND r.RECEIPT < 0" in sql, "credits are the negative receipts"

    def test_the_statement_is_the_verified_query_minus_the_links(self):
        # every column and join of CREDITS_SQL survives except the two
        # RECALLOC link aggregates
        keep = [
            line.strip()
            for line in CREDITS_SQL.splitlines()
            if line.strip()
            and "LIST(" not in line
            and "RECALLOC" not in line
            and "ra.RECEIPT = r.RECEIPT" not in line
            and "LEFT JOIN WAYBILL wb" not in line
            and "RECDATE" not in line
        ]
        for line in keep:
            assert line.rstrip(",") in revenue.CREDITS_WINDOW_SQL, line
        assert "WAYBILLS" not in revenue.CREDITS_WINDOW_SQL
        assert "INVOICES" not in revenue.CREDITS_WINDOW_SQL

    def test_a_moved_landmark_in_credits_sql_fails_at_derivation(self):
        with pytest.raises(AssertionError, match="landmark"):
            revenue._derive_credits_window_sql(
                CREDITS_SQL.replace("LIST(ra.WAYBILL", "LIST(x")
            )

    def test_revenue_summary_takes_its_notes_from_the_direct_read(self):
        db = year_db(credit_rows=CREDITS)
        r = revenue.revenue_summary(run=db)
        assert r["billed"]["day"] == D(3).isoformat()
        assert r["billed"]["credit_notes"] == {"count": 3, "total": 1300.0}
        assert r["billed"]["net_revenue"] == round(
            r["billed"]["gross_revenue"] - 1300.0, 2
        )
        ((_, params),) = credits_calls(db)
        assert params == (D(3), D(2))


# --- 4. the quarter-hour cache ------------------------------------------------


class TestGuardCache:
    def test_a_second_call_within_the_ttl_reads_no_day_counts(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(revenue, "_clock", lambda: clock[0])
        db = year_db()
        first = revenue.revenue_summary(run=db)
        n_wb, n_inv = len(count_calls(db, "wb")), len(count_calls(db, "inv"))
        assert (n_wb, n_inv) == (1, 1)
        clock[0] += 5 * 60
        second = revenue.revenue_summary(run=db)
        assert (len(count_calls(db, "wb")), len(count_calls(db, "inv"))) == (1, 1)
        assert second["billing_frontier"] == first["billing_frontier"]
        assert second["shipped"]["day"] == first["shipped"]["day"]
        assert second["billed"]["day"] == first["billed"]["day"]
        assert any("re-used from a read 5 min ago" in n for n in second["notes"])
        assert not any("re-used" in n for n in first["notes"])

    def test_the_cache_expires_after_the_ttl(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(revenue, "_clock", lambda: clock[0])
        db = year_db()
        revenue.revenue_summary(run=db)
        clock[0] += revenue.GUARD_CACHE_TTL_S - 1
        revenue.revenue_summary(run=db)
        assert len(count_calls(db, "wb")) == 1, "still inside the quarter-hour"
        clock[0] += 2
        r = revenue.revenue_summary(run=db)
        assert len(count_calls(db, "wb")) == 2, "expired: read again"
        assert len(count_calls(db, "inv")) == 2
        assert not any("re-used" in n for n in r["notes"])

    def test_the_cache_keeps_the_widening_note(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(revenue, "_clock", lambda: clock[0])
        wb = [full_day(D(n)) for n in range(61, 120)] + [
            full_day(D(n), inv=False) for n in range(1, 30)
        ]
        db = WindowDB(
            rows=[wb_row(WAYDATE=D(1), INVDATE=None, STATUS="Ready for Approval")],
            wb_counts=wb,
            inv_counts=[full_day(D(n)) for n in range(61, 120)],
        )
        revenue.revenue_summary(D(1).isoformat(), run=db)
        clock[0] += 60
        r = revenue.revenue_summary(D(1).isoformat(), run=db)
        assert any("full financial year" in n for n in r["notes"])
        assert any("re-used from a read 1 min ago" in n for n in r["notes"])

    def test_the_cache_is_per_data_source_and_per_day(self, monkeypatch):
        db1 = year_db()
        revenue.revenue_summary(run=db1)
        # another source: its own read, never db1's dates
        wb = [full_day(D(n)) for n in range(5, 120)]
        db2 = WindowDB(
            rows=[wb_row(WAYDATE=D(5), INVDATE=D(5))], wb_counts=wb, inv_counts=wb
        )
        r2 = revenue.revenue_summary(run=db2)
        assert len(count_calls(db2, "wb")) == 1
        assert r2["shipped"]["day"] == D(5).isoformat()
        # another "today": the key moves with the date
        monkeypatch.setattr(revenue, "_today", lambda: TODAY + timedelta(days=1))
        revenue.revenue_summary(run=db1)
        assert len(count_calls(db1, "wb")) == 2

    def test_clear_guard_cache_forces_a_fresh_read(self):
        db = year_db()
        revenue.revenue_summary(run=db)
        revenue.clear_guard_cache()
        revenue.revenue_summary(run=db)
        assert len(count_calls(db, "wb")) == 2
