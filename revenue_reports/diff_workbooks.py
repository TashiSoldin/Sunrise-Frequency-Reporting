"""Cell-by-cell diff of two workbooks (values + formulas), for Phase 0 reconciliation.

Usage: python diff_workbooks.py built.xlsx reference.xlsx [--tol 0.5] [--max-print 40]
Numeric mismatches within --drift-pct (default 1%) are classed as drift (live-DB).
"""

import argparse
from collections import Counter, defaultdict

import openpyxl


def cells(path):
    wb = openpyxl.load_workbook(path)
    out = {}
    for ws in wb.worksheets:
        d = {}
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    d[c.coordinate] = c.value
        out[ws.title] = d
    return out


def classify(a, b, tol, drift_pct):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(a - b) <= tol:
            return "match"
        if b and abs(a - b) / abs(b) <= drift_pct:
            return "drift"
        return "num_mismatch"
    if isinstance(a, str) and isinstance(b, str):
        if a == b:
            return "match"
        if a.replace(" ", "") == b.replace(" ", ""):
            return "ws_only"
        return "str_mismatch"
    return "type_mismatch"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("built")
    ap.add_argument("ref")
    ap.add_argument("--tol", type=float, default=0.5)
    ap.add_argument("--drift-pct", type=float, default=0.01)
    ap.add_argument("--max-print", type=int, default=40)
    ap.add_argument("--sheet", default=None)
    a = ap.parse_args()

    A, B = cells(a.built), cells(a.ref)
    sheets = [s for s in B if a.sheet is None or s == a.sheet]
    missing_sheets = [s for s in sheets if s not in A]
    if missing_sheets:
        print("MISSING SHEETS in built:", missing_sheets)
    grand = Counter()
    for s in sheets:
        if s not in A:
            continue
        av, bv = A[s], B[s]
        counts = Counter()
        samples = defaultdict(list)
        for k in sorted(set(av) | set(bv), key=lambda x: (len(x), x)):
            x, y = av.get(k), bv.get(k)
            if x is None:
                counts["only_in_ref"] += 1
                samples["only_in_ref"].append((k, y))
            elif y is None:
                counts["only_in_built"] += 1
                samples["only_in_built"].append((k, x))
            else:
                cl = classify(x, y, a.tol, a.drift_pct)
                counts[cl] += 1
                if cl != "match":
                    samples[cl].append((k, x, y))
        grand.update({f"{k}": v for k, v in counts.items()})
        bad = sum(v for k, v in counts.items() if k != "match")
        print(f"\n=== {s}: {counts['match']} match, {bad} diffs -> {dict(counts)}")
        for cl, items in samples.items():
            for it in items[: a.max_print // max(1, len(samples))]:
                print("   ", cl, *[repr(v)[:70] for v in it])
    print("\nGRAND:", dict(grand))


if __name__ == "__main__":
    main()
