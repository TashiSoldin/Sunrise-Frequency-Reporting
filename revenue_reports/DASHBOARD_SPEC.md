# Revenue Dashboard — reverse-engineered build spec

Everything needed to write `build_dashboard.py` without re-inspecting the reference.
Source of truth: `Revenue Dashboard.xlsx` (ref of 28 Jul 2026, MTD to 24 Jul), verified
cell-by-cell against the raw exports. See also the replication guide (Part 2).

## Verified data derivations (reconciled to the rand)

- **Gross (month, invoice basis)** = sum of `Subtotal` over INV-export rows with
  `Invoice Date` in month. Mar 15,332,028 · Apr 14,414,703 · May 16,431,463 ·
  Jun 15,899,983 · Jul MTD(1–24) 13,415,026 (drift ±0.03% vs live export).
- **kg** = sum `Chrg Mass` same window (Mar 3,772,490 etc.).
- **Credits (month)** = credits `.xls`: `Type ∈ {Credit Note, Journal Credit}`,
  serial `Date` in month, sum `Subtotal`. Mar 356,697 · Apr 359,481 · May 279,237 ·
  Jun 389,976 · Jul-to-24th 521,757.
- **Net per account** (month/MTD tabs "Actual") = account gross − account credits, same window.
- **PY (LY)** figures from PY exports (`* March25 - Feb26.` 24-col layout) + credits file
  (covers Mar24→). **Dedicated folding**: strip `DED`/`CDE`/`DE` suffix from PY account
  codes so LY lands on the parent client (footnote: "last-year dedicated-load revenue is
  merged into each client's LY where still billed").
- **Budget** from `FY26-27_Budget_v30_Sunrise.xlsx` tab `Client Monthly Compare`:
  header row idx 4; cols: 0 Rep-group code, 1 Sales Rep, 2 Branch, 3 Acct, 4 Customer,
  then pairs (`{Mon}-25 R` PY-actual, `{Mon}-26 T` target) Mar..Feb, 29 Total R, 30 Total T.
  Group header rows have col0 set, col3 empty: CN(5), TF(49), LS(106), NP(131), PM(169),
  HS(292), NEW(299), CLOSED(303), DEDI(311). Rows inside rep groups may carry
  `CLOSED` in col0 → treat as closed. NEW group contains acct `NEW` (pipeline, has target).
- Jul FY26 full-month net (YTD tab E29) = 12,737,385.

## Trading-day calendars (fixed inputs per run)

Mar 22 · Apr 21(est) · May 21(est) · Jun 22 · Jul-2026 23 total, 18 elapsed to 24 Jul.
YTD Mar–Jun = 87. Maintained as run parameters, weekdays Mon–Fri (SA public holidays
excluded — Larry edits these; "assumptions (editable)").

## Tab 1 — "YTD Revenue vs PY" (B2:P35)

Widths A2,B22,C–I13,J9,K12,L12,M9,N10,O10,P9. Title block rows 2–5 (brand/title/
subtitle/accent as in style.py, span B:P). B7 grey note 8pt "Net revenue, YTD Mar–Jun
completed months".
KPI band rows 8–10 (labels r8, values r9 merged r9:r10):
B8:C8 "NET REVENUE FY27" navy → B9:C10 `=E18` #,##0 16B;
D "NET REVENUE FY26 (PY)" navy `=H18`; F "VARIANCE (R)" orange `=I18` `#,##0;(#,##0)`;
H "YoY GROWTH" yellow `=J18` 0.0%; K:M "NET R/kg FY27" navy `=E18/K18` 0.00;
N:P "NET R/kg FY26 (Δ% in table)" navy2 `=H18/L18`.
Table header rows 12–13: B12:B13 "Month"; C12:E12 "FY27"; F12:H12 "FY26 (PY)" (navy2,
yellow text); I12:J12 "Variance (Net)" orange; K12:P12 "Chargeable weight (kg) & rate
per kg". r13 sub-heads: Gross/Credit Notes/Net ×2, Var R, Var %, kg FY27, kg FY26,
kg Δ%, R/kg FY27, R/kg FY26, R/kg Δ%.
Month rows 14–17 (Mar..Jun, striped): C,D,F,G,K,L = blue inputs
(fmt: D,G `(#,##0)`); E`=C-D` H`=F-G` I`=E-H` J`=IF(H=0,"",I/H)` M`=IF(L=0,"",K/L-1)`
N`=IF(K=0,"",E/K)` O`=IF(L=0,"",H/L)` P`=IF(OR(K=0,L=0,H=0),"",(E/K)/(H/L)-1)`.
Row 18 "YTD (Mar–Jun)" orange bold: SUMs + same derived. Row 19 "Jul MTD (N trading
days) ¹" inputs like month rows (J19`=I19/H19` unguarded). Row 20 "YTD incl. Jul MTD"
yellow bold: r18+r19.
July momentum block rows 22–30: B22 navy section "JULY MOMENTUM (MTD, net)";
G22:J22 "CREDIT NOTES % OF GROSS". Pairs (striped, labels B:D merged, values E):
23 Trading days elapsed **18**(blue) / G23 "FY27 (YTD Mar–Jun)" J23`=D18/C18` 0.0%;
24 Trading days in July **23** / FY26 `=G18/F18`; 25 Net FY27 avg/trading day
`=E19/E23` / FY27 incl `=D20/C20`; 26 Net FY26 avg/day (same window) `=H19/E23` /
FY26 incl `=G20/F20`; 27 Daily growth vs PY `=E25/E26-1`; 28 Projected full July FY27
(net) `=E25*E24`; 29 FY26 full July net (actual) **12737385** blue; 30 Projected July
growth vs PY `=E28/E29-1`.
Footnotes 33–35 grey 8pt (B:J merged): ¹ FY27 July = N invoiced trading days (1–24 Jul
2026). FY26 July shown like-for-like (first N trading days); full FY26 July net =
12,737,385. / Net revenue = gross invoiced (Subtotal, excl. VAT) less credit notes…
/ Source: "INV Date" revenue files… Blue = source inputs; black = formulas.

