<!--
Create the PR from the repo root with:

  gh pr create --base main --head feature/revenue-extraction \
    --title "Revenue reporting automation: extraction, five report builders, scheduled delivery" \
    --body-file PR-DESCRIPTION.md

(Delete this comment block first, or pass --title/--body inline. This file is untracked.)
-->

## Summary

End-to-end automation of Larry's daily revenue reporting, replacing the manual loop (staff export → download → prompt Claude to rebuild). Signed off by Larry on 3 Aug 2026 after his own cross-check matched the automated output to within pull-timing variance.

60 commits, +5,777 / −218 across 34 files. Everything new lives in `revenue_reports/`, `research/` and `tests/`; the only touch on the existing frequency/POD system is a small fix in `outlook_email_client.py` (attachment names from Windows paths).

## What's in here

**Extraction** — `extract_revenue.py` pulls the WB-date, INV-date and credit-notes exports directly from Parcel Perfect (Firebird: `VIEW_WBANALYSE` + `RECEIPT`), emitting drop-in replacements for the manual staff exports. Verified per-column: R0.00 diff across 84,106 invoice rows; credits reconciled to the cent over 3 FYs. Notable derivations: the "Consolidated" flag (no DB column exists — derived at 99.989% fidelity) and surcharge names via `VIEW_SURCHARGES`.

**Five report builders** — revenue dashboard (10 tabs), billing detail (incl. the Flash Comparison tab), flash, unbilled, credit notes — deterministic Python reconciled cell-by-cell against Larry's reference workbooks, including formatting fidelity (tab colours, freezes, fills, fonts, borders, number formats). All formula writes go through `xlsxvalues.py`, which requires a cached value so figures render outside desktop Excel (fixes the "all zeros" defect reported 2 Aug).

**Orchestration & delivery** — `run_daily.py` + `run_revenue_flash.bat` / `run_revenue_pm.bat` for the two Task Scheduler windows (07:00 flash Tue–Sat, 16:30 the other four on weekdays), emailing exco with the reports one trading day in arrears and landing them in the synced SharePoint folder. Date basis is `last_trading_day()` — the newest day that actually traded, so weekends, public holidays and not-yet-invoiced days are never reported. Credit notes key off the last invoiced day (`10381f9`). Logging follows `report_generation`'s rotating-handler convention; exit codes propagate to Task Scheduler.

**Tests & CI** — first test suite on the project: 53 tests (month selection/FY rollover, trading-day counts, formula cached values, formatting) plus an opt-in LibreOffice recalculation oracle; pytest job added to CI alongside ruff.

**Research scripts** — the schema-discovery and reconciliation probes (`research/`) kept for provenance.

## Deliberately unchanged

The frequency/POD reporting system (`report_generation/`, `run_reports.bat`, its Task Scheduler jobs and sender account) is untouched apart from the attachment-name fix — the revenue stream runs in its own scheduling bucket.

## Test plan

- `uv run pytest` (53 tests; `RECALC_ORACLE=1` additionally runs the LibreOffice oracle)
- Live: both scheduled jobs have run end-to-end on the BI server; outputs cross-checked by Larry against his manual pulls (3 Aug sign-off)
