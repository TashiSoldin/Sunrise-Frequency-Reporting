"""Shared Sunrise brand styling for xlsxwriter report builders."""

NAVY = "#05003C"
NAVY2 = "#0A0050"
ORANGE = "#FF6900"
YELLOW = "#FAB414"
RED = "#D00000"
RED_LIGHT = "#FCE4E4"
ALT = "#F0F0F8"
BLUE = "#0000FF"

NUM = "#,##0"
NUM1 = "#,##0.0"
NUM2 = "#,##0.00;(#,##0.00)"
DEC2 = "0.00"
PCT1 = "0.0%;(0.0%)"


class Styles:
    """Format cache so we don't create duplicate formats."""

    def __init__(self, wb):
        self.wb = wb
        self._cache = {}

    def get(self, **kw):
        key = tuple(sorted(kw.items()))
        if key not in self._cache:
            base = {"font_name": "Calibri"}
            base.update(kw)
            self._cache[key] = self.wb.add_format(base)
        return self._cache[key]


def title_block(ws, styles, last_col: str, brand_text: str, title: str, subtitle: str):
    """Rows 2-5: brand bar, title, subtitle, orange accent (1-indexed rows)."""
    ws.set_row(1, 24)
    ws.set_row(2, 30)
    ws.set_row(3, 16)
    ws.set_row(4, 4)
    ws.merge_range(f"B2:{last_col}2", brand_text, styles.get(bold=True, font_size=13, font_color=YELLOW, bg_color=NAVY))
    ws.merge_range(f"B3:{last_col}3", title, styles.get(bold=True, font_size=16, font_color="white", bg_color=NAVY))
    ws.merge_range(f"B4:{last_col}4", subtitle, styles.get(font_size=9, font_color="white", bg_color=NAVY2))
    ws.merge_range(f"B5:{last_col}5", "", styles.get(bg_color=ORANGE))
