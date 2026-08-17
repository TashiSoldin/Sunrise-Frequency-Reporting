"""Revenue tools — sales, revenue summary, unbilled and credit notes (Day 4).

ONE set of query logic serves both the inline answer and the workbook: the
verified extraction (extract_revenue.extraction_sql -> export_shaped) feeds
the aggregations here AND the report builders by injection — the same seam
Day 3 tested cell-for-cell against the file path (tests/test_export_transform,
commit 3169b08b). Nothing here re-derives a business rule: the FY exclusions,
the credit-note types, the unbilled selection, the billing frontier and the
last-trading-day guard are all imported from the modules that own them.

Usage contracts (Day 3 adversarial review):
- Filtered extracts (account / date bounds) feed INLINE ANSWERS ONLY — never
  a workbook build. build_flash's typical-weekday benchmark, build_unbilled's
  billing frontier and the dashboard's month spine all silently change
  meaning on filtered rows; every workbook built here starts from the
  unfiltered FY extract.
- The account filter is case-sensitive exact-ACCNUM. Codes are validated and
  uppercased before they reach the query (_validate_account), and a customer
  NAME is never passed as an account — match_customer resolves names first.

Guards (non-negotiable — the briefing page's date-column failure mode):
- future dates are refused, never answered;
- a day whose invoicing has not finished is answered with a warning (inline)
  or refused (billing-detail workbook) — never as a confident partial;
- date bases default to the last trading day (day_guards.last_trading_day),
  never a max() over the date column;
- a row cap that is HIT refuses the answer rather than truncating silently —
  a truncated extract is a plausible wrong number, and it does not raise.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The report builders import each other bare (from data import col, ...), so
# the revenue_reports directory itself goes on the path — the same convention
# run_daily.py and the tests use.
sys.path.insert(0, str(REPO / "revenue_reports"))

import build_credit_notes
import build_unbilled
from day_guards import (
    frontier_from_day_counts,
    is_completed_trading_day,
    last_trading_day,
)
from extract_revenue import (
    CREDITS_SQL,
    credits_shaped,
    day_counts_sql,
    export_shaped,
    extraction_sql,
    fy_start,
)

from data import col
from mcp_server.db import run_select

__all__ = [
    "InputError",
    "credit_notes",
    "daily_report",
    "match_customer",
    "revenue_summary",
    "sales_report",
    "unbilled_report",
]


class InputError(ValueError):
    """The request was refused before any query ran."""


# --- where files live -------------------------------------------------------
# Same folders the scheduled pipeline uses (run_revenue_pm.bat). On-demand
# workbooks land in their own subfolder so they can never overwrite a
# scheduled daily. The synced library is the ARCHIVE — Larry receives the
# workbook in the conversation (his ruling, 4 Aug 2026), the folder is where
# it is kept.
_SYNCED = Path(
    os.getenv(
        "SYNCED_DIR",
        r"C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents",
    )
)
DATA_DIR = Path(
    os.getenv(
        "REVENUE_DATA_DIR",
        str(_SYNCED / "Dashboards and Data Analysis" / "2. Revenue Data"),
    )
)
SCHEDULED_REPORT_DIR = Path(
    os.getenv("REVENUE_REPORT_DIR", str(_SYNCED / "Dashboards and Data Analysis"))
)
ONDEMAND_DIR = SCHEDULED_REPORT_DIR / "On Demand"

# Static dashboard inputs, by the names run_daily.py uses. run_daily itself is
# deliberately not imported — loading it configures logging and the mailer.
PY_INV_NAME = "INV Date - March25 - Feb26..xlsx"
BUDGET_NAME = "FY26-27_Budget_v30_Sunrise.xlsx"

DELIVERY_NOTE = (
    "Give Larry the workbook in the conversation (attachment or link) — "
    "the library folder is the archive, not the delivery."
)

# --- row caps (hit cap = refuse, never truncate) -----------------------------
EXTRACT_CAP = 500_000  # full-FY extract runs ~85k lines; headroom, not a limit
CREDITS_CAP = 100_000  # 3 FYs of credits is ~7k rows
CUSTOMER_CAP = 50_000
DAY_COUNTS_CAP = 400  # at most 366 day rows in one FY


def _capped(rows: list, cap: int, what: str) -> list:
    if len(rows) >= cap:
        raise RuntimeError(
            f"{what} returned {cap} rows or more and may be truncated — "
            "refusing to answer from a possibly-incomplete extract"
        )
    return rows


# --- small helpers -----------------------------------------------------------


def _parse_day(value, name: str = "date") -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as e:
        raise InputError(
            f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}"
        ) from e


def _parse_month(value) -> date:
    try:
        y, m = str(value).strip().split("-")
        return date(int(y), int(m), 1)
    except ValueError as e:
        raise InputError(f"month must look like YYYY-MM, got {value!r}") from e


def _month_end(first: date) -> date:
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _norm_date(v):
    return v.date() if isinstance(v, datetime) else v


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _r2(x) -> float:
    return round(float(x or 0), 2)


def _refusal(reason: str, **extra) -> dict:
    return {"ok": False, "refused": True, "reason": reason, **extra}


def _today() -> date:
    """Single seam for "now" — tests pin it, the tools never call
    date.today() directly, and fy_start always derives from the same day."""
    return date.today()


def _credits_start() -> date:
    """First day of the credits pool — two FYs before the current one (the
    pool holds three financial years, like the Credits export)."""
    return date(fy_start(_today()).year - 2, 3, 1)


def _pre_window_refusal(what: str, d: date, window_start: date) -> dict:
    """A day/month before the data window comes back EMPTY, and an empty
    extract answered confidently is a plausible zero that does not raise —
    so anything before the window is refused, never answered (Day 4
    adversarial review)."""
    return _refusal(
        f"{_iso(d)} is before {_iso(window_start)}, where the live "
        f"{what} begins — an answer would read as zero when the data "
        "simply is not pulled. Earlier periods live in the archived FY "
        "files, not this interface."
    )


# --- fetchers (all take run= so tests inject a fake) -------------------------


def fy_extract(basis: str, run=run_select) -> tuple[list[str], list[list]]:
    """The UNFILTERED FY extract in export shape — the only extract a
    workbook may be built from (usage contract 1)."""
    sql, params = extraction_sql(basis, fy_start(_today()))
    cols, rows = run(sql, tuple(params), EXTRACT_CAP)
    return export_shaped(cols, _capped(rows, EXTRACT_CAP, f"{basis} FY extract"))


def _validate_account(account) -> str:
    """The account filter is case-sensitive exact-ACCNUM: a lowercased code
    returns a silent EMPTY extract and an over-long one raises DataError
    (checked live 14 Aug 2026) — so refuse both here, before the query."""
    a = str(account).strip()
    if not a or len(a) > 6:
        raise InputError(f"{account!r} is not a valid account code (1-6 characters)")
    if a != a.upper():
        raise InputError(
            f"account code must be uppercase exact-ACCNUM, got {account!r} — "
            "the filter is case-sensitive and a lowercased code silently "
            "matches nothing"
        )
    return a


def filtered_extract(
    basis: str,
    *,
    account: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    run=run_select,
) -> tuple[list[str], list[list]]:
    """A filtered extract — INLINE ANSWERS ONLY, never a workbook build."""
    if account is not None:
        account = _validate_account(account)
    sql, params = extraction_sql(
        basis, fy_start(_today()), account=account, date_from=date_from, date_to=date_to
    )
    cols, rows = run(sql, tuple(params), EXTRACT_CAP)
    return export_shaped(cols, _capped(rows, EXTRACT_CAP, f"{basis} extract"))


def day_counts(basis: str, run=run_select) -> dict[date, tuple[int, float, int]]:
    """day -> (waybills, subtotal sum, invoiced count), FY-to-date, same
    exclusions as the extract (the SQL is shared, see day_counts_sql)."""
    sql, params = day_counts_sql(basis, fy_start(_today()))
    _, rows = run(sql, tuple(params), DAY_COUNTS_CAP)
    out: dict[date, tuple[int, float, int]] = {}
    for d, n, sub, inv in _capped(rows, DAY_COUNTS_CAP, "day counts"):
        d = _norm_date(d)
        if isinstance(d, date):
            out[d] = (int(n or 0), float(sub or 0), int(inv or 0))
    return out


def billing_frontier_live(run=run_select) -> date:
    """The share-invoiced billing frontier, from day counts — the same rule
    build_unbilled applies to extract rows (day_guards owns the arithmetic)."""
    counts = day_counts("wb", run)
    return frontier_from_day_counts({d: (inv, n) for d, (n, _, inv) in counts.items()})


def _traded_pairs(counts: dict[date, tuple[int, float, int]]):
    return [(d, s) for d, (_, s, _) in counts.items()]


def credits_pool(run=run_select) -> tuple[list[str], list[list]]:
    """All credits, 3 FYs, in credits-export shape — the verified RECEIPT
    query with its date bound as a parameter instead of an f-string."""
    start = _credits_start()
    sql = CREDITS_SQL.replace("DATE '{start}'", "?")
    cols, rows = run(sql, (start,), CREDITS_CAP)
    return credits_shaped(cols, _capped(rows, CREDITS_CAP, "credits extract"))


def _credit_notes_between(
    a: date, b: date, account: str | None = None, run=run_select, pool=None
) -> list[dict]:
    """Credit notes (types Credit Note + Journal Credit ONLY — the net-revenue
    rule) in the inclusive window, optionally for one account. The type filter
    is build_credit_notes.load_credits — imported, not re-derived."""
    hdr_rows = pool if pool is not None else credits_pool(run)
    notes = build_credit_notes.load_credits(None, hdr_rows)
    return [
        n
        for n in notes
        if a <= n["date"] <= b and (account is None or n["acct"] == account)
    ]


# --- customer matching -------------------------------------------------------

_ACCOUNT_SHAPE = re.compile(r"[A-Z0-9]{2,6}")
_NOISE_TOKENS = {
    "PTY",
    "LTD",
    "LIMITED",
    "PROPRIETARY",
    "CC",
    "INC",
    "TA",
    "T/A",
    "THE",
    "AND",
    "&",
}


def _name_key(s: str) -> str:
    tokens = re.sub(r"[^A-Z0-9 ]", " ", s.upper()).split()
    core = [t for t in tokens if t not in _NOISE_TOKENS]
    return " ".join(core or tokens)


def _customers(run) -> list[tuple[str, str]]:
    """The full (account, name) list, cleaned — CUSTOMER is ~2k rows."""
    _, rows = run("SELECT ACCNUM, CUSTNAME FROM CUSTOMER", (), CUSTOMER_CAP)
    _capped(rows, CUSTOMER_CAP, "customer list")
    return [(str(a or "").strip(), str(n or "").strip()) for a, n in rows]


def _scored(q: str, custs: list[tuple[str, str]]) -> list[tuple[float, str, str]]:
    """(score, account, name) for every customer the query plausibly names,
    best first. Exact normalised name = 1.0; query tokens a subset of the
    name's = at least 0.92."""
    qk = _name_key(q)
    scored: list[tuple[float, str, str]] = []
    for acc, name in custs:
        if not acc or not name:
            continue
        nk = _name_key(name)
        s = SequenceMatcher(None, qk, nk).ratio()
        qt, nt = set(qk.split()), set(nk.split())
        if qt and qt <= nt:
            s = max(s, 0.92)
        if qk and qk == nk:
            s = 1.0
        if s >= 0.55:
            scored.append((s, acc, name))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored


