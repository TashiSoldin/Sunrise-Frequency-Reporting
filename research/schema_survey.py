"""Schema survey — what is in the Parcel Perfect database, and what our login can read.

Run on the BI server from the repo root (same .env):

    uv run research/schema_survey.py

Everything is read-only. First job on QT-000004 (accepted 6 Aug 2026), and it
settles two things the quote already sold:

  * Quote line 4 buys "a schema-context resource so Claude writes valid Firebird
    SQL against real column names rather than guessing". This is that resource.
  * Quote line 1 needs to know whether the existing BI role can already only
    SELECT, or whether a dedicated read-only user has to come from Innate.

It also answers the question left open on the acceptance call. Larry wants the
vehicle utilisation tables reachable and nobody has looked for them; the domain
groupings at the end turn that into a lookup rather than another hunt.

Deliberately a FULL inventory, not a keyword scan. The credits pool was invisible
for a week in July because the smoke test scanned %CREDIT%/%INVOICE%/%DEBTOR% and
the data sat on the receipts side. Pull everything, filter afterwards.

What it writes, into --out-dir (run_schema_survey.bat points that at the synced
"Database Reference" folder, so the results can be read off the share instead of
only existing inside the RDP session):

    schema_relations_<date>.csv    one row per table/view: kind, columns, rows, owner
    schema_columns_<date>.csv      one row per column: type, length, nullable
    schema_privileges_<date>.csv   what CURRENT_USER and CURRENT_ROLE are granted
    schema_survey_<date>.txt       the console log, including the domain groupings

Every filename carries the run date. Nothing is overwritten and nothing is
wiped: the schema changes when Parcel Perfect is upgraded, so an older survey is
evidence of what was true then, not clutter. The newest set is the current one.

Flags:

    --out-dir DIR   Where the four files land. Defaults to the current directory,
                    which is the repo root when run by hand. The .bat points it
                    at the share.

    --no-counts     Skip SELECT COUNT(*) per table. The counts are the slow part
                    and the only part that reads data pages rather than metadata.
                    Skip them if you would rather not load the live database
                    during working hours — everything else is cheap.

    --probe-write   Definitively test whether the login can write, by executing
                    an UPDATE ... WHERE 1=0 inside a transaction that is always
                    rolled back. Firebird checks privileges before it checks the
                    WHERE clause, so a permission error is the answer and no row
                    is ever touched. OFF by default: it issues DML against
                    production, and the privilege metadata usually answers the
                    question on its own. Nothing is committed either way.

    --like PATTERN  Restrict the inventory to relations matching a pattern, e.g.
                    --like *VEH*. For follow-up runs; the first run should be
                    unfiltered. Write the wildcard as * rather than SQL's %:
                    cmd.exe eats a bare %VEH% on the command line, and this is
                    driven from a .bat. Both are accepted; * is translated.

A note on what the privilege section can and cannot tell you. If our login owns
the objects, or connects with RDB$ADMIN, it has full rights whether or not any
grant rows exist. The script reports ownership alongside the grants for exactly
that reason — read the two together, and use --probe-write if you need certainty.
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.revenue_extraction_test import connect, query_df


class _Tee:
    """Duplicate stdout to a file so the whole run lands on disk too.

    Copied rather than imported from research/revenue_extract_verify.py on
    purpose. That module pulls in revenue_reports.extract_revenue at import
    time, and this script belongs to a different engagement — it should not
    stop working because the revenue extraction module moved.
    """

    def __init__(self, path: str):
        self.file = open(path, "w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, s):
        self.stdout.write(s)
        self.file.write(s)

    def flush(self):
        self.stdout.flush()
        self.file.flush()

# Firebird internal field-type codes -> readable names.
FIELD_TYPES = {
    7: "SMALLINT", 8: "INTEGER", 9: "QUAD", 10: "FLOAT", 12: "DATE",
    13: "TIME", 14: "CHAR", 16: "BIGINT", 23: "BOOLEAN", 27: "DOUBLE PRECISION",
    35: "TIMESTAMP", 37: "VARCHAR", 40: "CSTRING", 45: "BLOB_ID", 261: "BLOB",
}

# Firebird privilege letters, as they appear in RDB$USER_PRIVILEGES.
PRIVILEGES = {
    "S": "SELECT", "I": "INSERT", "U": "UPDATE", "D": "DELETE",
    "R": "REFERENCES", "X": "EXECUTE", "M": "MEMBER OF", "G": "USAGE",
}

WRITE_PRIVILEGES = {"INSERT", "UPDATE", "DELETE"}

# Grouping only — a convenience view over the full inventory, never a filter on
# what gets collected. Order matters: a relation lands in the first group it
# matches, so the more specific groups come first.
DOMAINS = [
    ("Vehicles, fleet and utilisation", (
        "VEH", "FLEET", "TRUCK", "TRAILER", "HORSE", "DRIVER", "ODO",
        "UTIL", "TYRE", "SERVIC", "LICENC", "LICENS", "REGNO",
    )),
    ("Line haul, trips and manifests", (
        "TRIP", "MANIF", "MRG", "LINEHAUL", "LHAUL", "LOAD", "ROUTE",
        "LEG", "RSL", "DEPART", "ARRIV",
    )),
    ("Fuel and diesel", ("FUEL", "DIESEL", "R2D", "PETROL", "LITRE")),
    ("Waybills and freight", ("WAY", "WB", "PARCEL", "FREIGHT", "CONSIGN")),
    ("POD, events and scanning", (
        "POD", "EVENT", "SCAN", "IMAGE", "TRACK", "STATUS", "EXCEPT",
    )),
    ("Billing, revenue and credits", (
        "INV", "RECEIPT", "CREDIT", "DEBTOR", "RATE", "TARIFF", "SURCH",
        "PRICE", "CHARGE", "VAT", "JOURNAL", "BUDGET",
    )),
    ("Customers, agents and reps", (
        "CUST", "ACC", "CONTACT", "AGENT", "REP", "CLIENT", "DEBT",
    )),
    ("Users, staff and security", ("USER", "EMP", "STAFF", "SEC", "LOGIN", "AUDIT")),
    ("Reference and lookup", ("TYPE", "CODE", "LOOKUP", "PARAM", "SETUP", "CONFIG")),
]


def field_type_name(row) -> str:
    """Render a column's type the way you would write it in DDL."""
    base = FIELD_TYPES.get(row["FTYPE"], f"type {row['FTYPE']}")
    scale = int(row["FSCALE"] or 0)
    if base in ("SMALLINT", "INTEGER", "BIGINT") and scale < 0:
        # int() because pandas widens these to float when any row is null, and
        # NUMERIC(8.0,5) in a schema reference is a typo waiting to be copied.
        precision = int(row["FPREC"] or 18)
        return f"NUMERIC({precision},{abs(scale)})"
    if base in ("CHAR", "VARCHAR", "CSTRING"):
        return f"{base}({row['FLEN']})"
    if base == "BLOB":
        return "BLOB (text)" if row["FSUB"] == 1 else "BLOB (binary)"
    return base


