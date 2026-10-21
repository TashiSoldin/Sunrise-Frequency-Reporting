# ROUTING and VIEW_EVENTSCANS — query plans and timings (QT-000007 line 3)

Measured live on the BI server, Wed 21 Oct 2026, 09:52–10:00 SAST (the database clock reads
about three minutes ahead). Scripts: `routing_eventscans_defs.py` (definitions, no data reads),
`routing_eventscans_plans.py` (the main run), `routing_eventscans_plans_extra.py` (follow-ups).
Verbatim logs with every PLAN line as Firebird returned it:
`routing_eventscans_plans_2026-10-21.txt`, `routing_eventscans_plans_2026-10-21_extra.txt`;
machine-readable: `routing_eventscans_plans_2026-10-21.json`.

This file is the decision input for line 4. Numbers are measured; anything marked *estimate*
is arithmetic on measured numbers, not a measurement.

## 1. The proposed rule

**Plain words (for Reuven).** ROUTING and VIEW_EVENTSCANS can be queried, but every query has
to say which waybills or which days it is about. For ROUTING that means a waybill number (or a
list of up to 100), a manifest number, or a range of agent dates no wider than 31 days. For
VIEW_EVENTSCANS it means a waybill number or tracking number (or a list of up to 100), a manifest
number, or a range of event dates no wider than 3 days. A query that gives none of these is
refused before it reaches the database, with a message that says what to add. Other columns
can still be used to narrow a query further, but they do not count as the window: on
VIEW_EVENTSCANS a waybill date, an account or an event name on its own would make the
database read the whole scan history, so those need a waybill, tracking number, manifest or
event-date range beside them.

