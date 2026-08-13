"""waybill_status shaping and lookup logic — no database, the query runner is
injected. The rule under test: not-found is explicit, tilde variants are
surfaced, multiple matches are never reduced to one, and the SQL is a single
parameterised SELECT that passes the guard."""

import datetime
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mcp_server.sql_guard import assert_select_only
from mcp_server.waybill import (
    _COLUMNS,
    _SQL,
    MAX_MATCHES,
    WaybillInputError,
    lookup_waybill,
)


def _row(waybill="SLX123456", **overrides):
    values = {
        "WAYBILL": waybill,
        "STATUS": "POD Details Captured",
        "EVENTNAME": "POD Details Captured",
        "LASTEVENTHUB": "JNB",
        "LASTEVENTDATE": datetime.date(2026, 8, 12),
        "LASTEVENTTIME": "14:32",
        "PODRECIPIENT": "B NDLOVU",
        "PODDATE": datetime.date(2026, 8, 12),
        "PODTIME": "14:30",
        "PODCAPTUREDATE": datetime.date(2026, 8, 12),
        "PODCAPTURETIME": "14:35:00",
        "PODDISCREPANCY": None,
        "PODIMGPRESENT": "Y",
        "PODDETAILS": None,
        "DELIVERYAGENT": "JNB LOCAL",
        "SERVICE": "ONX",
        "ORIGPERS": "SENDER CO",
        "ORIGHUB": "CPT",
        "ORIGTOWN": "CAPE TOWN",
        "DESTPERS": "RECEIVER CO",
        "DESTHUB": "JNB",
        "DESTTOWN": "SANDTON  ",  # CHAR padding — must come back stripped
        "WAYDATE": datetime.date(2026, 8, 10),
        "DUEDATE": datetime.date(2026, 8, 12),
        "ACCNUM": "TOM001",
        "CUSTNAME": "TOMMY PDY LIMITED",
        "REFERENCE": "PO-9912",
        "PIECES": 3,
        "CHARGEMASS": Decimal("12.50"),
    }
    values.update(overrides)
    return tuple(values[c] for c in _COLUMNS)


def _runner(rows_by_param):
    """Fake run_select: rows keyed on the exact-match parameter."""
    calls = []

    def run(sql, params, max_rows):
        calls.append((sql, params, max_rows))
        return list(_COLUMNS), rows_by_param.get(params[0], [])

    run.calls = calls
    return run


def test_sql_is_a_single_guarded_parameterised_select():
    assert assert_select_only(_SQL) == _SQL
    assert _SQL.count("?") == 2
    assert "STARTING WITH" in _SQL


def test_not_found_is_explicit():
    answer = lookup_waybill("SLX000000", run=_runner({}))
    assert answer["found"] is False
    assert answer["matches"] == []
    assert "NOT FOUND" in answer["message"]
    # the message must rule out the "no activity yet" misreading
    assert "not that the shipment has had no activity" in answer["message"]


def test_single_match_shape():
    run = _runner({"SLX123456": [_row()]})
    answer = lookup_waybill("slx123456", run=run)
    assert answer["found"] is True
    assert answer["match_count"] == 1
    (m,) = answer["matches"]
    assert m["waybill"] == "SLX123456"
    assert m["is_tilde_variant"] is False
    assert m["status"] == "POD Details Captured"
    assert m["last_event"] == {
        "event": "POD Details Captured",
        "hub": "JNB",
        "date": "2026-08-12",
        "time": "14:32",
    }
    assert m["pod"]["recipient"] == "B NDLOVU"
    assert m["pod"]["image_present"] == "Y"
    assert m["route"]["destination_town"] == "SANDTON"  # padding stripped
    assert m["charge_mass"] == 12.5
    assert "message" not in answer


def test_tilde_lookup_parameter_and_variants_surfaced():
    run = _runner({"SLX123456": [_row("SLX123456~1"), _row("SLX123456")]})
    answer = lookup_waybill("SLX123456", run=run)
    # the second parameter drives the STARTING WITH '<no>~' variant match
    assert run.calls[0][1] == ("SLX123456", "SLX123456~")
    assert answer["match_count"] == 2
    # base waybill sorts first, tilde flagged, and the answer says so
    assert [m["waybill"] for m in answer["matches"]] == ["SLX123456", "SLX123456~1"]
    assert [m["is_tilde_variant"] for m in answer["matches"]] == [False, True]
    assert "do not silently pick one" in answer["message"]


def test_case_fallback_tries_as_typed_after_uppercase():
    run = _runner({"slx123456": [_row("slx123456")]})
    answer = lookup_waybill("slx123456", run=run)
    assert [c[1][0] for c in run.calls] == ["SLX123456", "slx123456"]
    assert answer["found"] is True


def test_uppercase_hit_does_not_query_twice():
    run = _runner({"SLX123456": [_row()]})
    lookup_waybill("SLX123456", run=run)
    assert len(run.calls) == 1


def test_cap_is_flagged_never_silent():
    rows = [_row(f"SLX123456~{i}") for i in range(MAX_MATCHES + 1)]
    answer = lookup_waybill("SLX123456", run=_runner({"SLX123456": rows}))
    assert answer["capped"] is True
    assert answer["match_count"] == MAX_MATCHES
    assert "flag it" in answer["message"]


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "SLX%", "*", "SLX?123", "x", "A" * 31, "WAY;BILL", "O'BRIEN’S"],
)
def test_bad_input_refused_before_any_query(bad):
    run = _runner({})
    with pytest.raises(WaybillInputError):
        lookup_waybill(bad, run=run)
    assert run.calls == []


def test_none_values_survive_shaping():
    row = _row(
        PODRECIPIENT=None,
        PODDATE=None,
        PODTIME=None,
        PODCAPTUREDATE=None,
        PODCAPTURETIME=None,
        PODIMGPRESENT=None,
        DELIVERYAGENT=None,
        EVENTNAME="Outbound Manifest Load",
        STATUS="Manifest",
    )
    answer = lookup_waybill("SLX123456", run=_runner({"SLX123456": [row]}))
    (m,) = answer["matches"]
    assert m["pod"]["date"] is None
    assert m["pod"]["recipient"] is None
    assert m["last_event"]["event"] == "Outbound Manifest Load"
