"""Build the Revenue Dashboard workbook — 10 tabs, per DASHBOARD_SPEC.md.

Replicates Larry's "Revenue Dashboard.xlsx" (reference of 28 Jul 2026).

Usage:
    python build_dashboard.py \
        --inv-file ".../INV Date - March26 - Feb27..xlsx" \
        --py-inv-file ".../INV Date - March25 - Feb26..xlsx" \
        --wb-file ".../WB Date - March26 - Feb27..xlsx" \
        --credits-file ".../Credits - March24 - Feb27.xls" \
        --budget-file ".../FY26-27_Budget_v30_Sunrise.xlsx" \
        --out-dir out

Data rules (PLAN.md / replication guide / DASHBOARD_SPEC.md):
  * Net = Subtotal (ex VAT) − credit notes (Type ∈ {Credit Note, Journal Credit}).
  * Invoice-date basis; tilde waybills excluded; columns read by header name.
  * Dedicated accounts (budget DEDI group / DED-CDE-DE suffixes) fold into parents.
  * Trading-day calendar is a fixed run parameter (Larry-editable assumption).
"""

import argparse
import calendar
from collections import defaultdict
from datetime import date, datetime

import xlrd
import xlsxwriter
from python_calamine import CalamineWorkbook

from data import col, excel_serial_to_date, load_export
from style import ALT, BLUE, NAVY, NAVY2, ORANGE, YELLOW, NUM, DEC2, PCT1, Styles, title_block

CREDIT_TYPES = ("Credit Note", "Journal Credit")
REP_ORDER = ["TF", "CN", "LS", "NP", "PM", "NEW", "AH"]
REP_DISPLAY = {
    "TF": "TF — Tracy Flandorp",
    "CN": "CN — Christine Naidoo",
    "LS": "LS — Larry Serman",
    "NP": "NP — Nishalan Pillay",
    "PM": "PM — Pearl Matabola",
    "NEW": "NEW — Adrian van Niekerk (New Business)",
    "AH": "AH — Arlene Harper (no budget)",
}
SUFFIXES = ("DED", "CDE", "DE")
MONTHS_FY = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2]  # Mar..Feb
# Trading-day calendar (fixed inputs per run — Larry-editable assumptions)
TRADING_DAYS = {3: 22, 4: 22, 5: 21, 6: 22, 7: 23}
FY = 2026  # FY27 starts Mar 2026


def acct_str(v):
    if isinstance(v, float) and v == int(v):
        return "000" if v == 0 else str(int(v))
    return str(v).strip()


def month_win(y, m):
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def trading_days_between(a: date, b: date) -> int:
    """Weekdays Mon–Fri in [a, b] (SA public holidays handled via the fixed calendar)."""
    n, d = 0, a
    from datetime import timedelta
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def nth_trading_day(y, m, n) -> date:
    from datetime import timedelta
    d = date(y, m, 1)
    k = 0
    while True:
        if d.weekday() < 5:
            k += 1
            if k == n:
                return d
        d += timedelta(days=1)


# ---------------------------------------------------------------- budget

class Budget:
    def __init__(self, path):
        rows = CalamineWorkbook.from_path(path).get_sheet_by_name(
            "Client Monthly Compare").to_python(skip_empty_area=False)
        hdr = [str(h).strip() for h in rows[4]]
        assert hdr[3] == "Acct" and hdr[5].startswith("Mar"), f"Budget layout changed: {hdr[:8]}"
        self.info = {}          # acct -> dict(group, branch, name, targets{month:val}, row)
        self.order = []         # budget row order of accts
        group = None
        for i, r in enumerate(rows[5:], start=5):
            c0, c3 = str(r[0]).strip(), acct_str(r[3]) if r[3] not in ("", None) else ""
            if c0 and not c3:
                group = c0.split("—")[0].strip()
                continue
            if not c3 or group is None:
                continue
            g = "CLOSED" if c0 == "CLOSED" and group != "CLOSED" else group
            targets = {}
            for k, m in enumerate(MONTHS_FY):
                v = r[6 + 2 * k]
                targets[m] = float(v) if isinstance(v, (int, float)) else 0.0
            self.info[c3] = dict(group=g, branch=str(r[2]).strip(),
                                 name=str(r[4]).strip(), targets=targets, row=i)
            self.order.append(c3)
        self.dedi = {a for a, d in self.info.items() if d["group"] == "DEDI"}
        self.nondedi = {a for a in self.info if a not in self.dedi}

    def rank(self, a):
        d = self.info.get(a)
        return d["row"] if d else 10 ** 9


def strip_suffix(a: str) -> str:
    for suf in SUFFIXES:
        if a.endswith(suf) and len(a) > len(suf) + 1:
            return a[: -len(suf)]
    return a


# ---------------------------------------------------------------- data pools

class Pool:
    """Per-account per-day aggregation of an export (folded account codes)."""

    def __init__(self):
        self.day = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # acct->day->[sub, kg]
        self.day_first = defaultdict(dict)  # acct -> day -> first file row index
        self.first_seen = {}
        self.names = {}
        self.salesrep = {}
        self._n = 0

    def add(self, acct, d, sub, kg, name=None, rep=None):
        cell = self.day[acct][d]
        cell[0] += sub
        cell[1] += kg
        self._n += 1
        if acct not in self.first_seen:
            self.first_seen[acct] = self._n
        if d not in self.day_first[acct]:
            self.day_first[acct][d] = self._n
        if name and acct not in self.names:
            self.names[acct] = name
        if rep and acct not in self.salesrep:
            self.salesrep[acct] = rep

    def win(self, acct, a, b):
        s = k = 0.0
        for d, (sub, kg) in self.day.get(acct, {}).items():
            if a <= d <= b:
                s += sub
                k += kg
        return s, k

    def total(self, a, b):
        s = k = 0.0
        for acct in self.day:
            ws, wk = self.win(acct, a, b)
            s += ws
            k += wk
        return s, k

    def first_seen_in_win(self, a, b):
        """acct -> (earliest day, file-row rank) of the account's rows inside [a, b]."""
        out = {}
        for acct, days in self.day_first.items():
            ds = [(d, i) for d, i in days.items() if a <= d <= b]
            if ds:
                out[acct] = min(ds)
        return out


def load_pools(inv_file, py_inv_file, wb_file, budget: Budget):
    fy27_raw = set()
    # discover raw FY27 accounts first (for fold rule)
    h, rows = load_export(inv_file)
    iA, iWB = col(h, "Account"), col(h, "Waybill")
    for r in rows:
        if "~" not in str(r[iWB]):
            fy27_raw.add(acct_str(r[iA]))

    def fold(a):
        # Only budget DEDI-group accounts fold into their parent client. Dedicated
        # accounts budgeted in their own right (e.g. J33DED) stay separate.
        return strip_suffix(a) if a in budget.dedi else a

    def norm_date(v):
        if isinstance(v, datetime):
            return v.date()
        return v if isinstance(v, date) else None

    inv = Pool()
    ix = {n: col(h, n) for n in ["Account", "Waybill", "Subtotal", "Chrg Mass",
                                 "Invoice Date", "Customer", "Salesrep"]}
    for r in rows:
        if "~" in str(r[ix["Waybill"]]):
            continue
        d = norm_date(r[ix["Invoice Date"]])
        if d is None:
            continue
        inv.add(fold(acct_str(r[ix["Account"]])), d, r[ix["Subtotal"]] or 0,
                r[ix["Chrg Mass"]] or 0, str(r[ix["Customer"]]).strip(),
                str(r[ix["Salesrep"]]).strip())

    py = Pool()
    h2, rows2 = load_export(py_inv_file)
    ix2 = {n: col(h2, n) for n in ["Account", "Waybill", "Subtotal", "Chrg Mass",
                                   "Invoice Date", "Customer"]}
    for r in rows2:
        if "~" in str(r[ix2["Waybill"]]):
            continue
        d = norm_date(r[ix2["Invoice Date"]])
        if d is None:
            continue
        py.add(fold(acct_str(r[ix2["Account"]])), d, r[ix2["Subtotal"]] or 0,
               r[ix2["Chrg Mass"]] or 0)

    wbp = Pool()
    h3, rows3 = load_export(wb_file)
    ix3 = {n: col(h3, n) for n in ["Account", "Waybill", "Subtotal", "Chrg Mass",
                                   "Waybill Date", "Customer", "Salesrep"]}
    for r in rows3:
        if "~" in str(r[ix3["Waybill"]]):
            continue
        d = norm_date(r[ix3["Waybill Date"]])
        if d is None:
            continue
        wbp.add(fold(acct_str(r[ix3["Account"]])), d, r[ix3["Subtotal"]] or 0,
                r[ix3["Chrg Mass"]] or 0, str(r[ix3["Customer"]]).strip(),
                str(r[ix3["Salesrep"]]).strip())

    return inv, py, wbp, fold


