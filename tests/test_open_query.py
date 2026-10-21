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
    DENIED,
    DENIED_COLUMNS,
    ROW_CAP,
    check_open_query,
    run_open_query,
    schema_context,
)
from mcp_server.sql_guard import GuardError

NEW_TABLES = [
    "RATE",
    "MASSRATE",
    "ITEMRATE",
    "RATENUM",
    "SURCHRATE",
    "SURCHNUM",
    "AGRATE",
    "AGRATENUM",
    "NOTE",
    "COLLECT",
]

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
            "SELECT m.MANIFEST FROM MANIFEST m, AGENT a, HUB h WHERE a.AGENT = m.AGENT"
        )
        assert tables == ["AGENT", "HUB", "MANIFEST"]

    def test_a_column_sharing_a_denied_tables_name_is_not_a_table(self):
        # AGENT.VEHICLE is a column; VEHICLE is also a (refused) relation.
        # Only table position counts — this query must pass.
        assert check_open_query("SELECT VEHICLE, CAPACITY FROM AGENT") == ["AGENT"]

    def test_cte_name_is_not_checked_as_a_table(self):
        tables = check_open_query(
            "WITH big AS (SELECT ACCNUM FROM CUSTOMER) SELECT ACCNUM FROM big"
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

    def test_selectable_procedure_in_from_is_refused(self):
        # Firebird selectable stored procedures are queried like a table:
        # SELECT ... FROM SOME_PROC(args). The FROM target is a procedure,
        # not a base relation, and a proc body can carry side effects the SQL
        # text never shows. The positive allowlist refuses it because no proc
        # name is on the list — pin that so it stays refused.
        with pytest.raises(GuardError, match="not on the open-path allowlist"):
            check_open_query("SELECT * FROM SOME_PROC(1, 2)")
        with pytest.raises(GuardError, match="not on the open-path allowlist"):
            check_open_query("SELECT * FROM SOME_PROC")

    def test_paren_after_a_table_name_cannot_hide_a_denied_table(self):
        # A '(' immediately after a table-position name used to be skipped whole
        # as "selectable procedure args" — which swallowed a subquery's inner
        # FROM. SELECT * FROM CUSTOMER(SELECT 1 FROM EVENT) then passed the
        # gate reading only CUSTOMER, with EVENT never checked: the fence must
        # refuse before Firebird, not lean on Firebird to reject the syntax.
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query("SELECT * FROM CUSTOMER(SELECT 1 FROM EVENT)")
        with pytest.raises(GuardError, match="WAYBILL"):
            check_open_query("SELECT X FROM AGENT(SELECT 1 FROM WAYBILL) t")

    def test_paren_hidden_denied_table_nested_two_deep(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT * FROM CUSTOMER(SELECT 1 FROM AGENT(SELECT 1 FROM EVENT))"
            )


# --- QT-000007 line 2: the column deny list ------------------------------------


class TestDeniedColumnsShape:
    def test_every_allowlisted_table_has_an_entry_even_if_empty(self):
        # "not covered" must never read as "nothing sensitive".
        assert set(DENIED_COLUMNS) == set(ALLOWLIST)

    def test_the_coda_name_matched_floor_is_in(self):
        # The starting list from the QT-000007 page, minus the edge cases
        # decided from live values (flags and RECEIPT.BANK — see the dict).
        floor = {
            "CUSTOMER": {
                "PHONE",
                "CELL",
                "FAX",
                "EMAIL",
                "EMAILSMS",
                "ICPASS",
                "BANK",
                "BANKACCNO",
            },
            "CONTACT": {"CELL", "PHONE", "EMAIL", "WEBPASSWORD", "RECOVERYEMAIL"},
            "AGENT": {"ACCNO", "PHONE", "FAX", "CELL", "EMAIL", "ICPASS"},
            "COLLECT": {"PHONE", "PHONE2", "CELL", "BOOKINGEMAIL"},
            "INVOICE": {"INVPHONE", "INVPHONE2", "INVCELL"},
            "VIEW_CUSTOMERS": {"PHONE", "AFTERHOURSPHONE", "CELL", "FAX", "EMAIL"},
            "VIEW_USERCODE": {"CELL", "EMAIL"},
            "VIEW_WBANALYSE": {"ORIGPERPHONE", "DESTPERPHONE"},
            "BRANCH": {"EMAIL"},
        }
        for table, cols in floor.items():
            assert cols <= DENIED_COLUMNS[table], table

    def test_beyond_the_name_match(self):
        # Read, not regexed: after-hours numbers, the IC login, the invoice PDFs.
        assert {"AFTHOURSNO", "ICUSER"} <= DENIED_COLUMNS["CUSTOMER"]
        assert "AFTERHOURS" in DENIED_COLUMNS["AGENT"]
        assert {"PDFCOPY", "PDFORIG", "INVHASH"} <= DENIED_COLUMNS["INVOICE"]
        # Fable re-review N1: the HASH|KEY|SECRET|TOKEN sweep — only these
        # three across the 30 tables, all withheld.
        assert {"HASHED", "SECRETKEY"} <= DENIED_COLUMNS["CONTACT"]
        with pytest.raises(GuardError, match="INVHASH"):
            check_open_query("SELECT INVHASH FROM INVOICE")
        assert {"SECRETKEY", "HASHED", "MFA"} <= DENIED_COLUMNS["CONTACT"]

    def test_branch_infrastructure_columns_are_withheld(self):
        # Fable review F2 (20 Oct 2026): internal IPs, DB file paths, the
        # replication server and the RTM path are infrastructure detail.
        assert {"IP", "DBPATH", "RDBSERVER", "RTMPATH"} <= DENIED_COLUMNS["BRANCH"]
        with pytest.raises(GuardError, match="DBPATH"):
            check_open_query("SELECT IP, DBPATH, RDBSERVER, RTMPATH FROM BRANCH")
        # the scan for IP|PATH|SERVER|HOST|PORT|URL|DSN|CONNECT found nothing
        # else that is infrastructure: EXPORT/REPORT/IMPORTERNUM are flags
        # and customs numbers and stay.
        assert check_open_query("SELECT EXPORT FROM INVOICE") == ["INVOICE"]
        assert check_open_query("SELECT IMPORTERNUM FROM CUSTOMER") == ["CUSTOMER"]

    def test_the_decided_edge_cases(self):
        # Flags are not addresses; RECEIPT.BANK is a bank code on Sunrise's
        # own receipts, not a customer's banking detail.
        assert (
            not {"EMAILINVIMAGE", "PODFAX", "PODSINGLEFAX", "PODEMAIL"}
            & DENIED_COLUMNS["CUSTOMER"]
        )
        assert "BANK" not in DENIED_COLUMNS["RECEIPT"]
        assert DENIED_COLUMNS["RATE"] == frozenset()

    def test_every_denied_column_exists_in_the_survey(self):
        ctx_cols = {
            t: {c["name"] for c in info["columns"]}
            for t, info in schema_context_raw()["tables"].items()
        }
        for table, cols in DENIED_COLUMNS.items():
            missing = cols - ctx_cols[table]
            assert not missing, (table, missing)


def schema_context_raw():
    from mcp_server.open_query import _schema_data

    return _schema_data()


class TestDeniedColumnsGate:
    """(a) a denied name as an identifier anywhere refuses — the oracle rule."""

    def test_select_list_refuses_and_names_the_column(self):
        with pytest.raises(GuardError, match="BANKACCNO \\(withheld on CUSTOMER\\)"):
            check_open_query("SELECT CUSTNAME, BANKACCNO FROM CUSTOMER")

    def test_where_on_a_password_is_an_oracle_and_refuses(self):
        with pytest.raises(GuardError, match="WEBPASSWORD"):
            check_open_query(
                "SELECT CUSTNAME FROM CUSTOMER c JOIN CONTACT k ON k.ACCNUM = c.ACCNUM "
                "WHERE k.WEBPASSWORD LIKE 'a%'"
            )
        with pytest.raises(GuardError, match="WEBPASSWORD"):
            check_open_query("SELECT NAME FROM CONTACT WHERE WEBPASSWORD LIKE 'a%'")

    def test_order_by_group_by_having_alias_and_expression_refuse(self):
        for sql in (
            "SELECT NAME FROM CONTACT ORDER BY EMAIL",
            "SELECT COUNT(*) FROM CONTACT GROUP BY CELL",
            "SELECT ACCNUM FROM CONTACT GROUP BY ACCNUM HAVING MAX(PHONE) > '0'",
            "SELECT UPPER(EMAIL) AS E FROM CONTACT",
            "SELECT NAME AS EMAIL FROM CONTACT",
            "SELECT SUBSTRING(k.WEBPASSWORD FROM 1 FOR 1) FROM CONTACT k",
            (
                "SELECT NAME FROM CONTACT WHERE ACCNUM IN "
                "(SELECT ACCNUM FROM CUSTOMER WHERE BANKACCNO IS NOT NULL)"
            ),
            "SELECT X FROM (SELECT EMAIL AS X FROM CONTACT) t",
            "WITH c AS (SELECT CELL FROM CONTACT) SELECT * FROM c",
            (
                "SELECT NAME FROM CONTACT WHERE EXISTS "
                "(SELECT 1 FROM CUSTOMER WHERE CUSTOMER.PHONE = CONTACT.NAME)"
            ),
        ):
            with pytest.raises(GuardError, match="withheld"):
                check_open_query(sql)

    def test_case_and_whitespace_do_not_dodge_it(self):
        with pytest.raises(GuardError, match="EMAIL"):
            check_open_query("select   name\nfrom contact where email like 'a%'")

    def test_the_message_says_why(self):
        with pytest.raises(GuardError, match="refused, not just hidden"):
            check_open_query("SELECT EMAIL FROM CONTACT")

    def test_a_denied_name_in_a_string_literal_does_not_refuse(self):
        # The guard strips literals: 'WEBPASSWORD' here is data, not a column.
        assert check_open_query(
            "SELECT NAME FROM CONTACT WHERE NAME = 'WEBPASSWORD' OR NAME = 'EMAIL'"
        ) == ["CONTACT"]
        assert check_open_query(
            "SELECT NAME FROM CONTACT -- EMAIL\n WHERE NAME = 'x' /* PHONE */"
        ) == ["CONTACT"]

    def test_a_denied_name_on_an_unreferenced_table_is_not_in_play(self):
        # MANIFEST.NOTE is a column; NOTE is also a table — neither is denied.
        # And EMAIL is denied on CONTACT, but a query that never references
        # CONTACT is not checked against CONTACT's list.
        assert check_open_query("SELECT NOTE FROM MANIFEST") == ["MANIFEST"]
        assert check_open_query("SELECT RATE, ACCNUM FROM RATE") == ["RATE"]

    def test_over_refusal_on_a_coincidental_name_is_reported_not_silent(self):
        # RECEIPT.BANK is allowed; CUSTOMER.BANK is not. A query that joins
        # both and names BANK is refused — by name across the statement — and
        # the message says exactly that, naming the table that carries the
        # allowed same-named column.
        with pytest.raises(GuardError) as e:
            check_open_query(
                "SELECT r.BANK, COUNT(*) FROM RECEIPT r "
                "JOIN CUSTOMER c ON c.ACCNUM = r.ACCNUM GROUP BY r.BANK"
            )
        msg = str(e.value)
        assert "BANK (withheld on CUSTOMER)" in msg
        assert "same-named column on RECEIPT" in msg
        assert "matched by name" in msg
        # ...and on its own, RECEIPT.BANK answers.
        assert check_open_query("SELECT BANK, COUNT(*) FROM RECEIPT GROUP BY BANK") == [
            "RECEIPT"
        ]

    def test_the_refusal_reason_carries_no_data(self):
        out = run_open_query(
            "who",
            "SELECT NAME FROM CONTACT WHERE WEBPASSWORD = 'hunter2'",
            run=fake_run([], []),
        )
        assert out["refused"]
        assert "hunter2" not in out["reason"]
        assert "WEBPASSWORD" in out["reason"]


def never_runs(sql, params=(), max_rows=None, timeout=None):
    raise AssertionError(f"the statement reached the database: {sql}")


class TestStarProjectionRefused:
    """Fable review F1 (BLOCKER, 20 Oct 2026): name-based projection was
    defeated by SELECT * under a derived-table column alias list, or a UNION
    taking its names from a WHERE 1=0 first branch — every withheld value
    came back under a different header, with no note. The fix removes the
    path: when ANY referenced table carries withheld columns, a projection
    star anywhere in the statement is refused before Firebird. Tests assert
    on the SOURCE column (the statement), never on the output name."""

    # The review's two bypasses, as close to verbatim as the identifier gate
    # allows (the UNION's first branch must not NAME a denied column, so it
    # repeats a served one under 18 aliases — exactly what an attacker does).
    BYPASS_A = (
        "SELECT * FROM (SELECT * FROM CONTACT) t "
        "(A1,A2,A3,A4,A5,A6,A7,A8,A9,A10,A11,A12,A13,A14,A15,A16,A17,A18)"
    )
    BYPASS_B = (
        "SELECT "
        + ", ".join(f"ACCNUM AS A{i}" for i in range(1, 19))
        + " FROM CONTACT WHERE 1=0 UNION ALL SELECT * FROM CONTACT"
    )

    @pytest.mark.parametrize(
        "sql",
        [
            BYPASS_A,
            BYPASS_B,
            "SELECT t.* FROM (SELECT * FROM CONTACT) t",
            "WITH c AS (SELECT * FROM CONTACT) SELECT ACCNUM FROM c",
            "SELECT * FROM HOLIDAY, CUSTOMER",  # CUSTOMER is in the statement
            "SELECT * FROM CUSTOMER",
            "SELECT c.* FROM CONTACT c",
            "SELECT FIRST 5 * FROM CUSTOMER",
            "SELECT FIRST (5) * FROM CUSTOMER",  # Firebird's parenthesised form
            "SELECT DISTINCT * FROM CONTACT",
            "SELECT c.*, 1 FROM CUSTOMER c",
            "SELECT CUSTNAME, * FROM CUSTOMER",
            "SELECT h.* FROM HOLIDAY h JOIN CUSTOMER c ON c.SALEDATE = h.HOLIDAY",
            "SELECT ACCNUM FROM CUSTOMER WHERE ACCNUM IN (SELECT * FROM CONTACT)",
            "SELECT (SELECT * FROM CONTACT) FROM HOLIDAY",
        ],
    )
    def test_a_star_is_refused_when_a_withheld_table_is_in_the_statement(self, sql):
        with pytest.raises(GuardError, match=r"SELECT \*") as e:
            check_open_query(sql)
        msg = str(e.value)
        assert "describe_schema" in msg
        assert "CONTACT" in msg or "CUSTOMER" in msg

    def test_the_message_says_to_write_select_1_in_exists_and_in(self):
        # Fable re-review N2: EXISTS (SELECT * FROM <withheld>) is refused
        # (conservative — the star projects nothing there); the message says
        # how to write it instead.
        with pytest.raises(
            GuardError, match=r"EXISTS and IN subqueries write SELECT 1"
        ):
            check_open_query(
                "SELECT ACCNUM FROM CUSTOMER c WHERE EXISTS "
                "(SELECT * FROM CONTACT k WHERE k.ACCNUM = c.ACCNUM)"
            )

    def test_the_message_names_only_the_tables_that_carry_withheld_columns(self):
        with pytest.raises(GuardError) as e:
            check_open_query("SELECT * FROM HOLIDAY, CUSTOMER")
        assert "CUSTOMER" in str(e.value)
        assert "HOLIDAY" not in str(e.value).split("describe_schema")[0]

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM HOLIDAY",  # empty deny set keeps its star
            "SELECT h.* FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB",
            "SELECT FIRST 5 * FROM RATE",
            "SELECT COUNT(*) FROM CUSTOMER",  # projects nothing
            "SELECT COUNT(*), MAX(CREDITLIMIT) FROM CUSTOMER",
            "SELECT COUNT( * ) FROM CONTACT",
            "SELECT CREDITLIMIT * 2 FROM CUSTOMER",  # multiplication
            "SELECT (CREDITLIMIT) * (2) FROM CUSTOMER",
            "SELECT ACCNUM FROM CUSTOMER WHERE CREDITLIMIT * 1.15 > SPEND",
            "SELECT ACCNUM FROM CUSTOMER c WHERE EXISTS (SELECT 1 FROM CONTACT k WHERE k.ACCNUM = c.ACCNUM)",
        ],
    )
    def test_count_star_multiplication_and_clean_tables_still_pass(self, sql):
        assert check_open_query(sql)

    def test_the_bypass_never_reaches_the_database_whatever_the_cursor_says(self):
        # A fake cursor whose names differ from the true source columns —
        # the review's live shape. The guard must refuse before run() is
        # called; the cursor names are irrelevant to the decision.
        out = run_open_query("names", self.BYPASS_A, run=never_runs)
        assert out["refused"] and "SELECT *" in out["reason"]
        out = run_open_query("names", self.BYPASS_B, run=never_runs)
        assert out["refused"] and "SELECT *" in out["reason"]

    def test_the_rule_is_what_refuses(self, monkeypatch):
        # Fable F3: the suite must not stay green with the rule switched off.
        # Empty CONTACT's deny set and the same statements pass the gate —
        # so a green suite proves the deny set, not a coincidence of shape.
        import mcp_server.open_query as oq

        with pytest.raises(GuardError):
            check_open_query("SELECT * FROM CONTACT")
        with pytest.raises(GuardError):
            check_open_query("SELECT NAME FROM CONTACT WHERE WEBPASSWORD LIKE 'a%'")
        monkeypatch.setitem(oq.DENIED_COLUMNS, "CONTACT", frozenset())
        assert check_open_query("SELECT * FROM CONTACT") == ["CONTACT"]
        assert check_open_query(self.BYPASS_A) == ["CONTACT"]
        assert check_open_query(
            "SELECT NAME FROM CONTACT WHERE WEBPASSWORD LIKE 'a%'"
        ) == ["CONTACT"]
        # ...and the result drop is off too: a denied name in the cursor is
        # served when the table's deny set is empty.
        out = run_open_query(
            "off",
            "SELECT NAME FROM CONTACT",
            run=fake_run(["NAME", "EMAIL"], [("Jo", "j@x")]),
        )
        assert out["columns"] == ["NAME", "EMAIL"]


