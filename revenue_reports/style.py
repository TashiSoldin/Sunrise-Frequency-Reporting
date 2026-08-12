"""Shared Sunrise brand styling for xlsxwriter report builders."""

NAVY = "#05003C"
NAVY2 = "#0A0050"
ORANGE = "#FF6900"
YELLOW = "#FAB414"
RED = "#D00000"
GREEN = "#1E7B34"      # favourable variance, per the flash-comparison reference
RED_LIGHT = "#FCE4E4"
ALT = "#F0F0F8"
BLUE = "#0000FF"

NUM = "#,##0"
NUMP = "#,##0;(#,##0)"   # negatives in parentheses, per the reference
NUM1 = "#,##0.0"
NUM2 = "#,##0.00;(#,##0.00)"
DEC2 = "0.00"
PCT1 = "0.0%;(0.0%)"
PCT_SIGNED = "+0.0%;(0.0%)"   # variance percentages carry an explicit sign


GRID = "#D9D9D9"  # thin grid the reference draws round every populated cell


class Styles:
    """Format cache so we don't create duplicate formats.

    Two defaults, both read off the reference workbooks: a thin grey box
    border on every cell, and vertical centring — the latter only shows once
    rows are taller than default, which is why it went unnoticed alongside the
    missing row heights.

    Pass border=0 for the title block, section headers and footnotes, which the
    reference leaves unbordered.
    """

    def __init__(self, wb):
        self.wb = wb
        self._cache = {}

    def get(self, **kw):
        key = tuple(sorted(kw.items()))
        if key not in self._cache:
            base = {"font_name": "Calibri", "valign": "vcenter",
                    "border": 1, "border_color": GRID}
            base.update(kw)
            if not base.get("border"):
                base.pop("border_color", None)
            self._cache[key] = self.wb.add_format(base)
        return self._cache[key]


# Tab colours, from Larry's reference workbook of 28 Jul 2026. The dashboard
# colour-codes its tabs by section — the tab strip is how people navigate the
# workbook, so this is wayfinding rather than decoration.
TAB_SUMMARY = NAVY      # YTD Revenue vs PY
TAB_BILLING = ORANGE    # month tabs, YTD, MTD Billing by Customer
TAB_DAILY = YELLOW      # Daily — Invoice date / Waybill date
TAB_CREDIT = RED        # MTD Credit Notes


# Row heights read off the reference workbooks. The title block (rows 2-5) is
# set by title_block(); these cover the header bands below it, which otherwise
# fall back to Excel's default 15 and render noticeably tighter than Larry's.
H_TAB1 = {7: 6, 8: 16, 9: 22, 10: 8, 12: 17, 13: 24}
H_CUSTOMER = {9: 15, 10: 18, 11: 10, 13: 18, 14: 24, 28: 24}
H_DAILY = {9: 14, 10: 18, 14: 24}
H_CREDIT = {7: 14, 8: 18, 11: 18}          # detail section rows set separately
H_BILLING = {7: 21.9}
H_BILLING_LATE = {9: 20.1}                 # credit-notes sub-tab, headings sit lower
H_FOOTNOTE = 13


def ordinal(day: int) -> str:
    """1 -> "1st", 3 -> "3rd", 11 -> "11th", 22 -> "22nd".

    Two report footnotes built the suffix as a bare "th" and read "the 3th" and
    "(to 31th)". Larry reads both daily. The teens are the case a naive
    last-digit rule gets wrong, so they are special-cased first.
    """
    if 11 <= day % 100 <= 13:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


def set_rows(ws, heights: dict):
    """Apply a {1-indexed row: height} map."""
    for row, h in heights.items():
        ws.set_row(row - 1, h)


def freeze_below(ws, header_row: int, col: int = 1):
    """Freeze everything above a header row, and the spacer column to its left.

    header_row is 1-indexed, matching the row the column headings sit on, so
    the headings stay visible once the detail scrolls. Larry's reference froze
    the customer tabs at B29, the daily tabs at B15 and credit notes at B41 —
    in each case the row directly below the headings.
    """
    ws.freeze_panes(header_row, col)


def title_block(ws, styles, last_col: str, brand_text: str, title: str, subtitle: str):
    """Rows 2-5: brand bar, title, subtitle, orange accent (1-indexed rows)."""
    ws.set_row(1, 24)
    ws.set_row(2, 30)
    ws.set_row(3, 16)
    ws.set_row(4, 4)
    ws.merge_range(f"B2:{last_col}2", brand_text,
                   styles.get(bold=True, font_size=13, font_color=YELLOW, bg_color=NAVY, border=0))
    ws.merge_range(f"B3:{last_col}3", title,
                   styles.get(bold=True, font_size=16, font_color="white", bg_color=NAVY, border=0))
    ws.merge_range(f"B4:{last_col}4", subtitle,
                   styles.get(font_size=9, font_color="white", bg_color=NAVY2, border=0))
    ws.merge_range(f"B5:{last_col}5", "", styles.get(bg_color=ORANGE, border=0))
