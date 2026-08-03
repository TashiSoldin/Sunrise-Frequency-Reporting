"""Tab colours and frozen headers.

Larry's reference workbooks colour-code their tabs by section and freeze the
row below each block of column headings. The Phase 0 replication reproduced
the cell formatting but dropped both, and nobody noticed for a month — the
reconciliation compared values, not sheet properties.

The tab strip is how people navigate these workbooks. Mistaking it is what
started the "July missing" report, so this is wayfinding rather than polish.
"""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILDERS = REPO / "revenue_reports"
sys.path.insert(0, str(BUILDERS))

from style import NAVY, ORANGE, RED, TAB_BILLING, TAB_CREDIT, TAB_DAILY, TAB_SUMMARY, YELLOW  # noqa: E402

# Read straight off Larry's reference of 28 Jul 2026 (dashboard) and 24 Jul
# (billing detail), via openpyxl's sheet_properties.tabColor.
REFERENCE_COLOURS = {
    "summary": "05003C",
    "billing": "FF6900",
    "daily": "FAB414",
    "credit": "D00000",
}

# Builders whose worksheets are colour-coded in the reference. Unbilled is
# excluded — none of Larry's five unbilled references carries a tab colour.
#
# The flash belongs here, though its obsolete 23 Jul reference has no colour:
# Larry redesigned that report on 24 Jul, and the current shape (24 and 27 Jul,
# which our builder replicates) has an orange tab. Always check the newest
# reference — comparing against the superseded one produced a wrong conclusion.
COLOURED = ["build_dashboard.py", "build_billing_detail.py", "build_flash.py"]


class TestColoursMatchTheReference:
    @pytest.mark.parametrize("const, key", [
        (TAB_SUMMARY, "summary"), (TAB_BILLING, "billing"),
        (TAB_DAILY, "daily"), (TAB_CREDIT, "credit"),
    ])
    def test_hex_matches(self, const, key):
        assert const.lstrip("#").upper() == REFERENCE_COLOURS[key]

    def test_reuses_the_brand_palette(self):
        """Tab colours are the existing brand constants, not new literals."""
        assert (TAB_SUMMARY, TAB_BILLING, TAB_DAILY, TAB_CREDIT) == (NAVY, ORANGE, YELLOW, RED)


class TestEveryWorksheetIsColoured:
    """Counted rather than positional — a new tab added without a colour fails."""

    @pytest.mark.parametrize("name", COLOURED)
    def test_colour_per_worksheet(self, name):
        src = (BUILDERS / name).read_text()
        sheets = len(re.findall(r"\.add_worksheet\(", src))
        coloured = len(re.findall(r"\.set_tab_color\(", src))
        assert coloured == sheets, (
            f"{name}: {sheets} worksheets, {coloured} tab colours. Every tab in this "
            f"workbook is colour-coded in Larry's reference."
        )


class TestFreezeBelow:
    def test_freezes_the_row_under_the_headings(self):
        """freeze_below(ws, 28) must produce B29 — headings visible, detail scrolls."""
        calls = []

        class FakeSheet:
            def freeze_panes(self, row, col):
                calls.append((row, col))

        from style import freeze_below
        freeze_below(FakeSheet(), 28)
        assert calls == [(28, 1)]        # xlsxwriter is 0-indexed: row 28 = B29

    def test_column_override_for_sheets_with_no_spacer(self):
        calls = []

        class FakeSheet:
            def freeze_panes(self, row, col):
                calls.append((row, col))

        from style import freeze_below
        freeze_below(FakeSheet(), 1, col=0)
        assert calls == [(1, 0)]         # A2, as the unbilled reference has