class TestDeniedColumnsOnResults:
    """(b) the cursor-name drop — defence in depth behind the gate. After F1
    no star over a withheld table reaches Firebird, so this layer only ever
    fires if a statement the gate accepted somehow returns a denied column
    name. Exercised here with a fake cursor that does exactly that."""

    def test_a_denied_cursor_name_behind_an_accepted_statement_is_dropped(self):
        cols = ["ACCNUM", "CUSTNAME", "PHONE", "EMAIL", "BANK", "BANKACCNO", "ICPASS"]
        rows = [("A01", "Acme", "011 555", "a@b.c", 3, "12345", "pw")]
        out = run_open_query(
            "all", "SELECT ACCNUM, CUSTNAME FROM CUSTOMER", run=fake_run(cols, rows)
        )
        assert out["ok"]
        assert out["columns"] == ["ACCNUM", "CUSTNAME"]
        assert out["rows"] == [["A01", "Acme"]]
        note = next(n for n in out["notes"] if n.startswith("Withheld columns"))
        for c in ("PHONE", "EMAIL", "BANK", "BANKACCNO", "ICPASS"):
            assert c in note
        # and no value of a withheld column survives anywhere in the answer
        dumped = str(out)
        for leaked in ("011 555", "a@b.c", "12345", "pw"):
            assert leaked not in dumped

    def test_drop_is_by_name_across_both_tables(self):
        # RECEIPT.BANK is allowed alone, but beside CUSTOMER it is dropped —
        # and the note says the drop is by name across the statement.
        cols = ["RECEIPT", "BANK", "CUSTNAME"]
        out = run_open_query(
            "r",
            "SELECT r.RECEIPT, c.CUSTNAME FROM RECEIPT r JOIN CUSTOMER c ON c.ACCNUM = r.ACCNUM",
            run=fake_run(cols, [(1, 3, "Acme")]),
        )
        assert out["columns"] == ["RECEIPT", "CUSTNAME"]
        assert any("by name across" in n for n in out["notes"])

    def test_a_result_with_only_withheld_columns_is_refused(self):
        out = run_open_query(
            "x",
            "SELECT NAME FROM CONTACT",
            run=fake_run(["EMAIL", "CELL"], [("a", "b")]),
        )
        assert out["refused"] and "every column" in out["reason"]

    def test_no_note_when_nothing_was_withheld(self):
        out = run_open_query(
            "h",
            "SELECT * FROM HUB",
            run=fake_run(["HUB", "NAME"], [("JNB", "Jo'burg")]),
        )
        assert out["ok"] and not any("Withheld" in n for n in out["notes"])

    def test_blob_bytes_are_decoded_not_repr(self):
        out = run_open_query(
            "n",
            "SELECT FIRST 1 MEMO FROM NOTE",
            run=fake_run(["MEMO"], [(b"1 box short\r\n",)]),
        )
        assert out["rows"] == [["1 box short"]]


