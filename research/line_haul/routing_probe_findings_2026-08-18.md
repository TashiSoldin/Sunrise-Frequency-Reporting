# Line-haul extraction recon — findings (18 Aug 2026)

Five trips probed live via `routing_probe.py` (per-trip outputs saved alongside, dated).
This file is the design anchor for the QT-000005 extraction. Numbers measured; anything
labelled "candidate" or "verify" is NOT settled.

## The result

| Trip | Branch | Lane | Agent | MANIFEST.NOWB | ROUTING distinct WB | Legs | Revenue (WBANALYSE SUBTOTAL) | MANIFEST.TOTAL |
|---|---|---|---|---|---|---|---|---|
| 37733 | 0 | JNB→DUR | 30105 | 124 | **124** | 2 | R76,610.27 | 17,135 |
| 37739 | 0 | JNB→DUR | 30105 | 189 | **189** | 2,3,4 | R136,462.80 | 17,135 |
| 37735 | 0 | JNB→CPT | 30240 | 106 | **106** | 2 | R93,321.05 | 35,650 |
| 1016558 | 1 | DUR→JNB | 30034 | 136 | **136** | 2 | R111,148.80 | 17,135 |
| 37746 | 0 | JNB→DUR | 30113 | 7 | **7** | 2,3 | R13,524.61 | 12,650 |

**ROUTING's distinct-waybill count equals MANIFEST.NOWB on every trip** — both branch
number-series, multi-leg trips, large and small. The staff export's Last-Manifest route
recovered 102/124 on 37733 (82%); the DB route recovers 100% on all five. The
VIEW_WBANALYSE join on WAYBILL resolved every waybill on every trip (never needed the
WAYBILLORIG fallback) — the join key is pinned.

## Extraction design rules (from the measurements)

1. **Trip universe**: `MANIFEST WHERE MTYPE='M'`, keyed **BRANCH + MTYPE + MANIFEST**
   (numbers look series-prefixed per branch — 37xxx/1xxxxxx/2xxxxxx — and no collision
   was observed, but key on the composite anyway). Filter out the placeholder shapes the
   July listing exposed: negative MANIFEST numbers (agent −995, same-hub, NOWB=0),
   agent 0 / blank-hub rows (e.g. 37761), and treat NOWB=0 trips as non-trips.
2. **Membership**: ROUTING filtered to the manifest → distinct WAYBILL (+ LEG). Within
   one manifest each waybill appears once; LEG is the waybill's journey position, and a
   single trip can carry waybills on different legs (37739: legs 2/3/4).
3. **Masses and revenue: take from VIEW_WBANALYSE via the join, NOT from ROUTING.**
   ROUTING's own mass columns are unreliable — branch 1's rows carry CHARGEMASS=0 /
   VOLMASS=NULL entirely, and where populated the semantics are inconsistent
   (ROUTING SUM(VOLMASS) equals MANIFEST.CHARGEMASS on 37733/37746 but not on
   37739/37735; MANIFEST.CHARGEMASS equals ACTKG on some trips and not others). The
   WBANALYSE CHARGEMASS sum tracked ROUTING's CHARGEMASS sum wherever ROUTING was
   populated, so the view is the consistent source.
4. **Trip-cost candidate — verify before using**: MANIFEST.SUBTOTAL is 0.0 on all five,
   but MANIFEST.TOTAL carries a per-trip value that repeats by lane/agent
   (17,135 on all three JNB↔DUR trips across two agents and both directions; 35,650 on
   the CPT trip; 12,650 on the small JNB→DUR trip). If this is the agent's trip charge,
   it is exactly what the QT-000005 cost-model line needs — **check it against the RSL
   table's cost column or ask staff; do not assert it.**
5. Single-waybill trips carry round CHARGEMASS values (30,000 / 20,000 / 7,200) that
   look keyed rather than measured — treat mass on 1-waybill trips as suspect.

## Still pending

- RSL cross-check beyond 37733's waybill count: waybill counts and revenue for
  37739/37735/1016558/37746 against the RSL July table, and what RSL "Revenue" counts
  (open ask to Larry/staff).
- MANIFEST.TOTAL meaning (rule 4).
- Cosmetic: the probe's em-dashes render as 'ù' in the cp850 console — harmless, the
  saved outputs are otherwise intact.
