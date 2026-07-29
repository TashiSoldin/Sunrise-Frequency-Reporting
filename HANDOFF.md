# Session Handoff — Sunrise Revenue Automation

Two workstreams, resumable independently. Connect this repo + "Dashboards and
Data Analysis" + "Claude General" folders first, then paste the relevant prompt.

**Standing instruction for every session:** when you complete a phase or make a
material decision/discovery, update the **"Sunrise Logistics" doc in Akha's Coda
workspace** (via the Superhuman Docs/Coda MCP — search for "Sunrise"): the
Overview status line, the Project Tasks table on the Tasks page, and the
Decisions & Open Questions page (28 Jul update pattern). Also update the Status
table below and commit. Email Akha via Spark on completions and blockers only (send from amanjezi@gmail.com).

## Workstream A — Phase 0 (report builders)

**Prompt:**

> Continue Phase 0 of the Sunrise revenue automation on branch
> `feature/revenue-extraction`. Read `PLAN.md`, then build `build_dashboard.py`
> per `revenue_reports/DASHBOARD_SPEC.md`, following the pattern of
> `build_flash.py` / `build_billing_detail.py` (shared `style.py`, `data.py`).
> Diff the output cell-by-cell against `Revenue Dashboard.xlsx` in the Dashboards
> folder and iterate to ~0 diffs (allow live-DB drift). Then build the unbilled
> report (reference: `Unbilled Waybills Report FY27 - 27 Jul 2026.xlsx`) and a
> standalone credit-notes report the same way. As you complete pieces, keep
> `HANDOFF.md` current (commit), update the "Sunrise Logistics" doc in my Coda
> workspace (Overview status, Project Tasks table, Decisions & Open Questions),
> and email me via Spark on completions and blockers (send from amanjezi@gmail.com).

## Workstream B — Phases 1–2 (DB extraction)

Use when Akha returns with output from `research/revenue_extraction_test.py`
(run on the BI server over RDC; output text + `revenue_sample_*.csv` pasted in
chat or dropped in the Claude General folder).

**Prompt:**

> Continue Phases 1–2 of the Sunrise revenue automation on branch
> `feature/revenue-extraction`. Read `PLAN.md` and `HANDOFF.md`. I've run the DB
> smoke test — output is [pasted below / in the Claude General folder]. Using the
> discovered VIEW_WBANALYSE schema: (1) reconcile the sample CSV against the
> matching date range of the manual export in "Dashboards and Data Analysis/2.
> Revenue Data" (row counts + Subtotal sums must match); (2) write the production
> extraction module in `revenue_reports/` producing the three daily files (WB-date
> FY dump, INV-date FY dump, credits) with the exact columns/format the report
> builders and Larry's current process expect; (3) from the smoke test's
> credit-notes table scan plus the Parcel Perfect manuals in the Claude General
> folder, write the credit-notes extraction query. I'll test each query iteration
> on the BI server and paste results back. As you complete pieces, keep
> `HANDOFF.md` current (commit), update the "Sunrise Logistics" doc in my Coda
> workspace (Overview status, Project Tasks table, Decisions & Open Questions),
> and email me via Spark on completions and blockers (send from amanjezi@gmail.com).

Context the new session needs: the manual export the extraction replaces is a full
dump of the "Analyze Waybills" screen (= VIEW_WBANALYSE), 1 March FY start onward,
tilde (`~`) waybills excluded, saved once keyed on waybill date and once on invoice
date. Credits come from a different data pool (receipts/debtors side — table name
unknown; the smoke test scan + manuals are the lead). Extraction must be schedulable
later on the BI server via Task Scheduler (Phase 4), same pattern as Alex's reports
in `report_generation/`.

## Status (29 Jul 2026)

**Next action (Akha, on the BI server):** `uv run research/consolidated_probe.py`
→ drop `consolidated_probe_*.txt`, `waybill_probe_*.csv` and
`credits_trial_*.csv` in the Claude General folder. That run (a) dumps
WAYBILL.* for known Consolidated=Yes/No waybills so the source field can be
spotted by direct comparison (last unmapped builder-consumed column),
(b) fetches BRANCH/COSTCNTR name lookups for the credits file, and (c) trial-
runs the production CREDITS_SQL for local reconciliation vs the manual
credits export. After that: full-FY trial of `extract_revenue.py` reconciled
against the day's manual exports → Phase 4 scheduling.

