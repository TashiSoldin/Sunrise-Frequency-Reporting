"""Day 2 acceptance helper: print waybill_status answers for the validation
waybills, formatted for reading side by side against the Parcel Perfect
waybill enquiry screen.

Run from the repo root on the BI server (needs the gitignored .env):

    uv run python research\\check_day2_waybills.py             # the standard six
    uv run python research\\check_day2_waybills.py GB123456    # any extra numbers

Read-only: every lookup goes through mcp_server.waybill -> run_select
(SELECT-only guard, read-only transaction, indexed lookup, ~25 ms each).
One-off helper for the Day 2 walkthrough -- not scheduled, not imported.
"""

import sys
from pathlib import Path

# Running a script by path puts research/ on sys.path, not the repo root —
# put the root first so mcp_server imports regardless of how this is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.waybill import WaybillInputError, lookup_waybill

# The five acceptance categories from the 13 Aug 2026 Decisions entry, plus
# the trailing-tilde form fixed in commit 75d50799.
DEFAULT = [
    ("SL0295181", "delivered with POD -- expect recipient SILVESTER, image Y"),
    ("GB-INV3141", "in transit -- expect Loaded for Delivery at GRJ, no POD"),
    ("32785623", "discrepancy -- expect 'FULL RETURN CUSTOMER TO COLLECT...'"),
    ("PTM317433", "tilde pair -- must return the base AND ~1, both flagged"),
    ("PTM317433~", "trailing tilde as read off a screen -- same two records"),
    ("SL0XX99999", "invented -- must answer NOT FOUND, 'not in the system'"),
]


def show(label, value):
    print(f"    {label:<18} {value if value is not None else '-'}")


def print_match(m):
    print(f"  [{m['waybill']}]" + ("  (~ variant)" if m["is_tilde_variant"] else ""))
    show("Status", m["status"])
    ev = m["last_event"]
    show("Last event", ev["event"])
    show("  at hub", ev["hub"])
    show("  date / time", f"{ev['date']}  {ev['time']}")
    pod = m["pod"]
    show("POD recipient", pod["recipient"])
    show("  date / time", f"{pod['date']}  {pod['time']}")
    show("  captured", f"{pod['capture_date']}  {pod['capture_time']}")
    show("  discrepancy", pod["discrepancy"])
    show("  image present", pod["image_present"])
    show("  details", pod["details"])
    show("Delivery agent", m["delivery_agent"])
    show("Service", m["service"])
    r = m["route"]
    show("Origin", f"{r['origin_hub']} {r['origin_town']}  ({r['sender']})")
    show(
        "Destination",
        f"{r['destination_hub']} {r['destination_town']}  ({r['receiver']})",
    )
    show("Waybill date", m["waybill_date"])
    show("Due date", m["due_date"])
    show("Account / cust", f"{m['account']}  {m['customer']}")
    show("Pieces / mass", f"{m['pieces']}  /  {m['charge_mass']}")


def main(numbers):
    todo = [(n, "extra") for n in numbers] if numbers else DEFAULT
    for no, why in todo:
        print("=" * 72)
        print(f"ASK: {no}   ({why})")
        try:
            answer = lookup_waybill(no)
        except WaybillInputError as e:
            print(f"  REFUSED before any query ran: {e}")
            continue
        if not answer["found"]:
            print("  NOT FOUND -- read the message exactly as Larry would hear it:")
            print(f"  {answer['message']}")
            continue
        n = answer["match_count"]
        print(
            f"  {n} record(s) returned"
            + (" -- CAPPED, flag it" if answer.get("capped") else "")
        )
        if answer.get("message"):
            print(f"  {answer['message']}")
        for m in answer["matches"]:
            print_match(m)
    print("=" * 72)
    print(
        "Pass = every line above matches the Parcel Perfect screen for the same\n"
        "number, and the invented number reads as 'not in the system' (never as\n"
        "'no activity'). Any mismatch: note the waybill and field, leave Day 2\n"
        "Blocked, and bring it back to a session."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