def match_customer(customer: str, run=run_select) -> dict:
    """Exact account code first, then fuzzy name returning CANDIDATES — never
    a silent best guess. Resolution is to an Account, because grouping is on
    Account, not the waybill customer name (94 names vs 92 accounts, 3 Aug).
    """
    if not isinstance(customer, str) or not customer.strip():
        raise InputError("customer is empty — provide an account code or a name")
    q = customer.strip()

    code = q.upper()
    if _ACCOUNT_SHAPE.fullmatch(code):
        _, rows = run(
            "SELECT ACCNUM, CUSTNAME FROM CUSTOMER WHERE ACCNUM = ?", (code,), 5
        )
        if rows:
            account = str(rows[0][0]).strip()
            name = str(rows[0][1] or "").strip()
            # An all-letters code also reads as a WORD: 'CBD' and 'RAPID' are
            # live account codes AND name fragments of many other customers
            # (CBD21 'CBD - BMSC Engineering', R32 'RAPID HEAT', ...).
            # Resolving silently would be the best guess this matcher exists
            # to refuse — return candidates, the code's owner first.
            if code.isalpha():
                others = [
                    (s, a, n)
                    for s, a, n in _scored(q, _customers(run))
                    if a != account and s >= 0.9
                ]
                if others:
                    candidates = [
                        {
                            "account": account,
                            "customer_name": name,
                            "score": 1.0,
                            "via": "exact account code",
                        }
                    ] + [
                        {"account": a, "customer_name": n, "score": round(s, 3)}
                        for s, a, n in others[:7]
                    ]
                    return {
                        "resolved": False,
                        "query": q,
                        "candidates": candidates,
                        "message": (
                            f"{q!r} is account code {account} ({name}) but "
                            "also matches other customers' names — ask which "
                            "is meant rather than guessing. Grouping is on "
                            "Account."
                        ),
                    }
            return {
                "resolved": True,
                "account": account,
                "customer_name": name,
                "via": "exact account code",
            }

    scored = _scored(q, _customers(run))

    # Resolve on an exact (normalised) name only when nothing else comes
    # close — a near-tie resolved silently would be exactly the best guess
    # this matcher exists to refuse (94 names vs 92 accounts, 3 Aug).
    exact = [(a, n) for s, a, n in scored if s == 1.0]
    near = [t for t in scored if 0.9 <= t[0] < 1.0]
    if len(exact) == 1 and not near:
        return {
            "resolved": True,
            "account": exact[0][0],
            "customer_name": exact[0][1],
            "via": "exact name match",
        }

    candidates = [
        {"account": a, "customer_name": n, "score": round(s, 3)}
        for s, a, n in scored[:8]
    ]
    if candidates:
        message = (
            f"{q!r} matches more than one customer — ask which account is "
            "meant rather than guessing. Grouping is on Account."
            if len(candidates) > 1
            else f"{q!r} is close to one customer but not an exact match — "
            "confirm before reporting on it."
        )
        if len(scored) > len(candidates):
            message += (
                f" (showing the closest {len(candidates)} of {len(scored)} "
                "possible matches)"
            )
    else:
        message = (
            f"No customer matches {q!r} — check the spelling or provide the "
            "account code. Nothing was assumed."
        )
    return {"resolved": False, "query": q, "candidates": candidates, "message": message}