def survey_relations(conn, like: str | None) -> pd.DataFrame:
    """Every user table and view. RDB$VIEW_BLR rather than RDB$RELATION_TYPE,
    because the former is present in every Firebird version we might meet."""
    where = "COALESCE(R.RDB$SYSTEM_FLAG, 0) = 0"
    if like:
        where += f" AND R.RDB$RELATION_NAME LIKE '{like}'"
    return query_df(conn, f"""
        SELECT TRIM(R.RDB$RELATION_NAME) AS REL,
               CASE WHEN R.RDB$VIEW_BLR IS NULL THEN 'table' ELSE 'view' END AS KIND,
               TRIM(COALESCE(R.RDB$OWNER_NAME, '')) AS OWNER,
               COALESCE(R.RDB$DESCRIPTION, '') AS DESCRIPTION
        FROM RDB$RELATIONS R
        WHERE {where}
        ORDER BY 1;
    """)


def survey_columns(conn, like: str | None) -> pd.DataFrame:
    where = "COALESCE(R.RDB$SYSTEM_FLAG, 0) = 0"
    if like:
        where += f" AND R.RDB$RELATION_NAME LIKE '{like}'"
    df = query_df(conn, f"""
        SELECT TRIM(RF.RDB$RELATION_NAME) AS REL,
               TRIM(RF.RDB$FIELD_NAME) AS COL,
               RF.RDB$FIELD_POSITION AS POS,
               F.RDB$FIELD_TYPE AS FTYPE,
               F.RDB$FIELD_SUB_TYPE AS FSUB,
               F.RDB$FIELD_LENGTH AS FLEN,
               F.RDB$FIELD_PRECISION AS FPREC,
               F.RDB$FIELD_SCALE AS FSCALE,
               COALESCE(RF.RDB$NULL_FLAG, F.RDB$NULL_FLAG, 0) AS NOTNULL
        FROM RDB$RELATION_FIELDS RF
        JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME = RF.RDB$RELATION_NAME
        LEFT JOIN RDB$FIELDS F ON F.RDB$FIELD_NAME = RF.RDB$FIELD_SOURCE
        WHERE {where}
        ORDER BY RF.RDB$RELATION_NAME, RF.RDB$FIELD_POSITION;
    """)
    if len(df):
        df["TYPE"] = df.apply(field_type_name, axis=1)
        df["NULLABLE"] = df["NOTNULL"].apply(lambda n: "no" if n else "yes")
        df = df[["REL", "POS", "COL", "TYPE", "NULLABLE"]]
    return df