class TestSchemaWithholds:
    def test_schema_context_carries_none_of_the_denied_names(self):
        import json
        import re

        ctx = schema_context()
        for table, cols in DENIED_COLUMNS.items():
            served = {c["name"] for c in ctx["tables"][table]["columns"]}
            assert not (cols & served), (table, cols & served)
        # Beyond the column lists, the names must not surface anywhere else in
        # the resource (justifications, hints) — except a name that is
        # legitimately served on another table (RECEIPT.BANK is a bank code
        # and stays; CUSTOMER.BANK is withheld), which is per-table by design.
        dumped = json.dumps(ctx)
        served_somewhere = {
            c["name"] for info in ctx["tables"].values() for c in info["columns"]
        }
        every_denied = set().union(*DENIED_COLUMNS.values())
        for name in every_denied - served_somewhere:
            assert not re.search(rf"\b{name}\b", dumped), name
        assert "BANK" in served_somewhere  # the RECEIPT decision, pinned

    def test_each_table_says_withheld_or_none(self):
        ctx = schema_context()
        assert ctx["tables"]["CUSTOMER"]["withheld_columns"].startswith(
            f"{len(DENIED_COLUMNS['CUSTOMER'])} contact/banking/password"
        )
        assert ctx["tables"]["RATE"]["withheld_columns"].startswith("none")

    def test_read_this_first_has_the_one_line(self):
        ctx = schema_context()
        assert any(
            "withheld" in line and "SELECT *" in line for line in ctx["read_this_first"]
        )

    def test_free_text_caveat_is_stated_where_the_text_lives(self):
        # Fable review F4: free text and unflagged contact fields can carry
        # hand-typed contact detail that no column guard strips — say so on
        # every table that has them, and once up front.
        ctx = schema_context()
        assert any(
            "free-text" in line.lower() and "cannot strip" in line
            for line in ctx["read_this_first"]
        )
        for table, needle in (
            ("NOTE", "MEMO"),
            ("COLLECT", "NOTESINT"),
            ("CUSTOMER", "SPECINSTRUCTION"),
            ("VIEW_WBANALYSE", "DESTPERCONTACT"),
        ):
            why = ALLOWLIST[table]
            assert needle in why, table
            assert "contact" in why.lower(), table

    def test_served_column_counts_are_the_survey_minus_the_withheld(self):
        ctx = schema_context("CONTACT")
        assert len(ctx["tables"]["CONTACT"]["columns"]) == 18 - len(
            DENIED_COLUMNS["CONTACT"]
        )