# --- aggregation helpers ------------------------------------------------------


def _row_indices(headers: list[str]) -> dict[str, int]:
    return {
        n: col(headers, n)
        for n in [
            "Waybill",
            "Waybill Date",
            "Invoice Date",
            "Account",
            "Customer",
            "Subtotal",
            "Chrg Mass",
            "Orig Hub",
        ]
    }


def _totals(rows: list[list], ix: dict[str, int]) -> dict:
    gross = sum(float(r[ix["Subtotal"]] or 0) for r in rows)
    kg = sum(float(r[ix["Chrg Mass"]] or 0) for r in rows)
    return {
        "waybills": len(rows),
        "gross_revenue": _r2(gross),
        "chargeable_kg": _r2(kg),
        "avg_r_per_kg": _r2(gross / kg) if kg else None,
    }


def _top_customers(rows: list[list], ix: dict[str, int], n: int = 5) -> list[dict]:
    by_acct: dict[str, list] = {}
    for r in rows:
        a = str(r[ix["Account"]]).strip()
        g = by_acct.setdefault(a, [0, 0.0, str(r[ix["Customer"]]).strip()])
        g[0] += 1
        g[1] += float(r[ix["Subtotal"]] or 0)
    ranked = sorted(by_acct.items(), key=lambda kv: -kv[1][1])[:n]
    return [
        {
            "account": a,
            "customer_name": name,
            "waybills": cnt,
            "gross_revenue": _r2(v),
        }
        for a, (cnt, v, name) in ranked
    ]


