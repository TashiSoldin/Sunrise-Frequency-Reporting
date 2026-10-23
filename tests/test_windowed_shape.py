"""The one-block shape for ROUTING and VIEW_EVENTSCANS (design change,
23 Oct 2026, after seven adversarial reviews each found a place a predicate
could hide in the accepted language). The language for the two windowed
tables is a whitelist of SHAPES; this file pins each rule's boundary, the
eleven regression forms, the result notes, the signed-rule data, the V6
connect race and the cap refusal text. The pins from reviews 1–7 live in
test_windowed_pins_reviews_1_to_7.py.
"""

import threading
import time

import pytest

from mcp_server import db
from mcp_server.open_query import (
    ALLOWLIST,
    DENIED,
    DENIED_COLUMNS,
    TIMEOUT_S,
    WINDOWED,
    GuardError,
    check_open_query,
    run_open_query,
    schema_context,
)

R = "SELECT COUNT(*) FROM ROUTING r"
V = "SELECT COUNT(*) FROM VIEW_EVENTSCANS v"
KEY = "r.WAYBILL = '102155314'"
VKEY = "v.WAYBILL = '102155314'"
WIN = "r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21'"


def never_runs(sql, params=(), max_rows=None, timeout=None):
    raise AssertionError("the database must not be reached")


def refuses(sql, rule=None, needle=None):
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    msg = str(e.value)
    if rule is not None:
        assert f"windowed shape rule {rule}" in msg, msg
    if needle is not None:
        assert needle in msg, msg
    assert "One-block form:" in msg and "Rule:" in msg
    out = run_open_query("probe", sql, run=never_runs)
    assert out["refused"]
    return msg


# --- the eleven regression forms (the sixth / seventh reviews' table) ---------------
# Form 9 used a CTE and is rewritten into the one-block form (a CTE is rule 1).
ELEVEN = [
    (
        "1 ROUTING by WAYBILL =",
        "SELECT r.WAYBILL, r.LEG, r.MTYPE, r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "2 ROUTING by WAYBILL IN (100)",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IN ("
        + ", ".join(f"'W{i}'" for i in range(100))
        + ")",
    ),
    (
        "3 ROUTING by MANIFEST =",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
    ),
    (
        "4 ROUTING AGENTDATE 31 d COUNT",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-09-21' AND '2026-10-21'",
    ),
    (
        "5 view by WAYBILL",
        "SELECT v.EVENTDATE, v.EVENTTIME, v.NAME, v.HUB FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = '102155314'",
    ),
    (
        "6 view by TRACKNO",
        "SELECT v.EVENTDATE, v.EVENTTIME, v.NAME FROM VIEW_EVENTSCANS v WHERE v.TRACKNO = '1021553140001'",
    ),
    (
        "7 view by MANIFEST = (COUNT)",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.MANIFEST = 37733",
    ),
    (
        "7b view by MANIFEST = (50 rows)",
        "SELECT FIRST 50 v.WAYBILL, v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.MANIFEST = 37733",
    ),
    (
        "8 view EVENTDATE 3 d COUNT",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "9 keyed ROUTING, one block (was a CTE)",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "10 ROUTING + VIEW_WBANALYSE both keyed",
        "SELECT r.LEG, w.ACCNUM FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "11 ROUTING + AGENTDRIVER keyed on AGENT",
        "SELECT FIRST 50 r.LEG, d.DRIVER FROM ROUTING r JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE r.WAYBILL = '102155314' AND d.AGENT = 30105",
    ),
]


class TestTheElevenForms:
    @pytest.mark.parametrize("label,sql", ELEVEN, ids=[e[0] for e in ELEVEN])
    def test_each_form_is_accepted_with_its_note(self, label, sql):
        windows = []
        tables = check_open_query(sql, windows)
        assert tables[0] in ("ROUTING", "VIEW_EVENTSCANS") or "ROUTING" in tables
        assert windows and all(
            "keyed by" in w or "window" in w
            for w in windows
            if not w.startswith("note:")
        )

    def test_the_old_cte_form_of_nine_is_now_rule_one(self):
        refuses(
            "WITH legs AS (SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT COUNT(*) FROM legs",
            rule=1,
            needle="WITH",
        )


# --- rule 1: one SELECT block --------------------------------------------------------


