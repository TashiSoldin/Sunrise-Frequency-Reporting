"""List line-haul manifests (MTYPE='M') in a date window, to pick probe trips.

Companion to routing_probe.py: prints MANIFEST, AGENT, AGENTDATE, hubs, NOWB,
PIECES, CHARGEMASS so trips can be matched against the RSL control table by
eye. Read-only, FIRST-capped, one indexed-ish window scan.

Run from the repo root on the BI server:

    uv run python research\\line_haul\\list_line_haul_trips.py [--from 2026-07-01] [--to 2026-08-01]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.db import run_select


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="lo", default="2026-07-01")
    ap.add_argument("--to", dest="hi", default="2026-08-01")
    a = ap.parse_args()

    cols, rows = run_select(
        f"SELECT FIRST 60 MANIFEST, AGENT, AGENTDATE, ORIGHUB, DESTHUB, "
        f"NOWB, PIECES, CHARGEMASS FROM MANIFEST "
        f"WHERE MTYPE = 'M' AND AGENTDATE >= DATE '{a.lo}' "
        f"AND AGENTDATE < DATE '{a.hi}' ORDER BY AGENTDATE, MANIFEST",
        max_rows=60,
        timeout=60,
    )
    print(" | ".join(cols))
    for r in rows:
        print(" | ".join(str(v) for v in r))
    print(f"\n({len(rows)} trips shown, FIRST 60 — narrow the window if capped)")


if __name__ == "__main__":
    main()
