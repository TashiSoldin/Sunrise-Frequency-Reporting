"""Day 4 adversarial review — live probes (read-only).

1. parity   : day_counts aggregates vs the full extract, same-moment-ish —
              per-day (count, subtotal, invoiced) plus frontier and
              last_trading_day from BOTH paths; join fan-out check.
2. names    : CUSTOMER hygiene attacks on match_customer — lowercase ACCNUMs,
              account codes colliding with words in other customers' names,
              name families where exact-resolve would silently drop siblings,
              punctuation/diacritics.
3. receipts : RECEIPT.ACCNUM case/whitespace vs CUSTOMER (credit netting join).

Usage: uv run research/day4_review_probes.py [parity|names|receipts|all]
"""

import io
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "revenue_reports"))

from day_guards import frontier_from_day_counts, last_trading_day
from extract_revenue import connect, day_counts_sql, extraction_sql, fetch, fy_start

from mcp_server import revenue


def check_parity():
    """Aggregate path vs full-pull path, one connection, back-to-back."""
    conn = connect()
    try:
        for basis in ("wb", "inv"):
            print(f"\n=== parity: basis={basis} ===")
            sql_a, p_a = day_counts_sql(basis, fy_start())
            _, agg = fetch(conn, sql_a, p_a)
            sql_f, p_f = extraction_sql(basis, fy_start())
            cols, raw = fetch(conn, sql_f, p_f)
            ix = {c: i for i, c in enumerate(cols)}
            di = ix["WAYDATE" if basis == "wb" else "INVDATE"]
            si, ssub = ix["STATUS"], ix["SUBTOTAL"]
            per = defaultdict(lambda: [0, 0.0, 0])
            for r in raw:
                d = r[di]
                if not isinstance(d, date):
                    continue
                cell = per[d]
                cell[0] += 1
                cell[1] += float(r[ssub] or 0)
                cell[2] += 1 if str(r[si]).strip() == "Invoiced" else 0
            agg_map = {d: (int(n), float(s or 0), int(inv)) for d, n, s, inv in agg}
            days = set(per) | set(agg_map)
            bad = 0
            for d in sorted(days):
                a = agg_map.get(d, (0, 0.0, 0))
                f = tuple(per.get(d, [0, 0.0, 0]))
                if a[0] != f[0] or a[2] != f[2] or abs(a[1] - f[1]) > 0.01:
                    bad += 1
                    print(f"  MISMATCH {d}: agg={a} full={f}")
            print(
                f"  days={len(days)} rows_full={len(raw)} "
                f"rows_agg_total={sum(v[0] for v in agg_map.values())} "
                f"mismatched_days={bad}"
            )
            # frontier + last_trading_day both ways (wb frontier only)
            if basis == "wb":
                fr_agg = frontier_from_day_counts(
                    {d: (v[2], v[0]) for d, v in agg_map.items()}
                )
                fr_full = frontier_from_day_counts(
                    {d: (v[2], v[0]) for d, v in per.items()}
                )
                print(
                    f"  frontier: agg={fr_agg} full={fr_full} "
                    f"{'OK' if fr_agg == fr_full else 'MISMATCH'}"
                )
            lt_agg = last_trading_day(
                [(d, v[1]) for d, v in agg_map.items()], date.today()
            )
            lt_full = last_trading_day(
                [(d, v[1]) for d, v in per.items()], date.today()
            )
            print(
                f"  last_trading_day: agg={lt_agg} full={lt_full} "
                f"{'OK' if lt_agg == lt_full else 'MISMATCH'}"
            )
    finally:
        conn.close()


