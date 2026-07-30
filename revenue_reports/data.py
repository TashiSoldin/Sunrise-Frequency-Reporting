"""Loaders for the Parcel Perfect revenue exports.

All readers return (headers, rows) and callers must resolve columns BY HEADER
NAME — export layouts drift over time (see PLAN.md / replication guide).
"""

from datetime import date, datetime, timedelta

from python_calamine import CalamineWorkbook


def load_export(path: str) -> tuple[list[str], list[list]]:
    """Read a WB/INV-date .xlsx export (large; calamine for speed)."""
    rows = (
        CalamineWorkbook.from_path(path)
        .get_sheet_by_index(0)
        .to_python(skip_empty_area=False)
    )
    headers = [str(h).strip() for h in rows[0]]
    return headers, rows[1:]


def col(headers: list[str], name: str) -> int:
    """Index of a column by exact header name; raises if missing."""
    try:
        return headers.index(name)
    except ValueError as e:
        raise KeyError(
            f"Column {name!r} not found in export — layout may have changed. "
            f"Available: {headers}"
        ) from e


def excel_serial_to_date(n: float) -> date:
    """Credit-notes .xls dates are Excel serials."""
    return (datetime(1899, 12, 30) + timedelta(days=n)).date()


def load_credit_sheet(path: str) -> tuple[list[str], list[list]]:
    """Read the credits export — the staff .xls (xlrd) or extract_revenue's
    .xlsx (calamine). Returns (headers, rows) with "Date" cells converted to
    datetime.date (None when missing/invalid). The trailing totals row
    (non-negative Receipt — real credits are negative receipt numbers) is
    dropped."""
    if path.lower().endswith(".xls"):
        import xlrd

        sh = xlrd.open_workbook(path).sheet_by_index(0)
        headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
        raw = [[sh.cell_value(i, c) for c in range(sh.ncols)]
               for i in range(1, sh.nrows)]
    else:
        from python_calamine import CalamineWorkbook

        rows = (CalamineWorkbook.from_path(path).get_sheet_by_index(0)
                .to_python(skip_empty_area=False))
        headers = [str(h).strip() for h in rows[0]]
        raw = [list(r) for r in rows[1:]]

    di, ri = headers.index("Date"), headers.index("Receipt")
    out = []
    for r in raw:
        try:
            rec = float(r[ri])
        except (TypeError, ValueError):
            rec = None
        if rec is None or rec >= 0:  # totals row / malformed
            continue
        v = r[di]
        if isinstance(v, datetime):
            v = v.date()
        elif isinstance(v, date):
            pass
        elif isinstance(v, (int, float)) and v:
            v = excel_serial_to_date(v)
        else:
            v = None
        r[di] = v
        out.append(r)
    return headers, out
