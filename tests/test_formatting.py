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

from style import (
    NAVY,
    ORANGE,
    RED,
    TAB_BILLING,
    TAB_CREDIT,
    TAB_DAILY,
    TAB_SUMMARY,
    YELLOW,
)

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
    @pytest.mark.parametrize(
        "const, key",
        [
            (TAB_SUMMARY, "summary"),
            (TAB_BILLING, "billing"),
            (TAB_DAILY, "daily"),
            (TAB_CREDIT, "credit"),
        ],
    )
    def test_hex_matches(self, const, key):
        assert const.lstrip("#").upper() == REFERENCE_COLOURS[key]

    def test_reuses_the_brand_palette(self):
        """Tab colours are the existing brand constants, not new literals."""
        assert (TAB_SUMMARY, TAB_BILLING, TAB_DAILY, TAB_CREDIT) == (
            NAVY,
            ORANGE,
            YELLOW,
            RED,
        )


class TestEveryWorksheetIsColoured:
    """Counted rather than positional — a new tab added without a colour fails."""

    @pytest.mark.parametrize("name", COLOURED)
    def test_colour_per_worksheet(self, name):
        src = (BUILDERS / name).read_text(encoding="utf-8")
        sheets = len(re.findall(r"\.add_worksheet\(", src))
        coloured = len(re.findall(r"\.set_tab_color\(", src))
        assert coloured == sheets, (
            f"{name}: {sheets} worksheets, {coloured} tab colours. Every tab in this "
            f"workbook is colour-coded in Larry's reference."
        )


class TestOrdinal:
    """Two footnotes Larry reads daily built the suffix as a bare "th" —
    the Flash Comparison's "waybills moved on the 3th" and the unbilled
    overview's "Jul 2026 (to 31th)". Teens are the case a naive last-digit
    rule gets wrong, so they are pinned alongside the ones that motivated it.
    """

    @pytest.mark.parametrize(
        "day, expected",
        [
            (1, "1st"),
            (2, "2nd"),
            (3, "3rd"),
            (4, "4th"),
            (11, "11th"),
            (12, "12th"),
            (13, "13th"),  # not 11st/12nd/13rd
            (21, "21st"),
            (22, "22nd"),
            (23, "23rd"),
            (30, "30th"),
            (31, "31st"),
        ],
    )
    def test_suffix(self, day, expected):
        from style import ordinal

        assert ordinal(day) == expected

    def test_every_day_of_a_month_is_covered(self):
        from style import ordinal

        for d in range(1, 32):
            assert ordinal(d).startswith(str(d)) and ordinal(d)[len(str(d)) :] in {
                "st",
                "nd",
                "rd",
                "th",
            }

    def test_no_builder_still_hand_rolls_the_suffix(self):
        """The two sites are fixed; this stops a third appearing."""
        offenders = [
            p.name
            for p in BUILDERS.glob("*.py")
            if re.search(r"\{[^}]*\.day[^}]*\}th", p.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"bare 'th' suffix in {offenders} — use style.ordinal()"


class TestFreezeBelow:
    def test_freezes_the_row_under_the_headings(self):
        """freeze_below(ws, 28) must produce B29 — headings visible, detail scrolls."""
        calls = []

        class FakeSheet:
            def freeze_panes(self, row, col):
                calls.append((row, col))

        from style import freeze_below

        freeze_below(FakeSheet(), 28)
        assert calls == [(28, 1)]  # xlsxwriter is 0-indexed: row 28 = B29

    def test_column_override_for_sheets_with_no_spacer(self):
        calls = []

        class FakeSheet:
            def freeze_panes(self, row, col):
                calls.append((row, col))

        from style import freeze_below

        freeze_below(FakeSheet(), 1, col=0)
        assert calls == [(1, 0)]  # A2, as the unbilled reference has
