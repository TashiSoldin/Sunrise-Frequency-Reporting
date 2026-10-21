"""QT-000007 line 3, step 1 — definitions only, no data reads.

Prints, from the system tables: the VIEW_EVENTSCANS source text, the columns
of ROUTING and VIEW_EVENTSCANS (name, type), and every index (with its
segments, uniqueness and direction) on ROUTING, EVENT and whatever base
tables the view source names. Written down BEFORE any measurement so the
PLAN lines in routing_eventscans_plans.py can be read against a known index
list rather than guessed at.

Run from the repo root on the BI server:

    uv run python -u research/db_query_interface/routing_eventscans_defs.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.db import run_select

TIMEOUT_S = 30

TYPE_NAMES = {
    7: "SMALLINT",
    8: "INTEGER",
    10: "FLOAT",
    12: "DATE",
    13: "TIME",
    14: "CHAR",
    16: "BIGINT",
    27: "DOUBLE",
    35: "TIMESTAMP",
    37: "VARCHAR",
    261: "BLOB",
}


def q(sql, params=(), max_rows=500):
    return run_select(sql, params, max_rows=max_rows, timeout=TIMEOUT_S)


def view_source(name):
    _cols, rows = q(
        "SELECT r.RDB$VIEW_SOURCE, r.RDB$RELATION_TYPE FROM RDB$RELATIONS r "
        "WHERE r.RDB$RELATION_NAME = ?",
        (name,),
    )
    if not rows:
        return None
    src = rows[0][0]
    if isinstance(src, bytes):
        src = src.decode("latin1")
    return src


def columns(name):
    _cols, rows = q(
        "SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, f.RDB$FIELD_SUB_TYPE, "
        "f.RDB$FIELD_LENGTH, f.RDB$FIELD_SCALE, TRIM(rf.RDB$BASE_FIELD) "
        "FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f "
        "ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE "
        "WHERE rf.RDB$RELATION_NAME = ? ORDER BY rf.RDB$FIELD_POSITION",
        (name,),
    )
    out = []
    for n, t, st, ln, sc, base in rows:
        tn = TYPE_NAMES.get(t, str(t))
        if tn in ("SMALLINT", "INTEGER", "BIGINT") and sc:
            tn = f"NUMERIC(.,{-sc})"
        if tn in ("CHAR", "VARCHAR"):
            tn = f"{tn}({ln})"
        out.append((n, tn, base))
    return out


def indexes(name):
    _cols, rows = q(
        "SELECT TRIM(i.RDB$INDEX_NAME), i.RDB$UNIQUE_FLAG, i.RDB$INDEX_TYPE, "
        "i.RDB$INDEX_INACTIVE, i.RDB$STATISTICS, s.RDB$FIELD_POSITION, "
        "TRIM(s.RDB$FIELD_NAME), i.RDB$FOREIGN_KEY "
        "FROM RDB$INDICES i JOIN RDB$INDEX_SEGMENTS s "
        "ON s.RDB$INDEX_NAME = i.RDB$INDEX_NAME "
        "WHERE i.RDB$RELATION_NAME = ? "
        "ORDER BY i.RDB$INDEX_NAME, s.RDB$FIELD_POSITION",
        (name,),
    )
    by = {}
    for iname, uniq, itype, inactive, stats, pos, field, fk in rows:
        d = by.setdefault(
            iname,
            {
                "unique": bool(uniq),
                "desc": itype == 1,
                "inactive": bool(inactive),
                "stats": stats,
                "fk": fk,
                "fields": [],
            },
        )
        d["fields"].append(field)
    return by


def print_indexes(name):
    _cols, rows = q(
        "SELECT r.RDB$RELATION_TYPE FROM RDB$RELATIONS r WHERE r.RDB$RELATION_NAME = ?",
        (name,),
    )
    rtype = rows[0][0] if rows else None
    print(f"\n== indexes on {name} (relation type {rtype}; 0=table, 1=view) ==")
    by = indexes(name)
    if not by:
        print("  (none)")
    for iname, d in by.items():
        flags = []
        if d["unique"]:
            flags.append("UNIQUE")
        if d["desc"]:
            flags.append("DESC")
        if d["inactive"]:
            flags.append("INACTIVE")
        if d["fk"]:
            flags.append(f"FK->{d['fk'].strip()}")
        sel = d["stats"]
        sel_s = f"selectivity={sel:.3g}" if sel is not None else "selectivity=?"
        print(f"  {iname:<28} ({', '.join(d['fields'])}) {' '.join(flags)} {sel_s}")


def main():
    print("== VIEW_EVENTSCANS source (RDB$RELATIONS.RDB$VIEW_SOURCE) ==")
    src = view_source("VIEW_EVENTSCANS")
    print(src)
    base_tables = sorted(
        {
            m.upper()
            for m in re.findall(
                r"(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_$]*)", src or "", re.IGNORECASE
            )
        }
    )
    print("\nbase relations named in the view source:", ", ".join(base_tables))

    for rel in ("ROUTING", "VIEW_EVENTSCANS"):
        print(f"\n== columns of {rel} ==")
        for n, t, base in columns(rel):
            extra = f"  <- {base}" if base and base != n else ""
            print(f"  {n:<22} {t}{extra}")

    for rel in ["ROUTING", "EVENT"] + [t for t in base_tables if t not in ("EVENT",)]:
        print_indexes(rel)

    # Row counts are known from the 6 Aug survey; repeat only the cheap
    # statistics Firebird keeps on the relation itself (no table scan).
    print(
        "\n(row counts: ROUTING 6,018,355 and EVENT 113,122,153 at the 6 Aug 2026 survey — not re-counted here)"
    )


if __name__ == "__main__":
    main()
