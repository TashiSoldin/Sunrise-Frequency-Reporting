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