# --- QT-000007 line 1: the ten new relations ----------------------------------


class TestNewRelations:
    @pytest.mark.parametrize("table", NEW_TABLES)
    def test_each_is_allowlisted_with_a_survey_justification(self, table):
        assert table in ALLOWLIST
        assert "rows" in ALLOWLIST[table]  # cites the survey count
        assert table not in DENIED

    @pytest.mark.parametrize("table", NEW_TABLES)
    def test_each_passes_the_gate_and_is_served_by_the_schema(self, table):
        assert check_open_query(f"SELECT COUNT(*) FROM {table}") == [table]
        ctx = schema_context(table)
        assert ctx["tables"][table]["columns"]
        assert ctx["tables"][table]["row_count"] > 0

    def test_routing_and_eventscans_stay_refused_until_lines_3_4(self):
        with pytest.raises(GuardError, match="window"):
            check_open_query("SELECT FIRST 1 * FROM ROUTING")
        with pytest.raises(GuardError, match="window"):
            check_open_query("SELECT FIRST 1 * FROM VIEW_EVENTSCANS")

    def test_the_row_cap_refusal_names_the_big_table(self):
        rows = [(i,) for i in range(ROW_CAP + 1)]
        out = run_open_query(
            "all rates", "SELECT RATE FROM RATE", run=fake_run(["RATE"], rows)
        )
        assert out["refused"]
        assert "RATE: 680,552 rows" in out["reason"]
        assert "filter by account" in out["reason"]

    def test_the_row_cap_refusal_is_unchanged_for_a_small_table(self):
        rows = [(i,) for i in range(ROW_CAP + 1)]
        out = run_open_query("hubs", "SELECT HUB FROM HUB", run=fake_run(["HUB"], rows))
        assert out["refused"] and out["reason"].endswith("genuinely wanted.")


