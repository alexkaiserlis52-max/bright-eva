# -*- coding: utf-8 -*-
"""One-off migration: add the 10 well-being/collaboration columns to
FoAssessment and backfill the demo cohort's existing rows.

- Idempotent: adds only missing headers; fills only EMPTY demo rows.
- Never touches real-student rows (they stay blank — optional fields).
- One batch_update for all writes.

Run:  .venv/Scripts/python.exe add_fo_wellbeing_fields.py
"""
import sys

sys.dont_write_bytecode = True

from dotenv import load_dotenv

load_dotenv()
import gspread  # noqa: F401  (ensures creds resolve the same way as the app)
import openai_reports as orp
from wellbeing_fields import ARCHETYPES, NEW_HEADERS, generate_fields


def main():
    ws = orp.gc.open("FoAssessment").sheet1

    # 1) headers ------------------------------------------------------------
    header = ws.row_values(1)
    missing = [h for h in NEW_HEADERS if h not in header]
    if missing:
        start_col = len(header) + 1
        ws.update(
            [missing],
            f"{gspread.utils.rowcol_to_a1(1, start_col)}:"
            f"{gspread.utils.rowcol_to_a1(1, start_col + len(missing) - 1)}",
        )
        print(f"headers: +{len(missing)} added (now {start_col + len(missing) - 1} cols)")
        header = ws.row_values(1)
    else:
        print("headers: all present")

    # 2) backfill demo rows ---------------------------------------------------
    rows = ws.get_all_values()
    updates = []
    seen = {}  # student id -> running session index
    for r, row in enumerate(rows[1:], start=2):
        sid = row[1].strip() if len(row) > 1 else ""
        if sid not in ARCHETYPES:
            continue  # real students stay untouched
        idx = seen.get(sid, 0)
        seen[sid] = idx + 1
        if len(row) > 8 and row[8].strip():
            continue  # already filled — idempotent
        scores = [int(row[c]) for c in range(2, 7)]
        values = generate_fields(sid, scores, idx)
        updates.append({"range": f"I{r}:R{r}", "values": [values]})

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"backfill: {len(updates)} demo rows filled "
          f"({len(rows) - 1} total data rows)")
    for sid in sorted(seen):
        print(f"  {sid}: {seen[sid]} sessions scanned")


if __name__ == "__main__":
    main()
