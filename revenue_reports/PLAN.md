# Revenue Reporting Automation — Plan

Goal: automate Larry's daily revenue reporting end-to-end. Today a staff member manually
exports three files from Parcel Perfect (Analyze Waybills screen), Larry drops them into
iCloud, and prompts Claude to rebuild the reports. See
`Revenue Reporting Workflow — Replication Guide.md` (shared by Larry) for the full
workflow and report conventions.

## Target architecture

```
Parcel Perfect (Firebird DB, BI server)
        │  scheduled extraction (this repo, Task Scheduler — same pattern as
        │  the existing frequency/booking reports)
        ▼
Shared folder (iCloud "Dashboards and Data Analysis/2. Revenue Data")
        │  report pipeline (extract_all.py + build_*.py per the guide —
        │  initially driven by Claude, later ported into this repo)
        ▼
5 outputs: Revenue Dashboard, Daily Invoice/Billing Detail, Flash,
           Unbilled, Credit Notes → delivered by email or shared folder
```

Open decision: keep Claude in the loop for report generation (hybrid) or port the
build scripts fully into this repo (fully scripted). Building the report pipeline as
code during Phase 0 makes this mostly moot — the logic will exist as scripts either way.

## Phases

**Phase 0 — Replicate the outputs (acceptance test #1)**
Using the daily files Larry drops in the shared folder, rebuild the Revenue Dashboard,
Flash, and Billing Detail per the guide, and diff against Larry's reference outputs
until they match. This validates we understand the data and the conventions.

**Phase 1 — DB access smoke test**
Run `research/revenue_extraction_test.py` on the BI server (RDC). Confirms the
Firebird connection works, discovers the actual columns of `VIEW_WBANALYSE`, checks
which billing fields exist, and hunts for the credit-notes source tables.

**Phase 2 — Revenue extraction + reconciliation (acceptance test #2)**
Write the production extraction: full-FY dump of the Analyze Waybills fields on both
waybill-date and invoice-date bases, tilde (re-delivery) waybills excluded — the
programmatic equivalent of the manual export. Reconcile row counts and Subtotal sums
against the manual export for the same date range. Must match before proceeding.

**Phase 3 — Credit notes extraction**
Different data pool from VIEW_WBANALYSE. Identify the table(s) via the PP manuals +
Phase 1 discovery, extract, reconcile against the manual credit-notes export.

**Phase 4 — Schedule + deliver**
Schedule the extraction on the BI server (Task Scheduler, per README pattern) writing
into the shared folder. Wire report generation + delivery (email vs folder — agree
with Larry). The manual morning export is now retired.

## Key data rules (from the guide — full detail in Part 2 there)

- Net revenue = Subtotal (excl VAT, incl fuel surcharge) − credit notes
  (types "Credit Note" + "Journal Credit" only; exclude Bad Debt and Cancelled).
- Financial year = March–February; exports run from 1 March.
- Invoice-date basis for dashboard/billing detail; waybill-date basis for flash.
- Exclude tilde waybills (`WAYBILL LIKE '%~%'`) — re-delivery duplicates. The existing
  queries in `data_extractor.py` already do this.
- Read columns by header name, never by position — export layouts drift.
