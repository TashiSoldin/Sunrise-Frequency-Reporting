"""The open path's fence (Day 5): allowlist, caps, date flags, honest boundary.

Every test here runs against a fake `run` — no database. The rules pinned:
a hostile statement (UPDATE, a cross-join over the waybill table, a second
statement, a quoted-identifier smuggle) is refused BEFORE Firebird; a hit row
cap refuses rather than truncates; implausible dates are flagged per column;
an empty result says "no matching rows", never reads as a verified zero; and
revenue-territory reads carry the honest-boundary caveat (the R3.49m lesson).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "revenue_reports"))

from day_guards import PP_NULL_DATE, classify_dates, plausible_window

from mcp_server.open_query import (
    ALLOWLIST,
    ROW_CAP,
    check_open_query,
    run_open_query,
    schema_context,
)
from mcp_server.sql_guard import GuardError

TODAY = date(2026, 8, 18)


def fake_run(columns, rows):
    def run(sql, params=(), max_rows=None, timeout=None):
        return columns, rows[:max_rows]

    return run


# --- the gate: what may pass ---------------------------------------------------


class TestAllowlistGate:
    def test_plain_select_on_allowlisted_view(self):
        assert check_open_query("SELECT FIRST 5 WAYBILL FROM VIEW_WBANALYSE") == [
            "VIEW_WBANALYSE"
        ]

    def test_join_finds_both_tables(self):
        tables = check_open_query(
            "SELECT m.MANIFEST, a.REGNO FROM MANIFEST m "
            "JOIN AGENT a ON a.AGENT = m.AGENT"
        )
        assert tables == ["AGENT", "MANIFEST"]

    def test_comma_list_finds_every_table(self):
        tables = check_open_query(
            "SELECT * FROM MANIFEST m, AGENT a, HUB h WHERE a.AGENT = m.AGENT"
        )
        assert tables == ["AGENT", "HUB", "MANIFEST"]

    def test_a_column_sharing_a_denied_tables_name_is_not_a_table(self):
        # AGENT.VEHICLE is a column; VEHICLE is also a (refused) relation.
        # Only table position counts — this query must pass.
        assert check_open_query("SELECT VEHICLE, CAPACITY FROM AGENT") == ["AGENT"]

    def test_cte_name_is_not_checked_as_a_table(self):
        tables = check_open_query(
            "WITH big AS (SELECT ACCNUM FROM CUSTOMER) SELECT * FROM big"
        )
        assert tables == ["CUSTOMER"]

    def test_derived_table_inner_from_is_still_checked(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query("SELECT * FROM (SELECT TRACKNO FROM EVENT) t")


class TestAllowlistRefusals:
    def test_update_is_refused(self):
        with pytest.raises(GuardError, match="only SELECT"):
            check_open_query("UPDATE CUSTOMER SET NAME = 'x'")

    def test_cross_join_over_the_waybill_table_is_refused(self):
        with pytest.raises(GuardError, match="VIEW_WBANALYSE is the sanctioned"):
            check_open_query("SELECT COUNT(*) FROM WAYBILL a, WAYBILL b")

    def test_event_gets_the_separate_quote_message(self):
        with pytest.raises(GuardError, match="separate quote"):
            check_open_query("SELECT COUNT(*) FROM EVENT")

    def test_second_statement_is_refused(self):
        with pytest.raises(GuardError, match="multiple statements"):
            check_open_query("SELECT 1 FROM CUSTOMER; SELECT 2 FROM CUSTOMER")

    def test_quoted_identifier_cannot_smuggle_a_table(self):
        with pytest.raises(GuardError, match="quoted identifiers"):
            check_open_query('SELECT * FROM "EVENT"')

    def test_system_tables_are_refused(self):
        with pytest.raises(GuardError, match="system relation"):
            check_open_query("SELECT * FROM RDB$RELATIONS")

    def test_unknown_table_refusal_names_the_allowlist(self):
        with pytest.raises(GuardError, match="not on the open-path allowlist"):
            check_open_query("SELECT * FROM NO_SUCH_TABLE")

    def test_select_with_no_from_is_refused(self):
        with pytest.raises(GuardError, match="no table"):
            check_open_query("SELECT 1 + 1")


# --- execution: caps and shaping ------------------------------------------------


class TestRunOpenQuery:
    SQL = "SELECT WAYBILL, WAYDATE FROM VIEW_WBANALYSE"

    def test_question_is_required(self):
        out = run_open_query("", self.SQL, run=fake_run(["A"], []))
        assert out["refused"] and "question" in out["reason"]

    def test_guard_refusal_comes_back_as_a_refusal_dict(self):
        out = run_open_query("hostile", "DELETE FROM CUSTOMER", run=fake_run([], []))
        assert out == {
            "ok": False,
            "refused": True,
            "reason": "only SELECT is allowed, got DELETE",
        }

    def test_hitting_the_row_cap_refuses_rather_than_truncates(self):
        rows = [(f"SLJNB{i}", date(2026, 8, 1)) for i in range(ROW_CAP + 1)]
        out = run_open_query("all waybills", self.SQL, run=fake_run(["W", "D"], rows))
        assert out["refused"]
        assert "refusing to truncate" in out["reason"]

    def test_exactly_at_cap_answers(self):
        rows = [(f"SLJNB{i}", date(2026, 8, 1)) for i in range(ROW_CAP)]
        out = run_open_query("many waybills", self.SQL, run=fake_run(["W", "D"], rows))
        assert out["ok"] and out["row_count"] == ROW_CAP

    def test_timeout_is_a_time_cap_refusal(self):
        def slow(sql, params=(), max_rows=None, timeout=None):
            raise TimeoutError("timed out")

        out = run_open_query("slow", self.SQL, run=slow)
        assert out["refused"] and "time cap" in out["reason"]

    def test_firebird_error_is_a_refusal_not_a_crash(self):
        def broken(sql, params=(), max_rows=None, timeout=None):
            raise ValueError("Dynamic SQL Error: column unknown NOPE")

        out = run_open_query("typo", self.SQL, run=broken)
        assert out["refused"] and "Firebird refused" in out["reason"]

    def test_unreachable_database_propagates_as_error_not_answer(self):
        def down(sql, params=(), max_rows=None, timeout=None):
            raise ConnectionError("the Parcel Perfect database is unreachable")

        with pytest.raises(ConnectionError):
            run_open_query("q", self.SQL, run=down)

    def test_empty_result_says_no_matching_rows_not_zero(self):
        out = run_open_query("ghosts", self.SQL, run=fake_run(["W", "D"], []))
        assert out["ok"] and out["row_count"] == 0
        assert any("not a verified zero" in n for n in out["notes"])

    def test_values_are_serialised(self):
        rows = [("SLJNB1  ", date(2026, 8, 1))]
        out = run_open_query("one", self.SQL, run=fake_run(["W", "D"], rows))
        assert out["rows"] == [["SLJNB1", "2026-08-01"]]


class TestDateFlags:
    SQL = "SELECT WAYBILL, DUEDATE FROM VIEW_WBANALYSE"

    def test_placeholder_dates_are_flagged_per_column(self):
        rows = [("A", PP_NULL_DATE), ("B", date(2026, 8, 1)), ("C", PP_NULL_DATE)]
        out = run_open_query(
            "due dates", self.SQL, run=fake_run(["W", "DUEDATE"], rows)
        )
        assert any(
            "DUEDATE" in w and "placeholder" in w and "2 of 3" in w
            for w in out["warnings"]
        )

    def test_future_dates_are_flagged_as_suspect_not_dropped(self):
        rows = [("A", date(9473, 1, 1))]
        out = run_open_query("frontier", self.SQL, run=fake_run(["W", "DUEDATE"], rows))
        assert out["row_count"] == 1  # the row is answered...
        assert any("after today" in w for w in out["warnings"])  # ...and flagged

    def test_plausible_dates_raise_no_flags(self):
        rows = [("A", date(2026, 8, 1))]
        out = run_open_query("clean", self.SQL, run=fake_run(["W", "DUEDATE"], rows))
        assert out["warnings"] == []


class TestHonestBoundary:
    def test_receipt_reads_carry_the_caveat(self):
        out = run_open_query(
            "credits", "SELECT RECNUM FROM RECEIPT", run=fake_run(["R"], [(1,)])
        )
        assert any("HONEST BOUNDARY" in n for n in out["notes"])

    def test_revenue_columns_on_the_waybill_view_carry_the_caveat(self):
        out = run_open_query(
            "sales",
            "SELECT SUM(SUBTOTAL) FROM VIEW_WBANALYSE",
            run=fake_run(["S"], [(1.0,)]),
        )
        assert any("HONEST BOUNDARY" in n for n in out["notes"])

    def test_tracking_reads_of_the_same_view_do_not(self):
        out = run_open_query(
            "hubs",
            "SELECT FIRST 1 ORIGHUB FROM VIEW_WBANALYSE",
            run=fake_run(["H"], [("JNB",)]),
        )
        assert not any("HONEST BOUNDARY" in n for n in out["notes"])


# --- the schema resource ----------------------------------------------------------


class TestSchemaContext:
    def test_every_allowlisted_table_is_served_with_real_columns(self):
        ctx = schema_context()
        assert set(ctx["tables"]) == set(ALLOWLIST)
        for name, info in ctx["tables"].items():
            assert info["columns"], name
            assert info["why_queryable"] == ALLOWLIST[name]

    def test_the_placeholder_caveat_is_stated(self):
        ctx = schema_context()
        assert any("1899-12-30" in line for line in ctx["read_this_first"])

    def test_one_table_lookup(self):
        ctx = schema_context("agent")
        assert list(ctx["tables"]) == ["AGENT"]
        cols = {c["name"] for c in ctx["tables"]["AGENT"]["columns"]}
        assert {"VEHICLE", "REGNO", "CAPACITY"} <= cols  # the 6 Aug fleet finding

    def test_denied_table_lookup_explains_itself(self):
        ctx = schema_context("EVENT")
        assert "separate quote" in ctx["error"]

    def test_view_row_counts_are_none_not_zero(self):
        # The survey could not count views; None must never read as empty.
        ctx = schema_context("VIEW_WBANALYSE")
        assert ctx["tables"]["VIEW_WBANALYSE"]["row_count"] is None


# --- day_guards: the plausible-window half of the hoist ----------------------------


class TestPlausibleWindow:
    def test_window_is_floor_to_today(self):
        lo, hi = plausible_window(TODAY)
        assert lo == date(1990, 1, 1) and hi == TODAY

    def test_classify_counts_each_bucket(self):
        values = [
            PP_NULL_DATE,  # placeholder
            date(1970, 1, 1),  # before floor (but not the placeholder)
            TODAY,  # plausible
            TODAY - timedelta(days=400),  # plausible
            date(9473, 1, 1),  # the year-typo that moved a frontier
            "not a date",  # ignored
            None,  # ignored
        ]
        assert classify_dates(values, TODAY) == {
            "plausible": 2,
            "placeholder": 1,
            "before_floor": 1,
            "future": 1,
        }

    def test_datetimes_are_judged_on_their_date(self):
        from datetime import datetime

        c = classify_dates([datetime(1899, 12, 30, 0, 0)], TODAY)
        assert c["placeholder"] == 1