_TWO_DATES_NOTE = (
    "Invoice date = when the invoice was raised (what was billed); waybill "
    "date = when the freight moved (what shipped). Invoicing lags shipping, "
    "so the same calendar day differs between the two bases — timing, not "
    "error."
)


# --- tools ---------------------------------------------------------------------


def sales_report(
    customer: str,
    date_from: str | None = None,
    date_to: str | None = None,
    run=run_select,
) -> dict:
    """Billed revenue for one customer (invoice-date basis), FY-to-date by
    default — an INLINE answer built from a filtered extract; branded
    workbooks come from the unfiltered FY extract via the other tools."""
    match = match_customer(customer, run)
    if not match["resolved"]:
        return {"ok": False, "needs": "customer_disambiguation", **match}
    account, cust_name = match["account"], match["customer_name"]

    today = _today()
    fy0 = fy_start(_today())
    d_from = _parse_day(date_from, "date_from") if date_from else fy0
    d_to = _parse_day(date_to, "date_to") if date_to else today
    if d_from > today:
        return _refusal(
            f"the period starts {d_from}, in the future — nothing can have "
            f"been billed there yet (today is {today}). Future dates are "
            "refused, not answered.",
        )
    if d_from > d_to:
        raise InputError(f"date_from {d_from} is after date_to {d_to}")

    warnings: list[str] = []
    if d_to > today:
        warnings.append(
            f"date_to {_iso(d_to)} is in the future — clamped to today "
            f"({_iso(today)}); a future day cannot be reported"
        )
        d_to = today
    if d_from < fy0:
        warnings.append(
            f"the live extract covers the current financial year (from "
            f"{_iso(fy0)}) — date_from clamped to {_iso(fy0)}; earlier "
            "periods live in the archived FY files, not this interface"
        )
        d_from = fy0

    headers, rows = filtered_extract(
        "inv", account=account, date_from=d_from, date_to=d_to, run=run
    )
    ix = _row_indices(headers)

    frontier = billing_frontier_live(run)
    if d_to >= frontier:
        warnings.append(
            f"invoicing is complete only up to {_iso(frontier - timedelta(days=1))} "
            f"— days from {_iso(frontier)} are still being invoiced, so "
            "figures that include them will still grow. This is not a final "
            "number for those days."
        )

    by_month: dict[str, list] = {}
    names_seen: set[str] = set()
    for r in rows:
        d = _norm_date(r[ix["Invoice Date"]])
        if not isinstance(d, date):
            continue
        key = f"{d.year:04d}-{d.month:02d}"
        g = by_month.setdefault(key, [0, 0.0, 0.0])
        g[0] += 1
        g[1] += float(r[ix["Subtotal"]] or 0)
        g[2] += float(r[ix["Chrg Mass"]] or 0)
        names_seen.add(str(r[ix["Customer"]]).strip())

    if len(names_seen) > 1:
        warnings.append(
            f"this account billed under {len(names_seen)} customer names in "
            "the period — figures are grouped on Account, which is the "
            "correct grouping"
        )

    credits = _credit_notes_between(d_from, d_to, account=account, run=run)
    credit_total = sum(n["value"] for n in credits)
    totals = _totals(rows, ix)

    return {
        "ok": True,
        "account": account,
        "customer_name": cust_name,
        "matched_via": match["via"],
        "basis": "invoice date (what was billed)",
        "period": {"from": _iso(d_from), "to": _iso(d_to)},
        **totals,
        "credit_notes": {
            "count": len(credits),
            "total": _r2(credit_total),
            "types_counted": "Credit Note + Journal Credit only",
        },
        "net_revenue": _r2(totals["gross_revenue"] - credit_total),
        "by_month": [
            {
                "month": k,
                "waybills": c,
                "gross_revenue": _r2(v),
                "chargeable_kg": _r2(kg),
                "avg_r_per_kg": _r2(v / kg) if kg else None,
            }
            for k, (c, v, kg) in sorted(by_month.items())
        ],
        "warnings": warnings,
        "notes": [
            (
                "Net revenue = gross invoiced Subtotal (excl VAT, incl fuel "
                "surcharge) less credit notes. Tilde and Cancelled waybills "
                "are excluded — the same verified rules as the daily reports."
            ),
        ],
    }