class TestRule1OneBlock:
    @pytest.mark.parametrize(
        "sql, needle",
        [
            (f"WITH q AS (SELECT 1 X FROM HOLIDAY) {R} WHERE {KEY}", "WITH"),
            (
                f"SELECT COUNT(*) FROM (SELECT r.WAYBILL FROM ROUTING r WHERE {KEY}) t",
                "second SELECT",
            ),
            (
                f"SELECT (SELECT COUNT(*) FROM HOLIDAY) FROM ROUTING r WHERE {KEY}",
                "second SELECT",
            ),
            (f"{R} WHERE {KEY} AND r.LEG IN (SELECT 1 FROM HOLIDAY)", "second SELECT"),
            (f"{R} WHERE {KEY} AND EXISTS (SELECT 1 FROM HOLIDAY)", "second SELECT"),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = (SELECT FIRST 1 h.NAME FROM HOLIDAY h) WHERE {KEY}",
                "second SELECT",
            ),
            (
                f"SELECT r.WAYBILL, COUNT(*) FROM ROUTING r WHERE {KEY} GROUP BY r.WAYBILL HAVING COUNT(*) > (SELECT 1 FROM HOLIDAY)",
                "second SELECT",
            ),
            (f"{R} WHERE {KEY} UNION ALL {R} WHERE {KEY}", "UNION"),
            (f"{R} WHERE {KEY} UNION SELECT COUNT(*) FROM HOLIDAY", "UNION"),
        ],
    )
    def test_a_second_block_anywhere_refuses(self, sql, needle):
        refuses(sql, rule=1, needle=needle)

    def test_one_block_passes(self):
        assert check_open_query(f"{R} WHERE {KEY}") == ["ROUTING"]


# --- rule 2: the FROM list ----------------------------------------------------------


class TestRule2FromList:
    @pytest.mark.parametrize(
        "sql, needle",
        [
            # the windowed table must come first
            (
                f"SELECT COUNT(*) FROM VIEW_WBANALYSE w JOIN ROUTING r ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A'",
                "first table",
            ),
            # two windowed tables
            (
                f"{R} JOIN VIEW_EVENTSCANS v ON v.WAYBILL = r.WAYBILL WHERE {KEY} AND {VKEY}",
                "more than once",
            ),
            (
                f"{R} JOIN ROUTING b ON b.WAYBILL = r.WAYBILL WHERE {KEY} AND b.WAYBILL = 'A'",
                "more than once",
            ),
            # a partner that is not one of the three
            (
                f"{R} JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE WHERE {KEY}",
                "HOLIDAY cannot be joined",
            ),
            (
                f"{R} JOIN HUB u ON u.HUB = r.ORIGHUB WHERE {KEY}",
                "HUB cannot be joined",
            ),
            # the same partner twice
            (
                f"{R} JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST JOIN MANIFEST m2 ON m2.MANIFEST = r.MANIFEST WHERE {KEY} AND m.MANIFEST = 1 AND m2.MANIFEST = 1",
                "twice",
            ),
            # every forbidden join spelling
            (
                f"SELECT COUNT(*) FROM ROUTING r, VIEW_WBANALYSE w WHERE {KEY} AND w.WAYBILL = r.WAYBILL AND w.WAYBILL = 'A'",
                "a comma",
            ),
            (
                f"{R} CROSS JOIN VIEW_WBANALYSE w WHERE {KEY} AND w.WAYBILL = 'A'",
                "CROSS JOIN",
            ),
            (
                f"{R} NATURAL JOIN VIEW_WBANALYSE w WHERE {KEY} AND w.WAYBILL = 'A'",
                "NATURAL JOIN",
            ),
            (
                f"{R} RIGHT JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A'",
                "RIGHT JOIN",
            ),
            (
                f"{R} FULL JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A'",
                "FULL JOIN",
            ),
            (
                f"{R} FULL OUTER JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A'",
                "FULL OUTER JOIN",
            ),
            # the ON: wrong key, extra conjunct, literal, reversed partner column, USING
            (
                f"{R} JOIN VIEW_WBANALYSE w ON w.ACCNUM = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A'",
                "w.WAYBILL = r.WAYBILL",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL AND w.WAYDATE = r.AGENTDATE WHERE {KEY} AND w.WAYBILL = 'A'",
                "nothing else",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = 'A' WHERE {KEY} AND w.WAYBILL = 'A'",
                "w.WAYBILL = r.WAYBILL",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.AWB WHERE {KEY} AND w.WAYBILL = 'A'",
                "w.WAYBILL = r.WAYBILL",
            ),
            (
                f"{R} JOIN MANIFEST m ON m.MANIFEST = r.LEG WHERE {KEY} AND m.MANIFEST = 1",
                "m.MANIFEST = r.MANIFEST",
            ),
            (
                f"{R} JOIN MANIFEST m ON m.AGENT = r.AGENT WHERE {KEY} AND m.MANIFEST = 1",
                "m.MANIFEST = r.MANIFEST",
            ),
            (
                f"{R} JOIN AGENTDRIVER d ON d.DRIVER = r.AGENT WHERE {KEY} AND d.AGENT = 1",
                "d.AGENT = r.AGENT",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON 1 = 1 WHERE {KEY} AND w.WAYBILL = 'A'",
                "w.WAYBILL = r.WAYBILL",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w USING (WAYBILL) WHERE {KEY} AND w.WAYBILL = 'A'",
                "w.WAYBILL = r.WAYBILL",
            ),
            (
                f"{R} JOIN VIEW_WBANALYSE w ON (w.WAYBILL = r.WAYBILL) WHERE {KEY} AND w.WAYBILL = 'A'",
                "nothing else",
            ),
            # the view has no AGENT column
            (
                f"{V} JOIN AGENTDRIVER d ON d.AGENT = v.AGENT WHERE {VKEY} AND d.AGENT = 1",
                "has no AGENT column",
            ),
            # a derived table in table position
            (
                f"{R} JOIN (SELECT 1 X FROM HOLIDAY) t ON 1 = 1 WHERE {KEY}",
                "second SELECT",
            ),
        ],
    )
    def test_the_from_list_boundaries(self, sql, needle):
        with pytest.raises(GuardError) as e:
            check_open_query(sql)
        assert needle in str(e.value), str(e.value)
        assert run_open_query("probe", sql, run=never_runs)["refused"]

    @pytest.mark.parametrize(
        "sql",
        [
            f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = '102155314'",
            f"{R} INNER JOIN VIEW_WBANALYSE w ON r.WAYBILL = w.WAYBILL WHERE {KEY} AND w.WAYBILL = '102155314'",
            f"{R} LEFT JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYDATE BETWEEN '2026-10-01' AND '2026-10-31'",
            f"{R} LEFT OUTER JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE {KEY} AND m.MANIFEST IN (1, 2)",
            f"{R} JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE {KEY} AND d.AGENT = 30105",
            f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST LEFT JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE {KEY} AND w.WAYBILL = 'A' AND m.MANIFEST = 1 AND d.AGENT = 1",
            f"{V} JOIN VIEW_WBANALYSE w ON w.WAYBILL = v.WAYBILL WHERE {VKEY} AND w.WAYBILL = '102155314'",
            f"{V} JOIN MANIFEST m ON m.MANIFEST = v.MANIFEST WHERE {VKEY} AND m.MANIFEST = 37733",
            "SELECT COUNT(*) FROM ROUTING AS r JOIN VIEW_WBANALYSE AS w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'A' AND w.WAYBILL = 'A'",
        ],
    )
    def test_the_sanctioned_joins_pass(self, sql):
        windows = []
        check_open_query(sql, windows)
        assert len([w for w in windows if not w.startswith("note:")]) >= 2

    def test_a_partner_without_its_own_key_is_refused_by_the_signed_join_rule(self):
        msg = refuses(
            f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY}", rule=3
        )
        assert "repeat the waybill filter on the VIEW_WBANALYSE alias" in msg
        msg = refuses(
            f"{R} JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE {KEY}", rule=3
        )
        assert "repeat the manifest filter on the MANIFEST alias" in msg
        msg = refuses(
            f"{R} JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE {KEY}", rule=3
        )
        assert "repeat the agent filter on the AGENTDRIVER alias" in msg
        refuses(
            f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYDATE BETWEEN '2026-09-01' AND '2026-10-02'",
            needle="32 days",
        )


