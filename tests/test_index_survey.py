"""The index survey behind the second-index rule and the index-walk note
(Fable eighth review E1–E4, fix pass 23 Oct 2026).

open_query derives the INDEXED-COLUMN SET of each windowed table and join
partner from the "indices" section of schema_context.json (written by
research/db_query_interface/index_survey.py from RDB$INDICES live). Nothing
is typed by hand, so three things are pinned here:

  1. the sets AS FOUND on 23 Oct 2026 — a change to the survey file shows
     up as a diff in this test, not as a silent widening or narrowing;
  2. the derivation rules (first segment only; a view through its base
     field; a UNION column by name against the derived-table relations;
     expression and inactive indexes match nothing);
  3. the survey against the LIVE catalogue: every relation's indexes and
     segments, and both views' base-field mappings, re-read from RDB$ and
     compared whole, so a new index on the server fails the suite rather
     than opening a gap. Runs wherever .env names a DB_HOST (the BI server,
     where the suite runs); skipped only when there is no database to ask.
"""

import copy
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from mcp_server import open_query as oq
from mcp_server.open_query import (
    _indexed_columns,
    _neutral_spelling,
    check_open_query,
)

SURVEY_JSON = Path(oq.__file__).resolve().parent / "schema_context.json"


def survey() -> dict:
    return json.loads(SURVEY_JSON.read_text())["indices"]


# --- 1. the sets as found ---------------------------------------------------------

ROUTING_INDEXED = {
    "AGENT": ("ROUTING.RO_AGENTWAYBILL", "ROUTING.RO_AGNTAGNTDATE"),
    "AGENTDATE": ("ROUTING.RO_AGNTDATEAGENT",),
    "AWB": ("ROUTING.RO_AWB",),
    "BOOKDATE": ("ROUTING.RO_BOOKDATE",),
    "COSTSERV": ("ROUTING.RO_COSTSERV",),
    "EXPORT": ("ROUTING.RO_EXPORT",),
    "MANIFEST": ("ROUTING.RO_MANIFEST",),
    "PAYGROUP": ("ROUTING.RO_PAYGROUP",),
    "WAYBILL": ("ROUTING.RDB$PRIMARY51",),
}
VIEW_EVENTSCANS_INDEXED = {
    "ACCNUM": (
        "WAYBILL.WA_ACCCAPTUREDT",
        "WAYBILL.WA_ACCDT",
        "WAYBILL.WA_ACCIDATEWDATEWB",
        "WAYBILL.WA_ACCNUM",
    ),
    "AGENTNAME": ("AGENT.AG_NAME",),
    "AGTRACKNO": ("TRACK.TR_AGTRACKNO",),
    "EVENTDATE": ("EVENT.EV_EVENTDATE",),
    "MANIFEST": ("EVENT.EV_MANIFEST",),
    "ORIGHUB": ("WAYBILL.WA_ORDE",),
    "PODDATE": ("POD.PO_DATE",),
    "REFERENCE": ("WAYBILL.WA_REFERENCE",),
    "SERVICE": ("WAYBILL.WA_SEORDE", "WAYBILL.WA_SERVICE"),
    "TRACKNO": ("EVENT.EV_TRACKDATETIME", "EVENT.RDB$PRIMARY130", "TRACK.TR_TRACKNO"),
    "USERNAME": ("USERCODE.UC_NAME",),
    "WAYBILL": ("TRACK.RDB$PRIMARY62", "WAYBILL.RDB$PRIMARY13"),
    "WAYDATE": ("WAYBILL.WA_WAYDATE",),
}
VIEW_WBANALYSE_INDEXED = {
    "ACCNUM",
    "AGENTWAYBILL",
    "BOOKDATE",
    "COLLECT",
    "COLLECTIONAGENT",
    "COLLECTIONDATE",
    "COLSTATUS",
    "COSTCNTRNAME",
    "DELIVERYAGENT",
    "DESTAREANAME",
    "DESTTOWN",
    "DUEDATE",
    "INSURANCEDESCRIPTION",
    "INVDATE",
    "INVOICE",
    "LASTDELDATE",
    "LASTEVENTDATE",
    "ORIGAREANAME",
    "ORIGHUB",
    "ORIGTOWN",
    "PODBATCH",
    "PODCAPTUREDATE",
    "PODDATE",
    "PODGROUP",
    "QUOTEDATE",
    "RECEIPT",
    "REFERENCE",
    "REP",
    "REPNAME",
    "SERVICE",
    "WAYBILL",
    "WAYBILLORIG",
    "WAYDATE",
}