## Tabs 2–5 "Mar/Apr/May/Jun FY27", tab 6 "YTD to Jun FY27", tab 7 "MTD Billing by Customer"

Shared build_tab layout (B2:S…; A2,B9,C34,D6,E–S per ref):
- Title: "Billing vs Target by Customer — {Mon} FY27 (full month)" / "…— YTD to June
  FY27 (Mar–Jun)" / "MTD Billing vs Target by Customer — July FY27". Subtitle: "Net
  billing (Subtotal less credit notes, invoice-date) · {window} · Targets from Budget
  v30 · LY = {window} FY26 net actual · ZAR".
- Row 7 yellow: "Trading days elapsed:" E7 (blue, editable) "Trading days in period:"
  H7; I7 note "← assumptions (editable)". Row 8 note 8pt.
- KPI band r9/r10: {Mon} TARGET `=F<selling-book subtotal row>`; EXPECTED `=G<sb>`;
  ACTUAL(orange) `=H<sb>`; % OF EXPECTED(yellow) `=I<sb>`; PROJECTED (all accts)
  `=J<total row>`; PROJ vs TARGET(orange) `=L<total row>`.
- "REP / SEGMENT SUMMARY" (r13) + header r14: Rep/segment, LY {win}, {win} Target,
  Expected, Actual, % Exp, Projected, Proj v Tgt, v Tgt %, v LY %, then (month & YTD
  tabs only) Chg kg, LY kg, kg Δ%, R/kg, LY R/kg, R/kg Δ%. Rows 15–21: TF, CN, LS,
  NP, PM, NEW, AH (each `=<their subtotal row>`); 22 yellow "Rep-allocated selling
  book" `=<sb row>`; 23 "House accounts (zeroed)"; 24 "Closed / lost accounts";
  25 orange "TOTAL — ALL ACCOUNTS".
