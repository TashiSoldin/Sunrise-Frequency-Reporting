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
| Dashboard builder (`build_dashboard.py`) | done, reconciled vs 28 Jul ref (`--inv-asof 2026-07-24 --wb-asof 2026-07-27`): 6 of 10 tabs zero diffs incl. all month tabs + YTD + Daily-Invoice; rest is live-DB drift + cosmetic tie-ordering in memo buckets (ref's MTD closed-block order is a non-deterministic artifact of its generator) + 1 stale-text bug in ref credit-notes footnote ("14 Jul"). Diff tool: `revenue_reports/diff_workbooks.py` |
| Unbilled builder (`build_unbilled.py`) | done; rule reverse-engineered from ref (PP invoice status ≤ 0, billing-frontier cutoff). Structure exact vs 27 Jul ref; row deltas are pure PP drift (29 waybills billed since ref snapshot, 5 status/rate changes) |
| Credit-notes builder (`build_credit_notes.py`) | done (no ref existed — new standalone report: Overview w/ FY27 monthly trend + by-reason, By Customer, Detail). KPIs/reason table reconcile exactly to dashboard MTD Credit Notes tab |
| Phases 2–4 (extraction, scheduling, delivery) | not started |

### Dashboard reconciliation subtleties (learned the hard way, encoded in build_dashboard.py)

- Trading days actually used by ref: Mar 22, **Apr 22**, May 21, Jun 22 (YTD 87), Jul 23/18 elapsed — spec's "Apr 21(est)" is wrong.
- Fold ONLY budget DEDI-group accounts into parents; separately-budgeted DED codes (J33DED) stay their own rows.
- Non-budget accounts per window: invoice rows → their salesrep section; credit-only activity → Closed; nets-to-zero → dropped. LY-only accounts (incl. credit-only, e.g. G59) → Closed when LY net ≠ 0. Universe must include credits-file-only accounts.
- Sort keys: budgeted by (−target, −max(actual, LY)); zero-target and month/YTD closed by (−max(actual, LY), budget-order, −LY, actual); house by (−max(actual,0), budget order). MTD tab's closed block uses the older cur/LY/rest decomposition.
- MTD tab displays LY = FULL July FY26 but tab 1 row 19 uses like-for-like (first 18 trading days).

## Environment notes

- OneDrive files are cloud placeholders; sandbox bash gets "Resource deadlock avoided"
  until hydrated — trigger download via osascript `do shell script "cat 'file' > /dev/null"`.
- Git operations on the mounted repo hit un-deletable lock files from the sandbox;
  run commits via osascript on the Mac instead.
- Large exports: read with python-calamine (61 MB, seconds); credits `.xls` with xlrd.
- Reference outputs were generated from slightly older exports than the current ones —
  expect small "drift" diffs (added waybills, renamed customers); revenue totals match.