# --- rule 3: the WHERE ----------------------------------------------------------------


class TestRule3Where:
    @pytest.mark.parametrize(
        "where, needle",
        [
            (f"{KEY} OR r.LEG = 1", "OR"),
            (f"{KEY} AND (r.LEG = 1 OR r.LEG = 2)", "parentheses"),
            (f"({KEY})", "parentheses"),
            (f"NOT {KEY}", "NOT"),
            (f"{KEY} AND NOT r.LEG = 1", "NOT"),
            (f"{KEY} AND r.LEG NOT IN (1, 2)", "NOT"),
            (f"{KEY} AND r.LEG IS FALSE", "IS NULL"),
            (f"{KEY} AND UPPER(r.MTYPE) = 'M'", "parentheses in the WHERE"),
            (f"{KEY} AND r.LEG + 1 = 2", "alias.COL <op> literal"),
            (f"{KEY} AND CASE WHEN r.LEG = 1 THEN 1 ELSE 0 END = 1", "CASE"),
            (
                f"{KEY} AND r.LEG BETWEEN 1 AND 2",
                "BETWEEN is accepted only on the window column",
            ),
            (
                f"{KEY} AND r.BOOKDATE BETWEEN '2026-10-01' AND '2026-10-02'",
                "BOOKDATE is a filter",
            ),
            (f"{KEY} AND r.LEG = r.MBRANCH", "column with a column"),
            (f"{KEY} AND r.AGENTDATE = CURRENT_DATE", "column with a column"),
            (f"{KEY} AND r.WAYBILL = ?", "not alias.COL <op> literal"),
            (f"{KEY} AND 1 = 1", "does not start with alias.COL"),
            (f"{KEY} AND r.LEG", "bare column"),
            (f"{KEY} AND r.NOSUCHCOL = 1", "not a column of ROUTING"),
            (f"{KEY} AND x.LEG = 1", "not an alias"),
            ("WAYBILL = 'A' AND r.LEG = 1", "unqualified"),
        ],
    )
    def test_each_forbidden_conjunct_form(self, where, needle):
        if needle == "unqualified":
            sql = f"{R} JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {where} AND w.WAYBILL = 'A'"
        else:
            sql = f"{R} WHERE {where}"
        refuses(sql, rule=3, needle=needle)

    @pytest.mark.parametrize(
        "where",
        [
            f"{KEY} AND r.MTYPE = 'M'",
            f"{KEY} AND r.MTYPE <> 'M'",
            f"{KEY} AND r.MTYPE != 'M'",
            f"{KEY} AND r.LEG >= 1 AND r.LEG <= 3",
            f"{KEY} AND r.LEG > 0",
            f"{KEY} AND r.MTYPE LIKE 'M%'",
            f"{KEY} AND r.MTYPE STARTING WITH 'M'",
            f"{KEY} AND r.MTYPE CONTAINING 'M'",
            f"{KEY} AND r.MTYPE IN ('M', 'R')",
            f"{KEY} AND r.BOOKDATE IS NOT NULL",
            f"{KEY} AND r.BOOKDATE IS NULL",
            f"{KEY} AND r.BOOKDATE >= '2026-10-01'",
            f"{KEY} AND r.AGENTDATE >= DATE '2026-10-01'",
            f"{WIN} AND r.AGENT = 30105 AND r.MTYPE = 'M'",
            f"r.MTYPE = 'M' AND {WIN}",
            f"{KEY} AND r.LEG = -1",
            "r.WAYBILL IN ('A', 'B') AND r.LEG = 1",
            "r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
            "r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE < '2026-10-08'",
            "r.AGENTDATE = '2026-10-19'",
        ],
    )
    def test_each_allowed_conjunct_form(self, where):
        assert check_open_query(f"{R} WHERE {where}") == ["ROUTING"]

    @pytest.mark.parametrize(
        "sql, needle",
        [
            (f"{R}", "no key or window on ROUTING (alias r)"),
            (f"{R} WHERE r.MTYPE = 'M'", "no key or window"),
            (
                f"{R} WHERE r.BOOKDATE >= '2026-10-01' AND r.BOOKDATE <= '2026-10-02'",
                "BOOKDATE is a filter",
            ),
            (f"{R} WHERE r.AGENT = 30105", "AGENT is a filter"),
            (f"{V} WHERE v.WAYDATE = '2026-10-19'", "WAYDATE is a filter"),
            (f"{V} WHERE v.NAME = 'x'", "NAME is a filter"),
            (f"{R} WHERE r.WAYBILL LIKE 'A%'", "LIKE / STARTING WITH"),
            (f"{R} WHERE r.WAYBILL <> 'A'", "is not a key"),
            (f"{R} WHERE r.WAYBILL BETWEEN 'A' AND 'B'", "BETWEEN … is not a key"),
            (f"{R} WHERE r.WAYBILL IS NOT NULL", "IS [NOT] NULL is not a key"),
            (f"{R} WHERE r.WAYBILL = 12345", "unquoted number"),
            (f"{R} WHERE r.WAYBILL = ''", "blank"),
            (f"{V} WHERE v.TRACKNO = ''", "blank"),
            (f"{R} WHERE r.AGENTDATE >= '2026-10-01'", "both ends"),
            (
                f"{R} WHERE r.AGENTDATE BETWEEN '2026-10-11' AND '2026-10-05'",
                "reversed",
            ),
            (f"{R} WHERE r.AGENTDATE BETWEEN '2026-09-01' AND '2026-10-02'", "32 days"),
            (f"{V} WHERE v.EVENTDATE BETWEEN '2026-10-18' AND '2026-10-21'", "4 days"),
            (f"{R} WHERE r.AGENTDATE IN ('2026-10-01')", "list of dates"),
            (
                f"{R} WHERE r.AGENTDATE BETWEEN '01.10.2026' AND '02.10.2026'",
                "YYYY-MM-DD",
            ),
            (f"{R} WHERE r.AGENTDATE <> '2026-10-01'", "not a date range"),
            (
                f"{R} WHERE r.WAYBILL IN ("
                + ", ".join(f"'W{i}'" for i in range(101))
                + ")",
                "101 literals",
            ),
        ],
    )
    def test_no_key_or_window_says_what_was_found(self, sql, needle):
        refuses(sql, rule=3, needle=needle)

    def test_the_refusal_carries_no_literal_values(self):
        with pytest.raises(GuardError) as e:
            check_open_query(
                f"{R} WHERE r.WAYBILL LIKE 'SECRETVALUE%' AND UPPER(r.MTYPE) = 'SECRET2'"
            )
        assert "SECRETVALUE" not in str(e.value) and "SECRET2" not in str(e.value)
        with pytest.raises(GuardError) as e:
            check_open_query(f"{R} WHERE r.MTYPE = 'SECRETVALUE' OR r.LEG = 1")
        assert "SECRETVALUE" not in str(e.value)