class TestTheSetsAsFound:
    def test_routing(self):
        assert _indexed_columns("ROUTING") == ROUTING_INDEXED

    def test_view_eventscans(self):
        assert _indexed_columns("VIEW_EVENTSCANS") == VIEW_EVENTSCANS_INDEXED

    def test_view_wbanalyse(self):
        assert set(_indexed_columns("VIEW_WBANALYSE")) == VIEW_WBANALYSE_INDEXED

    def test_the_partners_without_a_window(self):
        assert set(_indexed_columns("MANIFEST")) == {
            "AGENT",
            "AGENTDATE",
            "BRANCH",
            "DESTHUB",
            "EXPORT",
            "MANIFEST",
            "MAWBNO",
            "ORIGHUB",
            "PAYGROUP",
            "REFERENCE",
        }
        assert set(_indexed_columns("AGENTDRIVER")) == {
            "AGENT",
            "AGENTDRIVER",
            "FROMDATE",
            "ROUTE",
        }

    def test_a_table_outside_the_survey_has_no_set(self):
        assert _indexed_columns("HOLIDAY") == {}
        assert _indexed_columns("NOSUCH") == {}

    def test_the_neutral_spelling_follows_the_type(self):
        assert _neutral_spelling("ROUTING", "AGENT") == "+ 0"  # SMALLINT
        assert _neutral_spelling("ROUTING", "BOOKDATE") == "+ 0"  # DATE
        assert _neutral_spelling("ROUTING", "COSTSERV") == "|| ''"  # CHAR(4)
        assert _neutral_spelling("ROUTING", "WAYBILL") == "|| ''"  # VARCHAR(24)
        assert _neutral_spelling("VIEW_EVENTSCANS", "TRACKNO") == "|| ''"
        assert _neutral_spelling("VIEW_EVENTSCANS", "WAYDATE") == "+ 0"
        assert _neutral_spelling("ROUTING", "NOSUCH") is None


# --- 2. the derivation rules -------------------------------------------------------


class TestTheDerivation:
    def test_only_the_first_segment_counts(self):
        s = survey()["relations"]["ROUTING"]
        assert s["RDB$PRIMARY51"]["fields"] == ["WAYBILL", "LEG"]
        assert "LEG" not in _indexed_columns("ROUTING")
        assert s["RO_AGNTDATEAGENT"]["fields"] == ["AGENTDATE", "AGENT"]

    def test_expression_indexes_match_no_column(self):
        rels = survey()["relations"]
        expr = {
            (r, n) for r, idx in rels.items() for n, d in idx.items() if d["expression"]
        }
        assert expr == {
            ("CUSTOMER", "CU_UPPERACCNUM"),
            ("MANIFEST", "MA_UPPERMAWB"),
            ("WAYBILL", "WA_COALWAYORIG"),
            ("WAYBILL", "WA_UPPERREFERENCE"),
        }
        for r, n in expr:
            assert rels[r][n]["fields"] == []

    def test_a_union_column_resolves_by_name_against_the_derived_relations(self):
        v = survey()["views"]["VIEW_EVENTSCANS"]
        assert v["columns"]["TRACKNO"] is None and v["columns"]["HUB"] is None
        derived = {c["relation"] for c in v["contexts"].values() if c["derived"]}
        assert derived == {"EVENT", "TRACK", "WAYBILL"}
        assert "TRACKNO" in _indexed_columns("VIEW_EVENTSCANS")
        assert "HUB" not in _indexed_columns("VIEW_EVENTSCANS")  # 2nd PK segment
        assert "EVENTTIME" not in _indexed_columns("VIEW_EVENTSCANS")  # 3rd segment

    def test_a_view_column_resolves_through_its_base_field(self):
        v = survey()["views"]["VIEW_EVENTSCANS"]
        assert v["columns"]["ACCNUM"] == {"relation": "WAYBILL", "field": "ACCNUM"}
        assert v["columns"]["NAME"] == {"relation": "SCANRULE", "field": "NAME"}
        assert "NAME" not in _indexed_columns("VIEW_EVENTSCANS")  # SCANRULE: PK only

    def test_a_new_index_in_the_survey_widens_the_set(self, monkeypatch):
        data = copy.deepcopy(oq._schema_data())
        data["indices"]["relations"]["ROUTING"]["RO_NEW"] = {
            "fields": ["MTYPE"],
            "unique": False,
            "inactive": False,
            "expression": False,
        }
        monkeypatch.setattr(oq, "_schema_data", lambda: data)
        assert _indexed_columns("ROUTING")["MTYPE"] == ("ROUTING.RO_NEW",)
        with pytest.raises(oq.GuardError) as e:
            check_open_query(
                "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN "
                "'2026-10-19' AND '2026-10-21' AND r.MTYPE = 'M'"
            )
        assert "MTYPE is an indexed column of ROUTING (ROUTING.RO_NEW)" in str(e.value)

    def test_an_inactive_index_does_not_count(self, monkeypatch):
        data = copy.deepcopy(oq._schema_data())
        data["indices"]["relations"]["ROUTING"]["RO_AWB"]["inactive"] = True
        monkeypatch.setattr(oq, "_schema_data", lambda: data)
        assert "AWB" not in _indexed_columns("ROUTING")

    def test_without_the_section_the_rule_is_silent_not_an_error(self, monkeypatch):
        data = copy.deepcopy(oq._schema_data())
        del data["indices"]
        monkeypatch.setattr(oq, "_schema_data", lambda: data)
        assert _indexed_columns("ROUTING") == {}
        check_open_query(
            "SELECT COUNT(*) FROM ROUTING r WHERE r.AGENTDATE BETWEEN "
            "'2026-10-19' AND '2026-10-21' AND r.AGENT > 0"
        )


