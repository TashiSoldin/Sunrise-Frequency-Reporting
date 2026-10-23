"""Fable eighth review (23 Oct 2026, branch 9eeb6400): the structural
attacks on the shape pass that HELD — 116 statements, every verdict as the
gate gave it that day (accept, or refuse:N for shape rule N; refuse:0 for a
general-guard refusal before the shape check). Generated from the review's
probe battery; the ids are the battery's.

Groups: how a statement "touches" a windowed table (alias spelling, a
partner aliased ROUTING, quoted identifiers, the view joined to AGENTDRIVER);
one block (SELECT / WITH inside literals, subqueries after HAVING / in ORDER
BY / in IN / EXISTS, CASE, IIF, COALESCE, concatenation, parenthesised items);
the conjunct splitter (AND in a literal, AND with no spaces, chained
comparisons, IS [NOT] NULL vs NOT, parentheses, OR, BETWEEN hijacking the
next conjunct, BETWEEN off the window column); the operator and literal set
(literal on the left, 1e5 / .5 / +1 / 0x1F, ESCAPE, SIMILAR TO, COLLATE,
CURRENT_DATE, 'TODAY', the non-ISO date forms, a 32-day BETWEEN, a lone
bound, an IN of dates, an unquoted / blank / LIKE key, nested IN items); the
ON check (two equalities, reversed, self-join, partner-to-partner, wrapped,
expression, USING, RIGHT, LEFT OUTER, a partner twice, key only on the
partner, a comma list after ON); and the select list / GROUP / HAVING / ORDER
/ ROWS forms (position, `+ 0`, FIRST SKIP, ROWS, FETCH, OFFSET, DISTINCT in an
aggregate, HAVING with OR / BETWEEN / a column, PLAN, FOR UPDATE, r.*, v.*,
the four-way keyed join, MANIFEST comparisons, a second WHERE / GROUP BY,
column aliases, a constant select item, NULL, NULLS FIRST, COLLATE).

Firebird's own reading of the lexer-parity cases, prepared or run on 23 Oct:
`1AND` and `'x'AND` are two tokens for Firebird too; '20261019' and
'2026-10-19 10:00' pass the gate and Firebird refuses them at execute with
"conversion error from string"; ROWS 5 TO 1 is a Firebird error; 'TODAY'
beside a key runs on the key.
"""

import re

import pytest

from mcp_server.open_query import GuardError, check_open_query