def revenue_summary(day: str | None = None, run=run_select) -> dict:
    """One day's revenue on both bases — shipped (waybill date) and billed
    (invoice date) — defaulting to the last completed trading day per basis,
    never the max of the date column."""
    today = _today()
    warnings: list[str] = []
    notes = [_TWO_DATES_NOTE]

    wb_counts = day_counts("wb", run)
    inv_counts = day_counts("inv", run)
    frontier = frontier_from_day_counts(
        {d: (inv, n) for d, (n, _, inv) in wb_counts.items()}
    )

    if day is not None:
        d = _parse_day(day, "day")
        if d > today:
            return _refusal(
                f"{_iso(d)} is in the future (today is {_iso(today)}) — "
                "future dates are refused, not answered."
            )
        if d < fy_start(today):
            return _pre_window_refusal("financial year extract", d, fy_start(today))
        wb_day = inv_day = d
        if d == today:
            warnings.append(
                "today is still being captured — the shipped figures are a "
                "partial snapshot as of now, not a day total"
            )
        if d >= frontier:
            warnings.append(
                f"invoicing for {_iso(d)} has not finished (complete through "
                f"{_iso(frontier - timedelta(days=1))}) — the billed figures "
                "are partial and will still grow"
            )
    else:
        wb_day = last_trading_day(_traded_pairs(wb_counts), today)
        inv_day = last_trading_day(_traded_pairs(inv_counts), today)
        notes.append(
            "dates default to the last completed trading day per basis — one "
            "day in arrears, like the scheduled reports"
        )

    wb_h, wb_rows = filtered_extract("wb", date_from=wb_day, date_to=wb_day, run=run)
    inv_h, inv_rows = filtered_extract(
        "inv", date_from=inv_day, date_to=inv_day, run=run
    )
    wb_ix, inv_ix = _row_indices(wb_h), _row_indices(inv_h)

    from build_flash import BRANCH_MAP, BRANCH_ORDER

    by_branch: dict[str, list] = {b: [0, 0.0] for b in BRANCH_ORDER}
    for r in wb_rows:
        b = BRANCH_MAP.get(str(r[wb_ix["Orig Hub"]]).strip(), "Other")
        by_branch[b][0] += 1
        by_branch[b][1] += float(r[wb_ix["Subtotal"]] or 0)

    credits = _credit_notes_between(inv_day, inv_day, run=run)
    credit_total = sum(n["value"] for n in credits)
    billed = _totals(inv_rows, inv_ix)

    return {
        "ok": True,
        "shipped": {
            "basis": "waybill date",
            "day": _iso(wb_day),
            **_totals(wb_rows, wb_ix),
            "by_branch": [
                {"branch": b, "waybills": c, "gross_revenue": _r2(v)}
                for b, (c, v) in by_branch.items()
            ],
            "top_customers": _top_customers(wb_rows, wb_ix),
        },
        "billed": {
            "basis": "invoice date",
            "day": _iso(inv_day),
            **billed,
            "credit_notes": {"count": len(credits), "total": _r2(credit_total)},
            "net_revenue": _r2(billed["gross_revenue"] - credit_total),
        },
        "billing_frontier": _iso(frontier),
        "warnings": warnings,
        "notes": notes,
    }