class Credits:
    def __init__(self, path, fold):
        book = xlrd.open_workbook(path)
        sh = book.sheet_by_index(0)
        hdr = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
        ic = {n: hdr.index(n) for n in
              ["Receipt", "Account", "Customer Name", "Date", "Subtotal", "Reference",
               "Type", "Rep", "Reason", "Branch", "Credit Controller"]}
        self.day = defaultdict(lambda: defaultdict(float))  # acct -> day -> value
        self.rows = []  # (date, acct, dicts) for the credit-notes tab
        for i in range(1, sh.nrows):
            if str(sh.cell_value(i, ic["Type"])) not in CREDIT_TYPES:
                continue
            try:
                d = excel_serial_to_date(sh.cell_value(i, ic["Date"]))
            except (TypeError, ValueError):
                continue
            a = fold(acct_str(sh.cell_value(i, ic["Account"])))
            v = sh.cell_value(i, ic["Subtotal"]) or 0
            self.day[a][d] += v
            self.rows.append(dict(
                date=d, acct=a, value=v,
                ref=str(sh.cell_value(i, ic["Reference"])).strip(),
                reason=str(sh.cell_value(i, ic["Reason"])).strip(),
                rep=str(sh.cell_value(i, ic["Rep"])).strip(),
                branch=str(sh.cell_value(i, ic["Branch"])).strip(),
                controller=str(sh.cell_value(i, ic["Credit Controller"])).strip(),
                customer=str(sh.cell_value(i, ic["Customer Name"])).strip(),
                receipt=sh.cell_value(i, ic["Receipt"]),
            ))

    def win(self, acct, a, b):
        return sum(v for d, v in self.day.get(acct, {}).items() if a <= d <= b)

    def total(self, a, b):
        return sum(self.win(acct, a, b) for acct in self.day)


# ---------------------------------------------------------------- model

class Model:
    def __init__(self, inv: Pool, py: Pool, wbp: Pool, credits: Credits, budget: Budget):
        self.inv, self.py, self.wbp, self.credits, self.budget = inv, py, wbp, credits, budget
        # classification
        self.cls = {}
        universe = set(budget.nondedi) | set(inv.day) | set(py.day) | set(credits.day)
        for a in universe:
            self.cls[a] = self._classify(a)

    def _classify(self, a):
        d = self.budget.info.get(a)
        if d:
            g = d["group"]
            if g in ("TF", "CN", "LS", "NP", "PM", "NEW"):
                return g
            if g == "HS":
                return "HOUSE"
            if g == "CLOSED":
                return "CLOSED"
        sr = self.inv.salesrep.get(a)
        if sr in ("TF", "CN", "LS", "NP", "PM"):
            return sr
        if sr == "AN":
            return "NEW"
        if sr == "AH":
            return "AH"
        if sr == "HS":
            return "HOUSE"
        return "CLOSED"  # CA, blank, or LY-only accounts

    def name(self, a):
        d = self.budget.info.get(a)
        if d and d["name"]:
            return d["name"]
        return self.inv.names.get(a) or self.wbp.names.get(a) or a

    def branch(self, a):
        d = self.budget.info.get(a)
        return d["branch"] if d else ""

    def target(self, a, months):
        d = self.budget.info.get(a)
        return sum(d["targets"].get(m, 0) for m in months) if d else 0.0

    def net27(self, a, w):
        s, _ = self.inv.win(a, *w)
        return s - self.credits.win(a, *w)

    def kg27(self, a, w):
        return self.inv.win(a, *w)[1]

    def netly(self, a, w):
        s, _ = self.py.win(a, *w)
        return s - self.credits.win(a, *w)

    def kgly(self, a, w):
        return self.py.win(a, *w)[1]


# ---------------------------------------------------------------- formats

def F(st, **kw):
    return st.get(**kw)


def detail_formats(st):
    def make(bg):
        base = dict(font_size=9, bg_color=bg)
        return dict(
            txt=F(st, **base),
            blue_num=F(st, font_color=BLUE, num_format=NUM, **base),
            num=F(st, num_format=NUM, **base),
            pct=F(st, num_format=PCT1, **base),
            dec=F(st, num_format=DEC2, **base),
        )
    return {0: make("white"), 1: make(ALT)}


# ---------------------------------------------------------------- tab 1