# --- rule 4: MANIFEST ----------------------------------------------------------------


class TestRule4Manifest:
    @pytest.mark.parametrize(
        "sql",
        [
            f"{R} WHERE {WIN} AND r.MANIFEST > 0",
            f"{R} WHERE {WIN} AND r.MANIFEST <> 0",
            f"{R} WHERE {WIN} AND r.MANIFEST BETWEEN 1 AND 2",
            f"{R} WHERE {WIN} AND r.MANIFEST IS NOT NULL",
            f"{R} WHERE {WIN} AND r.MANIFEST LIKE '3%'",
            f"{R} WHERE {WIN} AND r.MANIFEST = 0",
            f"{R} WHERE {WIN} AND r.MANIFEST = -1",
            f"{R} WHERE {WIN} AND r.MANIFEST = '5'",
            f"{R} WHERE {WIN} AND r.MANIFEST = 5.0",
            f"{R} WHERE {WIN} AND r.MANIFEST IN (0, 5)",
            f"{R} WHERE {WIN} AND r.MANIFEST IN ("
            + ", ".join(str(i) for i in range(1, 22))
            + ")",
            f"{R} WHERE r.MANIFEST IN ("
            + ", ".join(str(i) for i in range(1, 22))
            + ")",
            f"{V} WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
            f"{V} WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST = 0",
            f"{R} JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE {KEY} AND m.MANIFEST > 0",
            f"{R} JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE {KEY} AND m.MANIFEST = 0",
            "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST > 0",
        ],
    )
    def test_manifest_in_a_non_key_position_in_the_where_refuses(self, sql):
        refuses(sql, rule=4)

    @pytest.mark.parametrize(
        "sql",
        [
            f"{R} WHERE r.MANIFEST = 37733",
            f"{R} WHERE r.MANIFEST IN (37733, 37739)",
            f"{R} WHERE {WIN} AND r.MANIFEST = 37733",
            f"{R} JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE {KEY} AND m.MANIFEST = 37733",
            f"SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE {KEY} GROUP BY r.MANIFEST",
            f"SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE {KEY} GROUP BY r.MANIFEST + 0",
            f"SELECT r.WAYBILL, r.MANIFEST FROM ROUTING r WHERE {KEY} ORDER BY r.MANIFEST DESC",
            f"SELECT r.WAYBILL, r.MANIFEST + 0 FROM ROUTING r WHERE {KEY} ORDER BY r.MANIFEST + 0",
            f"SELECT MAX(r.MANIFEST) FROM ROUTING r WHERE {KEY}",
            f"{V} JOIN MANIFEST m ON m.MANIFEST = v.MANIFEST WHERE {VKEY} AND m.MANIFEST = 37733",
        ],
    )
    def test_manifest_as_a_key_in_the_on_or_in_the_select_list_passes(self, sql):
        check_open_query(sql)

    def test_the_manifest_hint_and_the_navigation_note(self):
        windows = []
        check_open_query(f"{R} WHERE r.MANIFEST = 37733", windows)
        assert len(windows) == 1 and "MBRANCH" in windows[0] and "MTYPE" in windows[0]
        windows = []
        check_open_query(
            "SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' GROUP BY r.MANIFEST",
            windows,
        )
        assert windows[0] == "ROUTING (r): keyed by WAYBILL (1 literal)"
        assert (
            windows[1].startswith("note: grouping or ordering ROUTING by MANIFEST")
            and "r.MANIFEST + 0" in windows[1]
        )
        windows = []
        check_open_query(
            "SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' GROUP BY r.MANIFEST + 0",
            windows,
        )
        assert len(windows) == 1
        windows = []
        check_open_query(
            "SELECT v.MANIFEST, COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'A' GROUP BY v.MANIFEST",
            windows,
        )
        assert len(windows) == 1  # the view sorts; no note