def unbilled_report(workbook: bool = False, run=run_select) -> dict:
    """Waybills older than the billing frontier that have not been invoiced.
    Inline summary always; workbook=True also builds the branded report from
    the SAME rows (one extract, one selection, one frontier)."""
    headers, rows = fy_extract("wb", run)
    unbilled, frontier = build_unbilled.select_unbilled(headers, rows)

    by_status: dict[str, int] = {}
    by_acct: dict[str, list] = {}
    for u in unbilled:
        by_status[u["status"]] = by_status.get(u["status"], 0) + 1
        g = by_acct.setdefault(u["acct"], [0, 0.0, u["cust"]])
        g[0] += 1
        g[1] += u["sub"]
    top = sorted(by_acct.items(), key=lambda kv: -kv[1][1])[:10]

    answer = {
        "ok": True,
        "as_of": _iso(_today()),
        "billing_frontier": _iso(frontier),
        "unbilled_waybills": len(unbilled),
        "unbilled_value": _r2(sum(u["sub"] for u in unbilled)),
        "oldest_waybill_date": _iso(unbilled[0]["date"]) if unbilled else None,
        "by_status": by_status,
        "top_customers": [
            {
                "account": a,
                "customer_name": name,
                "waybills": c,
                "unbilled_value": _r2(v),
            }
            for a, (c, v, name) in top
        ],
        "warnings": [],
        "notes": [
            (
                "Unbilled = invoice status <= 0, dated before the billing "
                f"frontier ({_iso(frontier)}). Waybills from the frontier "
                "onward are normal billing lag, not unbilled freight."
            ),
            (
                "The frontier is judged by the SHARE of each day invoiced — "
                "a single early invoice does not move it."
            ),
        ],
    }
    if workbook:
        ONDEMAND_DIR.mkdir(parents=True, exist_ok=True)
        path = build_unbilled.build(
            None, str(ONDEMAND_DIR), exclude_from=frontier, data=(headers, rows)
        )
        answer["workbook"] = {"path": path, "delivery": DELIVERY_NOTE}
    return answer