def count_rows(conn, tables: list[str]) -> dict[str, int | None]:
    """SELECT COUNT(*) per table. Tables only — counting a view can be
    arbitrarily expensive and tells you nothing the base tables do not."""
    counts: dict[str, int | None] = {}
    started = time.monotonic()
    for i, rel in enumerate(tables, 1):
        try:
            counts[rel] = int(query_df(conn, f'SELECT COUNT(*) AS N FROM "{rel}"')["N"].iloc[0])
        except Exception as e:
            counts[rel] = None
            print(f"  ! {rel}: count failed ({type(e).__name__}: {e})")
        if i % 25 == 0 or i == len(tables):
            print(f"  counted {i}/{len(tables)} tables ({time.monotonic() - started:.0f}s)")
    return counts


def survey_privileges(conn) -> tuple[pd.DataFrame, dict]:
    identity = query_df(conn, """
        SELECT TRIM(CURRENT_USER) AS DB_USER, TRIM(COALESCE(CURRENT_ROLE, '')) AS DB_ROLE
        FROM RDB$DATABASE;
    """).iloc[0].to_dict()

    grants = query_df(conn, f"""
        SELECT TRIM(P.RDB$USER) AS GRANTEE,
               TRIM(P.RDB$RELATION_NAME) AS OBJECT,
               TRIM(P.RDB$PRIVILEGE) AS PRIV,
               COALESCE(P.RDB$GRANT_OPTION, 0) AS GRANT_OPTION,
               TRIM(COALESCE(P.RDB$FIELD_NAME, '')) AS COLUMN_NAME
        FROM RDB$USER_PRIVILEGES P
        WHERE TRIM(P.RDB$USER) IN ('{identity['DB_USER']}', '{identity['DB_ROLE']}')
           OR TRIM(P.RDB$USER) = 'PUBLIC'
        ORDER BY 1, 2, 3;
    """)
    if len(grants):
        grants["PRIVILEGE"] = grants["PRIV"].map(lambda p: PRIVILEGES.get(p, p))
    return grants, identity


def probe_write(conn, target: str, column: str) -> str:
    """Ask Firebird directly whether this login may write. The UPDATE matches no
    rows and the transaction is rolled back regardless of outcome — privileges
    are checked before the WHERE clause, so the answer comes from the error."""
    try:
        with conn.cursor() as cur:
            cur.execute(f'UPDATE "{target}" SET "{column}" = "{column}" WHERE 1 = 0')
        conn.rollback()
        return f"CAN WRITE — UPDATE on {target} was accepted (rolled back, nothing changed)."
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        message = str(e)
        if "no permission" in message.lower():
            return f"READ-ONLY — Firebird refused UPDATE on {target}: {message.strip()}"
        return (f"INCONCLUSIVE — UPDATE on {target} failed, but not on privileges: "
                f"{type(e).__name__}: {message.strip()}")