def build_tab1(wb, st, M: Model, p):
    ws = wb.add_worksheet("YTD Revenue vs PY")
    ws.hide_gridlines(2)
    widths = [2, 22] + [13] * 7 + [9, 12, 12, 9, 10, 10, 9]
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)

    mtd = p["mtd_max"]
    elapsed, injul = p["jul_elapsed"], TRADING_DAYS[7]
    title_block(ws, st, "P", "SUNRISE LOGISTICS",
                "YTD Revenue Analysis  —  FY27 vs FY26 (Prior Year)",
                f"Net revenue after credit notes · Invoice-date basis · ZAR · Financial year Mar–Feb · "
                f"Data through {mtd.day} {mtd.strftime('%b %Y')} ({elapsed} trading days)")
    note8 = F(st, font_size=8, font_color="#595959")
    ws.merge_range("B7:P7", "Net revenue, YTD Mar–Jun completed months", note8)

    # KPI band
    kl_navy = F(st, bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kl_navy2 = F(st, bold=True, font_size=8, font_color="white", bg_color=NAVY2)
    kl_or = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)
    kl_ye = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=YELLOW)

    def kv(bg, fc, fmt):
        return F(st, bold=True, font_size=16, font_color=fc, bg_color=bg,
                 num_format=fmt, align="left", valign="vcenter")

    ws.merge_range("B8:C8", "NET REVENUE  FY27", kl_navy)
    ws.merge_range("D8:E8", "NET REVENUE  FY26 (PY)", kl_navy)
    ws.merge_range("F8:G8", "VARIANCE  (R)", kl_or)
    ws.merge_range("H8:J8", "YoY GROWTH", kl_ye)
    ws.merge_range("K8:M8", "NET R/kg  FY27", kl_navy)
    ws.merge_range("N8:P8", "NET R/kg  FY26  (Δ% in table)", kl_navy2)
    ws.merge_range("B9:C10", "=E18", kv(NAVY, "white", NUM))
    ws.merge_range("D9:E10", "=H18", kv(NAVY, "white", NUM))
    ws.merge_range("F9:G10", "=I18", kv(ORANGE, NAVY, "#,##0;(#,##0)"))
    ws.merge_range("H9:J10", "=J18", kv(YELLOW, NAVY, "0.0%"))
    ws.merge_range("K9:M10", "=E18/K18", kv(NAVY, "white", DEC2))
    ws.merge_range("N9:P10", "=H18/L18", kv(NAVY2, "white", DEC2))

    # table header
    th = F(st, bold=True, font_size=9, font_color="white", bg_color=NAVY, align="center")
    th2 = F(st, bold=True, font_size=9, font_color=YELLOW, bg_color=NAVY2, align="center")
    tho = F(st, bold=True, font_size=9, font_color="white", bg_color=ORANGE, align="center")
    ws.merge_range("B12:B13", "Month", th)
    ws.merge_range("C12:E12", "FY27", th)
    ws.merge_range("F12:H12", "FY26 (PY)", th2)
    ws.merge_range("I12:J12", "Variance (Net)", tho)
    ws.merge_range("K12:P12", "Chargeable weight (kg) & rate per kg", th)
    subs = ["Gross", "Credit Notes", "Net", "Gross", "Credit Notes", "Net", "Var R",
            "Var %", "kg FY27", "kg FY26", "kg Δ%", "R/kg FY27", "R/kg FY26", "R/kg Δ%"]
    for i, s in enumerate(subs):
        ws.write(12, 2 + i, s, F(st, bold=True, font_size=9, font_color="white", bg_color=NAVY2, align="center"))

    months = [(3, "Mar"), (4, "Apr"), (5, "May"), (6, "Jun")]

    def rowvals(w27, wpy):
        g, kg = M.inv.total(*w27)
        c = M.credits.total(*w27)
        gp, kgp = M.py.total(*wpy)
        cp = M.credits.total(*wpy)
        return round(g), round(c), round(gp), round(cp), round(kg), round(kgp)

    def write_month_row(r, label, vals, label_fmt, blue_bg, bold=False):
        g, c, gp, cp, kg, kgp = vals
        bg = blue_bg
        base = dict(font_size=10, bg_color=bg, bold=bold)
        blue = dict(font_size=10, font_color=BLUE, bg_color=bg, bold=bold)
        ws.write(r - 1, 1, label, label_fmt)
        ws.write(r - 1, 2, g, F(st, num_format=NUM, **blue))
        ws.write(r - 1, 3, c, F(st, num_format="(#,##0)", **blue))
        ws.write_formula(r - 1, 4, f"=C{r}-D{r}", F(st, num_format=NUM, **base))
        ws.write(r - 1, 5, gp, F(st, num_format=NUM, **blue))
        ws.write(r - 1, 6, cp, F(st, num_format="(#,##0)", **blue))
        ws.write_formula(r - 1, 7, f"=F{r}-G{r}", F(st, num_format=NUM, **base))
        ws.write_formula(r - 1, 8, f"=E{r}-H{r}", F(st, num_format="#,##0;(#,##0)", **base))
        guard_j = f'=IF(H{r}=0,"",I{r}/H{r})' if label not in ("Jul MTD", "_sum") else f"=I{r}/H{r}"
        ws.write_formula(r - 1, 9, guard_j, F(st, num_format=PCT1, **base))
        ws.write(r - 1, 10, kg, F(st, num_format=NUM, **blue))
        ws.write(r - 1, 11, kgp, F(st, num_format=NUM, **blue))
        ws.write_formula(r - 1, 12, f'=IF(L{r}=0,"",K{r}/L{r}-1)', F(st, num_format=PCT1, **base))
        ws.write_formula(r - 1, 13, f'=IF(K{r}=0,"",E{r}/K{r})', F(st, num_format=DEC2, **base))
        ws.write_formula(r - 1, 14, f'=IF(L{r}=0,"",H{r}/L{r})', F(st, num_format=DEC2, **base))
        ws.write_formula(r - 1, 15,
                         f'=IF(OR(K{r}=0,L{r}=0,H{r}=0),"",(E{r}/K{r})/(H{r}/L{r})-1)',
                         F(st, num_format=PCT1, **base))

    for j, (m, lab) in enumerate(months):
        r = 14 + j
        bg = ALT if j % 2 == 0 else "white"
        write_month_row(r, lab, rowvals(month_win(FY, m), month_win(FY - 1, m)),
                        F(st, font_size=10, bg_color=bg), bg)

    # YTD row 18
    r = 18
    ob = dict(font_size=10, bold=True, bg_color=ORANGE)
    ws.write(r - 1, 1, "YTD  (Mar–Jun)", F(st, **ob))
    for cl, letter in [(2, "C"), (3, "D"), (5, "F"), (6, "G"), (10, "K"), (11, "L")]:
        ws.write_formula(r - 1, cl, f"=SUM({letter}14:{letter}17)",
                         F(st, num_format=NUM if letter not in "DG" else "(#,##0)", **ob))
    ws.write_formula(r - 1, 4, "=C18-D18", F(st, num_format=NUM, **ob))
    ws.write_formula(r - 1, 7, "=F18-G18", F(st, num_format=NUM, **ob))
    ws.write_formula(r - 1, 8, "=E18-H18", F(st, num_format="#,##0;(#,##0)", **ob))
    ws.write_formula(r - 1, 9, "=I18/H18", F(st, num_format=PCT1, **ob))
    ws.write_formula(r - 1, 12, '=IF(L18=0,"",K18/L18-1)', F(st, num_format=PCT1, **ob))
    ws.write_formula(r - 1, 13, '=IF(K18=0,"",E18/K18)', F(st, num_format=DEC2, **ob))
    ws.write_formula(r - 1, 14, '=IF(L18=0,"",H18/L18)', F(st, num_format=DEC2, **ob))
    ws.write_formula(r - 1, 15, '=IF(OR(K18=0,L18=0,H18=0),"",(E18/K18)/(H18/L18)-1)',
                     F(st, num_format=PCT1, **ob))

    # Jul MTD row 19
    w27 = (date(FY, 7, 1), mtd)
    wpy = (date(FY - 1, 7, 1), p["ly_mtd_max"])
    g, c, gp, cp, kg, kgp = rowvals(w27, wpy)
    r = 19
    base = dict(font_size=10, bg_color="white")
    blue = dict(font_size=10, font_color=BLUE, bg_color="white")
    ws.write(r - 1, 1, f"Jul MTD ({elapsed} trading days) ¹", F(st, **base))
    ws.write(r - 1, 2, g, F(st, num_format=NUM, **blue))
    ws.write(r - 1, 3, c, F(st, num_format="(#,##0)", **blue))
    ws.write_formula(r - 1, 4, "=C19-D19", F(st, num_format=NUM, **base))
    ws.write(r - 1, 5, gp, F(st, num_format=NUM, **blue))
    ws.write(r - 1, 6, cp, F(st, num_format="(#,##0)", **blue))
    ws.write_formula(r - 1, 7, "=F19-G19", F(st, num_format=NUM, **base))
    ws.write_formula(r - 1, 8, "=E19-H19", F(st, num_format="#,##0;(#,##0)", **base))
    ws.write_formula(r - 1, 9, "=I19/H19", F(st, num_format=PCT1, **base))
    ws.write(r - 1, 10, kg, F(st, num_format=NUM, **blue))
    ws.write(r - 1, 11, kgp, F(st, num_format=NUM, **blue))
    ws.write_formula(r - 1, 12, '=IF(L19=0,"",K19/L19-1)', F(st, num_format=PCT1, **base))
    ws.write_formula(r - 1, 13, '=IF(K19=0,"",E19/K19)', F(st, num_format=DEC2, **base))
    ws.write_formula(r - 1, 14, '=IF(L19=0,"",H19/L19)', F(st, num_format=DEC2, **base))
    ws.write_formula(r - 1, 15, '=IF(OR(K19=0,L19=0,H19=0),"",(E19/K19)/(H19/L19)-1)',
                     F(st, num_format=PCT1, **base))

    # YTD incl Jul MTD row 20
    r = 20
    yb = dict(font_size=10, bold=True, bg_color=YELLOW)
    ws.write(r - 1, 1, "YTD incl. Jul MTD", F(st, **yb))
    for cl, letter in [(2, "C"), (3, "D"), (5, "F"), (6, "G"), (10, "K"), (11, "L")]:
        ws.write_formula(r - 1, cl, f"={letter}18+{letter}19",
                         F(st, num_format=NUM if letter not in "DG" else "(#,##0)", **yb))
    ws.write_formula(r - 1, 4, "=C20-D20", F(st, num_format=NUM, **yb))
    ws.write_formula(r - 1, 7, "=F20-G20", F(st, num_format=NUM, **yb))
    ws.write_formula(r - 1, 8, "=E20-H20", F(st, num_format="#,##0;(#,##0)", **yb))
    ws.write_formula(r - 1, 9, "=I20/H20", F(st, num_format=PCT1, **yb))
    ws.write_formula(r - 1, 12, '=IF(L20=0,"",K20/L20-1)', F(st, num_format=PCT1, **yb))
    ws.write_formula(r - 1, 13, '=IF(K20=0,"",E20/K20)', F(st, num_format=DEC2, **yb))
    ws.write_formula(r - 1, 14, '=IF(L20=0,"",H20/L20)', F(st, num_format=DEC2, **yb))
    ws.write_formula(r - 1, 15, '=IF(OR(K20=0,L20=0,H20=0),"",(E20/K20)/(H20/L20)-1)',
                     F(st, num_format=PCT1, **yb))

    # July momentum block
    sect = F(st, bold=True, font_size=11, font_color="white", bg_color=NAVY)
    ws.merge_range("B22:E22", "JULY MOMENTUM (MTD, net)", sect)
    ws.merge_range("G22:J22", "CREDIT NOTES % OF GROSS", sect)
    jul_full_py = round(M.py.total(*month_win(FY - 1, 7))[0]
                        - M.credits.total(*month_win(FY - 1, 7)))
    pairs = [
        ("Trading days elapsed", elapsed, True, NUM),
        ("Trading days in July", injul, True, NUM),
        ("Net FY27 avg / trading day", "=E19/E23", False, NUM),
        ("Net FY26 avg / day (same window)", "=H19/E23", False, NUM),
        ("Daily growth vs PY", "=E25/E26-1", False, PCT1),
        ("Projected full July FY27 (net)", "=E25*E24", False, NUM),
        ("FY26 full July net (actual)", jul_full_py, True, NUM),
        ("Projected July growth vs PY", "=E28/E29-1", False, PCT1),
    ]
    right = [
        ("FY27 (YTD Mar–Jun)", "=D18/C18"),
        ("FY26 (YTD Mar–Jun)", "=G18/F18"),
        ("FY27 (incl. Jul MTD)", "=D20/C20"),
        ("FY26 (incl. Jul MTD)", "=G20/F20"),
    ]
    for j, (lab, v, is_input, fmt) in enumerate(pairs):
        r = 23 + j
        bg = ALT if j % 2 == 0 else "white"
        ws.merge_range(r - 1, 1, r - 1, 3, lab, F(st, font_size=10, bg_color=bg))
        vf = F(st, font_size=10, bg_color=bg, num_format=fmt,
               font_color=BLUE if is_input else "black")
        if is_input:
            ws.write(r - 1, 4, v, vf)
        else:
            ws.write_formula(r - 1, 4, v, vf)
    for j, (lab, f_) in enumerate(right):
        r = 23 + j
        bg = ALT if j % 2 == 0 else "white"
        ws.merge_range(r - 1, 6, r - 1, 8, lab, F(st, font_size=10, bg_color=bg))
        ws.write_formula(r - 1, 9, f_, F(st, font_size=10, bg_color=bg, num_format=PCT1))

    fn = [
        f"¹ FY27 July = {elapsed} invoiced trading days (1–{mtd.day} {mtd.strftime('%b %Y')}). "
        f"FY26 July shown like-for-like (first {elapsed} trading days) for valid comparison; "
        f"full FY26 July net = {jul_full_py:,}.",
        "Net revenue = gross invoiced (Subtotal, excl. VAT) less credit notes raised in the period. "
        "Bad debt write-offs (excluded here) are treated separately as a cost.",
        "Source: “INV Date” revenue files (invoice-date basis) and “Credits” file, Revenue Data folder. "
        "Blue = source inputs; black = formulas.",
    ]
    for j, t in enumerate(fn):
        ws.merge_range(32 + j, 1, 32 + j, 9, t, note8)