# --- rule 5: the select list and the trailing clauses ----------------------------------


class TestRule5SelectList:
    @pytest.mark.parametrize(
        "sql, needle",
        [
            (
                f"SELECT CASE WHEN r.LEG = 1 THEN 1 ELSE 0 END FROM ROUTING r WHERE {KEY}",
                "CASE expression",
            ),
            (f"SELECT UPPER(r.MTYPE) FROM ROUTING r WHERE {KEY}", "function call"),
            (f"SELECT r.LEG + 1 FROM ROUTING r WHERE {KEY}", "select list"),
            (f"SELECT r.LEG || r.MTYPE FROM ROUTING r WHERE {KEY}", "select list"),
            (f"SELECT COUNT(r.LEG + 1) FROM ROUTING r WHERE {KEY}", "aggregate"),
            (f"SELECT SUM(*) FROM ROUTING r WHERE {KEY}", "aggregate"),
            (f"SELECT LIST(r.WAYBILL) FROM ROUTING r WHERE {KEY}", "function call"),
            (
                f"SELECT EXTRACT(YEAR FROM r.AGENTDATE) FROM ROUTING r WHERE {KEY}",
                "function call",
            ),
            (f"SELECT r.NOSUCHCOL FROM ROUTING r WHERE {KEY}", "not a column"),
            (f"SELECT x.LEG FROM ROUTING r WHERE {KEY}", "not an alias"),
            (
                f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} GROUP BY UPPER(r.WAYBILL)",
                "function call",
            ),
            (
                f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} ORDER BY r.LEG + 1",
                "ORDER BY",
            ),
            (
                f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} ORDER BY r.LEG NULLS LAST",
                "ORDER BY",
            ),
            (
                f"SELECT r.WAYBILL, COUNT(*) FROM ROUTING r WHERE {KEY} GROUP BY r.WAYBILL HAVING r.WAYBILL = 'A'",
                "HAVING",
            ),
            (
                f"SELECT r.WAYBILL, COUNT(*) FROM ROUTING r WHERE {KEY} GROUP BY r.WAYBILL HAVING COUNT(*) > 1 OR 1 = 1",
                "HAVING",
            ),
            (f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} ROWS 1 TO 2 TO 3", "ROWS"),
            (
                f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} FETCH FIRST 1 ROWS ONLY",
                "FETCH",
            ),
            (f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} OFFSET 1 ROWS", "OFFSET"),
            (f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} INTO :x", "INTO"),
            (
                f"SELECT r.WAYBILL FROM ROUTING r ORDER BY r.LEG WHERE {KEY}",
                "out of order",
            ),
            (
                f"SELECT FIRST r.WAYBILL FROM ROUTING r WHERE {KEY}",
                "FIRST must be followed by a number",
            ),
            (f"SELECT r.WAYBILL, FROM ROUTING r WHERE {KEY}", "comma"),
        ],
    )
    def test_the_select_list_and_clause_boundaries(self, sql, needle):
        refuses(sql, rule=5, needle=needle)

    @pytest.mark.parametrize(
        "sql",
        [
            f"SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE {KEY}",
            f"SELECT r.WAYBILL AS W, r.LEG L FROM ROUTING r WHERE {KEY}",
            f"SELECT COUNT(*), COUNT(DISTINCT r.WAYBILL), SUM(r.TOTAL), MIN(r.LEG), MAX(r.LEG), AVG(r.LEG) FROM ROUTING r WHERE {KEY}",
            f"SELECT COUNT(*) N FROM ROUTING r WHERE {KEY}",
            f"SELECT FIRST 5 r.WAYBILL FROM ROUTING r WHERE {KEY}",
            f"SELECT FIRST 5 SKIP 5 r.WAYBILL FROM ROUTING r WHERE {KEY}",
            f"SELECT DISTINCT r.WAYBILL FROM ROUTING r WHERE {KEY}",
            f"SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE {WIN} GROUP BY r.MTYPE ORDER BY 2 DESC",
            f"SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE {WIN} GROUP BY 1 HAVING COUNT(*) > 1 AND COUNT(DISTINCT r.WAYBILL) >= 1 ORDER BY r.MTYPE ASC",
            f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} ROWS 10",
            f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY} ROWS 1 TO 10",
            f"SELECT 1, 'x', r.WAYBILL FROM ROUTING r WHERE {KEY}",
            f"SELECT v.* FROM VIEW_EVENTSCANS v WHERE {VKEY}",
            f"SELECT * FROM VIEW_EVENTSCANS v WHERE {VKEY}",
            "SELECT WAYBILL, LEG FROM ROUTING WHERE WAYBILL = 'A' ORDER BY LEG",
            f"SELECT r.WAYBILL FROM ROUTING r WHERE {KEY};",
            f"SELECT r.WAYBILL, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE {KEY} AND w.WAYBILL = 'A' ORDER BY w.CUSTNAME",
        ],
    )
    def test_the_allowed_select_lists_pass(self, sql):
        check_open_query(sql)

    def test_the_star_ban_still_runs_first_on_routing(self):
        with pytest.raises(GuardError, match="SELECT \\* / alias\\.\\* is refused"):
            check_open_query(f"SELECT * FROM ROUTING r WHERE {KEY}")
        with pytest.raises(GuardError, match="withheld column: DELOTP"):
            check_open_query(f"SELECT r.DELOTP FROM ROUTING r WHERE {KEY}")