HELD = [
    (
        "S01",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS = 'SELECT 1 FROM EVENT'",
    ),
    (
        "S02",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS = 'WITH q AS (SELECT 1) SELECT 1'",
    ),
    (
        "S03",
        "accept",
        "SELECT ROUTING.WAYBILL FROM ROUTING ROUTING WHERE ROUTING.WAYBILL = '102155314'",
    ),
    (
        "S04",
        "accept",
        "SELECT r.WAYBILL, ROUTING.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE ROUTING ON ROUTING.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314' AND ROUTING.WAYBILL = '102155314'",
    ),
    (
        "S05",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE ROUTING ON ROUTING.WAYBILL = r.WAYBILL WHERE ROUTING.WAYBILL = '102155314'",
    ),
    ("S06", "accept", "SELECT r.WAYBILL FROM ROUTING r WHERE WAYBILL = '102155314'"),
    (
        "S07",
        "refuse:0",
        "SELECT r.WAYBILL FROM \"ROUTING\" r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S08",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE r ON r.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S09",
        "refuse:2",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v JOIN AGENTDRIVER d ON d.AGENT = v.AGENT WHERE v.WAYBILL = '102155314' AND d.AGENT = 1",
    ),
    (
        "S10",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = '102155314' HAVING COUNT(*) > (SELECT 1 FROM HOLIDAY)",
    ),
    (
        "S11",
        "refuse:1",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY (SELECT 1 FROM HOLIDAY)",
    ),
    (
        "S12",
        "refuse:1",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IN (SELECT WAYBILL FROM VIEW_WBANALYSE)",
    ),
    (
        "S13",
        "refuse:5",
        "SELECT CASE WHEN r.LEG = 1 THEN 1 ELSE 0 END FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S14",
        "refuse:1",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND EXISTS (SELECT 1 FROM HOLIDAY)",
    ),
    (
        "S15",
        "refuse:1",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' UNION SELECT r.WAYBILL, r.LEG FROM ROUTING r",
    ),
    ("S16", "refuse:5", "SELECT (r.LEG) FROM ROUTING r WHERE r.WAYBILL = '102155314'"),
    (
        "S17",
        "refuse:5",
        "SELECT IIF(r.LEG = 1, 1, 0) FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S18",
        "refuse:5",
        "SELECT r.LEG || '' FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S19",
        "refuse:5",
        "SELECT COALESCE(r.LEG, 0) FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S20",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS = 'A AND B'",
    ),
    (
        "S21",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314'AND r.LEG = 1",
    ),
    (
        "S22",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.LEG = 1AND r.WAYBILL = '102155314'",
    ),
    (
        "S23",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' = 'x'",
    ),
    (
        "S24",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 1 = 1",
    ),
    (
        "S25",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IS NOT NULL",
    ),
    (
        "S26",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE NOT r.WAYBILL = 'x'",
    ),
    (
        "S27",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG NOT IN (1)",
    ),
    (
        "S28",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND NOT r.LEG IS NULL",
    ),
    (
        "S29",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG IS NOT NULL IS NOT NULL",
    ),
    (
        "S30",
        "refuse:0",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG IS DISTINCT FROM 1",
    ),
    (
        "S31",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 1 IS NOT NULL",
    ),
    (
        "S32",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND (r.LEG = 1)",
    ),
    (
        "S33",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE (r.WAYBILL = '102155314')",
    ),
    (
        "S34",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 1 OR r.LEG = 2",
    ),
    (
        "S35",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.LEG BETWEEN 1 AND r.WAYBILL = '102155314'",
    ),
    (
        "S36",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG BETWEEN 1 AND 2",
    ),
    (
        "S37",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.BOOKDATE BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "S38",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' AND r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "S40",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE '102155314' = r.WAYBILL",
    ),
    (
        "S41",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 1e5",
    ),
    (
        "S42",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = .5",
    ),
    (
        "S43",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = +1",
    ),
    (
        "S44",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = -1",
    ),
    (
        "S45",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 1.5",
    ),
    (
        "S46",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG = 0x1F",
    ),
    (
        "S47",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS LIKE 'A%' ESCAPE '!'",
    ),
    (
        "S48",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS STARTING WITH 'A'",
    ),
    (
        "S49",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS CONTAINING 'A'",
    ),
    (
        "S50",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS SIMILAR TO 'A'",
    ),
    (
        "S51",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS = 'a' || 'b'",
    ),
    (
        "S52",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.STATUS = 'a' COLLATE UNICODE",
    ),
    (
        "S53",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.AGENTDATE = CURRENT_DATE",
    ),
    (
        "S54",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.AGENTDATE = 'TODAY'",
    ),
    (
        "S55",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN 'YESTERDAY' AND 'TODAY'",
    ),
    (
        "S56",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '10/19/2026' AND '10/21/2026'",
    ),
    (
        "S57",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '19.10.2026' AND '21.10.2026'",
    ),
    (
        "S58",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '19-OCT-2026' AND '21-OCT-2026'",
    ),
    (
        "S59",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '20261019' AND '20261021'",
    ),
    (
        "S60",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19 10:00' AND '2026-10-21'",
    ),
    (
        "S61",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN DATE '2026-10-19' AND TIMESTAMP '2026-10-21 00:00:00'",
    ),
    (
        "S62",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-11-19'",
    ),
    (
        "S63",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE < '2026-11-01'",
    ),
    (
        "S64",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE <= '2026-11-01'",
    ),
    (
        "S65",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-19'",
    ),
    (
        "S66",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.AGENTDATE IN ('2026-10-19', '2026-10-20')",
    ),
    (
        "S67",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 102155314",
    ),
    ("S68", "refuse:3", "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = ''"),
    (
        "S69",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL LIKE '1021%'",
    ),
    (
        "S70",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL IN ('a' 'b')",
    ),
    (
        "S71",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG IN (1, (2))",
    ),
    (
        "S72",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG IN (-1)",
    ),
    (
        "S73",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.LEG IN (1, 2)",
    ),
    (
        "S74",
        "refuse:3",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' AND r.MANIFEST + 0 = 5",
    ),
    (
        "S80",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL AND 1 = 1 WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S81",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON r.WAYBILL = w.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S82",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = w.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S83",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST JOIN AGENTDRIVER d ON d.AGENT = m.AGENT WHERE r.MANIFEST = 37733 AND m.MANIFEST = 37733 AND d.AGENT = 1",
    ),
    (
        "S84",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON (w.WAYBILL = r.WAYBILL) WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S85",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL || '' WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S86",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w USING (WAYBILL) WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S87",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r RIGHT JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S88",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r LEFT OUTER JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314'",
    ),
    (
        "S89",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL JOIN VIEW_WBANALYSE w2 ON w2.WAYBILL = r.WAYBILL WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND w2.WAYBILL = '102155314'",
    ),
    (
        "S90",
        "refuse:3",
        "SELECT w.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE w.WAYBILL = '102155314'",
    ),
    (
        "S91",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL, MANIFEST m WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND m.MANIFEST = 1",
    ),
    (
        "S92",
        "accept",
        "SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY 1",
    ),
    (
        "S93",
        "refuse:5",
        "SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY 1 + 0",
    ),
    (
        "S94",
        "accept",
        "SELECT r.MANIFEST + 0 FROM ROUTING r WHERE r.WAYBILL = '102155314' GROUP BY r.MANIFEST + 0",
    ),
    (
        "S95",
        "refuse:5",
        "SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY r.MANIFEST + 1",
    ),
    (
        "S96",
        "accept",
        "SELECT FIRST 10 SKIP 5 r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    (
        "S97",
        "accept",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' ROWS 1 TO 5",
    ),
    (
        "S98",
        "refuse:5",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' FETCH FIRST 5 ROWS ONLY",
    ),
    (
        "S99",
        "refuse:5",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' OFFSET 5 ROWS",
    ),
    (
        "S100",
        "accept",
        "SELECT COUNT(DISTINCT r.WAYBILL) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "S101",
        "refuse:5",
        "SELECT COUNT(DISTINCT r.WAYBILL || '') FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "S102",
        "accept",
        "SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' GROUP BY r.MTYPE HAVING COUNT(*) > 1",
    ),
    (
        "S103",
        "refuse:5",
        "SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' GROUP BY r.MTYPE HAVING COUNT(*) > 1 OR COUNT(*) < 0",
    ),
    (
        "S104",
        "refuse:5",
        "SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' GROUP BY r.MTYPE HAVING COUNT(*) BETWEEN 1 AND 2",
    ),
    (
        "S105",
        "refuse:5",
        "SELECT r.MTYPE, COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' GROUP BY r.MTYPE HAVING r.MTYPE = 'M'",
    ),
    (
        "S106",
        "refuse:0",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' PLAN (r NATURAL)",
    ),
    (
        "S107",
        "refuse:0",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' FOR UPDATE",
    ),
    ("S108", "refuse:0", "SELECT r.* FROM ROUTING r WHERE r.WAYBILL = '102155314'"),
    (
        "S109",
        "accept",
        "SELECT v.* FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = '102155314'",
    ),
    ("S110", "accept", "SELECT * FROM VIEW_EVENTSCANS WHERE WAYBILL = '102155314'"),
    (
        "S111",
        "accept",
        "SELECT r.WAYBILL, w.CUSTNAME, m.AGENT, d.DRIVER FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE r.WAYBILL = '102155314' AND w.WAYBILL = '102155314' AND m.MANIFEST = 37733 AND d.AGENT = 30105",
    ),
    (
        "S112",
        "refuse:4",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-21' AND '2026-10-21' AND v.MANIFEST > 0",
    ),
    (
        "S113",
        "refuse:4",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-21' AND '2026-10-21' AND v.MANIFEST IS NOT NULL",
    ),
    (
        "S114",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-19' AND '2026-10-21' AND r.MANIFEST <> 0",
    ),
    (
        "S115",
        "refuse:5",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' WHERE r.LEG = 1",
    ),
    (
        "S116",
        "refuse:5",
        "SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = '102155314' GROUP BY r.LEG GROUP BY r.LEG",
    ),
    (
        "S117",
        "accept",
        "SELECT r.WAYBILL WB, r.LEG AS L FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
    ("S118", "accept", "SELECT 1 FROM ROUTING r WHERE r.WAYBILL = '102155314'"),
    ("S119", "refuse:5", "SELECT NULL FROM ROUTING r WHERE r.WAYBILL = '102155314'"),
    (
        "S120",
        "refuse:5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY r.WAYBILL NULLS FIRST",
    ),
    (
        "S121",
        "refuse:5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = '102155314' ORDER BY r.WAYBILL COLLATE UNICODE",
    ),
    (
        "S122",
        "accept",
        "SELECT DISTINCT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = '102155314'",
    ),
]


def _verdict(sql):
    try:
        check_open_query(sql)
        return "accept"
    except GuardError as e:
        m = re.search(r"windowed shape rule (\d)", str(e))
        return "refuse:" + (m.group(1) if m else "0")


@pytest.mark.parametrize("pid,verdict,sql", HELD, ids=[h[0] for h in HELD])
def test_the_structural_attack_still_holds(pid, verdict, sql):
    assert _verdict(sql) == verdict
