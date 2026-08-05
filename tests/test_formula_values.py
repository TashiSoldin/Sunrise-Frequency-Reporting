"""Every formula written must carry its computed result.

XlsxWriter caches 0 in formula cells unless told otherwise. Desktop Excel
recalculates on load and hides it; Excel for the web, the SharePoint preview,
the mobile apps, Numbers and Sheets do not. That is the defect behind "no
stats under each month for each BDE".

The reconciliation harness could not have caught it: diff_workbooks.py calls
openpyxl.load_workbook() without data_only=True, so it compares formula
strings and two files with identical formulas and different cached values look
the same. These tests check the values instead.
"""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILDERS = REPO / "revenue_reports"
sys.path.insert(0, str(BUILDERS))

from xlsxvalues import MissingFormulaValue, Vals, div, ratio_less_1, sub

BUILDER_FILES = sorted(BUILDERS.glob("build_*.py"))


class TestNoBareFormulaWrites:
    """The wrapper is only useful if nothing bypasses it."""

    @pytest.mark.parametrize("path", BUILDER_FILES, ids=lambda p: p.name)
    def test_no_direct_write_formula(self, path):
        hits = [f"{path.name}:{i}" for i, ln in enumerate(path.read_text().splitlines(), 1)
                if ".write_formula(" in ln]
        assert not hits, (
            f"write_formula called directly in {hits}. Use Vals.f(), which requires "
            f"value=, or the cell will cache 0 and read as 0 outside desktop Excel."
        )

    @pytest.mark.parametrize("path", BUILDER_FILES, ids=lambda p: p.name)
    def test_no_formula_smuggled_through_merge_range(self, path):
        """merge_range auto-detects a leading '=' and writes a 0-cached formula."""
        pattern = re.compile(r'merge_range\([^)]*?["\']=')
        hits = [f"{path.name}:{i}" for i, ln in enumerate(path.read_text().splitlines(), 1)
                if pattern.search(ln)]
        assert not hits, (
            f"merge_range given a formula in {hits}. Use Vals.mf(), which merges "
            f"blank and then writes the formula with its value."
        )


class TestWrapper:
    def test_rejects_a_missing_value(self):
        with pytest.raises(MissingFormulaValue):
            Vals(_FakeSheet()).f(0, 0, "=A1")

    def test_accepts_zero_and_empty_string(self):
        """0 and "" are legitimate results — only None means "not supplied"."""
        ws = _FakeSheet()
        Vals(ws).f(0, 0, "=A1", None, value=0)
        Vals(ws).f(1, 0, '=IF(A1=0,"",A1)', None, value="")
        assert [w[3] for w in ws.formulas] == [0, ""]


class TestGuardMirrors:
    """The helpers must return exactly what the Excel guard returns."""

    def test_div_blanks_on_zero_denominator(self):
        assert div(10, 0) == ""          # =IF(b=0,"",a/b)
        assert div(10, 4) == 2.5

    def test_ratio_less_1_blanks_on_zero_denominator(self):
        assert ratio_less_1(10, 0) == ""
        assert ratio_less_1(10, 4) == 1.5

    def test_sub_blanks_on_zero_guard(self):
        assert sub(10, 0) == ""          # =IF(F=0,"",J-F)
        assert sub(10, 4) == 6
        assert sub(10, 4, guard=0) == ""

    def test_blank_is_not_zero(self):
        """The distinction that matters: 0 renders as 0.0%, "" renders empty."""
        assert div(1, 0) != 0


class _FakeSheet:
    def __init__(self):
        self.formulas = []

    def write_formula(self, row, col, formula, fmt=None, value=None):
        self.formulas.append((row, col, formula, value))

    def merge_range(self, *a, **k):
        pass
