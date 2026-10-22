"""Sixth Fable review (22 Oct 2026), S1 — the invariant behind the fix, over a
corpus: every table-position item the allowlist scan sees is attributed to a
SELECT block by the window check (one walk, no second loop to disagree), and
the gate's verdict on each statement is the one the reviews recorded.

The corpus is the sixth review's two probe batteries: the accepted forms, the
statements of reviews 1–6 (B1–B4, H1, M1, M2, R1–R6, T1–T5, Q1–Q3, the 20 Oct
F1/F2, the fifth review's F1–F3, S1), the DENIED_COLUMNS / star shapes, and
the new-ground shapes. Verdicts marked "accept" are correct accepts (the key
is a genuine top-level conjunct); everything else refuses.
"""

from collections import Counter

import pytest

import mcp_server.open_query as oq
from mcp_server.open_query import GuardError, check_open_query

IN100 = ", ".join(f"'W{i}'" for i in range(100))
IN101 = ", ".join(f"'W{i}'" for i in range(101))

CORPUS = [
    # --- prior findings ---
    (
        "B1",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' UNION ALL SELECT r.WAYBILL FROM ROUTING r",
    ),
    (
        "B2",
        "refuse",
        "SELECT h.HOLIDAY FROM HOLIDAY h LEFT JOIN ROUTING r ON r.WAYBILL = 'X'",
    ),
    (
        "B2b",
        "refuse",
        "SELECT h.HOLIDAY FROM ROUTING r RIGHT JOIN HOLIDAY h ON r.WAYBILL = 'X'",
    ),
    (
        "B3a",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE (r.WAYBILL = 'X') IS NOT FALSE",
    ),
    (
        "B3b",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE IIF(r.WAYBILL = 'X', 1, 1) = 1",
    ),
    (
        "B3c",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE COALESCE(r.WAYBILL, 'X') = 'X'",
    ),
    ("B4", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 0"),
    ("B4b", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST IN (0, 5)"),
    (
        "H1",
        "refuse",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE w WHERE w.WAYBILL IN (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02')",
    ),
    (
        "H1b",
        "refuse",
        "WITH q AS (SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT w.WAYBILL FROM q JOIN VIEW_WBANALYSE w ON w.WAYBILL = q.WAYBILL",
    ),
    ("R1", "refuse", "SELECT 1 FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, EVENT e"),
    (
        "R1b",
        "refuse",
        "SELECT 1 FROM (SELECT 1 X FROM HOLIDAY) t, CONTACT c WHERE c.WEBPASSWORD = 'x'",
    ),
    (
        "R2",
        "refuse",
        "SELECT 1 FROM HOLIDAY h NATURAL JOIN HUB u, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "R2b",
        "refuse",
        "SELECT 1 FROM ROUTING r, HOLIDAY h NATURAL JOIN HUB u WHERE r.WAYBILL = 'X'",
    ),
    ("R3", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' OR 1 = 1"),
    (
        "R3b",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE 1 = 1 OR r.LEG = 1 AND r.WAYBILL = 'X'",
    ),
    ("R4", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL ~= 'X'"),
    ("R4b", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL ^= 'X'"),
    (
        "R5",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' PLAN (R NATURAL)",
    ),
    (
        "R6",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE IN ('2026-10-01')",
    ),
    (
        "T1",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE CASE WHEN 1 = 1 AND r.WAYBILL = 'X' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "T2",
        "refuse",
        "SELECT (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT FIRST 1 WEBPASSWORD FROM CONTACT) FROM HOLIDAY",
    ),
    (
        "T2b",
        "refuse",
        "SELECT 1 FROM HOLIDAY WHERE EXISTS (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT 1 FROM EVENT)",
    ),
    (
        "T3",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND q'{'} = q'{' OR 1=1}'",
    ),
    (
        "T3b",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND x'41' = x'41'",
    ),
    ("T5", "accept", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X';"),
    (
        "T5b",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X'; SELECT 1 FROM EVENT",
    ),
    ("Q1", "refuse", "SELECT 1 FROM HOLIDAY -- x\r, EVENT e"),
    ("Q1b", "refuse", "SELECT 1 FROM HOLIDAY /* x */, EVENT e"),
    ("Q1c", "refuse", "SELECT 1 FROM HOLIDAY WHERE 1 = 1 -- , EVENT e"),
    (
        "Q2",
        "refuse",
        "SELECT 1 FROM HOLIDAY h JOIN HUB u ON u.HUB STARTING WITH 'A', EVENT e",
    ),
    (
        "Q2b",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MTYPE STARTING WITH 'M' OR 1 = 1",
    ),
    ("F1star", "refuse", "SELECT * FROM (SELECT * FROM CONTACT) t (A1, A2)"),
    (
        "F1star2",
        "refuse",
        "SELECT NAME AS A FROM CONTACT WHERE 1 = 0 UNION ALL SELECT * FROM CONTACT",
    ),
    ("F2branch", "refuse", "SELECT IP FROM BRANCH"),
    ("F1except", "refuse", "SELECT 1 FROM HOLIDAY EXCEPT, EVENT e"),
    ("F1except2", "refuse", "SELECT 1 FROM HOLIDAY INTERSECT JOIN EVENT e ON 1 = 1"),
    (
        "F1except3",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' EXCEPT SELECT r.WAYBILL FROM ROUTING r",
    ),
    (
        "F2cte",
        "refuse",
        "WITH EVENT AS (SELECT 1 X FROM EVENT e) SELECT X FROM EVENT x, HOLIDAY h",
    ),
    (
        "F2cte2",
        "refuse",
        "WITH ROUTING AS (SELECT 1 X FROM ROUTING r) SELECT X FROM ROUTING x, HOLIDAY h",
    ),
    ("F3lock", "refuse", "SELECT 1 FROM HOLIDAY h ORDER BY STARTING WITH LOCK"),
    ("F3lock2", "refuse", "SELECT 1 FROM HOLIDAY h WHERE h.HOLIDAY = 'x' WITH LOCK"),
    ("F3lock3", "refuse", "SELECT 1 FROM HOLIDAY h WHERE A$STARTING WITH LOCK"),
    ("M1", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 12345"),
    ("M2", "refuse", "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.TRACKNO = ''"),
    (
        "cap",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1 "
        + "AND 1 = 1 " * 500,
    ),
    (
        "capchar",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1 "
        + "AND 1 = 1 " * 390
        + " ",
    ),
    # --- accepted forms ---
    (
        "A1",
        "accept",
        "SELECT r.WAYBILL, r.LEG, r.MTYPE FROM ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "A2",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IN (" + IN100 + ")",
    ),
    (
        "A2x",
        "refuse",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IN (" + IN101 + ")",
    ),
    (
        "A3",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
    ),
    (
        "A4",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-09-01' AND '2026-10-01'",
    ),
    (
        "A4x",
        "refuse",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-09-01' AND '2026-10-02'",
    ),
    (
        "A5",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X'",
    ),
    (
        "A6",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.TRACKNO = 'X'",
    ),
    (
        "A7",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.MANIFEST = 37733",
    ),
    (
        "A8",
        "accept",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "A8x",
        "refuse",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-18' AND '2026-10-21'",
    ),
    (
        "A9",
        "accept",
        "WITH legs AS (SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT COUNT(*) FROM legs",
    ),
    (
        "A10",
        "accept",
        "SELECT r.LEG, w.ACCNUM FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'X' AND w.WAYBILL = 'X'",
    ),
    (
        "A11",
        "accept",
        "SELECT r.LEG, d.DRIVER FROM ROUTING r JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE r.WAYBILL = 'X' AND d.AGENT = 123",
    ),
    (
        "A12",
        "accept",
        "SELECT v.RECIPIENT, v.USERNAME FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X'",
    ),
    ("D1", "refuse", "SELECT r.DELOTP FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    ("D2", "refuse", "SELECT r.* FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    (
        "D3",
        "refuse",
        "WITH q AS (SELECT * FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT COUNT(*) FROM q",
    ),
    (
        "D4",
        "refuse",
        "SELECT * FROM (SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 'X') t",
    ),
    ("D5", "accept", "SELECT c.ACCNUM, c.DELOTP FROM CUSTOMER c WHERE c.ACCNUM = 'X'"),
    # --- sixth review, S1 and the new ground ---
    (
        "S1a",
        "refuse",
        "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r WHERE r0.WAYBILL = 'X'",
    ),
    (
        "S1a-ctl",
        "refuse",
        "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t, ROUTING r WHERE r0.WAYBILL = 'X'",
    ),
    (
        "S1b",
        "refuse",
        "SELECT v0.WAYBILL FROM VIEW_EVENTSCANS v0, (SELECT 1 X FROM HOLIDAY) t (A), VIEW_EVENTSCANS v WHERE v0.WAYBILL = 'X'",
    ),
    (
        "S1c",
        "refuse",
        "SELECT t.A, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-31') t (A) JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.A",
    ),
    (
        "S1c-ctl",
        "refuse",
        "SELECT t.WAYBILL, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-31') t JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.WAYBILL",
    ),
    (
        "S1d",
        "refuse",
        "SELECT t.A, m.ROUTE FROM (SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = 'X') t (A), MANIFEST m WHERE m.MANIFEST = t.A",
    ),
    (
        "S1e",
        "refuse",
        "SELECT t.A, d.DRIVER FROM (SELECT r.AGENT FROM ROUTING r WHERE r.WAYBILL = 'X') AS t (A), AGENTDRIVER d WHERE d.AGENT = t.A",
    ),
    (
        "S1f",
        "refuse",
        "SELECT r0.WAYBILL FROM ROUTING r0 JOIN (SELECT 1 X FROM HOLIDAY) t (A) ON 1 = 1 JOIN ROUTING r ON r.WAYBILL = r0.WAYBILL WHERE r0.WAYBILL = 'X'",
    ),
    (
        "S1g",
        "accept",
        "SELECT r.WAYBILL FROM (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    ("N1", "refuse", "SELECT 1 FROM HOLIDAY h OUTER JOIN ROUTING r ON r.WAYBILL = 'X'"),
    (
        "N2",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' IS NOT NULL",
    ),
    (
        "N3",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE NOT BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    ("N4", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE NOT r.WAYBILL = 'X'"),
    ("N5", "refuse", "SELECT r.WAYBILL FROM ROUTING r, HOLIDAY h WHERE WAYBILL = 'X'"),
    (
        "N7",
        "refuse",
        "SELECT 1 FROM HOLIDAY h WHERE h.HOLIDAY IS DISTINCT FROM ROUTING",
    ),
    (
        "N8",
        "refuse",
        "WITH a AS (SELECT X FROM b), b AS (SELECT 1 X FROM HOLIDAY) SELECT X FROM a, ROUTING r",
    ),
    (
        "N9",
        "refuse",
        "WITH q AS (SELECT h.HOLIDAY X FROM HOLIDAY h) SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN (SELECT X FROM q)",
    ),
    (
        "N10",
        "accept",
        "WITH AGENTDATE AS (SELECT 1 X FROM HOLIDAY) SELECT r.WAYBILL FROM ROUTING r, AGENTDATE a WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "N11",
        "refuse",
        "SELECT 1 FROM (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT X FROM q) t, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "N12",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' FOR UPDATE",
    ),
    (
        "N13",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' RETURNING r.WAYBILL",
    ),
    ("N14", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' INTO :x"),
    (
        "N15",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND (1 = 1 OR r.LEG = 1)",
    ),
    (
        "N16",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE (r.WAYBILL = 'X' OR 1 = 1) AND 1 = 1",
    ),
    (
        "N17",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE ((r.WAYBILL = 'X')) AND (1 = 1 OR r.LEG = 1)",
    ),
    (
        "N18",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL BETWEEN 'A' AND 'Z'",
    ),
    (
        "N19",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = (SELECT FIRST 1 h.HOLIDAY FROM HOLIDAY h)",
    ),
    (
        "N20",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN (SELECT h.HOLIDAY FROM HOLIDAY h)",
    ),
    (
        "N21",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01'",
    ),
    (
        "N22",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE <= '2026-11-01'",
    ),
    (
        "N23",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE > '2026-09-30' AND r.AGENTDATE < '2026-11-01'",
    ),
    (
        "N24",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-1' AND '2026-10-02'",
    ),
    (
        "N25",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND x BETWEEN 1 AND 2 OR 1 = 1",
    ),
    (
        "N26",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE CASE WHEN r.WAYBILL = 'X' THEN 1 ELSE 1 END = 1",
    ),
    (
        "N27",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE EXISTS (SELECT 1 FROM HOLIDAY h WHERE r.WAYBILL = 'X')",
    ),
    (
        "N28",
        "refuse",
        "SELECT 1 FROM HOLIDAY h WHERE EXISTS (SELECT 1 FROM ROUTING r WHERE r.WAYBILL = h.HOLIDAY)",
    ),
    (
        "N29",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' UNION SELECT r2.WAYBILL FROM ROUTING r2 WHERE r2.LEG = 1",
    ),
    (
        "N30",
        "refuse",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE w, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "N31",
        "refuse",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE AS w JOIN ROUTING r ON r.WAYBILL = w.WAYBILL WHERE r.WAYBILL = 'X'",
    ),
    (
        "N32",
        "refuse",
        "SELECT d.DRIVER FROM AGENTDRIVER d JOIN ROUTING r ON r.AGENT = d.AGENT WHERE r.MANIFEST = 5",
    ),
    (
        "N33",
        "refuse",
        "SELECT m.ROUTE FROM MANIFEST m WHERE EXISTS (SELECT 1 FROM ROUTING r WHERE r.MANIFEST = m.MANIFEST AND r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02')",
    ),
    (
        "N34",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.LEG IS DISTINCT FROM 1",
    ),
    ("N35", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN ('X' 'Y')"),
    (
        "N36",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN ((SELECT 'X' FROM HOLIDAY))",
    ),
    ("N37", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 1.5"),
    ("N38", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = -1"),
    ("N39", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 1e3"),
    ("N40", "refuse", "SELECT r.WAYBILL FROM ROUTING r WHERE 'X' = r.WAYBILL"),
    (
        "N41",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1 GROUP BY r.WAYBILL HAVING COUNT(*) > 0 OR 1 = 1",
    ),
    (
        "N42",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE DATEDIFF(DAY FROM r.AGENTDATE TO r.AGENTDATE) = 0 AND r.WAYBILL = 'X'",
    ),
    ("N43", "refuse", "SELECT 1 FROM HOLIDAY h, LATERAL (SELECT 1 FROM ROUTING r) t"),
    (
        "N44",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1\n/*\n*/",
    ),
    (
        "N45",
        "refuse",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' ROWS 1 TO 10 WITH LOCK",
    ),
    (
        "N46",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.LEG = ANY (SELECT 1 FROM HOLIDAY)",
    ),
    # --- S2 (b), the key-only MANIFEST rule ---
    (
        "S2",
        "refuse",
        "SELECT FIRST 5 v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
    ),
    (
        "S2b",
        "refuse",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST > 0",
    ),
]


@pytest.mark.parametrize("pid,expect,sql", CORPUS, ids=[c[0] for c in CORPUS])
def test_the_verdict_is_the_one_the_reviews_recorded(pid, expect, sql):
    if expect == "accept":
        check_open_query(sql)
    else:
        with pytest.raises(GuardError):
            check_open_query(sql)


# Statements the gate refuses before the walk runs (a bare CR, a comment, an
# introduced literal, a second statement) are not meaningful to walk: their
# text is exactly what the strippers cannot be trusted with.
_BEFORE_THE_WALK = ("Q1", "Q1b", "Q1c", "T3", "T3b", "T5b", "N44", "cap", "capchar")


@pytest.mark.parametrize(
    "pid,sql",
    [(c[0], c[2]) for c in CORPUS if c[0] not in _BEFORE_THE_WALK],
    ids=[c[0] for c in CORPUS if c[0] not in _BEFORE_THE_WALK],
)
def test_every_table_the_scanner_sees_is_attributed_to_a_block(pid, sql):
    """The S1 invariant: the allowlist scan and the window check read the
    same walk, so every relation name in table position lands in exactly one
    SELECT block — or the statement refuses, which these do not for this
    reason (attribution never raises on the corpus)."""
    cleaned = oq._strip_literals_and_comments(sql.rstrip().removesuffix(";"))
    scanned, problem = oq._scan_from_lists(cleaned)
    if problem:
        # the walk itself refused (a parenthesised join, a stray token …) —
        # nothing is attributed because nothing is accepted
        with pytest.raises(GuardError):
            check_open_query(sql)
        return
    attributed = oq._attributed_table_refs(sql)
    names = [n for n, _b in attributed if n != "(derived)"]
    assert Counter(names) == Counter(scanned), (pid, attributed, scanned)
    assert all(isinstance(b, int) and b >= 1 for _n, b in attributed)


def test_an_item_the_window_tokenizer_cannot_place_refuses_not_skips(monkeypatch):
    """Belt and braces for the single walk: if the attribution ever met an
    item it cannot place (a token at an offset the window tokenizer does not
    start a token at), the statement refuses — never a silent skip."""
    real = oq._from_items

    def shifted(cleaned):
        items, problem = real(cleaned)
        for it in items:
            it.char += 1  # an offset no token starts at
        return items, problem

    monkeypatch.setattr(oq, "_from_items", shifted)
    with pytest.raises(GuardError, match="could not attribute to a SELECT block"):
        check_open_query("SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X'")
    with pytest.raises(GuardError, match="could not attribute to a SELECT block"):
        check_open_query("SELECT NAME FROM HOLIDAY")  # not windowed — still refuses
