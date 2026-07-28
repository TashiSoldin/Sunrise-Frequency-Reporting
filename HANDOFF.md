# Session Handoff — Sunrise Revenue Automation

**Prompt to resume in a fresh Cowork session** (connect this repo + "Dashboards and
Data Analysis" + "Claude General" folders first):

> Continue Phase 0 of the Sunrise revenue automation on branch
> `feature/revenue-extraction`. Read `PLAN.md`, then build `build_dashboard.py`
> per `revenue_reports/DASHBOARD_SPEC.md`, following the pattern of
> `build_flash.py` / `build_billing_detail.py` (shared `style.py`, `data.py`).
> Diff the output cell-by-cell against `Revenue Dashboard.xlsx` in the Dashboards
> folder and iterate to ~0 diffs (allow live-DB drift). Then build the unbilled
> report (reference: `Unbilled Waybills Report FY27 - 27 Jul 2026.xlsx`) and a
> standalone credit-notes report the same way. Email me progress/blockers via Spark.

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
