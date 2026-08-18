"""Generate mcp_server/schema_context.json from the 6 Aug schema survey.

Reads the newest schema_columns_*.csv and schema_relations_*.csv in the
Database Reference folder (Claude General SharePoint library) and writes the
column/type/row-count data for the open-path ALLOWLIST tables only. The
allowlist itself — and the justification for every entry — lives in
mcp_server/open_query.py; this script just materialises the survey data those
tables need, so the schema resource serves real Firebird column names instead
of guesses.

The JSON is checked into the repo: the survey CSVs live in a OneDrive-synced
folder that only exists on the BI server, and the Mac checkout must be able
to serve the schema resource too. Re-run this after a new schema survey
(a Parcel Perfect upgrade) and commit the diff.

Usage:  uv run python research/db_query_interface/build_schema_context.py
"""

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from mcp_server.open_query import ALLOWLIST

REFERENCE_DIR = Path(
    r"C:\Users\AkhaM\OneDrive - Sunrise Express"
    r"\Claude General - Documents\Dashboards and Data Analysis"
    r"\Database Reference"
)
OUT = REPO / "mcp_server" / "schema_context.json"


def newest(pattern: str) -> Path:
    files = sorted(REFERENCE_DIR.glob(pattern))
    if not files:
        raise SystemExit(f"no {pattern} in {REFERENCE_DIR} — run the schema survey")
    return files[-1]


def main() -> None:
    columns_csv = newest("schema_columns_*.csv")
    relations_csv = newest("schema_relations_*.csv")

    relations = {}
    with open(relations_csv, newline="") as f:
        for row in csv.DictReader(f):
            relations[row["REL"]] = row

    columns: dict[str, list[dict]] = {t: [] for t in ALLOWLIST}
    with open(columns_csv, newline="") as f:
        for row in csv.DictReader(f):
            if row["REL"] in columns:
                columns[row["REL"]].append(
                    {
                        "name": row["COL"],
                        "type": row["TYPE"],
                        "nullable": row["NULLABLE"] == "yes",
                    }
                )

    missing = [t for t, cols in columns.items() if not cols]
    if missing:
        raise SystemExit(f"allowlisted tables absent from the survey: {missing}")

    tables = {}
    for name in sorted(ALLOWLIST):
        rel = relations[name]
        rows = rel["ROWS"]
        tables[name] = {
            "kind": rel["KIND"],
            # views were not counted by the survey; None means "not counted",
            # never "empty"
            "row_count": int(float(rows)) if rows else None,
            "columns": columns[name],
        }

    OUT.write_text(
        json.dumps(
            {
                "survey_date": columns_csv.stem.rsplit("_", 1)[-1],
                "source": [columns_csv.name, relations_csv.name],
                "tables": tables,
            },
            indent=1,
        )
        + "\n"
    )
    n_cols = sum(len(t["columns"]) for t in tables.values())
    print(f"wrote {OUT} — {len(tables)} tables, {n_cols} columns")


if __name__ == "__main__":
    main()