# --- execution: caps and shaping ------------------------------------------------


class TestAvailabilityBoundaryIsNotClosed:
    """The row/time caps and the allowlist do NOT bound server-side DB load:
    a self-cross-join or an unbounded aggregate over an allowlisted table is
    accepted by the gate and only the WAIT is capped (15s socket timeout),
    while Firebird keeps grinding. Pinned so the limitation is explicit and
    nobody mistakes the gate for a load bound — it is flagged to Larry, and
    unfixable on Firebird 3.0.13 (no SET STATEMENT TIMEOUT) without a fragile
    heuristic. These assert the gate PASSES them; they never touch a DB."""

    def test_self_cross_join_over_an_allowlisted_table_passes_the_gate(self):
        assert check_open_query(
            "SELECT COUNT(*) FROM AGENTDRIVER a, AGENTDRIVER b"
        ) == ["AGENTDRIVER"]

    def test_unbounded_aggregate_over_the_waybill_view_passes_the_gate(self):
        assert check_open_query("SELECT MAX(WAYDATE) FROM VIEW_WBANALYSE") == [
            "VIEW_WBANALYSE"
        ]


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

    def test_the_drivers_recv_error_is_reported_as_the_time_cap(self):
        # firebirdsql reports a tripped socket timeout as OperationalError
        # "Can not recv() packets", not TimeoutError — seen live 18 Aug.
        def dead(sql, params=(), max_rows=None, timeout=None):
            raise ValueError("Can not recv() packets")

        out = run_open_query("slow", self.SQL, run=dead)
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

    def test_row_counts_are_marked_as_a_drifting_snapshot(self):
        # AGENT was 1,220 at the 6 Aug survey, 1,225 live on 18 Aug — a count
        # read off this resource must never be presented as the live figure.
        ctx = schema_context()
        assert any(
            "snapshot" in line.lower() and "count" in line.lower()
            for line in ctx["read_this_first"]
        )

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