# --- the signed rule as data, the schema, the notes -----------------------------------


class TestWindowedData:
    def test_both_tables_are_allowlisted_windowed_and_out_of_denied(self):
        for t in ("ROUTING", "VIEW_EVENTSCANS"):
            assert t in ALLOWLIST and t in WINDOWED and t not in DENIED
            assert "2026-10-21" in ALLOWLIST[t]
            assert t in DENIED_COLUMNS

    def test_the_signed_rule_as_data(self):
        r, v = WINDOWED["ROUTING"], WINDOWED["VIEW_EVENTSCANS"]
        assert r["keys"] == {"WAYBILL": 100, "MANIFEST": 20}
        assert (r["date"], r["max_days"]) == ("AGENTDATE", 31)
        assert "BOOKDATE" in r["filters_only"]
        assert v["keys"] == {"WAYBILL": 100, "TRACKNO": 100, "MANIFEST": 20}
        assert (v["date"], v["max_days"]) == ("EVENTDATE", 3)
        assert {"WAYDATE", "ACCNUM", "NAME", "HUB"} <= set(v["filters_only"])
        for t in ("ROUTING", "VIEW_EVENTSCANS"):
            assert "one-block shape" in WINDOWED[t]["rule"]

    def test_describe_schema_states_the_rule_per_table(self):
        for t in ("ROUTING", "VIEW_EVENTSCANS"):
            info = schema_context(t)["tables"][t]
            assert info["window_rule"] == WINDOWED[t]["rule"]
        assert "window_rule" not in schema_context("HUB")["tables"]["HUB"]
        ctx = schema_context()
        assert any(
            "ONE-BLOCK" in line and "ROUTING" in line for line in ctx["read_this_first"]
        )
        assert len(ctx["tables"]) == 32

    def test_the_notes_say_what_bounded_each_relation(self):
        windows = []
        check_open_query(
            f"{R} WHERE r.AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11'", windows
        )
        assert windows == [
            "ROUTING (r): AGENTDATE window 2026-10-05..2026-10-11 (7 days)"
        ]
        windows = []
        check_open_query(
            "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE WAYBILL IN ('A', 'B')", windows
        )
        assert windows == ["VIEW_EVENTSCANS: keyed by WAYBILL IN (2 literals)"]
        windows = []
        check_open_query(
            "SELECT r.LEG FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL IN ('A', 'B') AND w.WAYDATE >= '2026-10-01' AND w.WAYDATE <= '2026-10-07'",
            windows,
        )
        assert windows == [
            "ROUTING (r): keyed by WAYBILL IN (2 literals)",
            "VIEW_WBANALYSE (w): WAYDATE window 2026-10-01..2026-10-07 (7 days)",
        ]
        out = run_open_query(
            "legs", f"{R} WHERE {KEY}", run=lambda *a, **k: (["N"], [(1,)])
        )
        assert out["ok"] and any(n.startswith("Window applied") for n in out["notes"])

    def test_the_rule_is_what_refuses(self, monkeypatch):
        import mcp_server.open_query as oq

        refuses("SELECT COUNT(*) FROM ROUTING", rule=3)
        monkeypatch.setattr(oq, "WINDOWED", {})
        windows = []
        assert check_open_query("SELECT COUNT(*) FROM ROUTING", windows) == ["ROUTING"]
        assert windows == []

    def test_an_internal_error_in_the_shape_check_is_a_refusal(self, monkeypatch):
        import mcp_server.open_query as oq

        def boom(*a, **k):
            raise ZeroDivisionError("shape exploded")

        monkeypatch.setattr(oq, "_check_shape", boom)
        with pytest.raises(GuardError, match="could not parse"):
            check_open_query(f"{R} WHERE {KEY}")
        assert run_open_query("x", f"{R} WHERE {KEY}", run=never_runs)["refused"]
        assert check_open_query("SELECT NAME FROM HOLIDAY") == [
            "HOLIDAY"
        ]  # never enters the check

    @pytest.mark.parametrize(
        "sql",
        [
            f"{R} WHERE r.WAYBILL = = 'A' AND (",
            f"{R} WHERE ) r.WAYBILL = 'A'",
            f"{R} WHERE r.WAYBILL IN (",
            f"{R} WHERE r.AGENTDATE BETWEEN",
            f"{R} JOIN",
            f"{R} WHERE {KEY} AND",
            f"{R} WHERE AND {KEY}",
            f"{R} WHERE",
            f"{R} WHERE {KEY} GROUP BY",
            f"{R} WHERE {KEY} ORDER",
        ],
    )
    def test_a_malformed_statement_is_a_refusal_not_an_exception(self, sql):
        with pytest.raises(GuardError):
            check_open_query(sql)
        assert run_open_query("x", sql, run=never_runs)["refused"]

    def test_a_non_windowed_statement_never_enters_the_shape_check(self, monkeypatch):
        import mcp_server.open_query as oq

        calls = []
        real = oq._check_shape
        monkeypatch.setattr(
            oq, "_check_shape", lambda *a, **k: calls.append(1) or real(*a, **k)
        )
        check_open_query(
            "SELECT COUNT(*) FROM VIEW_WBANALYSE w JOIN MANIFEST m ON m.AGENT = w.ACCNUM"
        )
        check_open_query(
            "WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT X FROM q, HUB h WHERE h.HUB = 'A' OR 1 = 1"
        )
        assert calls == []
        check_open_query(f"{R} WHERE {KEY}")
        assert calls == [1]


