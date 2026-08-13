"""Firebird metadata nulls must not crash the schema survey.

This exists because of a defect that reached the BI server. `field_type_name`
originally interpolated the raw values, which printed NUMERIC(8.0,5) — cosmetic,
but a typo in a schema reference is a typo waiting to be copied into SQL. The
fix wrapped them in int() as `int(row["FPREC"] or 18)`, which is wrong in a way
that reads as obviously right: NaN is truthy, so the fallback never fires and
int(NaN) raises. It failed on the first live run, at section 2, having written
nothing.

The trap is that it only shows against real metadata. RDB$FIELD_PRECISION is
set for NUMERIC and DECIMAL and null for everything else, and pandas widens the
whole column to float to hold those nulls — so every CHAR, INTEGER and DATE row
arrives carrying NaN. A fixture of tidy integers passes and proves nothing,
which is why the fixture below is built the way pandas actually delivers them,
and why one test does nothing but check the fixture.
"""

import importlib
import math
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_module():
    """Import schema_survey without needing a database driver installed.

    It takes its connection helpers from research.revenue_extraction_test, which
    imports firebirdsql at module scope. These are tests of pure formatting
    logic and nothing below touches a database, so the helper is stubbed first.
    """
    stub = types.ModuleType("research.revenue_extraction_test")
    stub.connect = lambda: None
    stub.query_df = lambda *a, **k: None
    sys.modules.setdefault("research.revenue_extraction_test", stub)
    # moved from research/ in ff891e70 ("move to db query interface")
    return importlib.import_module("research.db_query_interface.schema_survey")


_survey = _load_module()
as_int = _survey.as_int
field_type_name = _survey.field_type_name


# A NUMERIC row, always present in the fixture frame. Without it every numeric
# column would be all-null, pandas would leave the dtype as object, and the
# missing values would arrive as None rather than NaN — which the broken code
# handled correctly. The first version of this fixture did exactly that, and the
# crash test passed against the code that had just crashed on the BI server.
_NUMERIC_ROW = {"FTYPE": 8, "FSUB": 1, "FLEN": 4, "FPREC": 15, "FSCALE": -2}


def row(ftype, sub=None, length=None, prec=None, scale=None):
    """One row as pandas actually hands it over: float columns carrying NaN.

    Built as a two-row frame so the numeric columns widen to float64 the way
    they do when read from RDB$FIELDS, where RDB$FIELD_PRECISION is set only
    for NUMERIC and DECIMAL and null for every other type.
    """
    frame = pd.DataFrame(
        [
            {
                "FTYPE": ftype,
                "FSUB": sub,
                "FLEN": length,
                "FPREC": prec,
                "FSCALE": scale,
            },
            _NUMERIC_ROW,
        ]
    )
    return frame.iloc[0]


def test_the_fixture_really_produces_nan():
    """Guard the guard. If this fails, every test below is testing nothing."""
    r = row(ftype=14, length=3)
    assert r["FPREC"] is not None
    assert isinstance(r["FPREC"], float)
    assert math.isnan(r["FPREC"]), f"expected NaN, got {r['FPREC']!r}"


class TestAsInt:
    def test_nan_falls_back_rather_than_raising(self):
        assert as_int(float("nan"), 18) == 18

    def test_none_falls_back(self):
        assert as_int(None, 18) == 18

    def test_a_float_from_pandas_becomes_an_int(self):
        assert as_int(8.0, 18) == 8

    def test_zero_is_kept_and_not_treated_as_missing(self):
        # The `or` form returned the fallback here too. A scale of 0 is meaningful.
        assert as_int(0.0, 18) == 0

    def test_negative_scale_survives(self):
        assert as_int(-2.0, 0) == -2

    def test_no_default_means_none(self):
        assert as_int(float("nan")) is None


class TestFieldTypeName:
    # Real shapes from the 6 Aug survey of the Parcel Perfect database.
    # (ftype, sub, length, prec, scale, expected)
    @pytest.mark.parametrize(
        ("ftype", "sub", "length", "prec", "scale", "expected"),
        [
            (37, 0, 40, None, 0, "VARCHAR(40)"),
            (14, 0, 3, None, 0, "CHAR(3)"),
            (8, 1, 4, 15, -2, "NUMERIC(15,2)"),
            (8, 0, 4, None, 0, "INTEGER"),
            (7, 0, 2, None, 0, "SMALLINT"),
            (12, 0, 4, None, 0, "DATE"),
            (13, 0, 4, None, 0, "TIME"),
            (35, 0, 8, None, 0, "TIMESTAMP"),
            (261, 1, 8, None, 0, "BLOB (text)"),
            (261, 0, 8, None, 0, "BLOB (binary)"),
        ],
    )
    def test_known_types(self, ftype, sub, length, prec, scale, expected):
        assert field_type_name(row(ftype, sub, length, prec, scale)) == expected

    def test_numeric_with_no_precision_of_its_own(self):
        # EVENT.LATITUDE and LONGITUDE: scale set, precision null. The crash.
        assert field_type_name(row(8, 1, 4, None, -5)) == "NUMERIC(18,5)"

    def test_every_null_metadata_field_at_once(self):
        # A CHAR column as pandas delivers it: precision, scale and sub all NaN.
        assert field_type_name(row(14, length=3)) == "CHAR(3)"

    def test_char_with_no_length_degrades_rather_than_crashing(self):
        assert field_type_name(row(14)) == "CHAR"

    def test_unknown_type_code_is_reported_not_swallowed(self):
        # A type this script has never seen should say so, so it gets noticed.
        assert field_type_name(row(999, scale=0)).startswith("type ")

    def test_no_rendered_type_contains_a_decimal_point(self):
        """The original symptom, stated as a rule rather than as cases."""
        for r in (
            row(8, 1, 4, 15, -2),
            row(8, 1, 4, None, -5),
            row(37, 0, 40, None, 0),
            row(14, length=3),
        ):
            rendered = field_type_name(r)
            assert "." not in rendered, rendered