def check_names():
    conn = connect()
    try:
        _, rows = fetch(conn, "SELECT ACCNUM, CUSTNAME FROM CUSTOMER")
    finally:
        conn.close()
    custs = [(str(a or "").strip(), str(n or "").strip()) for a, n in rows]
    custs = [(a, n) for a, n in custs if a]
    print(f"CUSTOMER rows: {len(custs)}")

    low = [(a, n) for a, n in custs if a != a.upper()]
    print(f"\nACCNUMs not fully uppercase: {len(low)}")
    for a, n in low[:10]:
        print(f"  {a!r}  {n!r}")

    # account codes that appear as a WORD in a DIFFERENT customer's name
    import re

    codes = {a for a, _ in custs}
    alpha_codes = {a for a in codes if a.isalpha() and len(a) >= 3}
    hits = []
    for a, n in custs:
        toks = set(re.sub(r"[^A-Z0-9 ]", " ", n.upper()).split())
        for c in alpha_codes & toks:
            if c != a:
                hits.append((c, a, n))
    print(
        f"\nalpha account codes appearing as a word in ANOTHER account's name: {len(hits)}"
    )
    for c, a, n in hits[:15]:
        code_owner = next(nn for aa, nn in custs if aa == c)
        print(f"  code {c!r} (owner: {code_owner!r}) is a word in {a!r} {n!r}")

    # families: same normalised name key on multiple accounts
    keyed = defaultdict(list)
    for a, n in custs:
        keyed[revenue._name_key(n)].append((a, n))
    dupes = {k: v for k, v in keyed.items() if len(v) > 1 and k}
    print(f"\nnormalised name keys shared by >1 account: {len(dupes)}")
    for k, v in list(dupes.items())[:10]:
        print(f"  {k!r}: {v}")

    # families by ACCNUM prefix where exact-name resolve would silently
    # drop siblings: sibling accounts (share >=3-char prefix with a shorter
    # code) whose name is NOT within 0.9 of the parent's
    from difflib import SequenceMatcher

    silent = []
    for a, n in custs:
        for b, m in custs:
            if b == a or len(b) <= len(a) or not b.startswith(a) or len(a) < 3:
                continue
            s = SequenceMatcher(
                None, revenue._name_key(n), revenue._name_key(m)
            ).ratio()
            qt = set(revenue._name_key(n).split())
            nt = set(revenue._name_key(m).split())
            subset = qt and qt <= nt
            if s < 0.9 and not subset:
                silent.append((a, n, b, m, round(s, 3)))
    print(
        f"\nACCNUM families where the sibling would NOT surface on the parent's exact name: {len(silent)}"
    )
    for row in silent[:20]:
        print(f"  {row}")

    # non-ascii / punctuation-heavy names
    odd = [(a, n) for a, n in custs if any(ord(ch) > 127 for ch in n)]
    print(f"\nnames with non-ASCII characters: {len(odd)}")
    for a, n in odd[:10]:
        print(f"  {a!r} {n!r}")


def check_receipts():
    conn = connect()
    try:
        _, r1 = fetch(
            conn,
            "SELECT COUNT(*) FROM RECEIPT WHERE RECEIPT < 0 AND ACCNUM <> UPPER(ACCNUM)",
        )
        _, r2 = fetch(
            conn,
            "SELECT COUNT(*) FROM RECEIPT r LEFT JOIN CUSTOMER c ON c.ACCNUM = r.ACCNUM WHERE r.RECEIPT < 0 AND c.ACCNUM IS NULL",
        )
        # fan-out check on the extraction joins: RECEIPT and WAYBILL PK-ness
        _, r3 = fetch(
            conn,
            "SELECT COUNT(*) FROM (SELECT RECEIPT FROM RECEIPT GROUP BY RECEIPT HAVING COUNT(*) > 1)",
        )
        _, r4 = fetch(
            conn,
            "SELECT COUNT(*) FROM (SELECT WAYBILL FROM WAYBILL GROUP BY WAYBILL HAVING COUNT(*) > 1)",
        )
        _, r5 = fetch(
            conn,
            "SELECT COUNT(*) FROM (SELECT USERCODE FROM VIEW_USERCODE GROUP BY USERCODE HAVING COUNT(*) > 1)",
        )
    finally:
        conn.close()
    print(f"negative receipts with non-uppercase ACCNUM: {r1[0][0]}")
    print(f"negative receipts whose ACCNUM has no CUSTOMER row: {r2[0][0]}")
    print(f"duplicate RECEIPT numbers: {r3[0][0]}")
    print(f"duplicate WAYBILL numbers: {r4[0][0]}")
    print(f"duplicate VIEW_USERCODE.USERCODE: {r5[0][0]}")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("parity", "all"):
        check_parity()
    if which in ("names", "all"):
        check_names()
    if which in ("receipts", "all"):
        check_receipts()