**Precisely (for line 4's `WINDOWED` spec).**

| Relation | Key forms (any one suffices) | Window (any one suffices) | Not a window (allowed only beside a key or window) |
|---|---|---|---|
| ROUTING | `WAYBILL = 'x'`; `WAYBILL IN (≤100 literals)`; `MANIFEST = n` (optionally `AND MBRANCH = b AND MTYPE = 't'` — recommended, see §4.2); `MANIFEST IN (≤20 literals)` | `AGENTDATE` range ≤ 31 days (`BETWEEN` or `>= … AND <=` with date literals) | `BOOKDATE` (indexed and cheap, but populated only on local-delivery rows — §4.3), `AGENT`, `ORIGHUB`/`DESTHUB`, `MTYPE`, `STATUS` |
| VIEW_EVENTSCANS | `WAYBILL = 'x'` / `IN (≤100)`; `TRACKNO = 'x'` / `IN (≤100)`; `MANIFEST = n` / `IN (≤20)` | `EVENTDATE` range ≤ 3 days | `WAYDATE`, `ACCNUM`, `NAME`, `HUB`, `USERNAME`, `AGENTNAME`, `ORIGHUB`/`DESTHUB` — each on its own plans a natural scan of TRACK (14M) and WAYBILL (3.1M) with an EVENT probe per row (§5.3) |

A join between the two needs each of them windowed on its own alias (ROUTING.WAYBILL = x does
not window VIEW_EVENTSCANS, and vice versa). The predicate must be on the windowed table's
alias, not merely on a column of the same name elsewhere in the query. Ranges given through
subqueries, parameters, `CURRENT_DATE` arithmetic, or OR-ed predicates are refused (line 4
cannot compute their width from literals).

**Why those widths.**

- ROUTING, AGENTDATE: the index `RO_AGNTDATEAGENT (AGENTDATE, AGENT)` drives every range.
  31 days = 48,680 rows, COUNT(*) 168 ms cold / 20 ms warm; 92 days = 139,763 rows, 463 / 54 ms.
  ROUTING on its own would tolerate a quarter. The limit is set by what a user does with the
  window: a join through VIEW_WBANALYSE costs about 0.165 ms per waybill (874 waybills by
  WAYDATE counted through the view in 144 ms), so 31 days of ROUTING joined to the view is
  *estimated* at ~8 s and 92 days at ~23 s. 31 days keeps the worst sensible query under the
  15 s client cap and covers a month of line-haul trips.
- VIEW_EVENTSCANS, EVENTDATE: `EV_EVENTDATE` drives the EVENT scan but the view then performs
  eight indexed lookups per event row (TRACK, WAYBILL twice, SCANRULE, USERCODE, BRANCH, AGENT,
  POD, ROUTING, FAILTYPE), about 24 µs per row warm. Measured COUNT(*): 1 day = 50,679 rows,
  5.7 s cold / 1.2 s warm; 2 days = 107,366, 7.1 / 2.5 s; 3 days = 149,966, 7.9 / 3.5 s;
  7 days = 287,856, 14.5 / 6.9 s. Three days is the widest window under ~5 s warm, and its
  cold time stays inside the 15 s cap; seven days is over both lines. (At ~50,000 events a
  day a plain row read of a date window hits the 500-row cap anyway; the window is for
  aggregates and for date + hub / account / name questions.)
- IN-lists: Firebird plans one index lookup per literal (`RDB$PRIMARY51, RDB$PRIMARY51, …`).
  ROUTING: 5 waybills 4 ms, 24 waybills 13 ms. VIEW_EVENTSCANS: 5 waybills 57 ms (208 rows),
  24 waybills 135 ms (hit the 501-row fetch). 100 literals is *estimated* at ~60 ms on ROUTING
  and ~0.6 s on the view before the row cap stops it; Firebird 3's own limit is 1,500 items.
  Manifests: one trip is 124–136 ROUTING rows (≈25 ms warm) and 1,456 view rows (40 ms), so a
  list of 20 manifests stays under a second on either.

## 2. Definitions (read before anything was executed)

### 2.1 VIEW_EVENTSCANS source

`RDB$RELATIONS.RDB$VIEW_SOURCE` is **NULL** for VIEW_EVENTSCANS (RDB$VIEW_BLR is present, owner
SYSDBA, relation type 1) — the view was created with its source text stripped, so the SQL
cannot be read back. Its structure comes from `RDB$VIEW_RELATIONS` and the per-column
`RDB$VIEW_CONTEXT` / `RDB$BASE_FIELD`:

| Context | Relation | Alias | Role |
|---|---|---|---|
| 2 | EVENT | EVENTS E | derived table **EVENTS**, branch 1: EVENT → TRACK → WAYBILL (parcel-level tracking numbers) |
| 3 | TRACK | EVENTS T | " |
| 4 | WAYBILL | EVENTS W | " |
| 5 | EVENT | EVENTS E | derived table **EVENTS**, branch 2: EVENT → WAYBILL (TRACKNO = waybill number) |
| 6 | WAYBILL | EVENTS W | " |
| 8 | WAYBILL | W | outer lookup: ACCNUM, SERVICE, ACTKG, CHARGEUNITS(=CHARGEMASS), REFERENCE, ORIGHUB, DESTHUB, WAYDATE |
| 9 | SCANRULE | S | NAME (event description), EXPECTED(=INPUTMETHOD) |
| 10 | USERCODE | U | USERNAME |
| 11 | BRANCH | B | BRANCHNAME |
| 12 | AGENT | AG | AGENTNAME |
| 13 | POD | POD | PODDATE, PODTIME |
| 14 | ROUTING | R | (joined on WAYBILL, LEG — plan shows `ROUTING INDEX (RDB$PRIMARY51)`) |
| 16 | FAILTYPE | F | FAILTYPE_DESC |

The EVENTS derived table is a UNION of the two branches — the plan always shows both,
`JOIN (EVENTS W, EVENTS T, EVENTS E)` and `JOIN (EVENTS W, EVENTS E)`. Columns with no base
context (WAYBILL, TRACKNO, EVENTDATE, EVENTTIME, INPUTMETHOD, HUB, MANIFEST, CHARGEMASS, BAY,
SCANSPEED, TRACKLEVEL, RECIPIENT, AGTRACKNO) come out of that union. EVENTTYPE itself is not
exposed; only its SCANRULE description `NAME` is.

Columns (29): WAYBILL VARCHAR(24), TRACKNO VARCHAR(28), EVENTDATE DATE, EVENTTIME TIME,
INPUTMETHOD CHAR(18), NAME VARCHAR(30), EXPECTED SMALLINT, HUB CHAR(3), MANIFEST INTEGER,
BRANCHNAME VARCHAR(20), USERNAME VARCHAR(30), ACCNUM VARCHAR(6), SERVICE CHAR(3), ACTKG FLOAT,
CHARGEUNITS FLOAT, REFERENCE VARCHAR(28), CHARGEMASS NUMERIC(.,2), ORIGHUB CHAR(3), DESTHUB
CHAR(3), WAYDATE DATE, BAY SMALLINT, SCANSPEED SMALLINT, FAILTYPE_DESC VARCHAR(30), TRACKLEVEL
CHAR(8), AGENTNAME VARCHAR(60), PODDATE DATE, PODTIME TIME, RECIPIENT VARCHAR(30), AGTRACKNO
VARCHAR(28).

EVENT columns (20): TRACKNO VARCHAR(28), HUB CHAR(3), EVENTTYPE CHAR(3), MANIFEST INTEGER,
EVENTDATE DATE, EVENTTIME TIME, AGENT INTEGER, BRANCH SMALLINT, EXPORT SMALLINT, USERCODE
INTEGER, EVENTDATETIME TIMESTAMP, WEBEXPORT, RULEGROUP, INPUTMETHOD, INHOUSE, BAY, WAYLEVEL
SMALLINT, LONGITUDE INTEGER, LATITUDE INTEGER, SCANSPEED SMALLINT.

ROUTING columns (67): WAYBILL VARCHAR(24), LEG SMALLINT, MBRANCH SMALLINT, MTYPE CHAR(1),
MANIFEST INTEGER, AGENT SMALLINT, AWB, REFERENCE, AGENTDATE DATE, COSTSERV, SERVTYPE, AREA,
ORIGHUB, DESTHUB, OTHERCHARGE, SUBTOTAL, VAT, TOTAL, CURRATE, STATUS, CUSTOMSGROUP, BRANCH,
EXPORT, COMPLETE, SORTORDER, PAYGROUP, CHARGEMASS, VATPAID, TOTPAID, VATTYPE, FAILTYPE, PIF,
INVAMOUNT, VOLRATE, VOLMASS, CLOSED, INHOUSE, BOOKDATE DATE, STARTTIME, ENDTIME, FLIGHT,
CUSTOMSDUTIES, CUSTOMSVAT, SECURITY, DELOTP, ESTATECODE, MOBEXPORT, SURCHARGEFLAG1–9,
SURCHARGE1–9, TOTSURCHARGE, HANDLING.

### 2.2 Indexes (RDB$INDICES / RDB$INDEX_SEGMENTS; selectivity as Firebird stores it)

**ROUTING** (6,221,145 rows today, counted in §4.5):

| Index | Columns | Selectivity |
|---|---|---|
| RDB$PRIMARY51 (unique) | WAYBILL, LEG | 1.77e-07 |
| RO_AGENTWAYBILL | AGENT, WAYBILL | 1.88e-07 |
| RO_AGNTAGNTDATE | AGENT, AGENTDATE | 3.51e-06 |
| RO_AGNTDATEAGENT | AGENTDATE, AGENT | 3.51e-06 |
| RO_AWB | AWB | 2.08e-04 |
| RO_BOOKDATE | BOOKDATE | 6.73e-04 |
| RO_COSTSERV | COSTSERV | 0.25 |
| RO_EXPORT | EXPORT | 0.5 |
| RO_MANIFEST | MANIFEST | 1.57e-06 |
| RO_PAYGROUP | PAYGROUP | 7.21e-05 |

No index starts with MBRANCH or MTYPE; a manifest read is driven by RO_MANIFEST alone and the
other two are filtered afterwards (cheap: ~130 rows per manifest number).

**EVENT** (113,122,153 rows at the 6 Aug survey):

| Index | Columns | Selectivity |
|---|---|---|
| RDB$PRIMARY130 (unique) | TRACKNO, HUB, EVENTTYPE, MANIFEST | 9.33e-09 |
| EV_TRACKDATETIME | TRACKNO, EVENTDATE, EVENTTIME | 9.51e-09 |
| EV_TYPEDATETIME | EVENTTYPE, EVENTDATE, EVENTTIME | 2.27e-08 |
| EV_EVENTDATE | EVENTDATE | 1.66e-04 |
| EV_MANIFEST | MANIFEST | 1.62e-06 |
| EV_AGENT_EVTYPE | AGENT, EVENTTYPE | 2.21e-04 |
| EV_EXPORT | EXPORT | 1 |
| EV_WEBEXPORT | WEBEXPORT | 0.333 |

**Other relations the view touches** (only the indexes the plans used or that matter):
TRACK — RDB$PRIMARY62 (WAYBILL, PARCELNO), TR_TRACKNO (TRACKNO); WAYBILL — RDB$PRIMARY13
(WAYBILL), WA_WAYDATE (WAYDATE, CUSTNAME), WA_ACCDT (ACCNUM, WAYDATE), WA_ACCNUM (ACCNUM);
POD — RDB$PRIMARY26 (WAYBILL); SCANRULE — RDB$PRIMARY131 (EVENTTYPE); USERCODE — RDB$PRIMARY65;
BRANCH — RDB$PRIMARY15; AGENT — RDB$PRIMARY7; FAILTYPE — RDB$PRIMARY75. Full lists are in the
defs output inside the main log.

## 3. Method

- Every statement is prepared with Firebird's plan option and its PLAN read **before** it is
  executed. A VIEW_EVENTSCANS statement whose plan showed a NATURAL scan on EVENT, TRACK,
  WAYBILL, ROUTING or POD was recorded and not executed (four of them, §5.3). The one deliberate
  natural scan is the unbounded ROUTING COUNT(*).
- Each executed statement ran twice on fresh connections: *cold* (first touch of those pages
  today) then *warm*. Timing is execute + fetch, wall-clock, from the BI server over the LAN.
- Two shapes: **rows** = `SELECT FIRST 501 <columns> …` (what open_query does: ROW_CAP + 1);
  **count** = `SELECT COUNT(*) …` (the full cost of the window — what any aggregate over it
  makes Firebird do). They cost different things and both are reported.
- Socket timeout 60 s. One statement tripped it (§6.2). A tripped timeout does not stop
  Firebird 3 server-side; MON$STATEMENTS was checked afterwards and nothing of ours was still
  running.
- Dates were chosen disjoint so a wider window is not pre-warmed by a narrower one: 1 day =
  2026-10-19 (Mon); 2 days = 2026-09-28..29; 3 days = 2026-10-13..15; 7 days = 2026-10-05..11;
  31 days = 2026-08-31..2026-09-30; 62 days = 2026-07-31..09-30; 92 days = 2026-07-01..09-30.
- Sample waybills came from VIEW_WBANALYSE (WAYDATE 2026-10-13, account S135, 24 clean numbers)
  so the ROUTING and EVENT pages were cold; the tracking number came from TRACK by its primary
  key; trips 37733 (branch 0) and 1016558 (branch 1) are the 18 Aug probe trips.

## 4. ROUTING

### 4.1 By waybill

| Probe | PLAN | cold | warm | rows |
|---|---|---|---|---|
| R1 `WHERE WAYBILL = ?` (FIRST 501) | `PLAN (ROUTING INDEX (RDB$PRIMARY51))` | 2 ms | 2 ms | 2 |
| R2 `WHERE WAYBILL IN (5 literals)` | `PLAN (ROUTING INDEX (RDB$PRIMARY51, RDB$PRIMARY51, RDB$PRIMARY51, RDB$PRIMARY51, RDB$PRIMARY51))` | 4 ms | 4 ms | 11 |
| R2b `WHERE WAYBILL IN (24 literals)` | `PLAN (ROUTING INDEX (RDB$PRIMARY51 ×24))` | 13 ms | 13 ms | 61 |

The PK prefix on WAYBILL serves equality and IN-lists; cost is linear in the list length.

### 4.2 By manifest

| Probe | PLAN | cold | warm | rows |
|---|---|---|---|---|
| R3 `MANIFEST = 37733 AND MBRANCH = 0 AND MTYPE = 'M'` | `PLAN (ROUTING INDEX (RO_MANIFEST))` | 59 ms | 23 ms | 124 |
| R3b `MANIFEST = 1016558 AND MBRANCH = 1 AND MTYPE = 'M'` | `PLAN (ROUTING INDEX (RO_MANIFEST))` | 54 ms | 25 ms | 136 |
| R3c `COUNT(*) WHERE MANIFEST = 37733` (no branch/type) | `PLAN (ROUTING INDEX (RO_MANIFEST))` | 1 ms | 1 ms | count 133 |

124 and 136 match the 18 Aug probe (= MANIFEST.NOWB). MANIFEST alone returns 133 rows for 37733
— nine rows from another MTYPE/branch sharing the number — so a manifest-keyed read is allowed
as a third form, and the message should say to add MBRANCH and MTYPE to get one trip.

### 4.3 By date

| Probe | PLAN | cold | warm | result |
|---|---|---|---|---|
| R4 AGENTDATE 1 day, count | `PLAN (ROUTING INDEX (RO_AGNTDATEAGENT))` | 14 ms | 2 ms | 2,364 |
| R4 AGENTDATE 1 day, rows | same | 92 ms | 85 ms | 501 (cap) |
| R4 AGENTDATE 7 days, count | same | 126 ms | 6 ms | 11,951 |
| R4 AGENTDATE 7 days, rows | same | 86 ms | 88 ms | 501 (cap) |
| R4 AGENTDATE 31 days, count | same | 168 ms | 20 ms | 48,680 |
| R4 AGENTDATE 31 days, rows | same | 89 ms | 88 ms | 501 (cap) |
| R4x AGENTDATE 62 days, count | same | 444 ms | 38 ms | 92,422 |
| R4x AGENTDATE 92 days, count | same | 463 ms | 54 ms | 139,763 |
| R7 AGENTDATE 7 days, `GROUP BY MTYPE, ORIGHUB, DESTHUB` with COUNT(DISTINCT WAYBILL) | `PLAN SORT (ROUTING INDEX (RO_AGNTDATEAGENT))` | 21 ms | 21 ms | 53 groups |
| R5 BOOKDATE 1 day, count | `PLAN (ROUTING INDEX (RO_BOOKDATE))` | 1 ms | 1 ms | 64 |
| R5 BOOKDATE 1 day, rows | same | 13 ms | 14 ms | 64 |
| R5 BOOKDATE 7 days, count | same | 2 ms | 1 ms | 260 |
| R5 BOOKDATE 7 days, rows | same | 49 ms | 53 ms | 260 |
| R5 BOOKDATE 31 days, count | same | 14 ms | 2 ms | 1,282 |
| R5 BOOKDATE 31 days, rows | same | 109 ms | 96 ms | 501 (cap) |

AGENTDATE is the window column: indexed (RO_AGNTDATEAGENT prefix), populated on every leg type,
~1,500–2,400 rows a day. **BOOKDATE is indexed and cheap but sparse**: over the same 31 days,
`GROUP BY MTYPE` gives BOOKDATE rows = {NULL: 36, '': 21, R: 1,225} against AGENTDATE rows =
{NULL: 1,993, '': 355, C: 9,660, M: 16,816, R: 19,856} with BOOKDATE populated on 1,178 of the
19,856 R rows and on no M or C row. A BOOKDATE window would silently answer about 2.6% of the
rows — a plausible wrong number — so it is accepted as a filter, not as the window.

### 4.4 The thing the guard prevents

| Probe | PLAN | time | result |
|---|---|---|---|
| R6 `SELECT COUNT(*) FROM ROUTING` (once) | `PLAN (ROUTING NATURAL)` | 7,897 ms | 6,221,145 |

An unwindowed aggregate over ROUTING is 8 s of table scan; ROUTING has grown from 6,018,355
(6 Aug) to 6,221,145 rows (≈2,700 a day).

## 5. VIEW_EVENTSCANS

Every view plan carries the same three parts: two one-line sub-plans for correlated lookups
inside the view (`PLAN (VIEW_EVENTSCANS EVENTS TRACK INDEX (TR_TRACKNO))` and
`PLAN (VIEW_EVENTSCANS ROUTING INDEX (RDB$PRIMARY51))`), then the main join. In the main join
the lookup tail is identical on every probe:

```
…, VIEW_EVENTSCANS W INDEX (RDB$PRIMARY13), VIEW_EVENTSCANS S INDEX (RDB$PRIMARY131)),
VIEW_EVENTSCANS U INDEX (RDB$PRIMARY65)), VIEW_EVENTSCANS B INDEX (RDB$PRIMARY15)),
VIEW_EVENTSCANS AG INDEX (RDB$PRIMARY7)), VIEW_EVENTSCANS POD INDEX (RDB$PRIMARY26)),
VIEW_EVENTSCANS R INDEX (RDB$PRIMARY51)), VIEW_EVENTSCANS F INDEX (RDB$PRIMARY75))
```

Below, "…+lookups" stands for that tail; the driving part — how the two EVENTS branches are
entered — is quoted in full because that is where the window either works or does not. The
.txt logs carry every line verbatim.

### 5.1 By key — pushed into EVENT

| Probe | Driving part of PLAN | cold | warm | rows |
|---|---|---|---|---|
| V1 `WAYBILL = ? ORDER BY EVENTDATE, EVENTTIME` | `PLAN SORT (JOIN (… JOIN (EVENTS W INDEX (RDB$PRIMARY13), EVENTS T INDEX (RDB$PRIMARY62), EVENTS E INDEX (EV_TRACKDATETIME)), JOIN (EVENTS W INDEX (RDB$PRIMARY13), EVENTS E INDEX (EV_TRACKDATETIME)) …+lookups))` | 8 ms | 7 ms | 16 |
| V1b `WAYBILL IN (5)` | same with `EVENTS W INDEX (RDB$PRIMARY13 ×5)` in both branches | 57 ms | 57 ms | 208 |
| X2 `WAYBILL IN (24)` | same, ×24 | 135 ms | 138 ms | 501 (cap) |
| V2 `TRACKNO = ?` | branch 1 `EVENTS T INDEX (TR_TRACKNO), EVENTS W INDEX (RDB$PRIMARY13), EVENTS E INDEX (EV_TRACKDATETIME)`; branch 2 `EVENTS W INDEX (RDB$PRIMARY13), EVENTS E INDEX (EV_TRACKDATETIME)` | 5 ms | 5 ms | 8 |
| V6c `MANIFEST = 37733` (rows) | both branches `EVENTS E INDEX (EV_MANIFEST)` then T / W by PK | 977 ms | 127 ms | 501 (cap) |
| X3 `MANIFEST = 37733` (count) | same | 40 ms | 39 ms | 1,456 |

The WAYBILL predicate is pushed into both union branches: WAYBILL by PK, then TRACK by PK, then
EVENT by `EV_TRACKDATETIME`. Sixteen scans for the sample waybill, eight of them parcel-level.
So WAYBILL, TRACKNO and MANIFEST are all real keys on the view.

### 5.2 By EVENTDATE — pushed into EVENT, cost is the per-row lookups

| Probe | Driving part of PLAN | cold | warm | result |
|---|---|---|---|---|
| V3 EVENTDATE 1 day, rows | `JOIN (EVENTS E INDEX (EV_EVENTDATE), EVENTS T INDEX (TR_TRACKNO), EVENTS W INDEX (RDB$PRIMARY13)), JOIN (EVENTS E INDEX (EV_EVENTDATE), EVENTS W INDEX (RDB$PRIMARY13)) …+lookups` | 736 ms | 136 ms | 501 (cap) |
| V3 EVENTDATE 1 day, count | same | 5,697 ms | 1,196 ms | 50,679 |
| X1 EVENTDATE 2 days, count | same | 7,097 ms | 2,533 ms | 107,366 |
| X1 EVENTDATE 3 days, count | same | 7,912 ms | 3,541 ms | 149,966 |
| V3 EVENTDATE 7 days, rows | same | 2,268 ms | 131 ms | 501 (cap) |
| V3 EVENTDATE 7 days, count | same | 14,518 ms | 6,922 ms | 287,856 |
| V5b `ACCNUM = 'S135' AND EVENTDATE` 7 days, count | same (ACCNUM filtered after the W lookup) | 2,541 ms | 2,559 ms | 4,063 |
| V6b `HUB = 'JNB' AND EVENTDATE` 1 day, count | same (HUB filtered inside the union) | 618 ms | 617 ms | 25,367 |
| E3 `NAME = 'Collected from Origin Address' AND EVENTDATE` 1 day, `GROUP BY EVENTDATE, HUB` | `PLAN SORT (JOIN (… EVENTS E INDEX (EV_EVENTDATE) … S INDEX (RDB$PRIMARY131) …))` | 520 ms | 518 ms | 3 groups |

EVENTDATE goes into EVENT through `EV_EVENTDATE` in both branches. The cost is then the eight
lookups per event row (~24 µs warm), which is why the view is ~50× dearer per row than ROUTING
and why its window is 3 days where ROUTING's is 31. A further filter (ACCNUM, HUB, NAME) does
not shrink the EVENT scan — it is applied after the lookups — but it does cut the fetched rows.

### 5.3 Not windows — the planner scans TRACK and WAYBILL (not executed)

| Probe | Driving part of PLAN |
|---|---|
| V4 `WAYDATE BETWEEN` 1 day (rows and count) | `JOIN (EVENTS T NATURAL, EVENTS W INDEX (RDB$PRIMARY13), EVENTS E INDEX (EV_TRACKDATETIME)), JOIN (EVENTS W NATURAL, EVENTS E INDEX (EV_TRACKDATETIME)) …+lookups` |
| V5 `ACCNUM = 'S135' AND WAYDATE BETWEEN` 7 days (rows and count) | identical |
| V6 `NAME = '…'` with no window | identical |

WAYDATE and ACCNUM belong to the outer W lookup (context 8), and NAME to SCANRULE; none of them
reaches the EVENTS union, so the planner walks all of TRACK (14.1M rows) and WAYBILL (3.1M)
and probes EVENT once per row. None of these four was executed; by the per-row cost measured
above they would run for minutes. **WAYDATE is not a window on this view.** The same applies
to USERNAME, AGENTNAME, BRANCHNAME, ORIGHUB/DESTHUB, PODDATE — all lookup-side columns.

## 6. Reuven's two event tools — measurements for the quote (not built)

### 6.1 Tool (a): every scan for one waybill, ordered by date and time

| Probe | PLAN | cold | warm | rows |
|---|---|---|---|---|
| V1 via the view, `WAYBILL = ? ORDER BY EVENTDATE, EVENTTIME` | as §5.1 | 8 ms | 7 ms | 16 |
| E1 direct on EVENT: `TRACKNO = ? UNION ALL (EVENT e JOIN TRACK t ON t.TRACKNO = e.TRACKNO WHERE t.WAYBILL = ?) ORDER BY 1, 2` | `PLAN SORT (E INDEX (EV_TRACKDATETIME), JOIN (T INDEX (RDB$PRIMARY62), E INDEX (EV_TRACKDATETIME)))` | 4 ms | 5 ms | 16 |

Both are keyed end to end; the view version gives the event name, hub name, user, agent and
POD columns without extra work. **Rough estimate: 2.5 h** as a named tool (`waybill_history`
or an option on `waybill_status`) with tilde / not-found handling like waybill_status, the
same column withholding, tests and README — the query is measured, the hours are the tool.

### 6.2 Tool (b): scans per day and per hub for one event type over a date range

Event types live in SCANRULE (112 rows, `EVENTTYPE CHAR(3)` → `NAME`; many are retired, prefixed
`XXX-`/`xxx`). "Collected from Origin Address" is `'O'`. Volumes on Mon 2026-10-19, each a
single `EV_TYPEDATETIME` range (1–4 ms): C Closed and Dispatched 8,600 · P POD Details Captured
6,851 · I POD Image Scanned 6,087 · 1 Loaded for Delivery 5,922 · B Consignment details captured
5,104 · 3 Manifest Outbound 3,066 · A Received at origin depot 2,895 · S Swadded 2,537 · D
Checked in at Origin Depot 1,416 · R Ready for Collection 1,405 · **O Collected from Origin
Address 1,256** · 2 Manifest Inbound 981 · F 623 · 4 612 · Y 247 · M Mis-routed 45 · U 9 · Z 6.

| Probe (direct on EVENT) | PLAN | cold | warm | rows out |
|---|---|---|---|---|
| E2 `EVENTTYPE = 'O' AND EVENTDATE` 1 day, `GROUP BY EVENTDATE, HUB` | `PLAN SORT (EVENT INDEX (EV_TYPEDATETIME))` | 29 ms | 3 ms | 3 |
| E2 same, 7 days | same | 12 ms | 12 ms | 19 |
| E2 same, 31 days | same | 964 ms | 51 ms | 80 |
| X6 `EVENTTYPE = 'C'` (heaviest type), 7 days | same | 44 ms | 44 ms | 61 |
| X6 same, 31 days | same | 696 ms | 196 ms | 285 |

**The (type, date) pair is supported by an index** — `EV_TYPEDATETIME (EVENTTYPE, EVENTDATE,
EVENTTIME)` — so the aggregate never scans the window: 31 days of the heaviest type is 0.7 s
cold. Two shapes to avoid, both measured:

- Through the view by NAME (E3): the planner drives from `EV_EVENTDATE` and filters NAME after
  the lookups — 520 ms for one day, so ~16 s *estimated* for 31 days. The tool must query
  EVENT directly (it is a named tool, not the open path), resolving the name to its code(s)
  via SCANRULE.
- Grouping over all types at once: `SELECT EVENTTYPE, COUNT(*) FROM EVENT WHERE EVENTDATE =
  DATE '2026-10-19' GROUP BY 1` planned as `PLAN SORT (EVENT ORDER EV_TYPEDATETIME INDEX
  (EV_EVENTDATE))` — Firebird walked the whole 113M-entry EV_TYPEDATETIME index in order —
  and was **aborted at 60 s** (statement E2a; it completed server-side on its own; nothing was
  left running when MON$STATEMENTS was read at 10:00). One type per index range is the safe
  shape; several types = several ranges (an IN-list of codes).

**Rough estimate: 3.5 h** — name → code resolution with an honest ambiguity answer (the
retired XXX- rules), a capped range (31 days measured at under a second on the heaviest type;
92 would still fit), per-day-per-hub output with the hub name, tests, README, review.

## 7. Caveats carried into line 4

- Firebird 3.0.13 has no server-side statement timeout; the 15 s client cap bounds the wait,
  not the load. The window is the load guard, which is why both widths sit well inside the
  cap cold.
- Cold numbers were taken mid-morning on a quiet database; the 16:30 run and Reuven's own
  sessions will share the cache. Warm numbers are the steady state for repeated questions.
- The joined-to-VIEW_WBANALYSE estimate (§1) is arithmetic; VIEW_WBANALYSE is already
  unbounded on the open path, so this is a pre-existing exposure the window narrows, not one
  it creates.
- ROUTING rows with NULL or blank MTYPE exist (1,993 + 355 in September by AGENTDATE); a
  manifest-keyed read with MTYPE given will not see them, which is correct for a trip read.
- VIEW_EVENTSCANS.RECIPIENT and USERNAME are people's names (POD recipient, the staff member who
  scanned); line 4 decides whether the column guard withholds them, as the Chunk 3 prompt says.