def credit_notes(
    month: str | None = None, workbook: bool = False, run=run_select
) -> dict:
    """Credit notes for one month (default: the month of the last invoiced
    trading day, the scheduled reports' rule). Types Credit Note + Journal
    Credit only — the net-revenue definition."""
    today = _today()
    warnings: list[str] = []

    if month is not None:
        m0 = _parse_month(month)
        if m0 > today:
            return _refusal(
                f"{month} is in the future — future months are refused, not answered."
            )
        if m0 < _credits_start():
            return _pre_window_refusal(
                "credits pool (three financial years)", m0, _credits_start()
            )
    else:
        inv_day = last_trading_day(_traded_pairs(day_counts("inv", run)), today)
        m0 = inv_day.replace(day=1)
    m_end = _month_end(m0)
    if m0 <= today <= m_end:
        warnings.append(
            "this month is still in progress — the figures are month-to-date, "
            "and more credit notes may still be raised"
        )

    pool = credits_pool(run)
    sel = _credit_notes_between(m0, m_end, run=run, pool=pool)

    by_reason: dict[str, list] = {}
    by_acct: dict[str, list] = {}
    for n in sel:
        g = by_reason.setdefault(n["reason"], [0, 0.0])
        g[0] += 1
        g[1] += n["value"]
        a = by_acct.setdefault(n["acct"], [0, 0.0, n["customer"]])
        a[0] += 1
        a[1] += n["value"]

    fy0 = fy_start(_today())
    trend: dict[str, float] = {}
    for n in _credit_notes_between(fy0, today, run=run, pool=pool):
        key = f"{n['date'].year:04d}-{n['date'].month:02d}"
        trend[key] = trend.get(key, 0.0) + n["value"]

    answer = {
        "ok": True,
        "month": f"{m0.year:04d}-{m0.month:02d}",
        "credit_notes": len(sel),
        "total_value": _r2(sum(n["value"] for n in sel)),
        "types_counted": "Credit Note + Journal Credit only (the net-revenue "
        "rule; Bad Debt and Cancelled are excluded)",
        "by_reason": [
            {"reason": r, "count": c, "value": _r2(v)}
            for r, (c, v) in sorted(by_reason.items(), key=lambda kv: -kv[1][1])
        ],
        "top_customers": [
            {"account": a, "customer_name": name, "count": c, "value": _r2(v)}
            for a, (c, v, name) in sorted(by_acct.items(), key=lambda kv: -kv[1][1])[
                :10
            ]
        ],
        "fy_monthly_trend": [
            {"month": k, "value": _r2(v)} for k, v in sorted(trend.items())
        ],
        "warnings": warnings,
        "notes": ["Values are the credits' Subtotal (excl VAT); they reduce revenue."],
    }
    if workbook:
        ONDEMAND_DIR.mkdir(parents=True, exist_ok=True)
        path = build_credit_notes.build(None, str(ONDEMAND_DIR), month=m0, data=pool)
        answer["workbook"] = {"path": path, "delivery": DELIVERY_NOTE}
    return answer