# --- the cap refusal text and the V6 connect race ----------------------------------------


class TestCapAndConnectRace:
    def test_the_time_cap_refusal_says_narrow_never_retry_and_may_still_run(self):
        def dead(sql, params=(), max_rows=None, timeout=None):
            raise OSError("Can not recv() packets")

        out = run_open_query("j", f"{R} WHERE {KEY}", run=dead)
        assert out["refused"]
        r = out["reason"]
        assert f"{TIMEOUT_S} s wall-clock time cap" in r
        assert "may still be running server-side" in r
        assert "do not retry it as-is" in r
        assert "narrow the window or the key" in r
        assert "retry" not in r.replace("do not retry it as-is", "")

    def test_the_open_path_connects_with_the_five_second_budget(self, monkeypatch):
        import mcp_server.open_query as oq

        seen = {}

        def fake_run_select(
            sql, params=(), max_rows=None, timeout=None, connect_timeout=None
        ):
            seen.update(
                timeout=timeout, connect_timeout=connect_timeout, max_rows=max_rows
            )
            return ["N"], [(1,)]

        monkeypatch.setattr(oq, "run_select", fake_run_select)
        assert oq._run_select_open("SELECT 1 FROM HOLIDAY", (), 7, timeout=15) == (
            ["N"],
            [(1,)],
        )
        assert seen == {
            "timeout": 15,
            "connect_timeout": oq.CONNECT_BUDGET_S,
            "max_rows": 7,
        }
        assert oq.CONNECT_BUDGET_S == 5.0 and oq.CONNECT_BUDGET_S < TIMEOUT_S
        assert run_open_query.__defaults__[0] is oq._run_select_open

    def test_a_cancel_during_connect_stops_the_statement_before_it_runs(
        self, monkeypatch
    ):
        """V6: the slot is registered BEFORE the connect; a cancel that lands
        while connecting is honoured the moment the connection exists and the
        statement never executes."""
        started = threading.Event()
        release = threading.Event()
        executed = []

        class Cur:
            description = [("N",)]

            def execute(self, sql, params):
                executed.append(sql)

            def fetchmany(self, n):
                return [(1,)]

            def close(self):
                pass

        class Conn:
            closed = False

            def cursor(self):
                return Cur()

            def close(self):
                Conn.closed = True

        def slow_connect(timeout=None, connect_timeout=None):
            started.set()
            release.wait(5)
            return Conn()

        monkeypatch.setattr(db, "connect", slow_connect)
        result = {}

        def work():
            try:
                db.run_select("SELECT 1 FROM HOLIDAY", timeout=1)
            except BaseException as e:
                result["error"] = e

        t = threading.Thread(target=work, daemon=True)
        t.start()
        assert started.wait(2)
        with db._ACTIVE_LOCK:
            assert db._ACTIVE.get(t.ident) is db._CONNECTING
        assert db.cancel_thread(t.ident) is True  # cancelled while connecting
        release.set()
        t.join(5)
        assert not t.is_alive()
        assert executed == []  # the statement never ran
        assert isinstance(result["error"], TimeoutError)
        assert Conn.closed
        with db._ACTIVE_LOCK:
            assert t.ident not in db._ACTIVE and t.ident not in db._CANCELLED

    def test_the_deadline_cancels_a_worker_still_connecting(self, monkeypatch):
        from mcp_server.open_query import _DeadlineExceeded, _run_with_deadline

        executed = []
        release = threading.Event()

        class Cur:
            description = [("N",)]

            def execute(self, sql, params):
                executed.append(sql)

            def fetchmany(self, n):
                return [(1,)]

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        def slow_connect(timeout=None, connect_timeout=None):
            release.wait(5)
            return Conn()

        monkeypatch.setattr(db, "connect", slow_connect)
        t0 = time.perf_counter()
        with pytest.raises(_DeadlineExceeded):
            _run_with_deadline(db.run_select, "SELECT 1 FROM HOLIDAY", 0.3)
        assert time.perf_counter() - t0 < 2
        release.set()
        time.sleep(0.3)
        assert executed == []

    def test_connect_passes_the_budget_to_the_probe_and_the_handshake(
        self, monkeypatch
    ):
        seen = {}

        class Raw:
            def settimeout(self, t):
                seen["settimeout"] = t

        class Stream:
            _sock = Raw()

        class FakeConn:
            sock = Stream()

        class Probe:
            def close(self):
                pass

        monkeypatch.setattr(
            db.socket,
            "create_connection",
            lambda addr, timeout=None: seen.update(probe=timeout) or Probe(),
        )
        monkeypatch.setattr(
            db.firebirdsql,
            "connect",
            lambda **kw: seen.update(handshake=kw["timeout"]) or FakeConn(),
        )
        monkeypatch.setattr(db, "load_dotenv", lambda: None)
        monkeypatch.setenv("DB_HOST", "h")
        monkeypatch.setenv("DB_PORT", "3050")
        db.connect(15, connect_timeout=5)
        assert seen == {"probe": 5, "handshake": 5, "settimeout": 15}
        db.connect(None)
        assert seen["probe"] == db.CONNECT_TIMEOUT_S and seen["settimeout"] is None