| Item | State |
|---|---|
| PLAN.md (phases 0–4) | done |
| Phase 1 DB smoke test | **passed 29 Jul** — output + sample CSV in Claude General folder root. VIEW_WBANALYSE = 134 cols; export headers are renames (REP→Salesrep, INVDATE→Invoice Date, INVOICE→Invoice #): build a DB→export-header column map. Raw view includes Cancelled rows — filter. Credits table not found by scan (only INVOICE/PROINVOICE); next lead: `%RECEIPT%` tables + PP manuals |
| Flash builder | done, reconciled vs 27 Jul ref (drift-only diffs; "typical weekday" formula flagged as assumption) |
| Billing detail builder | done, 3/5 tabs zero diffs; flash-comparison arithmetically corrected vs ref; consolidation ordering cosmetic |
| Dashboard builder (`build_dashboard.py`) | done, reconciled vs 28 Jul ref (`--inv-asof 2026-07-24 --wb-asof 2026-07-27`): 6 of 10 tabs zero diffs incl. all month tabs + YTD + Daily-Invoice; rest is live-DB drift + cosmetic tie-ordering in memo buckets (ref's MTD closed-block order is a non-deterministic artifact of its generator) + 1 stale-text bug in ref credit-notes footnote ("14 Jul"). Diff tool: `revenue_reports/diff_workbooks.py` |
| Unbilled builder (`build_unbilled.py`) | done; rule reverse-engineered from ref (PP invoice status ≤ 0, billing-frontier cutoff). Structure exact vs 27 Jul ref; row deltas are pure PP drift (29 waybills billed since ref snapshot, 5 status/rate changes) |
| Credit-notes builder (`build_credit_notes.py`) | done (no ref existed — new standalone report: Overview w/ FY27 monthly trend + by-reason, By Customer, Detail). KPIs/reason table reconcile exactly to dashboard MTD Credit Notes tab |
| Phase 2 reconciliation (sample vs manual export) | **passed 29 Jul** — 22–27 Jul window vs 28 Jul manual WB export: same-status rows 2,431 with **zero** subtotal diffs; all 360 mismatches were status-transition drift (re-rated between pulls); row deltas = 36 Cancelled (export filters them) + 5 new/2 gone drift. Export rules confirmed: exclude tilde + `STATUS <> 'Cancelled'`, include all other statuses, **no upper date cap** (manual export contains future-dated waybills, e.g. 31 Jul in a 28 Jul pull) |
| Production extraction (`revenue_reports/extract_revenue.py`) | **column map VERIFIED 29 Jul** — per-column diff vs manual export (2,431 same-status waybills): all money/mass/count columns 100%. Fixes applied from the diff: surcharge order per `VIEW_SURCHARGES` (S1=Sameday…S6=Fuel…S9=Townships); cost-centre headers are crossed in PP's export (Waybill CC=CCNAME, Customer CC=COSTCNTRNAME); export's "Last Delivery Driver" duplicates Delivery Agent (both ← DELIVERYAGENT); INPUTMETHOD/COLSTATUS code→name maps; flags → Excel booleans; times truncated to seconds; Customs Group default-fills "Documents". 112/157 mapped. Remaining gaps: `Consolidated` (WAYREF probe queued) + `Scan Batch` (not PODBATCH; IMAGEBATCH1/PAGEEVENTBATCH queued); rest of the diff deltas were pure POD/receipt drift between the 28 Jul export and 29 Jul DB |
| Phase 3 credit notes | **writer WIRED** (`write_credits_xlsx`, exact 28-header staff layout): RECTYPE codes confirmed by exact count match vs credits file (N=5718 Credit Note, B=497 Bad Debt, X=249 Cancelled, J=1 Journal Credit); Reason = NOTETYPE lookup (descriptions match verbatim); User Name + Credit Controller via VIEW_USERCODE; Rep via CUSTOMER.REP→REP.NAME; Reference↔r.REFERENCE and Comment↔r.COMMENT confirmed against DB sample. Branch/Cost Centre written as raw codes pending BRANCH/COSTCNTR lookups (iteration 4); Capture Date/Time source unknown (no builder consumes them — blank). Output is `.xlsx` (staff file is `.xls`) — credits readers in build_credit_notes.py / build_dashboard.py to be adapted before switchover. Reconciliation of the trial dump = next session |
| Verify iteration 2 (`revenue_extract_verify.py`) | **done 29 Jul** — surcharge names via VIEW_SURCHARGES; RECEIPT table found; %CONSOL% only hit AGENT.CONSOLIDATE (not waybill-level) |
| Discovery iteration 3 (`credits_discovery.py`) | **done 29 Jul** — RECTYPE/NOTETYPE/joins resolved (above); USERCODE table SELECT-denied for BI role → use VIEW_USERCODE; Scan Batch = IMAGEBATCH1 (verified via scanbatch dump; ~6% both-populated conflicts = re-scan drift); Consolidated STILL unresolved: not account-level (20 mixed accounts), not First Ref group-size (82%), not ref-points-at-waybill (89%) — WAYBILL.* probe queued |
| Probe iteration 4 (`consolidated_probe.py`) | **ready to run** — see Next action above |
| Phase 4 (scheduling, delivery) | not started |

### Dashboard reconciliation subtleties (learned the hard way, encoded in build_dashboard.py)

- Trading days actually used by ref: Mar 22, **Apr 22**, May 21, Jun 22 (YTD 87), Jul 23/18 elapsed — spec's "Apr 21(est)" is wrong.
- Fold ONLY budget DEDI-group accounts into parents; separately-budgeted DED codes (J33DED) stay their own rows.
- Non-budget accounts per window: invoice rows → their salesrep section; credit-only activity → Closed; nets-to-zero → dropped. LY-only accounts (incl. credit-only, e.g. G59) → Closed when LY net ≠ 0. Universe must include credits-file-only accounts.
- Sort keys: budgeted by (−target, −max(actual, LY)); zero-target and month/YTD closed by (−max(actual, LY), budget-order, −LY, actual); house by (−max(actual,0), budget order). MTD tab's closed block uses the older cur/LY/rest decomposition.
- MTD tab displays LY = FULL July FY26 but tab 1 row 19 uses like-for-like (first 18 trading days).

### Open questions for Larry (beyond DASHBOARD_SPEC.md's open items)

- **Bad debt**: "Bad Debt" is confirmed to be a credits *Type* (497 rows) — the guide's
  type-level exclusion is what the reference and our builders implement. BUT rows *typed*
  "Credit Note" with *reason* `CNB - Bad Debt` (~R763k across the credits file, R36,783 in
  Jul) DO reduce revenue in both. Intended, or miscaptured write-offs?
- **Unbilled**: waybills with status "Approved for Invoicing" (positive PP code) are
  excluded from the unbilled report (reference behaviour). They're pre-invoice though —
  should they be listed? Also confirm the billing-frontier cutoff rule (day after last
  invoiced waybill date) vs. e.g. last trading day.
- Trading-day calendar ownership + counts, flash "typical weekday" definition, standalone
  credit-notes layout sign-off — see DASHBOARD_SPEC.md open items / PLAN.md.

## Session blockers

- **Spark email**: designated sender is **amanjezi@gmail.com** (connected), but all
  Spark accounts are currently exposed read-only — sending/drafting fails until Akha
  raises the access level for that account in Spark Desktop → Settings. Until then,
  deliver progress notes in-chat and flag the blocker.

## Environment notes

- OneDrive files are cloud placeholders; sandbox bash gets "Resource deadlock avoided"
  until hydrated — trigger download via osascript `do shell script "cat 'file' > /dev/null"`.
- Git operations on the mounted repo hit un-deletable lock files from the sandbox;
  run commits via osascript on the Mac instead.
- Large exports: read with python-calamine (61 MB, seconds); credits `.xls` with xlrd.
- Reference outputs were generated from slightly older exports than the current ones —
  expect small "drift" diffs (added waybills, renamed customers); revenue totals match.