# --- hot-fix 21 Oct 2026: the FROM-list scanner (Fable re-review R1) and PLAN (R5)


class TestFromListScanner:
    """R1: the Day 5 scanner stopped at the first ON or closing paren, so a
    comma-listed table after JOIN … ON … or after a derived table was never
    seen by the allowlist, DENIED_COLUMNS or the star ban. Live on main from
    18 Aug to 21 Oct 2026. Every FROM list is now read to its end, and a list
    the scanner cannot finish refuses (fail closed)."""

    def test_event_after_a_comma_following_join_on_is_seen(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, EVENT e"
            )

    def test_webpassword_after_a_comma_following_join_on_is_refused(self):
        with pytest.raises(GuardError, match="withheld column: WEBPASSWORD"):
            check_open_query(
                "SELECT c.WEBPASSWORD FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, CONTACT c"
            )
        with pytest.raises(GuardError, match="SELECT \\*"):
            check_open_query(
                "SELECT * FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, CONTACT c"
            )

    def test_comma_after_a_derived_table_is_seen(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM (SELECT 1 AS X FROM HOLIDAY) t, EVENT e"
            )
        with pytest.raises(GuardError, match="window"):
            check_open_query(
                "SELECT COUNT(*) FROM (SELECT 1 AS X FROM HOLIDAY) t, ROUTING r"
            )

    def test_three_table_comma_lists_after_join_on(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = h.NAME, AREA a, EVENT e"
            )
        assert check_open_query(
            "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = h.NAME, AREA a, BRANCH b"
        ) == ["AREA", "BRANCH", "HOLIDAY", "HUB"]

    def test_nested_derived_tables_followed_by_a_comma(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM (SELECT X FROM (SELECT 1 AS X FROM HOLIDAY) i) t, EVENT e"
            )
        assert check_open_query(
            "SELECT COUNT(*) FROM (SELECT X FROM (SELECT 1 AS X FROM HOLIDAY) i) t, AREA a"
        ) == ["AREA", "HOLIDAY"]

    def test_the_servicegroup_demo_sees_both_tables(self):
        assert check_open_query(
            "SELECT COUNT(*) FROM HOLIDAY h JOIN HOLIDAY h2 ON h2.HOLIDAY = h.HOLIDAY, SERVICEGROUP g"
        ) == ["HOLIDAY", "SERVICEGROUP"]

    def test_join_after_on_and_after_a_derived_table(self):
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = h.NAME JOIN EVENT e ON e.HUB = u.HUB"
            )
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM (SELECT 1 AS X FROM HOLIDAY) t JOIN EVENT e ON 1 = 1"
            )
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query("SELECT COUNT(*) FROM HOLIDAY h NATURAL JOIN EVENT e")
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = LEFT(u.HUB, 3) JOIN EVENT e ON 1 = 1"
            )
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h LEFT OUTER JOIN HUB u ON u.HUB IN (SELECT HUB FROM HUB), EVENT e"
            )
        with pytest.raises(GuardError, match="EVENT is deliberately off"):
            check_open_query(
                "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u USING (HUB), EVENT e"
            )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT COUNT(*) FROM HOLIDAY h, (HUB u JOIN AREA a ON a.AREA = u.HUB)",
            "SELECT COUNT(*) FROM (HOLIDAY h JOIN HUB u ON u.HUB = u.HUB) JOIN AREA a ON 1 = 1",
            "SELECT COUNT(*) FROM HOLIDAY h,",
            "SELECT COUNT(*) FROM HOLIDAY h JOIN",
            "SELECT COUNT(*) FROM HOLIDAY h HUB u",
            "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB ) x",
        ],
    )
    def test_a_from_list_the_scanner_cannot_finish_refuses(self, sql):
        # fail closed: every name here is allowlisted, so only the scanner's
        # refusal stands between the statement and Firebird. Proven
        # load-bearing on 21 Oct 2026 by deleting the refusal in a scratch
        # copy: this test then fails (the first shape is accepted with
        # tables == ['HOLIDAY']).
        with pytest.raises(GuardError, match="could not be read to its end"):
            check_open_query(sql)
        assert run_open_query("scan", sql, run=never_runs)["refused"]

    def test_existing_shapes_unchanged(self):
        assert check_open_query("SELECT FIRST 5 WAYBILL FROM VIEW_WBANALYSE") == [
            "VIEW_WBANALYSE"
        ]
        assert check_open_query(
            "SELECT m.MANIFEST FROM MANIFEST m, AGENT a, HUB h WHERE a.AGENT = m.AGENT"
        ) == ["AGENT", "HUB", "MANIFEST"]
        assert check_open_query(
            "WITH big AS (SELECT ACCNUM FROM CUSTOMER) SELECT b.ACCNUM FROM big b JOIN HUB h ON 1 = 1"
        ) == ["CUSTOMER", "HUB"]
        assert check_open_query(
            "SELECT h.NAME FROM HOLIDAY h WHERE h.HOLIDAY IN (SELECT HOLIDAY FROM HOLIDAY) "
            "AND EXISTS (SELECT 1 FROM HUB u WHERE u.HUB = 'JNB')"
        ) == ["HOLIDAY", "HUB"]
        assert check_open_query(
            "SELECT NAME FROM HOLIDAY UNION ALL SELECT NAME FROM HUB"
        ) == ["HOLIDAY", "HUB"]


class TestPlanClauseRefused:
    """R5: a user PLAN clause beats the key — `… PLAN (R NATURAL)` is a scan
    on demand. The server chooses the plan."""

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT COUNT(*) FROM HOLIDAY PLAN (HOLIDAY NATURAL)",
            "SELECT COUNT(*) FROM HOLIDAY h WHERE h.NAME = 'x' PLAN (H INDEX (RDB$PRIMARY33))",
            "SELECT COUNT(*) FROM HOLIDAY h ORDER BY 1 plan (h natural)",
        ],
    )
    def test_plan_keyword_is_refused(self, sql):
        with pytest.raises(GuardError, match="PLAN clause is not accepted"):
            check_open_query(sql)
        out = run_open_query("plan", sql, run=never_runs)
        assert out["refused"] and "PLAN" in out["reason"]

    def test_plan_in_a_literal_or_comment_is_fine(self):
        assert check_open_query(
            "SELECT NAME FROM HOLIDAY WHERE NAME = 'PLAN' -- PLAN"
        ) == ["HOLIDAY"]
        assert check_open_query("SELECT NAME FROM HOLIDAY /* PLAN (x) */") == [
            "HOLIDAY"
        ]