# ---------------------------------------------------------------- customer tabs

def customer_universe(M: Model, w27, wly, months, memo_mode="unified"):
    """Returns dict bucket -> ordered account list."""
    per_rep = defaultdict(list)
    active = {}
    seen = M.py.first_seen_in_win(*wly) if wly else {}
    inv_seen = M.inv.first_seen_in_win(*w27)
    for a, c in M.cls.items():
        tgt = M.target(a, months)
        h = M.net27(a, w27)
        n = M.kg27(a, w27)
        e = M.netly(a, wly) if wly else 0.0
        o = M.kgly(a, wly) if wly else 0.0
        active[a] = (tgt, h, n, e, o)
    for a, c in M.cls.items():
        tgt, h, n, e, o = active[a]
        if a in M.budget.nondedi:
            g = M.budget.info[a]["group"]
            bucket = {"HS": "HOUSE", "CLOSED": "CLOSED"}.get(g, g)
            per_rep[bucket].append(a)
        elif h:
            # net-active non-budget accounts: rows in window -> their salesrep bucket;
            # credit-only activity (no invoice rows) -> Closed. Accounts whose window
            # nets to exactly zero drop off (matches reference behaviour).
            per_rep[c if a in inv_seen else "CLOSED"].append(a)
        elif e:
            per_rep["CLOSED"].append(a)  # LY-only listing (LY net ≠ 0, incl. credit-only)

    def rep_sort(accts):
        """Budgeted accounts by target desc, then zero-target; ties by max(actual, LY) desc."""
        def size(a):
            return max(active[a][1], active[a][3])
        budgeted = [a for a in accts if active[a][0] > 0]
        zero = [a for a in accts if active[a][0] <= 0]
        budgeted.sort(key=lambda a: (-active[a][0], -size(a), M.budget.rank(a)))
        zero.sort(key=lambda a: (-size(a), M.budget.rank(a),
                                 M.inv.first_seen.get(a, 10 ** 9)))
        return budgeted + zero

    for c in ("TF", "CN", "LS", "NP", "PM", "NEW", "AH"):
        per_rep[c] = rep_sort(per_rep[c])

    # memo-bucket ordering (matches the reference builds):
    #  house — budget order, positive actuals pulled forward.
    #  closed, month/YTD tabs — same unified key as rep sections: max(actual, LY) desc.
    #  closed, MTD tab — invoiced-this-window accounts (FY27-export first-seen), then
    #  LY-only zero-actual accounts (PY-export first-seen), then the rest by actual desc.
    if memo_mode == "mtd":
        cur = [a for a in per_rep["CLOSED"] if active[a][1] > 0]
        cur.sort(key=lambda a: -active[a][1])
        ly = [a for a in per_rep["CLOSED"] if active[a][1] == 0 and a in seen]
        ly.sort(key=lambda a: (a in M.budget.nondedi,
                               M.budget.rank(a) if a in M.budget.nondedi else seen[a]))
        rest = [a for a in per_rep["CLOSED"] if a not in cur and a not in ly]
        rest.sort(key=lambda a: (-active[a][1], M.budget.rank(a)))
        per_rep["CLOSED"] = cur + ly + rest
    else:
        per_rep["CLOSED"].sort(
            key=lambda a: (-max(active[a][1], active[a][3]), M.budget.rank(a),
                           -active[a][3], active[a][1]))
    per_rep["HOUSE"].sort(key=lambda a: (-max(active[a][1], 0), M.budget.rank(a)))
    return per_rep, active