# --- 3. the survey against the live catalogue ---------------------------------------

load_dotenv()
LIVE = pytest.mark.skipif(
    not os.getenv("DB_HOST"), reason="no DB_HOST in .env — nothing to compare with"
)

INDEX_SQL = (
    "SELECT TRIM(i.RDB$INDEX_NAME), i.RDB$UNIQUE_FLAG, i.RDB$INDEX_INACTIVE, "
    "i.RDB$EXPRESSION_SOURCE, s.RDB$FIELD_POSITION, TRIM(s.RDB$FIELD_NAME) "
    "FROM RDB$INDICES i LEFT JOIN RDB$INDEX_SEGMENTS s "
    "ON s.RDB$INDEX_NAME = i.RDB$INDEX_NAME "
    "WHERE i.RDB$RELATION_NAME = ? "
    "ORDER BY i.RDB$INDEX_NAME, s.RDB$FIELD_POSITION"
)
CONTEXT_SQL = (
    "SELECT RDB$VIEW_CONTEXT, TRIM(RDB$RELATION_NAME), TRIM(RDB$CONTEXT_NAME) "
    "FROM RDB$VIEW_RELATIONS WHERE RDB$VIEW_NAME = ? ORDER BY RDB$VIEW_CONTEXT"
)
COLUMN_SQL = (
    "SELECT TRIM(RDB$FIELD_NAME), RDB$VIEW_CONTEXT, TRIM(RDB$BASE_FIELD) "
    "FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = ? "
    "ORDER BY RDB$FIELD_POSITION"
)


def live(sql, params):
    from mcp_server.db import run_select

    _cols, rows = run_select(sql, params, max_rows=2000, timeout=30)
    return rows


@LIVE
class TestAgainstTheLiveCatalogue:
    def test_every_relations_indexes_match_rdb_indices(self):
        """Names, segments in order, uniqueness, inactivity and the
        expression flag — the whole section, relation by relation."""
        drift = {}
        for rel, recorded in survey()["relations"].items():
            seen: dict[str, dict] = {}
            for name, uniq, inactive, expr, _pos, field in live(INDEX_SQL, (rel,)):
                d = seen.setdefault(
                    name,
                    {
                        "fields": [],
                        "unique": bool(uniq),
                        "inactive": bool(inactive),
                        "expression": expr is not None,
                    },
                )
                if field:
                    d["fields"].append(field)
            if seen != recorded:
                drift[rel] = {
                    "new_or_changed": {
                        n: d for n, d in seen.items() if recorded.get(n) != d
                    },
                    "gone": sorted(set(recorded) - set(seen)),
                }
        assert not drift, (
            "the index survey no longer matches the server — re-run "
            "research/db_query_interface/index_survey.py and review the sets: "
            f"{drift}"
        )

    @pytest.mark.parametrize("view", ["VIEW_EVENTSCANS", "VIEW_WBANALYSE"])
    def test_the_view_mappings_match_the_catalogue(self, view):
        recorded = survey()["views"][view]
        contexts = {}
        for ctx, rel, name in live(CONTEXT_SQL, (view,)):
            contexts[str(ctx)] = {
                "relation": rel,
                "name": name,
                "derived": len(name.split()) > 1,
            }
        assert contexts == recorded["contexts"]
        columns = {}
        for col, ctx, base in live(COLUMN_SQL, (view,)):
            columns[col] = (
                None
                if ctx is None or base is None
                else {"relation": contexts[str(ctx)]["relation"], "field": base}
            )
        assert columns == recorded["columns"]

    def test_the_survey_covers_every_relation_the_views_touch(self):
        rels = set(survey()["relations"])
        for view in ("VIEW_EVENTSCANS", "VIEW_WBANALYSE"):
            for _ctx, rel, _name in live(CONTEXT_SQL, (view,)):
                assert rel in rels, f"{view} touches {rel}, absent from the survey"
        assert {"ROUTING", "MANIFEST", "AGENTDRIVER"} <= rels
