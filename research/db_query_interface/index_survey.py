"""Add the index survey to mcp_server/schema_context.json (QT-000007, Fable
eighth review E1-E4, 23 Oct 2026).

Reads, from the Firebird system tables only (no data rows):

  * every index on the relations the windowed shape can touch — ROUTING,
    MANIFEST, AGENTDRIVER and every base relation of VIEW_EVENTSCANS and
    VIEW_WBANALYSE (RDB$VIEW_RELATIONS) — with its segments in order
    (RDB$INDICES / RDB$INDEX_SEGMENTS);
  * the two views' contexts and each view column's base relation and field
    (RDB$RELATION_FIELDS.RDB$VIEW_CONTEXT / RDB$BASE_FIELD). A column of a
    UNION inside the view has no base field in the metadata; the gate
    resolves those by name against the relations of the derived-table
    contexts (the ones whose context name is two words, "EVENTS E").

and writes them under the "indices" key of schema_context.json, beside the
6 Aug column survey. open_query derives the per-table INDEXED-COLUMN SETS
from this section (a column that is the FIRST segment of an index; for a
view, through its base field) — nothing is typed by hand — and
tests/test_index_survey.py asserts the section against the live RDB$INDICES
so a new index on the server fails the suite instead of opening a gap.

Usage (on the BI server, from the repo root):

    uv run python research/db_query_interface/index_survey.py
"""

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from mcp_server.db import run_select

OUT = REPO / "mcp_server" / "schema_context.json"
VIEWS = ("VIEW_EVENTSCANS", "VIEW_WBANALYSE")
ALWAYS = ("ROUTING", "MANIFEST", "AGENTDRIVER")

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


def q(sql, params):
    _cols, rows = run_select(sql, params, max_rows=2000, timeout=30)
    return rows


def indices_of(relation: str) -> dict:
    out: dict[str, dict] = {}
    for name, unique, inactive, expression, _pos, field in q(INDEX_SQL, (relation,)):
        d = out.setdefault(
            name,
            {
                "fields": [],
                "unique": bool(unique),
                "inactive": bool(inactive),
                "expression": expression is not None,
            },
        )
        if field:
            d["fields"].append(field)
    return dict(sorted(out.items()))


def view_survey(view: str) -> dict:
    contexts = {}
    for ctx, relation, ctx_name in q(CONTEXT_SQL, (view,)):
        words = ctx_name.split()
        contexts[str(ctx)] = {
            "relation": relation,
            "name": ctx_name,
            # "EVENTS E": the relation sits inside a derived table named EVENTS
            "derived": len(words) > 1,
        }
    columns = {}
    for col, ctx, base in q(COLUMN_SQL, (view,)):
        if ctx is None or base is None:
            columns[col] = None  # a UNION / expression column — no base field
        else:
            columns[col] = {"relation": contexts[str(ctx)]["relation"], "field": base}
    return {"contexts": contexts, "columns": columns}


def survey() -> dict:
    views = {v: view_survey(v) for v in VIEWS}
    relations = set(ALWAYS)
    for v in views.values():
        relations.update(c["relation"] for c in v["contexts"].values())
    return {
        "survey_date": dt.date.today().isoformat(),
        "source": (
            "RDB$INDICES / RDB$INDEX_SEGMENTS / RDB$VIEW_RELATIONS / "
            "RDB$RELATION_FIELDS, read live by "
            "research/db_query_interface/index_survey.py"
        ),
        "relations": {r: indices_of(r) for r in sorted(relations)},
        "views": views,
    }


def main() -> None:
    data = json.loads(OUT.read_text())
    data["indices"] = survey()
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    rels = data["indices"]["relations"]
    n_idx = sum(len(v) for v in rels.values())
    print(f"wrote {OUT} — {len(rels)} relations, {n_idx} indices, {len(VIEWS)} views")


if __name__ == "__main__":
    main()
