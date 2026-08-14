"""The lifted export transform must equal a write/read round trip.

Day 3 of the DB query interface lifts the row-building loop out of write_xlsx
(export_rows / export_shaped) so a live query can feed the report builders
without producing an export file first. The contract is exact equivalence:
export_shaped(db_cols, rows) must return cell-for-cell what load_export reads
back from a file that write_xlsx wrote from the same rows — because every
report figure was reconciled against Parcel Perfect through that file path,
and the injected path inherits that verification only if the shapes match.
"""

import sys
from datetime import date, time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "revenue_reports"))

from extract_revenue import (
    CREDITS_HEADERS,
    DB_COLS,
    EXPORT_HEADERS,
    credits_shaped,
    export_rows,
    export_shaped,
    extraction_sql,
    totals_row,
    write_credits_xlsx,
    write_xlsx,
)

from data import load_credit_sheet, load_export

# fetch() returns cursor-description order: the SELECT lists DB_COLS then the
# two join aliases.
FETCH_COLS = [*DB_COLS, "RECEIPT_USERNAME", "WB_TOTSURCHARGE"]


def db_row(**fields) -> tuple:
    """A raw DB row: None everywhere except the named columns."""
    ix = {c: i for i, c in enumerate(FETCH_COLS)}
    row = [None] * len(FETCH_COLS)
    for k, v in fields.items():
        row[ix[k]] = v
    return tuple(row)


ROWS = [
    db_row(
        WAYBILL="SLJNB100001",
        WAYDATE=date(2026, 8, 12),
        SERVICE="ON",
        CUSTNAME="Tommy PDY Limited",
        ACCNUM="TOM001",
        ORIGHUB="JNB",
        PIECES=5,
        ACTKG=Decimal("12.40"),
        CHARGEMASS=Decimal("20.00"),
        SUBTOTAL=Decimal("150.55"),
        STATUS="Invoiced",
        REP="TF",
        REPNAME="Tommy Fields",
        INPUTMETHOD="1",
        COLSTATUS="C",
        INSURANCEFLAG="Y",
        PODCAPTURETIME=time(9, 30, 15, 123456),
    ),
    # Consolidation child: Invoiced, zero subtotal, chargeable service,
    # external account -> Consolidated must derive "Yes".
    db_row(
        WAYBILL="SLJNB100002",
        WAYDATE=date(2026, 8, 12),
        SERVICE="ON",
        CUSTNAME="Tommy PDY Limited",
        ACCNUM="TOM001",
        ORIGHUB="JNB",
        PIECES=1,
        CHARGEMASS=Decimal("0.00"),
        SUBTOTAL=Decimal("0.00"),
        STATUS="Invoiced",
    ),
    # No-charge service at zero: NOT a consolidation. Blank customs group
    # default-fills to "Documents" on every row.
    db_row(
        WAYBILL="SLJNB100003",
        WAYDATE=date(2026, 8, 13),
        SERVICE="NCH",
        CUSTNAME="Sunrise Internal",
        ACCNUM="000",
        SUBTOTAL=Decimal("0.00"),
        CHARGEMASS=Decimal("0.00"),
        STATUS="Invoiced",
        CUSTOMSGROUP="Freight",
    ),
]


class TestDerivedFields:
    def test_r_per_kg_customs_group_and_consolidated(self):
        out = export_rows(FETCH_COLS, ROWS)
        ix = {h: i for i, h in enumerate(EXPORT_HEADERS)}
        assert out[0][ix["Avg R per kg"]] == round(150.55 / 20.00, 2)
        assert out[1][ix["Avg R per kg"]] is None  # zero mass -> blank
        assert out[0][ix["Customs Group"]] == "Documents"  # default fill
        assert out[2][ix["Customs Group"]] == "Freight"
        assert out[0][ix["Consolidated"]] == "No"
        assert out[1][ix["Consolidated"]] == "Yes"
        assert out[2][ix["Consolidated"]] == "No"  # no-charge service

    def test_value_maps_bools_and_time_truncation(self):
        out = export_rows(FETCH_COLS, ROWS)
        ix = {h: i for i, h in enumerate(EXPORT_HEADERS)}
        assert out[0][ix["Waybill Input Method"]] == "PPOnline"
        assert out[0][ix["Collect Status"]] == "Collected"
        assert out[0][ix["Insurance"]] is True
        assert out[0][ix["POD Capture Time"]] == time(9, 30, 15)


class TestRoundTrip:
    """export_shaped == write_xlsx -> load_export, cell for cell."""

    def test_shaped_rows_match_a_written_file(self, tmp_path):
        path = str(tmp_path / "roundtrip.xlsx")
        write_xlsx(path, FETCH_COLS, ROWS)
        f_headers, f_rows = load_export(path)
        s_headers, s_rows = export_shaped(FETCH_COLS, ROWS)

        assert f_headers == s_headers == EXPORT_HEADERS
        assert len(f_rows) == len(s_rows) + 1  # file carries the totals row
        for i, (f_row, s_row) in enumerate(zip(f_rows, s_rows)):
            for h, fv, sv in zip(EXPORT_HEADERS, f_row, s_row):
                assert fv == sv, f"row {i}, column {h!r}: file {fv!r} != shaped {sv!r}"

    def test_totals_row_matches_the_written_file(self, tmp_path):
        path = str(tmp_path / "totals.xlsx")
        write_xlsx(path, FETCH_COLS, ROWS)
        _, f_rows = load_export(path)
        expected = totals_row(export_rows(FETCH_COLS, ROWS))
        for h, fv, ev in zip(EXPORT_HEADERS, f_rows[-1], expected):
            ev = "" if ev is None else ev  # blanks read back as ''
            assert fv == ev, f"totals column {h!r}: file {fv!r} != computed {ev!r}"


