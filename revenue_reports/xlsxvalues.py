"""Formula writes that carry their own answer.

XlsxWriter cannot evaluate formulas, so `write_formula` caches a placeholder of
0 in every cell it writes. Desktop Excel recalculates on load and hides this
(the workbook sets fullCalcOnLoad), but Excel for the web, the SharePoint
preview pane, the mobile apps, Numbers and Google Sheets all render the cached
value — so every derived cell in the report reads 0.

That is what "no stats under each month for each BDE" was: 23,236 formula cells
each caching 0, next to hard-written source cells that looked fine.

The fix is to pass `value=` on every formula write. This module makes that
mandatory rather than optional: `Vals.f()` raises if the caller omits it, and
`check_all_formulas_have_values()` (used by the test suite) asserts no bare
`write_formula` survives in the builders.

Note `blank`: formulas guarded as `=IF(X=0,"",...)` evaluate to an empty
string, not to zero. The cached value has to match, or the file shows 0.0%
where Excel would show nothing.
"""

BLANK = ""  # what =IF(cond,"",...) evaluates to when the guard trips


class MissingFormulaValue(Exception):
    """Raised when a formula is written without its computed result."""


class Vals:
    """Wraps an xlsxwriter worksheet so formulas must carry a cached value.

    Only the formula-writing calls go through here; plain `ws.write(...)` for
    literals is unchanged and still used directly.
    """

    __slots__ = ("ws",)

    def __init__(self, ws):
        self.ws = ws

    def f(self, row, col, formula, fmt=None, value=None):
        """write_formula, but `value` is required.

        `value` may legitimately be 0 or "" — only None is rejected, which is
        why this is an explicit sentinel check rather than a truthiness test.
        """
        if value is None:
            raise MissingFormulaValue(
                f"formula {formula!r} at r{row}c{col} written without a cached "
                f"value; pass value= so it renders outside desktop Excel"
            )
        self.ws.write_formula(row, col, formula, fmt, value)

    def mf(self, cell_range, formula, fmt=None, value=None):
        """Merged formula cell.

        merge_range() has no `value` parameter and would auto-detect the
        leading '=' and write a 0-cached formula, so merge blank first and then
        write the formula over the top-left cell.
        """
        if value is None:
            raise MissingFormulaValue(
                f"merged formula {formula!r} at {cell_range} written without a "
                f"cached value; pass value= so it renders outside desktop Excel"
            )
        self.ws.merge_range(cell_range, "", fmt)
        first = cell_range.split(":")[0]
        col = 0
        i = 0
        while i < len(first) and first[i].isalpha():
            col = col * 26 + (ord(first[i].upper()) - 64)
            i += 1
        self.ws.write_formula(int(first[i:]) - 1, col - 1, formula, fmt, value)

    def __getattr__(self, name):
        # everything else (write, merge_range, set_column, ...) passes through
        return getattr(self.ws, name)


def div(a, b, blank=BLANK):
    """Mirror of =IF(b=0,"",a/b)."""
    return blank if not b else a / b


def ratio_less_1(a, b, blank=BLANK):
    """Mirror of =IF(b=0,"",a/b-1)."""
    return blank if not b else a / b - 1


def sub(a, b, blank=BLANK, guard=None):
    """Mirror of =IF(guard=0,"",a-b); guard defaults to b."""
    g = b if guard is None else guard
    return blank if not g else a - b