def daily_report(report: str, day: str | None = None, run=run_select) -> dict:
    """Build one of the branded daily workbooks — flash, billing_detail or
    dashboard — from the UNFILTERED FY extract, in the existing formats.
    (unbilled and credit_notes have their own tools with workbook=True.)"""
    if report not in {"flash", "billing_detail", "dashboard"}:
        raise InputError(
            f"unknown report {report!r} — choose flash, billing_detail or "
            "dashboard (unbilled_report and credit_notes build their own "
            "workbooks with workbook=True)"
        )
    today = _today()
    warnings: list[str] = []
    notes = [DELIVERY_NOTE]
    ONDEMAND_DIR.mkdir(parents=True, exist_ok=True)

    if report == "flash":
        counts = day_counts("wb", run)
        d = (
            _parse_day(day, "day")
            if day
            else last_trading_day(_traded_pairs(counts), today)
        )
        if d > today:
            return _refusal(f"{_iso(d)} is in the future — refused.")
        if d < fy_start(today):
            return _pre_window_refusal("financial year extract", d, fy_start(today))
        if d == today:
            return _refusal(
                "today is still being captured — the flash is a completed-day "
                "snapshot and a partial one would read as final. Ask "
                "revenue_summary for a live view of today, clearly flagged "
                "as partial."
            )
        if not is_completed_trading_day(_traded_pairs(counts), d, today):
            # A dead day (weekend, holiday, a mis-keyed handful of rows)
            # still builds a plausible-looking flash — the original dead-
            # Sunday failure, reachable on demand until this guard.
            ltd = last_trading_day(_traded_pairs(counts), today)
            n = counts.get(d, (0, 0.0, 0))[0]
            return _refusal(
                f"{_iso(d)} does not look like a trading day — it carries "
                f"{n} waybills, below half a typical recent day — so a "
                "flash for it would read as a real day's trading. The "
                f"newest completed trading day is {_iso(ltd)}.",
                last_trading_day=_iso(ltd),
            )
        headers_rows = fy_extract("wb", run)
        import build_flash

        path = build_flash.build(d, None, str(ONDEMAND_DIR), data=headers_rows)

    elif report == "billing_detail":
        wb_counts = day_counts("wb", run)
        inv_counts = day_counts("inv", run)
        frontier = frontier_from_day_counts(
            {d2: (inv, n) for d2, (n, _, inv) in wb_counts.items()}
        )
        d = (
            _parse_day(day, "day")
            if day
            else last_trading_day(_traded_pairs(inv_counts), today)
        )
        if d > today:
            return _refusal(f"{_iso(d)} is in the future — refused.")
        if d < fy_start(today):
            return _pre_window_refusal("financial year extract", d, fy_start(today))
        if d >= frontier:
            if day is not None:
                return _refusal(
                    f"invoicing for {_iso(d)} has not finished (complete "
                    f"through {_iso(frontier - timedelta(days=1))}) — a "
                    "billing detail for it would be a confident partial. A "
                    "not-yet-invoiced day gets a flash, never a billing "
                    "detail.",
                    last_fully_invoiced_day=_iso(frontier - timedelta(days=1)),
                )
            # No day asked for: roll back to the newest fully-invoiced day,
            # the same way the scheduled pipeline reports one day in arrears.
            d = frontier - timedelta(days=1)
            warnings.append(
                f"rolled back to {_iso(d)}, the newest day whose invoicing "
                "has finished — later days are still being invoiced"
            )
        if inv_counts.get(d, (0, 0.0, 0))[0] == 0:
            # Zero invoice lines carry this date (weekends and holidays have
            # no invoice run) — the builder would die on it, and a near-empty
            # detail would read as a real day's billing anyway.
            return _refusal(
                f"no invoices carry {_iso(d)} as their invoice date — there "
                "is nothing to detail for that day. The newest fully-"
                f"invoiced day is {_iso(frontier - timedelta(days=1))}.",
                last_fully_invoiced_day=_iso(frontier - timedelta(days=1)),
            )
        inv_data = fy_extract("inv", run)
        credits_data = credits_pool(run)
        flash_path = (
            SCHEDULED_REPORT_DIR / f"Flash Revenue - {d.day:02d} {d:%b %Y}.xlsx"
        )
        flash_file = str(flash_path) if flash_path.exists() else None
        if flash_file is None:
            warnings.append(
                f"no frozen flash workbook found for {_iso(d)} — the Flash "
                "Comparison tab is omitted (the tab deliberately reads the "
                "morning's frozen flash, never a recomputation)"
            )
        import build_billing_detail

        path = build_billing_detail.build(
            d,
            None,
            None,
            str(ONDEMAND_DIR),
            flash_file=flash_file,
            inv_data=inv_data,
            credits_data=credits_data,
        )

    else:  # dashboard
        if day is not None:
            warnings.append(
                "the dashboard is an as-of workbook — it always builds to the "
                "latest completed trading/invoiced days; the day argument "
                "was ignored"
            )
        py_inv = DATA_DIR / PY_INV_NAME
        budget = DATA_DIR / BUDGET_NAME
        missing = [str(p) for p in (py_inv, budget) if not p.exists()]
        if missing:
            return _refusal(
                "the dashboard needs its two static inputs (prior-FY invoice "
                f"file and budget workbook) and these are missing: {missing}"
            )
        wb_counts = day_counts("wb", run)
        inv_counts = day_counts("inv", run)
        wb_day = last_trading_day(_traded_pairs(wb_counts), today)
        inv_day = last_trading_day(_traded_pairs(inv_counts), today)
        inv_data = fy_extract("inv", run)
        wb_data = fy_extract("wb", run)
        credits_data = credits_pool(run)
        import build_dashboard

        path = build_dashboard.build(
            None,
            str(py_inv),
            None,
            None,
            str(budget),
            str(ONDEMAND_DIR),
            inv_asof=inv_day,
            wb_asof=wb_day,
            inv_data=inv_data,
            wb_data=wb_data,
            credits_data=credits_data,
        )
        d = inv_day

    return {
        "ok": True,
        "report": report,
        "day": _iso(d),
        "workbook": {"path": path, "delivery": DELIVERY_NOTE},
        "warnings": warnings,
        "notes": notes,
    }