# --- credits ----------------------------------------------------------------

CREDIT_COLS = [
    "RECEIPT",
    "ACCNUM",
    "CUSTNAME",
    "RECDATE",
    "AMOUNT",
    "DISCOUNT",
    "REFERENCE",
    "RECTYPE",
    "REASON",
    "ALLOCATED",
    "COMMENT",
    "AIF",
    "USERNAME",
    "EXPORT",
    "VAT",
    "VATTYPE",
    "BRANCHNAME",
    "BANK",
    "CUSTOMSVAT",
    "CUSTOMSDUTIES",
    "REPNAME",
    "COSTCNTRNAME",
    "CREDCONTROLLER",
]


def credit_row(**fields) -> tuple:
    ix = {c: i for i, c in enumerate(CREDIT_COLS)}
    row = [None] * len(CREDIT_COLS)
    for k, v in fields.items():
        row[ix[k]] = v
    return tuple(row)


CREDIT_ROWS = [
    credit_row(
        RECEIPT=-1001,
        ACCNUM="TOM001",
        CUSTNAME="Tommy PDY Limited",
        RECDATE=date(2026, 8, 5),
        AMOUNT=Decimal("-115.00"),
        VAT=Decimal("-15.00"),
        RECTYPE="N",
        REASON="Rate query",
        ALLOCATED=Decimal("-115.00"),
        USERNAME="MARI",
    ),
    credit_row(
        RECEIPT=-1002,
        ACCNUM="ABC002",
        CUSTNAME="ABC Freight",
        RECDATE=date(2026, 8, 6),
        AMOUNT=Decimal("-57.50"),
        VAT=Decimal("-7.50"),
        RECTYPE="J",
    ),
]


class TestCreditsRoundTrip:
    def test_shaped_rows_match_a_written_file(self, tmp_path):
        path = str(tmp_path / "credits.xlsx")
        write_credits_xlsx(path, CREDIT_COLS, CREDIT_ROWS)
        f_headers, f_rows = load_credit_sheet(path)
        s_headers, s_rows = credits_shaped(CREDIT_COLS, CREDIT_ROWS)

        assert f_headers == s_headers == CREDITS_HEADERS
        # load_credit_sheet drops the totals row (non-negative Receipt)
        assert len(f_rows) == len(s_rows)
        for i, (f_row, s_row) in enumerate(zip(f_rows, s_rows)):
            for h, fv, sv in zip(CREDITS_HEADERS, f_row, s_row):
                assert fv == sv, f"row {i}, column {h!r}: file {fv!r} != shaped {sv!r}"

    def test_rectype_maps_to_display_names(self):
        _, rows = credits_shaped(CREDIT_COLS, CREDIT_ROWS)
        ti = CREDITS_HEADERS.index("Type")
        assert [r[ti] for r in rows] == ["Credit Note", "Journal Credit"]


# --- extraction_sql parameterisation ----------------------------------------


class TestExtractionSqlFilters:
    START = date(2026, 3, 1)

    def test_account_filter_is_bound_never_interpolated(self):
        hostile = "X'; DELETE FROM WAYBILL; --"
        sql, params = extraction_sql("inv", self.START, account=hostile)
        assert hostile not in sql
        assert "wba.ACCNUM = ?" in sql
        assert params == [self.START, date(2027, 3, 1), hostile]

    def test_period_filters_bound_the_basis_column(self):
        sql, params = extraction_sql(
            "inv",
            self.START,
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31),
        )
        assert sql.count("wba.INVDATE >= ?") == 2  # FY floor + period floor
        assert "wba.INVDATE <= ?" in sql
        assert params == [
            self.START,
            date(2027, 3, 1),
            date(2026, 7, 1),
            date(2026, 7, 31),
        ]

    def test_wb_basis_filters_the_waybill_date(self):
        sql, params = extraction_sql("wb", self.START, date_from=date(2026, 8, 13))
        assert "wba.WAYDATE >= ?" in sql
        assert "INVDATE" not in sql.split("WHERE")[1]  # filters hit WAYDATE only
        assert params == [self.START, date(2027, 3, 1), date(2026, 8, 13)]

    def test_no_values_are_interpolated_into_the_sql(self):
        sql, _ = extraction_sql(
            "wb",
            self.START,
            account="TOM001",
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31),
        )
        assert "2026" not in sql
        assert "TOM001" not in sql
        assert "DATE '" not in sql


# --- builder injection --------------------------------------------------------


class TestBuilderInjection:
    """build(data=...) must produce the identical workbook to build from the
    file written from the same rows — the injected path inherits the file
    path's verification only if the outputs are indistinguishable."""

    def test_flash_from_injected_rows_equals_flash_from_file(self, tmp_path):
        import openpyxl
        from build_flash import build

        export = str(tmp_path / "WB Date - test.xlsx")
        write_xlsx(export, FETCH_COLS, ROWS)
        day = date(2026, 8, 12)

        out_file = tmp_path / "from_file"
        out_data = tmp_path / "from_data"
        out_file.mkdir()
        out_data.mkdir()
        a = build(day, export, str(out_file))
        b = build(day, None, str(out_data), data=export_shaped(FETCH_COLS, ROWS))

        wa, wb_ = openpyxl.load_workbook(a), openpyxl.load_workbook(b)
        assert wa.sheetnames == wb_.sheetnames
        for name in wa.sheetnames:
            sa, sb = wa[name], wb_[name]
            cells_a = {c.coordinate: c.value for row in sa.iter_rows() for c in row}
            cells_b = {c.coordinate: c.value for row in sb.iter_rows() for c in row}
            assert cells_a == cells_b, f"sheet {name!r} differs"