- Detail: header r28, then per-rep sections: navy2 header "TF — Tracy Flandorp   (59
  customers)", customer rows (striped): B acct, C name, D branch (budget col2),
  E LY (net PY, dedicated folded), F target (budget), G `=F*$E$7/$H$7`,
  H actual (net, blue input), I `=IF(G=0,"",H/G)`, J `=H/$E$7*$H$7` (completed months
  E7=H7 so J=H; memo rows use `=H`), K `=IF(F=0,"",J-F)`, L `=IF(F=0,"",J/F-1)`,
  M `=IF(E=0,"",J/E-1)`, N kg (blue), O LY kg, P `=IF(O=0,"",(N/$E$7*$H$7)/O-1)`,
  Q `=IF(N=0,"",H/N)`, R `=IF(O=0,"",E/O)`, S guarded R/kg Δ%.
  Order within rep: budgeted accts by target desc, then zero-target accts by actual
  desc. Rep sections in order TF, CN, LS, NP, PM, NEW, AH; "{code} subtotal" orange
  bold SUM rows. Then "SUBTOTAL — Rep-allocated selling book" (sum of rep subtotals),
  "House accounts (zeroed) (…) — no sales target…" section + subtotal, "Closed / lost
  accounts (…)" + subtotal (J memo `=H363` style: memo buckets J=H frozen, footnote),
  "TOTAL — ALL ACCOUNTS" navy 12B = selling book + house + closed.
- Footnotes (~r366+): Expected/Projected formulas; non-budget under invoice salesrep;
  dedicated folding; kg notes; Sources … Budget v30.
- Rep display names: TF Tracy Flandorp, CN Christine Naidoo, LS Larry Serman,
  NP Nishalan Pillay, PM Pearl Matabola, NEW — Adrian van Niekerk (New Business),
  AH — Arlene Harper (no budget). NEW absorbs salesrep AN actuals.
- Account classification comes from the budget sheet groups (incl. inline `CLOSED`
  col0 markers); accounts billing in-window but absent from budget → zero-target row
  under their invoice salesrep. DEDI group accounts fold into parents.

## Tab 8/9 — "Daily — Invoice date" / "Daily — Waybill date" (B2:J~290)

Title "Daily Revenue by Customer — {Invoice|Waybill} date {DD Mon YYYY}"; subtitle
"Customers billed on … vs pro-rata daily target · net (excl VAT, less credit notes) ·
ZAR". Row 7 yellow: "Trading days in month:" E7=23; F7 note "Day target = monthly
budget target ÷ trading days…". KPI r9/r10: DAY NET `=E<total>`, DAY TARGET (full
book) `=F<total>`, % OF DAY TARGET `=H<total>`, CHG KG `=I<total>`, R/kg guarded.
Header r14: Acct, Customer, Br, Day Net, Day Tgt, Var v Day Tgt, % Day Tgt, Chg kg,
R/kg. Rep sections "TF — …   (29 billed, 23 target-holders)"-style headers; customer
rows sorted Day Net desc; F literal `={monthly_target}/$E$7`; G/H/J guarded. Day =
MTD_MAX for invoice tab; latest waybill day (27 Jul) for waybill tab. Net at day level
= subtotal − credits dated that day per account.

## Tab 10 — "MTD Credit Notes" (B2:J176)

Title "MTD Credit Notes Processed — July FY27". KPI r7/r8: TOTAL CREDITS 524,057.52 ·
# CREDIT NOTES 131 · LARGEST NOTE 215,584.91 · "TOP REASON: CNIE - Inc Rates"
243,922.21. Section "CREDIT NOTES BY REASON" r11; header r12 Reason/Value/# Notes/
% of Total (`=G13/$G$37` refs total row); reason rows value desc. Then detail listing
(remaining ~130 rows) — CN #, account, customer, rep, reason, value etc. Window =
month-to-date (1 Jul → today's file, NOT capped at MTD_MAX: 524,058 = full Jul credits
in the 28-Jul file vs 521,757 through 24th on the YTD tab).

## Styling

Palette/formats as `style.py`. Blue `#0000FF` font = source inputs; black = formulas.
Stripes `#F0F0F8`/white; orange subtotal rows; yellow emphasis rows; navy section
headers; navy2 rep headers; grey `#595959` 8pt footnotes. Gridlines hidden.
All divisions guarded `IF(x=0,"",…)` so the workbook opens error-free.
Write values for inputs + real Excel formulas for derived cells (recalc on open).

## Open items

- Trading-day calendar: confirm Apr/May counts against Larry (est. from 87 YTD).
- "Typical weekday" flash benchmark definition (flagged in build_flash.py).
- MTD Credit Notes includes Bad Debt in reason table? (CNB - Bad Debt row present
  in by-reason listing — the *revenue* credit deduction excludes it, but the MTD
  credit-notes tab appears to list it; verify against credits file when building.)
