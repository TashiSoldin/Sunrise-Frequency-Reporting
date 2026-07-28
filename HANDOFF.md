# Session Handoff — Sunrise Revenue Automation

Two workstreams, resumable independently. Connect this repo + "Dashboards and
Data Analysis" + "Claude General" folders first, then paste the relevant prompt.

## Workstream A — Phase 0 (report builders)

**Prompt:**

> Continue Phase 0 of the Sunrise revenue automation on branch
> `feature/revenue-extraction`. Read `PLAN.md`, then build `build_dashboard.py`
> per `revenue_reports/DASHBOARD_SPEC.md`, following the pattern of
> `build_flash.py` / `build_billing_detail.py` (shared `style.py`, `data.py`).
> Diff the output cell-by-cell against `Revenue Dashboard.xlsx` in the Dashboards
> folder and iterate to ~0 diffs (allow live-DB drift). Then build the unbilled
> report (reference: `Unbilled Waybills Report FY27 - 27 Jul 2026.xlsx`) and a
> standalone credit-notes report the same way. Email me progress/blockers via Spark.

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
> on the BI server and paste results back.

Context the new session needs: the manual export the extraction replaces is a full
dump of the "Analyze Waybills" screen (= VIEW_WBANALYSE), 1 March FY start onward,
tilde (`~`) waybills excluded, saved once keyed on waybill date and once on invoice
date. Credits come from a different data pool (receipts/debtors side — table name
unknown; the smoke test scan + manuals are the lead). Extraction must be schedulable
later on the BI server via Task Scheduler (Phase 4), same pattern as Alex's reports
in `report_generation/`.

## Status (28 Jul 2026)

| Item | State |
|---|---|
| PLAN.md (phases 0–4) | done |
| Phase 1 DB smoke test (`research/revenue_extraction_test.py`) | written; Akha to run on BI server over RDC (needs `.env` creds from Alex) |
| Flash builder | done, reconciled vs 27 Jul ref (drift-only diffs; "typical weekday" formula flagged as assumption) |
| Billing detail builder | done, 3/5 tabs zero diffs; flash-comparison arithmetically corrected vs ref; consolidation ordering cosmetic |
| Dashboard | fully specced in `revenue_reports/DASHBOARD_SPEC.md`, builder not yet written |
| Unbilled + standalone credit notes | not started; references in Dashboards folder |
| Phases 2–4 (extraction, scheduling, delivery) | not started |

## Environment notes

- OneDrive files are cloud placeholders; sandbox bash gets "Resource deadlock avoided"
  until hydrated — trigger download via osascript `do shell script "cat 'file' > /dev/null"`.
- Git operations on the mounted repo hit un-deletable lock files from the sandbox;
  run commits via osascript on the Mac instead.
- Large exports: read with python-calamine (61 MB, seconds); credits `.xls` with xlrd.
- Reference outputs were generated from slightly older exports than the current ones —
  expect small "drift" diffs (added waybills, renamed customers); revenue totals match.
