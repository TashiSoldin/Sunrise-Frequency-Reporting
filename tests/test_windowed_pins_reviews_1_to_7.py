"""Every statement reviews 1–7 pinned on ROUTING or VIEW_EVENTSCANS (21–23 Oct
2026: B1–B4, H1, M1, M2, R1–R8, T1–T5, Q1–Q3, both F1/F2 sets, F3, S1–S5,
V1–V3 and the accepted forms), re-pinned under the ONE-BLOCK SHAPE (design
change, 23 Oct 2026). A verdict "refuse:N" means the shape rule N refuses it
(0 = a general-guard refusal before the shape check: allowlist, star ban,
DENIED_COLUMNS, WITH position, comments, literals, PLAN, length). Shapes the
old judge accepted that the one-block shape makes unexpressible (CTEs,
derived tables, subqueries, HOLIDAY / HUB joins, comma joins, OR groups,
CASE, unqualified columns in a join) are pinned as refusals; the forms the
signed rule allows stay accepted.

Generated from the old pins by the design-change pass; the ids name the old
file and line (oq = tests/test_open_query.py, r6c = the review 6 corpus,
r6s1 / r6s2 = the review 6 S1 / S2 files, r7 = the review 7 file) or the
hand-carried `where` fragments.
"""

import pytest

from mcp_server.open_query import GuardError, check_open_query