def build_customer_tab(wb, st, M: Model, sheet, title, subtitle, kpi_prefix, lyhdr,
                       elapsed, period, w27, wly, months, round_vals=False,
                       memo_mode="unified"):
    ws = wb.add_worksheet(sheet)
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 9, 34, 6, 13, 13, 12, 13, 9, 13, 13, 10, 9, 12, 12, 9, 8, 8, 9]):
        ws.set_column(i, i, w)
    title_block(ws, st, "S", "SUNRISE LOGISTICS", title, subtitle)

    per_rep, active = customer_universe(M, w27, wly, months, memo_mode)
    reps = [c for c in REP_ORDER if per_rep[c]]
    house, closed = per_rep["HOUSE"], per_rep["CLOSED"]

    # --- layout pass: assign rows (1-indexed)
    sections = []  # (code, header_row, first, last, subtotal_row)
    r = 29
    for c in reps:
        n = len(per_rep[c])
        sections.append((c, r, r + 1, r + n, r + n + 1))
        r = r + n + 2
    sb_row = r
    house_hdr = r + 2
    house_sub = house_hdr + len(house) + 1
    closed_hdr = house_sub + 1
    closed_sub = closed_hdr + len(closed) + 1
    total_row = closed_sub + 1

    # --- row 7/8: assumptions
    ye = dict(font_size=10, bg_color=YELLOW)
    ws.write("B7", "Trading days elapsed:", F(st, bold=True, **ye))
    ws.merge_range("C7:D7", "", F(st, **ye))
    ws.write("E7", elapsed, F(st, font_color=BLUE, bold=True, **ye))
    ws.write("F7", "Trading days in period:", F(st, bold=True, **ye))
    ws.write("G7", "", F(st, **ye))
    ws.write("H7", period, F(st, font_color=BLUE, bold=True, **ye))
    ws.write("I7", "← assumptions (editable)", F(st, font_size=8, font_color="#595959"))
    ws.write("B8", "KPIs cover the rep-allocated selling book. Non-budget accounts appear "
                   "under their rep with 0 target.", F(st, font_size=8, font_color="#595959"))

    # --- KPI band
    kl_navy = F(st, bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kl_or = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)
    kl_ye = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=YELLOW)

    def kv(bg, fc, fmt):
        return F(st, bold=True, font_size=14, font_color=fc, bg_color=bg,
                 num_format=fmt, align="left", valign="vcenter")

    kpis = [("B", "C", f"{kpi_prefix} TARGET", f"=F{sb_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("D", "E", "EXPECTED", f"=G{sb_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("F", "G", "ACTUAL", f"=H{sb_row}", kl_or, kv(ORANGE, NAVY, NUM)),
            ("H", "I", "% OF EXPECTED", f"=I{sb_row}", kl_ye, kv(YELLOW, NAVY, PCT1)),
            ("J", "K", "PROJECTED (all accts)", f"=J{total_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("L", "M", "PROJ vs TARGET", f"=L{total_row}", kl_or, kv(ORANGE, NAVY, PCT1))]
    for c1, c2, lab, f_, lf, vf in kpis:
        ws.merge_range(f"{c1}9:{c2}9", lab, lf)
        ws.merge_range(f"{c1}10:{c2}10", f_, vf)

    # --- summary block
    sect = F(st, bold=True, font_size=11, font_color="white", bg_color=NAVY)
    ws.merge_range("B13:S13", "REP / SEGMENT SUMMARY", sect)
    hdr = ["Rep / segment", "", "", f"LY {lyhdr}", f"{kpi_prefix} Target", "Expected", "Actual",
           "% Exp", "Projected", "Proj v Tgt", "v Tgt %", "v LY %", "Chg kg", "LY kg",
           "kg Δ%", "R/kg", "LY R/kg", "R/kg Δ%"]
    th = F(st, bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    ws.merge_range("B14:D14", hdr[0], th)
    for i, h in enumerate(hdr[3:]):
        ws.write(13, 4 + i, h, th)

    def summary_row(r, label, ref_row, fmt):
        ws.merge_range(r - 1, 1, r - 1, 3, label, fmt["txt"])
        for i, letter in enumerate("EFGHIJKLMNOPQRS"):
            f2 = fmt["pct"] if letter in "ILMPS" else (fmt["dec"] if letter in "QR" else fmt["num"])
            ws.write_formula(r - 1, 4 + i, f"={letter}{ref_row}", f2)

    def mk_fmt(bg, bold=False, fc="black", size=10):
        base = dict(font_size=size, bg_color=bg, bold=bold, font_color=fc)
        return dict(txt=F(st, **base), num=F(st, num_format=NUM, **base),
                    pct=F(st, num_format=PCT1, **base), dec=F(st, num_format=DEC2, **base))

    r = 15
    for j, (c, hrow, first, last, srow) in enumerate(sections):
        summary_row(r, REP_DISPLAY[c], srow, mk_fmt(ALT if j % 2 == 0 else "white"))
        r += 1
    summary_row(r, "Rep-allocated selling book", sb_row, mk_fmt(YELLOW, True)); r += 1
    summary_row(r, "House accounts (zeroed)", house_sub, mk_fmt("white")); r += 1
    summary_row(r, "Closed / lost accounts", closed_sub, mk_fmt(ALT)); r += 1
    summary_row(r, "TOTAL — ALL ACCOUNTS", total_row, mk_fmt(ORANGE, True))

    # --- detail
    dh = ["Acct", "Customer", "Br", f"LY {lyhdr}", f"{kpi_prefix} Target", "Expected", "Actual",
          "% Exp", "Projected", "Proj v Tgt", "v Tgt %", "v LY %", "Chg kg", "LY kg",
          "kg Δ%", "R/kg", "LY R/kg", "R/kg Δ%"]
    for i, h in enumerate(dh):
        ws.write(27, 1 + i, h, th)

    rep_hdr_fmt = F(st, bold=True, font_size=10, font_color="white", bg_color=NAVY2)
    sub_fmt = mk_fmt(ORANGE, True, size=10)

    def rnd(v):
        return round(v) if round_vals else v

    def write_acct_row(r, a, memo, stripe):
        tgt, h, n, e, o = active[a]
        bg = ALT if stripe else "white"
        base = dict(font_size=9, bg_color=bg)
        blue = dict(font_size=9, font_color=BLUE, bg_color=bg)
        ws.write(r - 1, 1, a, F(st, **base))
        ws.write(r - 1, 2, M.name(a), F(st, **base))
        br = M.branch(a)
        ws.write(r - 1, 3, br, F(st, **base)) if br else ws.write_blank(r - 1, 3, None, F(st, **base))
        ws.write(r - 1, 4, rnd(e), F(st, num_format=NUM, **blue))
        ws.write(r - 1, 5, rnd(tgt), F(st, num_format=NUM, **blue))
        ws.write_formula(r - 1, 6, f"=F{r}*$E$7/$H$7", F(st, num_format=NUM, **base))
        ws.write(r - 1, 7, rnd(h), F(st, num_format=NUM, **blue))
        ws.write_formula(r - 1, 8, f'=IF(G{r}=0,"",H{r}/G{r})', F(st, num_format=PCT1, **base))
        jf = f"=H{r}" if memo else f"=H{r}/$E$7*$H$7"
        ws.write_formula(r - 1, 9, jf, F(st, num_format=NUM, **base))
        ws.write_formula(r - 1, 10, f'=IF(F{r}=0,"",J{r}-F{r})', F(st, num_format=NUM, **base))
        ws.write_formula(r - 1, 11, f'=IF(F{r}=0,"",J{r}/F{r}-1)', F(st, num_format=PCT1, **base))
        ws.write_formula(r - 1, 12, f'=IF(E{r}=0,"",J{r}/E{r}-1)', F(st, num_format=PCT1, **base))
        ws.write(r - 1, 13, rnd(n), F(st, num_format=NUM, **blue))
        ws.write(r - 1, 14, rnd(o), F(st, num_format=NUM, **blue))
        pf = (f'=IF(O{r}=0,"",N{r}/O{r}-1)' if memo
              else f'=IF(O{r}=0,"",(N{r}/$E$7*$H$7)/O{r}-1)')
        ws.write_formula(r - 1, 15, pf, F(st, num_format=PCT1, **base))
        ws.write_formula(r - 1, 16, f'=IF(N{r}=0,"",H{r}/N{r})', F(st, num_format=DEC2, **base))
        ws.write_formula(r - 1, 17, f'=IF(O{r}=0,"",E{r}/O{r})', F(st, num_format=DEC2, **base))
        ws.write_formula(r - 1, 18,
                         f'=IF(OR(N{r}=0,O{r}=0,E{r}=0),"",(H{r}/N{r})/(E{r}/O{r})-1)',
                         F(st, num_format=PCT1, **base))

    def write_subtotal(r, label, first, last, memo, fmt):
        ws.merge_range(r - 1, 1, r - 1, 3, label, fmt["txt"])
        for cl, letter in [(4, "E"), (5, "F"), (7, "H"), (13, "N"), (14, "O")]:
            ws.write_formula(r - 1, cl, f"=SUM({letter}{first}:{letter}{last})", fmt["num"])
        ws.write_formula(r - 1, 6, f"=F{r}*$E$7/$H$7", fmt["num"])
        ws.write_formula(r - 1, 8, f'=IF(G{r}=0,"",H{r}/G{r})', fmt["pct"])
        jf = f"=H{r}" if memo else f"=H{r}/$E$7*$H$7"
        ws.write_formula(r - 1, 9, jf, fmt["num"])
        ws.write_formula(r - 1, 10, f'=IF(F{r}=0,"",J{r}-F{r})', fmt["num"])
        ws.write_formula(r - 1, 11, f'=IF(F{r}=0,"",J{r}/F{r}-1)', fmt["pct"])
        ws.write_formula(r - 1, 12, f'=IF(E{r}=0,"",J{r}/E{r}-1)', fmt["pct"])
        pf = (f'=IF(O{r}=0,"",N{r}/O{r}-1)' if memo
              else f'=IF(O{r}=0,"",(N{r}/$E$7*$H$7)/O{r}-1)')
        ws.write_formula(r - 1, 15, pf, fmt["pct"])
        ws.write_formula(r - 1, 16, f'=IF(N{r}=0,"",H{r}/N{r})', fmt["dec"])
        ws.write_formula(r - 1, 17, f'=IF(O{r}=0,"",E{r}/O{r})', fmt["dec"])
        ws.write_formula(r - 1, 18,
                         f'=IF(OR(N{r}=0,O{r}=0,E{r}=0),"",(H{r}/N{r})/(E{r}/O{r})-1)',
                         fmt["pct"])

    for c, hrow, first, last, srow in sections:
        ws.merge_range(hrow - 1, 1, hrow - 1, 18,
                       f"{REP_DISPLAY[c]}   ({len(per_rep[c])} customers)", rep_hdr_fmt)
        for j, a in enumerate(per_rep[c]):
            write_acct_row(first + j, a, memo=False, stripe=(first + j) % 2 == 0)
        write_subtotal(srow, f"{c} subtotal", first, last, memo=False, fmt=sub_fmt)

    # selling book
    sb_fmt = mk_fmt(YELLOW, True, size=10)
    ws.merge_range(sb_row - 1, 1, sb_row - 1, 3, "SUBTOTAL — Rep-allocated selling book", sb_fmt["txt"])
    subrefs = [s[4] for s in sections]
    for cl, letter in [(4, "E"), (5, "F"), (7, "H"), (9, "J"), (13, "N"), (14, "O")]:
        ws.write_formula(sb_row - 1, cl, "=" + "+".join(f"{letter}{sr}" for sr in subrefs), sb_fmt["num"])
    ws.write_formula(sb_row - 1, 6, f"=F{sb_row}*$E$7/$H$7", sb_fmt["num"])
    ws.write_formula(sb_row - 1, 8, f"=H{sb_row}/G{sb_row}", sb_fmt["pct"])
    ws.write_formula(sb_row - 1, 10, f"=J{sb_row}-F{sb_row}", sb_fmt["num"])
    ws.write_formula(sb_row - 1, 11, f"=J{sb_row}/F{sb_row}-1", sb_fmt["pct"])
    ws.write_formula(sb_row - 1, 12, f"=J{sb_row}/E{sb_row}-1", sb_fmt["pct"])
    ws.write_formula(sb_row - 1, 15,
                     f'=IF(O{sb_row}=0,"",(N{sb_row}/$E$7*$H$7)/O{sb_row}-1)', sb_fmt["pct"])
    ws.write_formula(sb_row - 1, 16, f'=IF(N{sb_row}=0,"",H{sb_row}/N{sb_row})', sb_fmt["dec"])
    ws.write_formula(sb_row - 1, 17, f'=IF(O{sb_row}=0,"",E{sb_row}/O{sb_row})', sb_fmt["dec"])
    ws.write_formula(sb_row - 1, 18,
                     f'=IF(OR(N{sb_row}=0,O{sb_row}=0,E{sb_row}=0),"",(H{sb_row}/N{sb_row})/(E{sb_row}/O{sb_row})-1)',
                     sb_fmt["pct"])

    memo_hdr = F(st, bold=True, font_size=10, font_color="white", bg_color=NAVY2)
    ws.merge_range(house_hdr - 1, 1, house_hdr - 1, 18,
                   f"House accounts (zeroed)   ({len(house)} accounts) — no sales target (not run-rated)",
                   memo_hdr)
    for j, a in enumerate(house):
        write_acct_row(house_hdr + 1 + j, a, memo=True, stripe=(house_hdr + 1 + j) % 2 == 0)
    write_subtotal(house_sub, "House accounts (zeroed) subtotal",
                   house_hdr + 1, house_sub - 1, memo=True, fmt=sub_fmt)

    ws.merge_range(closed_hdr - 1, 1, closed_hdr - 1, 18,
                   f"Closed / lost accounts   ({len(closed)} accounts) — no sales target (not run-rated)",
                   memo_hdr)
    for j, a in enumerate(closed):
        write_acct_row(closed_hdr + 1 + j, a, memo=True, stripe=(closed_hdr + 1 + j) % 2 == 0)
    write_subtotal(closed_sub, "Closed / lost accounts subtotal",
                   closed_hdr + 1, closed_sub - 1, memo=True, fmt=sub_fmt)

    # total
    tot_fmt = mk_fmt(NAVY, True, "white", 12)
    ws.merge_range(total_row - 1, 1, total_row - 1, 3, "TOTAL — ALL ACCOUNTS", tot_fmt["txt"])
    for cl, letter in [(4, "E"), (5, "F"), (7, "H"), (9, "J"), (13, "N"), (14, "O")]:
        ws.write_formula(total_row - 1, cl,
                         f"={letter}{sb_row}+{letter}{house_sub}+{letter}{closed_sub}", tot_fmt["num"])
    ws.write_formula(total_row - 1, 6, f"=F{total_row}*$E$7/$H$7", tot_fmt["num"])
    ws.write_formula(total_row - 1, 8, f"=H{total_row}/G{total_row}", tot_fmt["pct"])
    ws.write_formula(total_row - 1, 10, f"=J{total_row}-F{total_row}", tot_fmt["num"])
    ws.write_formula(total_row - 1, 11, f"=J{total_row}/F{total_row}-1", tot_fmt["pct"])
    ws.write_formula(total_row - 1, 12, f"=J{total_row}/E{total_row}-1", tot_fmt["pct"])
    ws.write_formula(total_row - 1, 15,
                     f'=IF(O{total_row}=0,"",(N{total_row}/$E$7*$H$7)/O{total_row}-1)', tot_fmt["pct"])
    ws.write_formula(total_row - 1, 16, f'=IF(N{total_row}=0,"",H{total_row}/N{total_row})', tot_fmt["dec"])
    ws.write_formula(total_row - 1, 17, f'=IF(O{total_row}=0,"",E{total_row}/O{total_row})', tot_fmt["dec"])
    ws.write_formula(total_row - 1, 18,
                     f'=IF(OR(N{total_row}=0,O{total_row}=0,E{total_row}=0),"",(H{total_row}/N{total_row})/(E{total_row}/O{total_row})-1)',
                     tot_fmt["pct"])

    note8 = F(st, font_size=8, font_color="#595959")
    fns = [
        "Expected = target × (trading days elapsed ÷ trading days in period). Projected = actual ÷ "
        "elapsed × days in period. For completed months elapsed = days in period, so Expected = target "
        "and Projected = actual.",
        "Non-budget accounts are listed under the rep they are allocated to (invoice salesrep), 0 target. "
        "House and Closed/Lost accounts have no target (memo) and are NOT run-rated — their Projected = "
        "actual MTD (a lost account won't bill further), so one-off credits/closures don't distort the "
        "projected total.",
        "Last-year dedicated-load revenue is merged into each client's LY where still billed. Figures are "
        "net invoiced (Subtotal excl VAT less credit notes), invoice-date.",
        "Chg kg = chargeable weight (Chrg Mass) this period; LY kg = same period last year. kg Δ% compares "
        "projected kg vs LY. R/kg = net ÷ chargeable kg (2 dp); LY R/kg = last-year rate; R/kg Δ% = rate "
        "change.",
        "Sources: INV Date FY26 & FY27, Credits file, FY26-27 Budget v30 (targets). Blue = source inputs / "
        "assumptions; black = formulas.",
    ]
    for j, t in enumerate(fns):
        ws.merge_range(total_row + 1 + j, 1, total_row + 1 + j, 9, t, note8)


# ---------------------------------------------------------------- daily tabs

def build_daily_tab(wb, st, M: Model, sheet, basis, day, pool: Pool, subtract_credits):
    ws = wb.add_worksheet(sheet)
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 9, 34, 6, 13, 12, 13, 9, 12, 8]):
        ws.set_column(i, i, w)
    long_date = f"{day.day} {day.strftime('%b %Y')}"
    title_block(ws, st, "J", "SUNRISE LOGISTICS",
                f"Daily Revenue by Customer — {basis} date {long_date}",
                f"Customers billed on {long_date} vs pro-rata daily target · net (excl VAT, less "
                f"credit notes) · ZAR")

    # data: billed accounts (any lines on the day), net = sub − credits(day)
    billed = {}
    for a in pool.day:
        if day in pool.day[a]:
            sub, kg = pool.day[a][day]
            net = sub - (M.credits.win(a, day, day) if subtract_credits else 0)
            billed[a] = (net, kg)
    jul_t = {a: M.target(a, [7]) for a in set(M.cls) | set(billed)}

    per_rep = defaultdict(lambda: ([], []))  # code -> (billed, notbilled)
    for a, (net, kg) in billed.items():
        c = M.cls.get(a) or "CLOSED"
        per_rep[c][0].append(a)
    for a, c in M.cls.items():
        if a in billed:
            continue
        if jul_t.get(a, 0) > 0 and c in ("TF", "CN", "LS", "NP", "PM", "NEW", "AH"):
            per_rep[c][1].append(a)
    for c in per_rep:
        per_rep[c][0].sort(key=lambda a: (-billed[a][0], M.budget.rank(a)))
        per_rep[c][1].sort(key=lambda a: (-jul_t[a], M.budget.rank(a)))

    reps = [c for c in REP_ORDER if per_rep.get(c) and (per_rep[c][0] or per_rep[c][1])]
    house_b = sorted(per_rep["HOUSE"][0], key=lambda a: (-billed[a][0], M.budget.rank(a))) \
        if "HOUSE" in per_rep else []
    closed_b = sorted(per_rep["CLOSED"][0], key=lambda a: (-billed[a][0], M.budget.rank(a))) \
        if "CLOSED" in per_rep else []

    # layout
    sections = []
    r = 15
    for c in reps:
        b, nb = per_rep[c]
        nrows = len(b) + (1 if nb else 0) + len(nb)
        sections.append((c, r, r + 1, r + nrows, r + nrows + 1))
        r = r + nrows + 2
    sb_row = r
    rr = r + 2
    house_hdr = house_sub = None
    if house_b:
        house_hdr = rr
        house_sub = rr + len(house_b) + 1
        rr = house_sub + 1
    closed_hdr = closed_sub = None
    if closed_b:
        closed_hdr = rr
        closed_sub = rr + len(closed_b) + 1
        rr = closed_sub + 1
    total_row = rr

    ye = dict(font_size=10, bg_color=YELLOW)
    ws.write("B7", "Trading days in month:", F(st, bold=True, **ye))
    ws.merge_range("C7:D7", "", F(st, **ye))
    ws.write("E7", TRADING_DAYS[7], F(st, font_color=BLUE, bold=True, **ye))
    ws.merge_range("F7:J7", "Day target = monthly budget target ÷ trading days (editable)",
                   F(st, font_size=8, font_color="#595959"))

    kl_navy = F(st, bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kl_or = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)
    kl_ye = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=YELLOW)

    def kv(bg, fc, fmt):
        return F(st, bold=True, font_size=14, font_color=fc, bg_color=bg,
                 num_format=fmt, align="left", valign="vcenter")

    for c1, c2, lab, f_, lf, vf in [
            ("B", "C", "DAY NET", f"=E{total_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("D", "E", "DAY TARGET (full book)", f"=F{total_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("F", "G", "% OF DAY TARGET", f"=H{total_row}", kl_ye, kv(YELLOW, NAVY, PCT1)),
            ("H", "I", "CHG KG", f"=I{total_row}", kl_navy, kv(NAVY, "white", NUM)),
            ("J", "J", "R/kg", f'=IF(I{total_row}=0,"",E{total_row}/I{total_row})',
             kl_or, kv(ORANGE, NAVY, DEC2))]:
        if c1 == c2:
            ws.write(f"{c1}9", lab, lf)
            ws.write_formula(f"{c1}10", f_, vf)
        else:
            ws.merge_range(f"{c1}9:{c2}9", lab, lf)
            ws.merge_range(f"{c1}10:{c2}10", f_, vf)

    th = F(st, bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    for i, h in enumerate(["Acct", "Customer", "Br", "Day Net", "Day Tgt", "Var v Day Tgt",
                           "% Day Tgt", "Chg kg", "R/kg"]):
        ws.write(13, 1 + i, h, th)

    rep_hdr_fmt = F(st, bold=True, font_size=10, font_color="white", bg_color=NAVY2)
    sub_base = dict(font_size=9, bold=True, bg_color=ORANGE)
    lab_fmt = F(st, font_size=9, bold=True, italic=True)

    def tgt_str(a):
        t = jul_t.get(a, 0)
        t = int(t) if t == int(t) else t
        return f"={t}/$E$7"

    def write_row(r, a, net, kg, stripe):
        bg = ALT if stripe else "white"
        base = dict(font_size=9, bg_color=bg)
        blue = dict(font_size=9, font_color=BLUE, bg_color=bg)
        ws.write(r - 1, 1, a, F(st, **base))
        ws.write(r - 1, 2, M.name(a), F(st, **base))
        br = M.branch(a)
        ws.write(r - 1, 3, br, F(st, **base)) if br else ws.write_blank(r - 1, 3, None, F(st, **base))
        ws.write(r - 1, 4, round(net), F(st, num_format=NUM, **blue))
        ws.write_formula(r - 1, 5, tgt_str(a), F(st, num_format=NUM, **base))
        ws.write_formula(r - 1, 6, f'=IF(F{r}=0,"",E{r}-F{r})', F(st, num_format=NUM, **base))
        ws.write_formula(r - 1, 7, f'=IF(F{r}=0,"",E{r}/F{r})', F(st, num_format=PCT1, **base))
        ws.write(r - 1, 8, round(kg), F(st, num_format=NUM, **blue))
        ws.write_formula(r - 1, 9, f'=IF(I{r}=0,"",E{r}/I{r})', F(st, num_format=DEC2, **base))

    def write_sub(r, label, first, last):
        ws.merge_range(r - 1, 1, r - 1, 3, label, F(st, **sub_base))
        ws.write_formula(r - 1, 4, f"=SUM(E{first}:E{last})", F(st, num_format=NUM, **sub_base))
        ws.write_formula(r - 1, 5, f"=SUM(F{first}:F{last})", F(st, num_format=NUM, **sub_base))
        ws.write_formula(r - 1, 6, f'=IF(F{r}=0,"",E{r}-F{r})', F(st, num_format=NUM, **sub_base))
        ws.write_formula(r - 1, 7, f'=IF(F{r}=0,"",E{r}/F{r})', F(st, num_format=PCT1, **sub_base))
        ws.write_formula(r - 1, 8, f"=SUM(I{first}:I{last})", F(st, num_format=NUM, **sub_base))
        ws.write_formula(r - 1, 9, f'=IF(I{r}=0,"",E{r}/I{r})', F(st, num_format=DEC2, **sub_base))

    for c, hrow, first, last, srow in sections:
        b, nb = per_rep[c]
        ws.merge_range(hrow - 1, 1, hrow - 1, 9,
                       f"{REP_DISPLAY[c]}   ({len(b)} billed, {len(nb)} not billed)", rep_hdr_fmt)
        r = first
        for a in b:
            write_row(r, a, billed[a][0], billed[a][1], r % 2 == 0)
            r += 1
        if nb:
            ws.write(r - 1, 1, "Not billed on the day (targeted):", lab_fmt)
            r += 1
            for a in nb:
                write_row(r, a, 0, 0, r % 2 == 0)
                r += 1
        write_sub(srow, f"{c} subtotal", first, last)

    sbf = dict(font_size=10, bold=True, bg_color=YELLOW)
    ws.merge_range(sb_row - 1, 1, sb_row - 1, 3, "SUBTOTAL — Rep-allocated (billed today)", F(st, **sbf))
    subrefs = [s[4] for s in sections]
    for cl, letter in [(4, "E"), (5, "F"), (8, "I")]:
        ws.write_formula(sb_row - 1, cl, "=" + "+".join(f"{letter}{sr}" for sr in subrefs),
                         F(st, num_format=NUM, **sbf))
    ws.write_formula(sb_row - 1, 6, f"=E{sb_row}-F{sb_row}", F(st, num_format=NUM, **sbf))
    ws.write_formula(sb_row - 1, 7, f"=E{sb_row}/F{sb_row}", F(st, num_format=PCT1, **sbf))
    ws.write_formula(sb_row - 1, 9, f'=IF(I{sb_row}=0,"",E{sb_row}/I{sb_row})',
                     F(st, num_format=DEC2, **sbf))

    memo_hdr = F(st, bold=True, font_size=10, font_color="white", bg_color=NAVY2)
    parts = [f"E{sb_row}"]
    for blk, hdr_r, sub_r, label in [
            (house_b, house_hdr, house_sub, "House accounts (zeroed)"),
            (closed_b, closed_hdr, closed_sub, "Closed / lost accounts")]:
        if not blk:
            continue
        ws.merge_range(hdr_r - 1, 1, hdr_r - 1, 9,
                       f"{label}   ({len(blk)} billed) — no target", memo_hdr)
        r = hdr_r + 1
        for a in blk:
            write_row(r, a, billed[a][0], billed[a][1], r % 2 == 0)
            r += 1
        write_sub(sub_r, f"{label} subtotal", hdr_r + 1, sub_r - 1)
        parts.append(f"E{sub_r}")

    tf = dict(font_size=11, bold=True, font_color="white", bg_color=NAVY)
    ws.merge_range(total_row - 1, 1, total_row - 1, 3, "TOTAL — ALL ACCOUNTS BILLED", F(st, **tf))
    refs = [p[1:] for p in parts]  # row numbers
    for cl, letter in [(4, "E"), (5, "F"), (8, "I")]:
        ws.write_formula(total_row - 1, cl, "=" + "+".join(f"{letter}{r}" for r in refs),
                         F(st, num_format=NUM, **tf))
    ws.write_formula(total_row - 1, 6, f"=E{total_row}-F{total_row}", F(st, num_format=NUM, **tf))
    ws.write_formula(total_row - 1, 7, f"=E{total_row}/F{total_row}", F(st, num_format=PCT1, **tf))
    ws.write_formula(total_row - 1, 9, f'=IF(I{total_row}=0,"",E{total_row}/I{total_row})',
                     F(st, num_format=DEC2, **tf))

    note8 = F(st, font_size=8, font_color="#595959")
    fns = [
        "Each rep section lists customers billed on the day first, then targeted customers with no "
        "billing that day (Day Net 0). Day Tgt = monthly budget target ÷ trading days; subtotals & "
        "totals sum through, so % Day Tgt is measured against the full budgeted book.",
        "INV tab = invoice-date basis, net of credit notes raised that date. WB tab = waybill-date "
        "basis (value of waybills raised that day), gross of credit notes. R/kg = day net ÷ "
        "chargeable kg.",
        "Non-budget accounts appear under their rep (0 target). Blue = source inputs / assumptions; "
        "black = formulas.",
    ]
    for j, t in enumerate(fns):
        ws.merge_range(total_row + 1 + j, 1, total_row + 1 + j, 9, t, note8)


# ---------------------------------------------------------------- credit notes tab

def build_credit_tab(wb, st, M: Model, mtd_max: date):
    ws = wb.add_worksheet("MTD Credit Notes")
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 9, 13, 9, 32, 18, 14, 22, 13, 20]):
        ws.set_column(i, i, w)
    title_block(ws, st, "J", "SUNRISE LOGISTICS", "MTD Credit Notes Processed — July FY27",
                "Credit notes processed to date · net value excl VAT · ZAR · reduces revenue")

    w = (date(FY, 7, 1), month_win(FY, 7)[1])
    notes = [n for n in M.credits.rows if w[0] <= n["date"] <= w[1]]
    total = sum(n["value"] for n in notes)
    reasons = defaultdict(lambda: [0.0, 0])
    for n in notes:
        rs = n["reason"] or "(unspecified)"
        reasons[rs][0] += n["value"]
        reasons[rs][1] += 1
    top_reason = max(reasons.items(), key=lambda kv: kv[1][0])
    largest = max((n["value"] for n in notes), default=0)

    kl_navy = F(st, bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kl_or = F(st, bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)

    def kv(bg, fc, fmt):
        return F(st, bold=True, font_size=14, font_color=fc, bg_color=bg,
                 num_format=fmt, align="left", valign="vcenter")

    ws.merge_range("B7:C7", "TOTAL CREDITS", kl_navy)
    ws.merge_range("D7:E7", "# CREDIT NOTES", kl_navy)
    ws.merge_range("F7:G7", "LARGEST NOTE", kl_navy)
    ws.merge_range("H7:J7", f"TOP REASON: {top_reason[0]}", kl_or)
    ws.merge_range("B8:C8", total, kv(NAVY, "white", NUM))
    ws.merge_range("D8:E8", len(notes), kv(NAVY, "white", NUM))
    ws.merge_range("F8:G8", largest, kv(NAVY, "white", NUM))
    ws.merge_range("H8:J8", top_reason[1][0], kv(ORANGE, NAVY, NUM))

    sect = F(st, bold=True, font_size=11, font_color="white", bg_color=NAVY)
    ws.merge_range("B11:J11", "CREDIT NOTES BY REASON", sect)
    th = F(st, bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    ws.merge_range("B12:F12", "Reason", th)
    ws.merge_range("G12:H12", "Value", th)
    ws.write("I12", "# Notes", th)
    ws.write("J12", "% of Total", th)

    ordered = sorted(reasons.items(), key=lambda kv: -kv[1][0])
    r0 = 13
    total_r = r0 + len(ordered)
    for j, (rs, (val, cnt)) in enumerate(ordered):
        r = r0 + j
        bg = ALT if r % 2 == 1 else "white"
        base = dict(font_size=9, bg_color=bg)
        ws.merge_range(r - 1, 1, r - 1, 5, rs, F(st, **base))
        ws.merge_range(r - 1, 6, r - 1, 7, round(val), F(st, num_format=NUM, font_color=BLUE, **base))
        ws.write(r - 1, 8, cnt, F(st, num_format=NUM, font_color=BLUE, **base))
        ws.write_formula(r - 1, 9, f"=G{r}/$G${total_r}", F(st, num_format=PCT1, **base))
    ob = dict(font_size=9, bold=True, bg_color=ORANGE)
    ws.merge_range(total_r - 1, 1, total_r - 1, 5, "Total", F(st, **ob))
    ws.merge_range(total_r - 1, 6, total_r - 1, 7, f"=SUM(G{r0}:G{total_r - 1})",
                   F(st, num_format=NUM, **ob))
    ws.write_formula(total_r - 1, 8, f"=SUM(I{r0}:I{total_r - 1})", F(st, num_format=NUM, **ob))
    ws.write_formula(total_r - 1, 9, f"=G{total_r}/G{total_r}", F(st, num_format=PCT1, **ob))

    dsec = total_r + 2
    ws.merge_range(dsec - 1, 1, dsec - 1, 9, "CREDIT NOTE DETAIL (largest first)", sect)
    dh = dsec + 1
    for i, h in enumerate(["Date", "CN Ref", "Account", "Customer", "Rep", "Branch",
                           "Reason", "Value", "Credit Controller"]):
        ws.write(dh - 1, 1 + i, h, th)
    detail = sorted(notes, key=lambda n: -n["value"])
    r = dh + 1
    for n in detail:
        bg = ALT if r % 2 == 0 else "white"
        base = dict(font_size=9, bg_color=bg)
        vals = [n["date"].strftime("%d %b"), n["ref"], n["acct"], n["customer"],
                n["rep"], n["branch"], n["reason"] or "(unspecified)",
                round(n["value"]), n["controller"]]
        for j, v in enumerate(vals):
            kw = dict(base)
            if j == 7:
                kw["num_format"] = NUM
                kw["font_color"] = BLUE
            ws.write(r - 1, 1 + j, v, F(st, **kw))
        r += 1
    ws.write(r - 1, 1, "TOTAL", F(st, font_size=9, bold=True, bg_color=ORANGE))
    ws.write_formula(r - 1, 8, f"=SUM(I{dh + 1}:I{r - 1})",
                     F(st, num_format=NUM, font_size=9, bold=True, bg_color=ORANGE))

    note8 = F(st, font_size=8, font_color="#595959")
    fns = [
        "Listing of all credit notes processed in July FY27 to date (by processing date). Value = "
        "Subtotal (net, excl VAT); credit notes reduce revenue.",
        f"The MTD Billing tab nets credit notes dated through {mtd_max.day} "
        f"{mtd_max.strftime('%b %Y')}; notes dated later appear here and will flow into billing as "
        f"the data extends.",
        "Reason and Credit Controller are as captured in the credits system. Blue = source values.",
    ]
    for j, t in enumerate(fns):
        ws.merge_range(r + 1 + j, 1, r + 1 + j, 9, t, note8)


# ---------------------------------------------------------------- main

def build(inv_file, py_inv_file, wb_file, credits_file, budget_file, out_dir,
          inv_asof=None, wb_asof=None):
    budget = Budget(budget_file)
    inv, py, wbp, fold = load_pools(inv_file, py_inv_file, wb_file, budget)
    credits = Credits(credits_file, fold)
    M = Model(inv, py, wbp, credits, budget)

    mtd_max = max(d for days in inv.day.values() for d in days
                  if d.month == 7 and d.year == FY and (inv_asof is None or d <= inv_asof))
    wb_max = max(d for days in wbp.day.values() for d in days
                 if d.month == 7 and d.year == FY and (wb_asof is None or d <= wb_asof))
    jul_elapsed = trading_days_between(date(FY, 7, 1), mtd_max)
    ly_mtd_max = nth_trading_day(FY - 1, 7, jul_elapsed)
    p = dict(mtd_max=mtd_max, jul_elapsed=jul_elapsed, ly_mtd_max=ly_mtd_max)

    out_path = f"{out_dir}/Revenue Dashboard.xlsx"
    wb = xlsxwriter.Workbook(out_path)
    st = Styles(wb)

    build_tab1(wb, st, M, p)

    for m, name in [(3, "Mar"), (4, "Apr"), (5, "May"), (6, "Jun")]:
        month_full = {"Mar": "Mar", "Apr": "Apr", "May": "May", "Jun": "Jun"}[name]
        build_customer_tab(
            wb, st, M, f"{name} FY27",
            f"Billing vs Target by Customer — {name} FY27 (full month)",
            f"Net billing (Subtotal less credit notes, invoice-date) · full completed month · "
            f"Targets from Budget v30 · LY = {name} FY26 net actual · ZAR",
            name, name, TRADING_DAYS[m], TRADING_DAYS[m],
            month_win(FY, m), month_win(FY - 1, m), [m])

    ytd_days = sum(TRADING_DAYS[m] for m in (3, 4, 5, 6))
    build_customer_tab(
        wb, st, M, "YTD to Jun FY27",
        "Billing vs Target by Customer — YTD to June FY27 (Mar–Jun)",
        "Net billing (Subtotal less credit notes, invoice-date) · YTD Mar–Jun (complete) · "
        "Targets from Budget v30 · LY = Mar–Jun FY26 net actual · ZAR",
        "YTD", "YTD", ytd_days, ytd_days,
        (date(FY, 3, 1), month_win(FY, 6)[1]), (date(FY - 1, 3, 1), month_win(FY - 1, 6)[1]),
        [3, 4, 5, 6])

    build_customer_tab(
        wb, st, M, "MTD Billing by Customer",
        "MTD Billing vs Target by Customer — July FY27",
        f"Net billing (Subtotal less credit notes, invoice-date) · month-to-date, "
        f"{p['jul_elapsed']} of {TRADING_DAYS[7]} trading days · Targets from Budget v30 · "
        f"LY = July FY26 net actual · ZAR",
        "Jul", "Jul", p["jul_elapsed"], TRADING_DAYS[7],
        (date(FY, 7, 1), mtd_max), month_win(FY - 1, 7), [7], round_vals=True,
        memo_mode="mtd")

    build_daily_tab(wb, st, M, "Daily — Invoice date", "Invoice", mtd_max, inv, True)
    build_daily_tab(wb, st, M, "Daily — Waybill date", "Waybill", wb_max, wbp, True)
    build_credit_tab(wb, st, M, mtd_max)

    wb.close()
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inv-file", required=True)
    ap.add_argument("--py-inv-file", required=True)
    ap.add_argument("--wb-file", required=True)
    ap.add_argument("--credits-file", required=True)
    ap.add_argument("--budget-file", required=True)
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--inv-asof", default=None,
                    help="Cap invoice-date data at this date (YYYY-MM-DD); for reconciliation runs")
    ap.add_argument("--wb-asof", default=None, help="Cap waybill-date data (YYYY-MM-DD)")
    a = ap.parse_args()
    print(build(a.inv_file, a.py_inv_file, a.wb_file, a.credits_file, a.budget_file, a.out_dir,
                date.fromisoformat(a.inv_asof) if a.inv_asof else None,
                date.fromisoformat(a.wb_asof) if a.wb_asof else None))