def group_by_domain(relations: pd.DataFrame) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {name: [] for name, _ in DOMAINS}
    grouped["Everything else"] = []
    for rel in relations["REL"]:
        upper = rel.upper()
        for name, keywords in DOMAINS:
            if any(k in upper for k in keywords):
                grouped[name].append(rel)
                break
        else:
            grouped["Everything else"].append(rel)
    return grouped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=".",
                    help="where the four output files land (default: current directory)")
    ap.add_argument("--no-counts", action="store_true",
                    help="skip SELECT COUNT(*) per table (the only part that reads data)")
    ap.add_argument("--probe-write", action="store_true",
                    help="definitively test write access with a rolled-back UPDATE")
    ap.add_argument("--like", default=None,
                    help="restrict to relations matching a pattern, e.g. *VEH* "
                         "(* is translated to SQL's %%, which cmd.exe would eat)")
    args = ap.parse_args()

    # cmd.exe strips a bare %VEH% off the command line before Python sees it, and
    # this is driven from a .bat, so * is the wildcard people can actually type.
    like = args.like.replace("*", "%") if args.like else None

    today = date.today().isoformat()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"schema_survey_{today}.txt"
    sys.stdout = _Tee(str(log_path))
    print(f"(also writing this output to {log_path})\n")

    conn = connect()

    print("== 1. Who we are ==")
    grants, identity = survey_privileges(conn)
    print(f"CURRENT_USER: {identity['DB_USER']}")
    print(f"CURRENT_ROLE: {identity['DB_ROLE'] or '(none)'}")
    try:
        mon = query_df(conn, """
            SELECT TRIM(MON$DATABASE_NAME) AS DB, MON$ODS_MAJOR AS ODS_MAJOR,
                   MON$ODS_MINOR AS ODS_MINOR, MON$PAGE_SIZE AS PAGE_SIZE
            FROM MON$DATABASE;
        """).iloc[0]
        print(f"database: {mon['DB']} (ODS {mon['ODS_MAJOR']}.{mon['ODS_MINOR']}, "
              f"page size {mon['PAGE_SIZE']})")
    except Exception as e:
        print(f"(MON$DATABASE unavailable: {e})")
    print()

    print("== 2. Inventory ==")
    relations = survey_relations(conn, like)
    columns = survey_columns(conn, like)
    tables = relations.loc[relations["KIND"] == "table", "REL"].tolist()
    views = relations.loc[relations["KIND"] == "view", "REL"].tolist()
    print(f"{len(relations)} user relations: {len(tables)} tables, {len(views)} views")
    print(f"{len(columns)} columns across them")
    owners = relations["OWNER"].value_counts().to_dict()
    print(f"owners: {owners}")
    if identity["DB_USER"] in owners:
        print(f"NOTE: {identity['DB_USER']} owns {owners[identity['DB_USER']]} of these "
              "relations, so it has full rights on them regardless of any GRANT rows.")
    print()

    counts = {}
    if args.no_counts:
        print("== 3. Row counts — SKIPPED (--no-counts) ==\n")
    else:
        print(f"== 3. Row counts ({len(tables)} tables; views skipped) ==")
        counts = count_rows(conn, tables)
        populated = {r: n for r, n in counts.items() if n}
        print(f"{len(populated)} tables hold rows; {len(tables) - len(populated)} are "
              "empty or unreadable.")
        print("\nLargest 25 by row count:")
        for rel, n in sorted(populated.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {n:>12,}  {rel}")
        print()

    relations["ROWS"] = relations["REL"].map(lambda r: counts.get(r))
    relations["COLUMNS"] = relations["REL"].map(columns["REL"].value_counts()).fillna(0).astype(int)

    print("== 4. What this login is granted ==")
    if not len(grants):
        print("No GRANT rows for this user, role or PUBLIC.")
        print("That means access comes from ownership or RDB$ADMIN, not from grants — "
              "read this together with the owner list above, and use --probe-write "
              "if you need certainty.")
    else:
        summary = grants.groupby("PRIVILEGE")["OBJECT"].nunique().sort_values(ascending=False)
        print("Distinct objects per privilege:")
        for priv, n in summary.items():
            print(f"  {priv:<12} {n}")
        held = set(summary.index) & WRITE_PRIVILEGES
        if held:
            print(f"\nWRITE PRIVILEGES PRESENT: {', '.join(sorted(held))}. "
                  "This login is not read-only, so the interface needs its own user — "
                  "that is the ask to Innate, since creating one needs SYSDBA.")
        else:
            print("\nNo INSERT/UPDATE/DELETE grants found. Confirm with --probe-write "
                  "before relying on it.")
    print()

    if args.probe_write:
        print("== 5. Write probe ==")
        candidates = [(r, n) for r, n in counts.items() if n] or [(t, None) for t in tables]
        if candidates:
            target = min(candidates, key=lambda kv: kv[1] or 0)[0]
            column = columns.loc[columns["REL"] == target, "COL"]
            if len(column):
                print(probe_write(conn, target, column.iloc[0]))
            else:
                print(f"(no columns found for {target} — skipped)")
        else:
            print("(no candidate table — skipped)")
        print()

    print("== 6. Relations by domain ==")
    print("Grouping only. The CSVs hold everything; this is a reading aid, and the "
          "first group is the one the acceptance call was about.\n")
    for name, rels in group_by_domain(relations).items():
        print(f"-- {name} ({len(rels)}) --")
        if not rels:
            print("  (none)\n")
            continue
        for rel in rels:
            n = counts.get(rel)
            kind = relations.loc[relations["REL"] == rel, "KIND"].iloc[0]
            shown = f"{n:,}" if isinstance(n, int) else ("view" if kind == "view" else "?")
            print(f"  {rel:<32} {shown:>14} rows")
        print()

    rel_out = out_dir / f"schema_relations_{today}.csv"
    col_out = out_dir / f"schema_columns_{today}.csv"
    priv_out = out_dir / f"schema_privileges_{today}.csv"
    relations[["REL", "KIND", "COLUMNS", "ROWS", "OWNER", "DESCRIPTION"]].to_csv(rel_out, index=False)
    columns.to_csv(col_out, index=False)
    grants.to_csv(priv_out, index=False)

    conn.close()
    print("== Files ==")
    for f in (rel_out, col_out, priv_out, log_path):
        print(f"  {f}")
    print("\nDone.")
    print("Next: read the vehicle/fleet group against what Larry asked for on the "
          "acceptance call, and settle whether line 4's allowlist reaches it.")


if __name__ == "__main__":
    main()