PINS = [
    (
        "oq-1472",
        "accept",
        "SELECT WAYBILL, LEG, MANIFEST FROM ROUTING WHERE WAYBILL = '102155314'",
    ),
    (
        "oq-1473",
        "accept",
        "SELECT EVENTDATE, EVENTTIME, NAME, HUB FROM VIEW_EVENTSCANS WHERE WAYBILL = '102155314'",
    ),
    (
        "oq-1884",
        "refuse:3",
        "SELECT FIRST 5 r.WAYBILL, r.LEG, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL IN ('A', 'B')",
    ),
    (
        "oq-1798",
        "accept",
        "SELECT r.WAYBILL, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'A' AND w.WAYBILL = 'A'",
    ),
    (
        "oq-1805",
        "refuse:2",
        "SELECT r.WAYBILL FROM VIEW_WBANALYSE w JOIN ROUTING r ON r.WAYBILL = w.WAYBILL AND r.AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11' WHERE w.WAYDATE = '2026-10-05'",
    ),
    (
        "oq-1812",
        "refuse:2",
        "SELECT r.LEG, v.NAME FROM ROUTING r JOIN VIEW_EVENTSCANS v ON v.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'A' AND v.WAYBILL = 'A'",
    ),
    (
        "oq-1819",
        "refuse:1",
        "WITH k AS (SELECT WAYBILL, LEG FROM ROUTING WHERE WAYBILL IN ('A', 'B')) SELECT k.WAYBILL, COUNT(*) FROM k GROUP BY 1",
    ),
    (
        "oq-1825",
        "refuse:1",
        "SELECT t.WAYBILL FROM (SELECT WAYBILL FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'A') t",
    ),
    (
        "oq-1925",
        "refuse:2",
        "SELECT r.LEG FROM ROUTING r, VIEW_WBANALYSE w WHERE w.WAYBILL = r.WAYBILL AND r.WAYBILL = 'A'",
    ),
    (
        "oq-1937",
        "refuse:3",
        "SELECT r.LEG, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-1945",
        "refuse:3",
        "SELECT r.WAYBILL, m.AGENT FROM ROUTING r JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
    ),
    (
        "oq-1965",
        "refuse:3",
        "SELECT r.WAYBILL, d.DRIVER FROM ROUTING r JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2047",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' UNION ALL SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11'",
    ),
    (
        "oq-2082",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r LEFT JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2086",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN ROUTING r ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2088",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h INNER JOIN ROUTING r ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2215",
        "refuse:1",
        "WITH k AS (SELECT WAYBILL FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11') SELECT w.CUSTNAME FROM VIEW_WBANALYSE w JOIN k ON k.WAYBILL = w.WAYBILL WHERE w.WAYDATE BETWEEN '2026-10-01' AND '2026-10-11'",
    ),
    (
        "oq-2225",
        "refuse:1",
        "SELECT COUNT(*) FROM VIEW_WBANALYSE w WHERE w.WAYBILL IN (SELECT WAYBILL FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11')",
    ),
    (
        "oq-2337",
        "refuse:2",
        "SELECT r.LEG FROM ROUTING r JOIN HUB h ON h.HUB = r.ORIGHUB JOIN BRANCH b ON b.BRANCH = r.MBRANCH LEFT JOIN HOLIDAY ho ON ho.HOLIDAY = r.AGENTDATE WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2342",
        "refuse:2",
        "SELECT r.LEG FROM HUB h JOIN ROUTING r ON h.HUB = r.ORIGHUB AND r.WAYBILL = 'A' JOIN BRANCH b ON b.BRANCH = r.MBRANCH",
    ),
    (
        "oq-2375",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = LEFT(u.HUB, 3) JOIN ROUTING r ON r.ORIGHUB = u.HUB WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-1512",
        "accept",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL IN ('A', 'B', 'C')",
    ),
    (
        "oq-1513",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
    ),
    (
        "oq-1514",
        "accept",
        "SELECT WAYBILL FROM ROUTING WHERE MANIFEST IN (37733, 37739, 1016558)",
    ),
    (
        "oq-1515",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN DATE '2026-09-01' AND DATE '2026-10-01'",
    ),
    (
        "oq-1516",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE <= '2026-10-07'",
    ),
    (
        "oq-1517",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= DATE '2026-10-01' AND AGENTDATE < DATE '2026-10-08'",
    ),
    (
        "oq-1518",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE = DATE '2026-10-19'",
    ),
    (
        "oq-1519",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN TIMESTAMP '2026-10-01 00:00' AND TIMESTAMP '2026-10-03 23:59'",
    ),
    (
        "oq-1520",
        "accept",
        "SELECT MTYPE, COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11' AND BOOKDATE IS NOT NULL GROUP BY 1",
    ),
    (
        "oq-1521",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11' AND (MTYPE = 'M' OR MTYPE = 'R')",
    ),
    ("oq-1522", "accept", "select waybill from routing where waybill = 'x'"),
    (
        "oq-1532",
        "accept",
        "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE TRACKNO = '1021553140001'",
    ),
    (
        "oq-1533",
        "accept",
        "SELECT WAYBILL FROM VIEW_EVENTSCANS v WHERE v.TRACKNO IN ('A', 'B')",
    ),
    ("oq-1534", "accept", "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE MANIFEST = 37733"),
    (
        "oq-1535",
        "accept",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '2026-10-13' AND DATE '2026-10-15'",
    ),
    (
        "oq-1536",
        "accept",
        "SELECT NAME, COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN '2026-10-13' AND '2026-10-15' GROUP BY NAME",
    ),
    (
        "oq-1537",
        "accept",
        "SELECT NAME, HUB, COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN '2026-10-14' AND '2026-10-15' AND NAME = 'Collected from Origin Address' GROUP BY 1, 2",
    ),
    (
        "oq-1602",
        "accept",
        "SELECT WAYBILL FROM ROUTING WHERE MANIFEST = 37733 AND MBRANCH = 0 AND MTYPE = 'M'",
    ),
    (
        "oq-1610",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11'",
    ),
    (
        "oq-1618",
        "accept",
        "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE WAYBILL IN ('A', 'B')",
    ),
    (
        "oq-2026",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' UNION ALL SELECT COUNT(*) FROM ROUTING r",
    ),
    (
        "oq-2027",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING WHERE ROUTING.WAYBILL = 'A' UNION ALL SELECT COUNT(*) FROM ROUTING",
    ),
    (
        "oq-2028",
        "refuse:1",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'A' UNION ALL SELECT COUNT(*) FROM VIEW_EVENTSCANS v",
    ),
    (
        "oq-2030",
        "refuse:1",
        "SELECT t.N FROM (SELECT COUNT(*) N FROM ROUTING r WHERE r.WAYBILL = 'A' UNION ALL SELECT COUNT(*) FROM ROUTING r) t",
    ),
    (
        "oq-2033",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r UNION ALL SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2061",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r LEFT JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2063",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r LEFT JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE AND r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-07'",
    ),
    (
        "oq-2066",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h RIGHT JOIN ROUTING r ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2067",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r FULL JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2068",
        "refuse:2",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v LEFT JOIN HOLIDAY h ON h.HOLIDAY = v.EVENTDATE AND v.WAYBILL = 'A'",
    ),
    (
        "oq-2070",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r LEFT JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE AND r.AGENTDATE <= '2026-10-07' WHERE r.AGENTDATE >= '2026-10-01'",
    ),
    (
        "oq-2073",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r LEFT OUTER JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE AND r.WAYBILL = 'A'",
    ),
    ("oq-2150", "refuse:4", "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE MANIFEST = 0"),
    (
        "oq-2151",
        "refuse:4",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE MANIFEST IN (0)",
    ),
    (
        "oq-2152",
        "refuse:4",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE MANIFEST IN (37733, 0)",
    ),
    ("oq-2153", "refuse:4", "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST = 0"),
    ("oq-2154", "refuse:4", "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST = -5"),
    (
        "oq-2155",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST IN (-1, 37733)",
    ),
    ("oq-2156", "refuse:4", "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST = '37733'"),
    ("oq-2157", "refuse:4", "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST = 37733.0"),
    (
        "oq-2181",
        "refuse:1",
        "WITH k AS (SELECT WAYBILL FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11') SELECT w.CUSTNAME FROM VIEW_WBANALYSE w JOIN k ON k.WAYBILL = w.WAYBILL",
    ),
    (
        "oq-2185",
        "refuse:1",
        "SELECT w.CUSTNAME FROM VIEW_WBANALYSE w JOIN (SELECT WAYBILL FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11') k ON k.WAYBILL = w.WAYBILL",
    ),
    (
        "oq-2193",
        "refuse:1",
        "SELECT COUNT(*) FROM VIEW_WBANALYSE w WHERE EXISTS (SELECT 1 FROM ROUTING r WHERE r.WAYBILL = w.WAYBILL AND r.AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11')",
    ),
    (
        "oq-2197",
        "refuse:1",
        "SELECT COUNT(*), SUM(w.SUBTOTAL) FROM (SELECT DISTINCT WAYBILL FROM ROUTING WHERE MANIFEST = 37733 AND MBRANCH = 0 AND MTYPE = 'M') t JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.WAYBILL",
    ),
    (
        "oq-2201",
        "refuse:1",
        "SELECT m.NOWB FROM MANIFEST m WHERE m.MANIFEST IN (SELECT MANIFEST FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11')",
    ),
    (
        "oq-2280",
        "accept",
        "SELECT SUM(TOTAL), SUM(VAT) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-01' AND '2026-10-07'",
    ),
    (
        "oq-2288",
        "accept",
        "SELECT LEG, COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-01' AND '2026-10-07' GROUP BY 1",
    ),
    (
        "oq-2360",
        "refuse:0",
        "SELECT COUNT(*) FROM (HOLIDAY h JOIN HUB u ON u.HUB = u.HUB) JOIN ROUTING r ON r.ORIGHUB = u.HUB",
    ),
    ("oq-2361", "refuse:2", "SELECT COUNT(*) FROM HOLIDAY h NATURAL JOIN ROUTING r"),
    (
        "oq-2362",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = LEFT(u.HUB, 3) JOIN ROUTING r ON r.ORIGHUB = u.HUB",
    ),
    (
        "oq-2363",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = RIGHT(u.HUB, 3) JOIN VIEW_EVENTSCANS v ON v.HUB = u.HUB",
    ),
    (
        "oq-2364",
        "refuse:0",
        "SELECT COUNT(*) FROM ROUTING r, (HOLIDAY h JOIN HUB u ON u.HUB = u.HUB)",
    ),
    (
        "oq-2365",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN ROUTING r USING (HUB)",
    ),
    (
        "oq-2389",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND r.LEG = 1 OR r.LEG = 2",
    ),
    (
        "oq-2390",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE 1 = 1 OR 1 = 1 AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2391",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.LEG BETWEEN 1 AND 9 OR 1 = 1 AND r.WAYBILL = 'A'",
    ),
    (
        "oq-2393",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-13' AND '2026-10-15' AND v.HUB = 'JNB' OR v.HUB = 'CPT'",
    ),
    (
        "oq-2396",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND NOT r.LEG = 1 OR r.LEG = 2",
    ),
    (
        "oq-2397",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' OR r.WAYBILL = 'B'",
    ),
    (
        "oq-2398",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN ROUTING r ON r.WAYBILL = 'A' AND r.LEG = 1 OR r.LEG = 2",
    ),
    ("oq-2435", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL {op} 'A'"),
    (
        "oq-2436",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.MANIFEST {op} 37733",
    ),
    (
        "oq-2437",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.TRACKNO {op} 'A'",
    ),
    (
        "oq-2438",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.WAYBILL {op} 'A'",
    ),
    (
        "oq-2489",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE IN ('2026-10-01', '2026-10-02')",
    ),
    (
        "oq-2490",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE IN ('2026-10-01', '2026-10-02')",
    ),
    ("oq-2503", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE ) r.WAYBILL = 'A'"),
    ("oq-2505", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN"),
    ("oq-2506", "refuse:0", "SELECT COUNT(*) FROM ROUTING r JOIN"),
    ("oq-2525", "accept", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A'"),
    (
        "oq-2582",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN 1 = 1 AND r.WAYBILL = 'A' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "oq-2584",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN 1 = 1 AND r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE <= '2026-10-07' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "oq-2587",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE CASE WHEN 1 = 1 AND v.WAYBILL = 'A' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "oq-2589",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN ROUTING r ON CASE WHEN 1 = 1 AND r.WAYBILL = 'A' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "oq-2593",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN 1 = 1 THEN CASE WHEN 1 = 1 AND r.WAYBILL = 'A' AND 1 = 1 THEN 1 ELSE 1 END ELSE 1 END = 1",
    ),
    (
        "oq-2596",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN r.LEG = 1 AND r.WAYBILL = 'A' THEN 1 ELSE 1 END = 1",
    ),
    (
        "oq-2597",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE r.LEG WHEN 1 THEN 1 ELSE 1 END = 1 AND CASE WHEN 1 = 1 AND r.WAYBILL = 'A' THEN 1 END = 1",
    ),
    (
        "oq-2598",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE IIF(1 = 1 AND r.WAYBILL = 'A' AND 1 = 1, 1, 1) = 1",
    ),
    (
        "oq-2599",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE NULLIF(r.WAYBILL = 'A', FALSE)",
    ),
    (
        "oq-2600",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE COALESCE(1 = 1 AND r.WAYBILL = 'A', TRUE)",
    ),
    (
        "oq-2629",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN r.LEG = 1 THEN 1 ELSE 0 = 1",
    ),
    (
        "oq-2630",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN 1 = 1 AND r.WAYBILL = 'A' THEN 1",
    ),
    (
        "oq-2631",
        "refuse:3",
        "SELECT CASE WHEN 1 = 1 THEN 1 END FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN 1 = 1 THEN 1",
    ),
    (
        "oq-1571",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-09-01' AND '2026-10-01'",
    ),
    (
        "oq-1575",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-09-01' AND '2026-10-02'",
    ),
    (
        "oq-1578",
        "accept",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN '2026-10-13' AND '2026-10-15'",
    ),
    (
        "oq-1582",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN '2026-10-13' AND '2026-10-16'",
    ),
    (
        "oq-1586",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= '2026-09-01' AND AGENTDATE < '2026-10-02'",
    ),
    ("oq-1592", "accept", "SELECT WAYBILL FROM ROUTING WHERE MANIFEST = 37733"),
    ("oq-1636", "refuse:3", "SELECT COUNT(*) FROM ROUTING"),
    ("oq-1637", "refuse:3", "SELECT FIRST 5 WAYBILL FROM VIEW_EVENTSCANS"),
    ("oq-1638", "refuse:3", "SELECT WAYBILL FROM ROUTING r"),
    (
        "oq-1641",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN (SELECT MIN(HOLIDAY) FROM HOLIDAY) AND '2026-10-01'",
    ),
    (
        "oq-1645",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= CURRENT_DATE - 400",
    ),
    (
        "oq-1649",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE",
    ),
    ("oq-1652", "refuse:3", "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL = ?"),
    (
        "oq-1654",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL = (SELECT FIRST 1 WAYBILL FROM VIEW_WBANALYSE)",
    ),
    (
        "oq-1658",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL IN (SELECT WAYBILL FROM VIEW_WBANALYSE WHERE WAYDATE = '2026-10-13')",
    ),
    (
        "oq-1663",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'A' OR MTYPE = 'M'",
    ),
    (
        "oq-1667",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE (WAYBILL = 'A' AND LEG = 1) OR MANIFEST = 5",
    ),
    (
        "oq-1670",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'A' OR WAYBILL = 'B'",
    ),
    (
        "oq-1673",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE BOOKDATE BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "oq-1677",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYDATE BETWEEN '2026-10-19' AND '2026-10-19'",
    ),
    (
        "oq-1681",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE ACCNUM = 'S135'",
    ),
    (
        "oq-1685",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE NAME = 'Collected from Origin Address'",
    ),
    (
        "oq-1689",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENT = 30105 AND MTYPE = 'M'",
    ),
    (
        "oq-1694",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-11' AND '2026-10-05'",
    ),
    (
        "oq-1698",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= '2026-10-11' AND AGENTDATE <= '2026-10-05'",
    ),
    (
        "oq-1702",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= '2026-10-01'",
    ),
    (
        "oq-1706",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE <= '2026-10-01'",
    ),
    (
        "oq-1710",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '1899-12-30' AND '2026-10-01'",
    ),
    (
        "oq-1714",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-01' AND '9473-10-01'",
    ),
    (
        "oq-1718",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '01.10.2026' AND '02.10.2026'",
    ),
    ("oq-1722", "refuse:3", "SELECT WAYBILL FROM ROUTING WHERE WAYBILL LIKE 'DSN%'"),
    ("oq-1723", "refuse:3", "SELECT WAYBILL FROM ROUTING WHERE WAYBILL <> 'A'"),
    (
        "oq-1724",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL NOT IN ('A', 'B')",
    ),
    ("oq-1725", "refuse:3", "SELECT WAYBILL FROM ROUTING WHERE NOT (WAYBILL = 'A')"),
    ("oq-1726", "refuse:3", "SELECT WAYBILL FROM ROUTING WHERE NOT WAYBILL = 'A'"),
    (
        "oq-1729",
        "refuse:5",
        "SELECT WAYBILL FROM ROUTING GROUP BY WAYBILL HAVING WAYBILL = 'A'",
    ),
    (
        "oq-1732",
        "refuse:5",
        "SELECT CASE WHEN WAYBILL = 'A' THEN 1 ELSE 0 END FROM ROUTING",
    ),
    (
        "oq-1735",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE w.WAYBILL = 'A'",
    ),
    (
        "oq-1739",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE WAYBILL = 'A'",
    ),
    (
        "oq-1744",
        "refuse:2",
        "SELECT r.LEG, v.NAME FROM ROUTING r JOIN VIEW_EVENTSCANS v ON v.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-1750",
        "refuse:1",
        "WITH k AS (SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'A') SELECT r.WAYBILL FROM ROUTING r JOIN k ON k.WAYBILL = r.WAYBILL",
    ),
    (
        "oq-1757",
        "refuse:1",
        "WITH k AS (SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'A') SELECT ROUTING.WAYBILL FROM ROUTING JOIN k ON k.WAYBILL = ROUTING.WAYBILL",
    ),
    ("oq-1781", "refuse:3", "SELECT COUNT(*) FROM VIEW_EVENTSCANS"),
    (
        "oq-1788",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL LIKE 'SECRETVALUE%'",
    ),
    (
        "oq-1831",
        "refuse:2",
        "SELECT a.LEG FROM ROUTING a JOIN ROUTING b ON b.WAYBILL = a.WAYBILL WHERE a.WAYBILL = 'A'",
    ),
    (
        "oq-1834",
        "refuse:2",
        "SELECT a.LEG FROM ROUTING a JOIN ROUTING b ON b.WAYBILL = a.WAYBILL WHERE a.WAYBILL = 'A' AND b.WAYBILL = 'A'",
    ),
    (
        "oq-1848",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYDATE = '2026-10-19'",
    ),
    (
        "oq-1979",
        "accept",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11'",
    ),
    ("oq-1991", "accept", "SELECT COUNT(*) FROM VIEW_WBANALYSE"),
    (
        "oq-1995",
        "accept",
        "SELECT COUNT(*) FROM MANIFEST m JOIN AGENTDRIVER d ON d.AGENT = m.AGENT",
    ),
    ("oq-2135", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A')"),
    (
        "oq-2138",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.AGENTDATE BETWEEN '2026-10-13' AND '2026-10-15' AND r.LEG = 2)",
    ),
    ("oq-2243", "refuse:3", "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL = 102155314"),
    (
        "oq-2245",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL IN (102155314, 102155340)",
    ),
    (
        "oq-2249",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYBILL = 102155314",
    ),
    (
        "oq-2253",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE TRACKNO = 1021553140001",
    ),
    ("oq-2256", "refuse:3", "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE TRACKNO = ''"),
    (
        "oq-2258",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE TRACKNO IN ('A', '')",
    ),
    ("oq-2261", "refuse:3", "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL = ''"),
    ("oq-2262", "refuse:3", "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL = '   '"),
    ("oq-2332", "accept", "SELECT COUNT(*) FROM ROUTING WHERE ROUTING.WAYBILL = 'A'"),
    (
        "oq-2422",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' OR r.LEG = 2",
    ),
    ("oq-2465", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL ~ = 'A'"),
    ("oq-2467", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' ^ 1"),
    (
        "oq-2474",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-05' AND r.AGENTDATE <= '2026-10-11'",
    ),
    (
        "oq-2477",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE > '2026-10-04' AND r.AGENTDATE < '2026-10-12'",
    ),
    (
        "oq-2539",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, ROUTING r",
    ),
    (
        "oq-2543",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT 1 AS X FROM HOLIDAY) t, VIEW_EVENTSCANS v",
    ),
    (
        "oq-2546",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, ROUTING r WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2549",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT 1 AS X FROM HOLIDAY) t, VIEW_EVENTSCANS v WHERE v.WAYBILL = 'A'",
    ),
    (
        "oq-2553",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r JOIN HOLIDAY h ON h.HOLIDAY = r.AGENTDATE, VIEW_WBANALYSE w WHERE r.WAYBILL = 'A' AND w.WAYBILL = r.WAYBILL",
    ),
    (
        "oq-2560",
        "refuse:0",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' PLAN (R NATURAL)",
    ),
    (
        "oq-2643",
        "refuse:5",
        "SELECT CASE WHEN r.LEG = 1 THEN 'first' ELSE 'later' END, COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' GROUP BY 1",
    ),
    (
        "oq-2649",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN r.LEG = 1 OR r.LEG = 2 THEN 1 ELSE 0 END = 1",
    ),
    ("oq-2657", "accept", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A';"),
    ("oq-2661", "accept", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' ;"),
    (
        "oq-2667",
        "refuse:0",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A'; SELECT 1 FROM HOLIDAY",
    ),
    (
        "oq-2676",
        "refuse:0",
        "SELECT COUNT(*) FROM HOLIDAY h WHERE EXISTS (WITH q AS (SELECT 1 AS X FROM HOLIDAY) SELECT 1 FROM ROUTING)",
    ),
    (
        "oq-2680",
        "refuse:0",
        "SELECT (WITH q AS (SELECT 1 AS X FROM HOLIDAY) SELECT FIRST 1 WEBPASSWORD FROM CONTACT) FROM HOLIDAY",
    ),
    (
        "oq-2684",
        "refuse:0",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND r.MTYPE = q'{'}' OR 1 = 1 AND r.MTYPE = q'{'}'",
    ),
    ("oq-2688", "refuse:0", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = x'41'"),
    (
        "oq-2719",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND r.MTYPE STARTING WITH 'M' OR 1 = 1",
    ),
    (
        "oq-2723",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.MTYPE STARTING WITH 'M' OR r.WAYBILL = 'A'",
    ),
    (
        "oq-2727",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL STARTING WITH 'A'",
    ),
    (
        "oq-2731",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.TRACKNO STARTING WITH 'A'",
    ),
    (
        "oq-2735",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB STARTING WITH 'J', ROUTING r",
    ),
    (
        "oq-2739",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN ROUTING r ON r.ORIGHUB STARTING WITH 'J' AND r.WAYBILL = 'A' OR 1 = 1",
    ),
    (
        "oq-2751",
        "refuse:2",
        "SELECT COUNT(*) FROM HOLIDAY h JOIN HUB u ON u.HUB STARTING WITH 'J', ROUTING r WHERE r.WAYBILL = 'A'",
    ),
    (
        "oq-2764",
        "refuse:2",
        "SELECT EXCEPT.LEG FROM ROUTING EXCEPT, VIEW_WBANALYSE w WHERE EXCEPT.WAYBILL = 'A'",
    ),
    (
        "oq-2767",
        "refuse:2",
        "SELECT EXCEPT.LEG FROM ROUTING EXCEPT, VIEW_WBANALYSE w WHERE EXCEPT.WAYBILL = 'A' AND w.WAYBILL = 'A'",
    ),
    ("oq-2771", "refuse:3", "SELECT INTERSECT.LEG FROM ROUTING INTERSECT"),
    (
        "r6s1-26",
        "refuse:1",
        "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r WHERE r0.WAYBILL = 'X'",
    ),
    (
        "r6s1-31",
        "refuse:1",
        "SELECT v0.WAYBILL FROM VIEW_EVENTSCANS v0, (SELECT 1 X FROM HOLIDAY) t (A), VIEW_EVENTSCANS v WHERE v0.WAYBILL = 'X'",
    ),
    (
        "r6s1-36",
        "refuse:1",
        "SELECT t.A, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-31') t (A) JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.A",
    ),
    (
        "r6s1-41",
        "refuse:1",
        "SELECT t.A, m.ROUTE FROM (SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = 'X') t (A), MANIFEST m WHERE m.MANIFEST = t.A",
    ),
    (
        "r6s1-46",
        "refuse:1",
        "SELECT t.A, d.DRIVER FROM (SELECT r.AGENT FROM ROUTING r WHERE r.WAYBILL = 'X') AS t (A), AGENTDRIVER d WHERE d.AGENT = t.A",
    ),
    (
        "r6s1-65",
        "refuse:1",
        "SELECT r0.WAYBILL FROM ROUTING r0, (SELECT 1 X FROM HOLIDAY) t, ROUTING r WHERE r0.WAYBILL = 'X'",
    ),
    (
        "r6s1-69",
        "refuse:1",
        "SELECT t.WAYBILL, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-31') t JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.WAYBILL",
    ),
    (
        "r6s1-85",
        "refuse:1",
        "SELECT t.A, w.ACCNUM FROM (SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X') t (A) JOIN VIEW_WBANALYSE w ON w.WAYBILL = t.A WHERE w.WAYBILL = 'X'",
    ),
    (
        "r6s1-90",
        "refuse:1",
        "SELECT r.WAYBILL FROM (SELECT 1 X FROM HOLIDAY) t (A), ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6s1-91",
        "refuse:1",
        "SELECT r.WAYBILL FROM (SELECT 1 X FROM HOLIDAY) t (A) JOIN ROUTING r ON r.WAYBILL = 'X'",
    ),
    (
        "r6s1-103",
        "refuse:2",
        "SELECT 1 FROM HOLIDAY h OUTER JOIN ROUTING r ON r.WAYBILL = 'X'",
    ),
    (
        "r6c-28",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' UNION ALL SELECT r.WAYBILL FROM ROUTING r",
    ),
    (
        "r6c-33",
        "refuse:2",
        "SELECT h.HOLIDAY FROM HOLIDAY h LEFT JOIN ROUTING r ON r.WAYBILL = 'X'",
    ),
    (
        "r6c-38",
        "refuse:2",
        "SELECT h.HOLIDAY FROM ROUTING r RIGHT JOIN HOLIDAY h ON r.WAYBILL = 'X'",
    ),
    (
        "r6c-43",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE (r.WAYBILL = 'X') IS NOT FALSE",
    ),
    (
        "r6c-48",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE IIF(r.WAYBILL = 'X', 1, 1) = 1",
    ),
    (
        "r6c-53",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE COALESCE(r.WAYBILL, 'X') = 'X'",
    ),
    ("r6c-55", "refuse:4", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 0"),
    (
        "r6c-56",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST IN (0, 5)",
    ),
    (
        "r6c-60",
        "refuse:1",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE w WHERE w.WAYBILL IN (SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02')",
    ),
    (
        "r6c-65",
        "refuse:1",
        "WITH q AS (SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT w.WAYBILL FROM q JOIN VIEW_WBANALYSE w ON w.WAYBILL = q.WAYBILL",
    ),
    (
        "r6c-67",
        "refuse:0",
        "SELECT 1 FROM HOLIDAY h JOIN HUB u ON u.HUB = u.HUB, EVENT e",
    ),
    (
        "r6c-71",
        "refuse:0",
        "SELECT 1 FROM (SELECT 1 X FROM HOLIDAY) t, CONTACT c WHERE c.WEBPASSWORD = 'x'",
    ),
    (
        "r6c-76",
        "refuse:2",
        "SELECT 1 FROM HOLIDAY h NATURAL JOIN HUB u, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-81",
        "refuse:2",
        "SELECT 1 FROM ROUTING r, HOLIDAY h NATURAL JOIN HUB u WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-83",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' OR 1 = 1",
    ),
    (
        "r6c-87",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE 1 = 1 OR r.LEG = 1 AND r.WAYBILL = 'X'",
    ),
    ("r6c-89", "refuse:3", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL ~= 'X'"),
    ("r6c-90", "refuse:3", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL ^= 'X'"),
    (
        "r6c-94",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' PLAN (R NATURAL)",
    ),
    (
        "r6c-99",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE IN ('2026-10-01')",
    ),
    (
        "r6c-104",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE CASE WHEN 1 = 1 AND r.WAYBILL = 'X' AND 1 = 1 THEN 1 ELSE 1 END = 1",
    ),
    (
        "r6c-109",
        "refuse:0",
        "SELECT (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT FIRST 1 WEBPASSWORD FROM CONTACT) FROM HOLIDAY",
    ),
    (
        "r6c-114",
        "refuse:0",
        "SELECT 1 FROM HOLIDAY WHERE EXISTS (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT 1 FROM EVENT)",
    ),
    (
        "r6c-119",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND q'{'} = q'{' OR 1=1}'",
    ),
    (
        "r6c-124",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND x'41' = x'41'",
    ),
    ("r6c-126", "accept", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X';"),
    (
        "r6c-130",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X'; SELECT 1 FROM EVENT",
    ),
    ("r6c-132", "refuse:0", "SELECT 1 FROM HOLIDAY -- x\r, EVENT e"),
    ("r6c-133", "refuse:0", "SELECT 1 FROM HOLIDAY /* x */, EVENT e"),
    ("r6c-134", "refuse:0", "SELECT 1 FROM HOLIDAY WHERE 1 = 1 -- , EVENT e"),
    (
        "r6c-138",
        "refuse:0",
        "SELECT 1 FROM HOLIDAY h JOIN HUB u ON u.HUB STARTING WITH 'A', EVENT e",
    ),
    (
        "r6c-143",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MTYPE STARTING WITH 'M' OR 1 = 1",
    ),
    ("r6c-145", "refuse:0", "SELECT * FROM (SELECT * FROM CONTACT) t (A1, A2)"),
    (
        "r6c-149",
        "refuse:0",
        "SELECT NAME AS A FROM CONTACT WHERE 1 = 0 UNION ALL SELECT * FROM CONTACT",
    ),
    ("r6c-151", "refuse:0", "SELECT IP FROM BRANCH"),
    ("r6c-152", "refuse:0", "SELECT 1 FROM HOLIDAY EXCEPT, EVENT e"),
    ("r6c-153", "refuse:0", "SELECT 1 FROM HOLIDAY INTERSECT JOIN EVENT e ON 1 = 1"),
    (
        "r6c-157",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' EXCEPT SELECT r.WAYBILL FROM ROUTING r",
    ),
    (
        "r6c-162",
        "refuse:0",
        "WITH EVENT AS (SELECT 1 X FROM EVENT e) SELECT X FROM EVENT x, HOLIDAY h",
    ),
    (
        "r6c-167",
        "refuse:0",
        "WITH ROUTING AS (SELECT 1 X FROM ROUTING r) SELECT X FROM ROUTING x, HOLIDAY h",
    ),
    ("r6c-169", "refuse:0", "SELECT 1 FROM HOLIDAY h ORDER BY STARTING WITH LOCK"),
    ("r6c-170", "refuse:0", "SELECT 1 FROM HOLIDAY h WHERE h.HOLIDAY = 'x' WITH LOCK"),
    ("r6c-171", "refuse:0", "SELECT 1 FROM HOLIDAY h WHERE A$STARTING WITH LOCK"),
    ("r6c-172", "refuse:3", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 12345"),
    (
        "r6c-173",
        "refuse:3",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.TRACKNO = ''",
    ),
    (
        "r6c-191",
        "accept",
        "SELECT r.WAYBILL, r.LEG, r.MTYPE FROM ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-211",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-09-01' AND '2026-10-01'",
    ),
    (
        "r6c-216",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-09-01' AND '2026-10-02'",
    ),
    (
        "r6c-221",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X'",
    ),
    (
        "r6c-226",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.TRACKNO = 'X'",
    ),
    (
        "r6c-231",
        "accept",
        "SELECT v.EVENTDATE, v.NAME FROM VIEW_EVENTSCANS v WHERE v.MANIFEST = 37733",
    ),
    (
        "r6c-236",
        "accept",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-19' AND '2026-10-21'",
    ),
    (
        "r6c-241",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE BETWEEN '2026-10-18' AND '2026-10-21'",
    ),
    (
        "r6c-246",
        "refuse:1",
        "WITH legs AS (SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT COUNT(*) FROM legs",
    ),
    (
        "r6c-251",
        "accept",
        "SELECT r.LEG, w.ACCNUM FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL = 'X' AND w.WAYBILL = 'X'",
    ),
    (
        "r6c-256",
        "accept",
        "SELECT r.LEG, d.DRIVER FROM ROUTING r JOIN AGENTDRIVER d ON d.AGENT = r.AGENT WHERE r.WAYBILL = 'X' AND d.AGENT = 123",
    ),
    (
        "r6c-261",
        "accept",
        "SELECT v.RECIPIENT, v.USERNAME FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X'",
    ),
    ("r6c-263", "refuse:0", "SELECT r.DELOTP FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    ("r6c-264", "refuse:0", "SELECT r.* FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    (
        "r6c-268",
        "refuse:0",
        "WITH q AS (SELECT * FROM ROUTING r WHERE r.WAYBILL = 'X') SELECT COUNT(*) FROM q",
    ),
    (
        "r6c-273",
        "refuse:0",
        "SELECT * FROM (SELECT r.WAYBILL, r.LEG FROM ROUTING r WHERE r.WAYBILL = 'X') t",
    ),
    (
        "r6c-275",
        "accept",
        "SELECT c.ACCNUM, c.DELOTP FROM CUSTOMER c WHERE c.ACCNUM = 'X'",
    ),
    (
        "r6c-315",
        "refuse:1",
        "SELECT r0.WAYBILL FROM ROUTING r0 JOIN (SELECT 1 X FROM HOLIDAY) t (A) ON 1 = 1 JOIN ROUTING r ON r.WAYBILL = r0.WAYBILL WHERE r0.WAYBILL = 'X'",
    ),
    (
        "r6c-326",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' IS NOT NULL",
    ),
    (
        "r6c-331",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE NOT BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "r6c-333",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE NOT r.WAYBILL = 'X'",
    ),
    (
        "r6c-334",
        "refuse:2",
        "SELECT r.WAYBILL FROM ROUTING r, HOLIDAY h WHERE WAYBILL = 'X'",
    ),
    (
        "r6c-338",
        "refuse:2",
        "SELECT 1 FROM HOLIDAY h WHERE h.HOLIDAY IS DISTINCT FROM ROUTING",
    ),
    (
        "r6c-343",
        "refuse:1",
        "WITH a AS (SELECT X FROM b), b AS (SELECT 1 X FROM HOLIDAY) SELECT X FROM a, ROUTING r",
    ),
    (
        "r6c-348",
        "refuse:1",
        "WITH q AS (SELECT h.HOLIDAY X FROM HOLIDAY h) SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN (SELECT X FROM q)",
    ),
    (
        "r6c-353",
        "refuse:1",
        "WITH AGENTDATE AS (SELECT 1 X FROM HOLIDAY) SELECT r.WAYBILL FROM ROUTING r, AGENTDATE a WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "r6c-358",
        "refuse:0",
        "SELECT 1 FROM (WITH q AS (SELECT 1 X FROM HOLIDAY) SELECT X FROM q) t, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-363",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' FOR UPDATE",
    ),
    (
        "r6c-368",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' RETURNING r.WAYBILL",
    ),
    (
        "r6c-370",
        "refuse:5",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' INTO :x",
    ),
    (
        "r6c-374",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND (1 = 1 OR r.LEG = 1)",
    ),
    (
        "r6c-379",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE (r.WAYBILL = 'X' OR 1 = 1) AND 1 = 1",
    ),
    (
        "r6c-384",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE ((r.WAYBILL = 'X')) AND (1 = 1 OR r.LEG = 1)",
    ),
    (
        "r6c-389",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL BETWEEN 'A' AND 'Z'",
    ),
    (
        "r6c-394",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = (SELECT FIRST 1 h.HOLIDAY FROM HOLIDAY h)",
    ),
    (
        "r6c-399",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN (SELECT h.HOLIDAY FROM HOLIDAY h)",
    ),
    (
        "r6c-404",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01'",
    ),
    (
        "r6c-409",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-01' AND r.AGENTDATE <= '2026-11-01'",
    ),
    (
        "r6c-414",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE > '2026-09-30' AND r.AGENTDATE < '2026-11-01'",
    ),
    (
        "r6c-419",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-1' AND '2026-10-02'",
    ),
    (
        "r6c-424",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND x BETWEEN 1 AND 2 OR 1 = 1",
    ),
    (
        "r6c-429",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE CASE WHEN r.WAYBILL = 'X' THEN 1 ELSE 1 END = 1",
    ),
    (
        "r6c-434",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE EXISTS (SELECT 1 FROM HOLIDAY h WHERE r.WAYBILL = 'X')",
    ),
    (
        "r6c-439",
        "refuse:1",
        "SELECT 1 FROM HOLIDAY h WHERE EXISTS (SELECT 1 FROM ROUTING r WHERE r.WAYBILL = h.HOLIDAY)",
    ),
    (
        "r6c-444",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' UNION SELECT r2.WAYBILL FROM ROUTING r2 WHERE r2.LEG = 1",
    ),
    (
        "r6c-449",
        "refuse:2",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE w, ROUTING r WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-454",
        "refuse:2",
        "SELECT w.WAYBILL FROM VIEW_WBANALYSE AS w JOIN ROUTING r ON r.WAYBILL = w.WAYBILL WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6c-459",
        "refuse:2",
        "SELECT d.DRIVER FROM AGENTDRIVER d JOIN ROUTING r ON r.AGENT = d.AGENT WHERE r.MANIFEST = 5",
    ),
    (
        "r6c-464",
        "refuse:1",
        "SELECT m.ROUTE FROM MANIFEST m WHERE EXISTS (SELECT 1 FROM ROUTING r WHERE r.MANIFEST = m.MANIFEST AND r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02')",
    ),
    (
        "r6c-469",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.LEG IS DISTINCT FROM 1",
    ),
    (
        "r6c-471",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN ('X' 'Y')",
    ),
    (
        "r6c-475",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL IN ((SELECT 'X' FROM HOLIDAY))",
    ),
    ("r6c-477", "refuse:4", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 1.5"),
    ("r6c-478", "refuse:4", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = -1"),
    ("r6c-479", "refuse:3", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 1e3"),
    ("r6c-480", "refuse:3", "SELECT r.WAYBILL FROM ROUTING r WHERE 'X' = r.WAYBILL"),
    (
        "r6c-484",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1 GROUP BY r.WAYBILL HAVING COUNT(*) > 0 OR 1 = 1",
    ),
    (
        "r6c-489",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE DATEDIFF(DAY FROM r.AGENTDATE TO r.AGENTDATE) = 0 AND r.WAYBILL = 'X'",
    ),
    (
        "r6c-491",
        "refuse:0",
        "SELECT 1 FROM HOLIDAY h, LATERAL (SELECT 1 FROM ROUTING r) t",
    ),
    (
        "r6c-495",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1\n/*\n*/",
    ),
    (
        "r6c-500",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' ROWS 1 TO 10 WITH LOCK",
    ),
    (
        "r6c-505",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.LEG = ANY (SELECT 1 FROM HOLIDAY)",
    ),
    (
        "r6c-511",
        "refuse:4",
        "SELECT FIRST 5 v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
    ),
    (
        "r6c-516",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST > 0",
    ),
    (
        "r6c-177",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1",
    ),
    ("r6c-574", "accept", "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    ("r6c-576", "accept", "SELECT NAME FROM HOLIDAY"),
    (
        "r6s2-27",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST <> 5",
    ),
    (
        "r6s2-28",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST >= 1",
    ),
    (
        "r6s2-29",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST BETWEEN 1 AND 9",
    ),
    (
        "r6s2-30",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND NOT r.MANIFEST = 5",
    ),
    (
        "r6s2-31",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST IS NOT NULL",
    ),
    (
        "r6s2-32",
        "refuse:3",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND COALESCE(r.MANIFEST, 0) = 5",
    ),
    (
        "r6s2-33",
        "refuse:1",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST IN (SELECT MANIFEST FROM MANIFEST)",
    ),
    (
        "r6s2-35",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 0",
    ),
    (
        "r6s2-36",
        "refuse:4",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 1.5",
    ),
    (
        "r6s2-38",
        "refuse:4",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL = 'X' AND MANIFEST > 0",
    ),
    (
        "r6s2-40",
        "refuse:2",
        "SELECT r.WAYBILL FROM HOLIDAY h JOIN ROUTING r ON r.MANIFEST > 0 AND r.WAYBILL = 'X'",
    ),
    (
        "r6s2-41",
        "refuse:2",
        "SELECT h.NAME FROM HOLIDAY h LEFT JOIN ROUTING r ON r.MANIFEST > 0 WHERE r.WAYBILL = 'X'",
    ),
    (
        "r6s2-43",
        "refuse:1",
        "SELECT t.W FROM (SELECT v.WAYBILL W FROM VIEW_EVENTSCANS v WHERE v.WAYBILL = 'X' AND v.MANIFEST > 0) t",
    ),
    ("r6s2-73", "accept", "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST = 37733"),
    (
        "r6s2-74",
        "accept",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.MANIFEST IN (1, 2, 3) AND r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-02'",
    ),
    (
        "r6s2-75",
        "accept",
        "SELECT v.WAYBILL FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST = 37733",
    ),
    (
        "r6s2-78",
        "accept",
        "SELECT r.WAYBILL, m.AGENT FROM ROUTING r JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE r.MANIFEST = 37733 AND m.MANIFEST = 37733",
    ),
    ("r6s2-82", "accept", "SELECT m.ROUTE FROM MANIFEST m WHERE m.MANIFEST > 0"),
    ("r6s2-84", "accept", "SELECT r.MANIFEST FROM ROUTING r WHERE r.WAYBILL = 'X'"),
    (
        "r6s2-105",
        "refuse:4",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0",
    ),
    (
        "r6s2-65",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'X' AND r.MANIFEST = 0",
    ),
    (
        "oq-in100",
        "accept",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL IN ('W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'W12', 'W13', 'W14', 'W15', 'W16', 'W17', 'W18', 'W19', 'W20', 'W21', 'W22', 'W23', 'W24', 'W25', 'W26', 'W27', 'W28', 'W29', 'W30', 'W31', 'W32', 'W33', 'W34', 'W35', 'W36', 'W37', 'W38', 'W39', 'W40', 'W41', 'W42', 'W43', 'W44', 'W45', 'W46', 'W47', 'W48', 'W49', 'W50', 'W51', 'W52', 'W53', 'W54', 'W55', 'W56', 'W57', 'W58', 'W59', 'W60', 'W61', 'W62', 'W63', 'W64', 'W65', 'W66', 'W67', 'W68', 'W69', 'W70', 'W71', 'W72', 'W73', 'W74', 'W75', 'W76', 'W77', 'W78', 'W79', 'W80', 'W81', 'W82', 'W83', 'W84', 'W85', 'W86', 'W87', 'W88', 'W89', 'W90', 'W91', 'W92', 'W93', 'W94', 'W95', 'W96', 'W97', 'W98', 'W99')",
    ),
    (
        "oq-in101",
        "refuse:3",
        "SELECT WAYBILL FROM ROUTING WHERE WAYBILL IN ('W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'W12', 'W13', 'W14', 'W15', 'W16', 'W17', 'W18', 'W19', 'W20', 'W21', 'W22', 'W23', 'W24', 'W25', 'W26', 'W27', 'W28', 'W29', 'W30', 'W31', 'W32', 'W33', 'W34', 'W35', 'W36', 'W37', 'W38', 'W39', 'W40', 'W41', 'W42', 'W43', 'W44', 'W45', 'W46', 'W47', 'W48', 'W49', 'W50', 'W51', 'W52', 'W53', 'W54', 'W55', 'W56', 'W57', 'W58', 'W59', 'W60', 'W61', 'W62', 'W63', 'W64', 'W65', 'W66', 'W67', 'W68', 'W69', 'W70', 'W71', 'W72', 'W73', 'W74', 'W75', 'W76', 'W77', 'W78', 'W79', 'W80', 'W81', 'W82', 'W83', 'W84', 'W85', 'W86', 'W87', 'W88', 'W89', 'W90', 'W91', 'W92', 'W93', 'W94', 'W95', 'W96', 'W97', 'W98', 'W99', 'W100')",
    ),
    (
        "oq-m20",
        "accept",
        "SELECT WAYBILL FROM ROUTING WHERE MANIFEST IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20)",
    ),
    (
        "oq-m21",
        "refuse:4",
        "SELECT WAYBILL FROM ROUTING WHERE MANIFEST IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21)",
    ),
    (
        "oq-vin100",
        "accept",
        "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE WAYBILL IN ('W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'W12', 'W13', 'W14', 'W15', 'W16', 'W17', 'W18', 'W19', 'W20', 'W21', 'W22', 'W23', 'W24', 'W25', 'W26', 'W27', 'W28', 'W29', 'W30', 'W31', 'W32', 'W33', 'W34', 'W35', 'W36', 'W37', 'W38', 'W39', 'W40', 'W41', 'W42', 'W43', 'W44', 'W45', 'W46', 'W47', 'W48', 'W49', 'W50', 'W51', 'W52', 'W53', 'W54', 'W55', 'W56', 'W57', 'W58', 'W59', 'W60', 'W61', 'W62', 'W63', 'W64', 'W65', 'W66', 'W67', 'W68', 'W69', 'W70', 'W71', 'W72', 'W73', 'W74', 'W75', 'W76', 'W77', 'W78', 'W79', 'W80', 'W81', 'W82', 'W83', 'W84', 'W85', 'W86', 'W87', 'W88', 'W89', 'W90', 'W91', 'W92', 'W93', 'W94', 'W95', 'W96', 'W97', 'W98', 'W99')",
    ),
    (
        "oq-vin101",
        "refuse:3",
        "SELECT WAYBILL FROM VIEW_EVENTSCANS WHERE WAYBILL IN ('W0', 'W1', 'W2', 'W3', 'W4', 'W5', 'W6', 'W7', 'W8', 'W9', 'W10', 'W11', 'W12', 'W13', 'W14', 'W15', 'W16', 'W17', 'W18', 'W19', 'W20', 'W21', 'W22', 'W23', 'W24', 'W25', 'W26', 'W27', 'W28', 'W29', 'W30', 'W31', 'W32', 'W33', 'W34', 'W35', 'W36', 'W37', 'W38', 'W39', 'W40', 'W41', 'W42', 'W43', 'W44', 'W45', 'W46', 'W47', 'W48', 'W49', 'W50', 'W51', 'W52', 'W53', 'W54', 'W55', 'W56', 'W57', 'W58', 'W59', 'W60', 'W61', 'W62', 'W63', 'W64', 'W65', 'W66', 'W67', 'W68', 'W69', 'W70', 'W71', 'W72', 'W73', 'W74', 'W75', 'W76', 'W77', 'W78', 'W79', 'W80', 'W81', 'W82', 'W83', 'W84', 'W85', 'W86', 'W87', 'W88', 'W89', 'W90', 'W91', 'W92', 'W93', 'W94', 'W95', 'W96', 'W97', 'W98', 'W99', 'W100')",
    ),
    (
        "oq-dup101",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING WHERE WAYBILL IN ('A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A', 'A')",
    ),
    (
        "r6c-cap",
        "refuse:0",
        "SELECT r.WAYBILL FROM ROUTING r WHERE r.WAYBILL = 'X' AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 AND 1 = 1 ",
    ),
    (
        "where-01",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN r.WAYBILL = 'A' THEN 1 ELSE 1 END = 1",
    ),
    (
        "where-02",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE IIF(r.WAYBILL = 'A', 1, 1) = 1",
    ),
    (
        "where-03",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A') IS FALSE",
    ),
    (
        "where-04",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A') IS NOT TRUE",
    ),
    (
        "where-05",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A') = FALSE",
    ),
    (
        "where-06",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE COALESCE(r.WAYBILL = 'A', TRUE)",
    ),
    (
        "where-07",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.AGENTDATE BETWEEN '2026-10-13' AND '2026-10-15') IS FALSE",
    ),
    (
        "where-08",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE NOT (r.WAYBILL = 'A')",
    ),
    (
        "where-09",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE UPPER(r.WAYBILL) = 'A'",
    ),
    (
        "where-10",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' OR 1 = 1",
    ),
    (
        "where-11",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A' OR r.LEG = 1)",
    ),
    (
        "where-12",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL || '' = 'A'",
    ),
    (
        "where-13",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' + 0",
    ),
    ("where-14", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE 'A' = r.WAYBILL"),
    (
        "where-15",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN CAST('2026-10-13' AS DATE) AND CAST('2026-10-15' AS DATE)",
    ),
    (
        "where-16",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = ANY ('A')",
    ),
    (
        "where-17",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL IN ('A', (SELECT FIRST 1 WAYBILL FROM VIEW_WBANALYSE))",
    ),
    (
        "where-18",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL IN (('A'))",
    ),
    (
        "where-20",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL IN ('A', 'B')",
    ),
    (
        "where-21",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN DATE '2026-10-13' AND DATE '2026-10-15'",
    ),
    (
        "where-22",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN TIMESTAMP '2026-10-13 00:00' AND TIMESTAMP '2026-10-15 23:59'",
    ),
    (
        "where-23",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-13' AND r.AGENTDATE <= '2026-10-15'",
    ),
    (
        "where-24",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE >= '2026-10-13' AND r.LEG = 2 AND r.AGENTDATE < '2026-10-16'",
    ),
    (
        "where-25",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE = '2026-10-13'",
    ),
    (
        "where-26",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND (r.LEG = 1 OR r.LEG = 2)",
    ),
    (
        "where-27",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A') AND r.LEG = 1",
    ),
    (
        "where-28",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE (r.WAYBILL = 'A' AND r.LEG = 1) AND (r.LEG = 1 OR r.LEG = 2)",
    ),
    ("where-29", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL ~= 'A'"),
    ("where-30", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL ^= 'A'"),
    ("where-31", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL != 'A'"),
    ("where-32", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL <> 'A'"),
    (
        "where-33",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.MANIFEST ~= 37733",
    ),
    (
        "where-34",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.MANIFEST <> 37733",
    ),
    (
        "where-35",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE ~< '2026-10-11' AND r.AGENTDATE ~> '2026-10-05'",
    ),
    (
        "where-36",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE ^< '2026-10-11' AND r.AGENTDATE ^> '2026-10-05'",
    ),
    (
        "where-37",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE !< '2026-10-11' AND r.AGENTDATE !> '2026-10-05'",
    ),
    (
        "where-38",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE ~< '2026-10-11'",
    ),
    ("where-39", "refuse:3", "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL LIKE 'A'"),
    (
        "where-41",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL CONTAINING 'A'",
    ),
    (
        "where-42",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL SIMILAR TO 'A'",
    ),
    (
        "where-45",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN r.LEG = 1 THEN 1 ELSE 0 END = 1",
    ),
    (
        "where-46",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE CASE WHEN r.LEG = 1 THEN 1 ELSE 0 END = 1 AND r.WAYBILL = 'A'",
    ),
    (
        "where-47",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN r.LEG = 1 AND r.MTYPE = 'M' THEN 1 ELSE 0 END = 1",
    ),
    (
        "where-48",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND CASE WHEN 1 = 1 THEN CASE WHEN r.LEG = 1 THEN 1 END ELSE 0 END = 1",
    ),
    (
        "where-49",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-01' AND '2026-10-07' AND CASE r.MTYPE WHEN 'M' THEN 1 ELSE 0 END = 1",
    ),
    (
        "where-51",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.MTYPE STARTING WITH 'M' AND r.WAYBILL = 'A'",
    ),
    (
        "where-52",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND r.MTYPE STARTING WITH 'M'",
    ),
    (
        "where-53",
        "refuse:3",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.WAYBILL = 'A' AND (r.MTYPE STARTING WITH 'M' OR r.MTYPE STARTING WITH 'R')",
    ),
    (
        "where-54",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST > 0 AND 1 = 1",
    ),
    (
        "vwhere-01",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE (v.EVENTDATE BETWEEN '2026-10-13' AND '2026-10-15') IS FALSE",
    ),
    (
        "vwhere-02",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE CASE WHEN v.WAYBILL = 'A' THEN 1 ELSE 1 END = 1",
    ),
    (
        "vwhere-03",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE COALESCE(v.TRACKNO = 'A', TRUE)",
    ),
    (
        "vwhere-04",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.TRACKNO ~= 'A'",
    ),
    (
        "vwhere-05",
        "refuse:3",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v WHERE v.WAYBILL <> 'A'",
    ),
    (
        "r7-01",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r, HOLIDAY h WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST > 0",
    ),
    (
        "r7-02",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r, HOLIDAY h WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST = 0",
    ),
    (
        "r7-03",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r, HOLIDAY h WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST BETWEEN 0 AND 99999999",
    ),
    (
        "r7-04",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r, HOLIDAY h WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND CAST(MANIFEST AS INTEGER) > 0",
    ),
    (
        "r7-05",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r JOIN HOLIDAY h ON MANIFEST > 0 WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21'",
    ),
    (
        "r7-06",
        "refuse:2",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v, HOLIDAY h WHERE v.EVENTDATE = '2026-10-21' AND MANIFEST > 0",
    ),
    (
        "r7-07",
        "refuse:2",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v, HOLIDAY h WHERE v.EVENTDATE = '2026-10-21' AND MANIFEST = 0",
    ),
    (
        "r7-08",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT r.MANIFEST FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') t WHERE t.MANIFEST > 0",
    ),
    (
        "r7-09",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT r.MANIFEST FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') t WHERE t.MANIFEST = 0",
    ),
    (
        "r7-10",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT r.MANIFEST AS M FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') t WHERE t.M BETWEEN 1 AND 99999999",
    ),
    (
        "r7-11",
        "refuse:1",
        "WITH q AS (SELECT r.MANIFEST AS M FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') SELECT COUNT(*) FROM q WHERE q.M > 0",
    ),
    (
        "r7-12",
        "refuse:1",
        "WITH q AS (SELECT r.MANIFEST AS M, r.WAYBILL AS W FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') SELECT COUNT(*) FROM q JOIN HOLIDAY h ON 1 = 1 WHERE q.M > 0",
    ),
    (
        "r7-13",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT v.MANIFEST FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21') t WHERE t.MANIFEST > 0",
    ),
    (
        "r7-14",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT v.MANIFEST FROM VIEW_EVENTSCANS v WHERE v.EVENTDATE = '2026-10-21') t WHERE t.MANIFEST = 0",
    ),
    (
        "r7-15",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r, (SELECT 0 AS A FROM HOLIDAY) t WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST = t.A",
    ),
    (
        "r7-16",
        "refuse:1",
        "SELECT COUNT(*) FROM ROUTING r, (SELECT FIRST 1 0 AS A FROM HOLIDAY) t WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST = t.A",
    ),
    (
        "r7-17",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r, BRANCH b WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST = b.BRANCH",
    ),
    (
        "r7-18",
        "refuse:2",
        "SELECT COUNT(*) FROM ROUTING r JOIN AREA a ON r.MANIFEST = a.AREA WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21'",
    ),
    (
        "r7-19",
        "refuse:1",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v, (SELECT 0 AS A FROM HOLIDAY) t WHERE v.EVENTDATE = '2026-10-21' AND v.MANIFEST = t.A",
    ),
    (
        "r7-20",
        "refuse:2",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v JOIN BRANCH b ON v.MANIFEST = b.BRANCH WHERE v.EVENTDATE = '2026-10-21'",
    ),
    (
        "r7-21",
        "accept",
        "SELECT COUNT(*) FROM ROUTING r JOIN MANIFEST m ON m.MANIFEST = r.MANIFEST WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND m.MANIFEST = 37733",
    ),
    (
        "r7-22",
        "refuse:2",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS v, VIEW_EVENTSCANS v2 WHERE v.EVENTDATE = '2026-10-21' AND v2.WAYBILL = 'X' AND v.MANIFEST = v2.MANIFEST",
    ),
    (
        "r7-23",
        "accept",
        "SELECT r.MANIFEST, COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND r.MANIFEST = 37733 GROUP BY r.MANIFEST",
    ),
    (
        "r7-24",
        "refuse:1",
        "SELECT COUNT(*) FROM (SELECT r.MANIFEST, r.LEG FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21') t WHERE t.LEG = 1",
    ),
    (
        "r7-25",
        "refuse:4",
        "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN '2026-10-20' AND '2026-10-21' AND MANIFEST > 0",
    ),
]


@pytest.mark.parametrize("pid,verdict,sql", PINS, ids=[p[0] for p in PINS])
def test_the_pin_holds_under_the_one_block_shape(pid, verdict, sql):
    if verdict == "accept":
        check_open_query(sql)
        return
    rule = int(verdict.split(":")[1])
    with pytest.raises(GuardError) as e:
        check_open_query(sql)
    if rule:
        assert f"windowed shape rule {rule}" in str(e.value)
    else:
        assert "windowed shape rule" not in str(e.value)


def test_the_corpus_covers_every_review():
    ids = {p[0].split("-")[0] for p in PINS}
    assert {"oq", "r6c", "r6s1", "r6s2", "r7", "where", "vwhere"} <= ids
    assert sum(1 for p in PINS if p[1] == "accept") >= 50
    assert sum(1 for p in PINS if p[1].startswith("refuse")) >= 300
