# -*- coding: utf-8 -*-
"""One-off migration: add the new framework-anchored fields to SelfAssessment,
PreAssessment, PostAssessment and LessonAssessment, and backfill the demo
cohort's existing rows.

- Idempotent: adds only missing headers; fills only EMPTY demo rows.
- Never touches real-student rows.
- Self rows pair with the same session's formative scores (weeks 3,5,8 ->
  FoAssessment rows 3,5,8) so the self-view gap stays coherent.

Run:  .venv/Scripts/python.exe add_other_form_fields.py
"""
import sys

sys.dont_write_bytecode = True

from dotenv import load_dotenv

load_dotenv()
import gspread
import openai_reports as orp
from wellbeing_fields import (
    ARCHETYPES, LESSON_HEADERS, POST_HEADERS, PRE_HEADERS, SELF_HEADERS,
    gen_lesson_fields, gen_post_fields, gen_pre_fields, gen_self_fields,
)


def _ensure_headers(ws, new_headers):
    """Add missing headers at the end; return (first new col index, #added).
    col0 is derived from the header POSITION — safe on re-runs."""
    header = ws.row_values(1)
    missing = [h for h in new_headers if h not in header]
    if missing:
        start_col = len(header) + 1
        ws.update(
            [missing],
            f"{gspread.utils.rowcol_to_a1(1, start_col)}:"
            f"{gspread.utils.rowcol_to_a1(1, start_col + len(missing) - 1)}",
        )
        header = ws.row_values(1)
    return header.index(new_headers[0]) + 1, len(missing)


def _range(row, col0, ncols):
    a = gspread.utils.rowcol_to_a1(row, col0)
    b = gspread.utils.rowcol_to_a1(row, col0 + ncols - 1)
    return f"{a}:{b}"


def main():
    # formative scores per (student, session) — for coherent self-view values
    fo_ws = orp.gc.open("FoAssessment").sheet1
    fo_scores = {}
    seen = {}
    for row in fo_ws.get_all_values()[1:]:
        sid = row[1].strip() if len(row) > 1 else ""
        if sid not in ARCHETYPES:
            continue
        idx = seen.get(sid, 0)
        seen[sid] = idx + 1
        fo_scores[(sid, idx)] = [int(row[c]) for c in range(2, 7)]
    FO_IDX_FOR_SELF = [2, 4, 7]  # self-assessment weeks 3, 5, 8

    # --- SelfAssessment (new cols F:H) --------------------------------------
    ws = orp.gc.open("SelfAssessment").sheet1
    col0, added = _ensure_headers(ws, SELF_HEADERS)
    print(f"SelfAssessment: +{added} headers")
    updates = []
    seen = {}
    for r, row in enumerate(ws.get_all_values()[1:], start=2):
        sid = row[1].strip() if len(row) > 1 else ""
        if sid not in ARCHETYPES:
            continue
        n = seen.get(sid, 0)
        seen[sid] = n + 1
        if len(row) >= col0 and row[col0 - 1].strip():
            continue
        fo_idx = FO_IDX_FOR_SELF[min(n, 2)]
        scores = fo_scores.get((sid, fo_idx), [3, 3, 3, 3, 3])
        values = gen_self_fields(sid, scores, fo_idx)
        updates.append({"range": _range(r, col0, 3), "values": [values]})
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"SelfAssessment: {len(updates)} demo rows filled")

    # --- PreAssessment (new cols G:I) ---------------------------------------
    ws = orp.gc.open("PreAssessment").sheet1
    col0, added = _ensure_headers(ws, PRE_HEADERS)
    print(f"PreAssessment: +{added} headers")
    updates = []
    for r, row in enumerate(ws.get_all_values()[1:], start=2):
        sid = row[1].strip() if len(row) > 1 else ""
        if sid not in ARCHETYPES:
            continue
        if len(row) >= col0 and row[col0 - 1].strip():
            continue
        updates.append({"range": _range(r, col0, 3), "values": [gen_pre_fields(sid)]})
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"PreAssessment: {len(updates)} demo rows filled")

    # --- PostAssessment (new cols F:H) --------------------------------------
    ws = orp.gc.open("PostAssessment").sheet1
    col0, added = _ensure_headers(ws, POST_HEADERS)
    print(f"PostAssessment: +{added} headers")
    updates = []
    for r, row in enumerate(ws.get_all_values()[1:], start=2):
        sid = row[1].strip() if len(row) > 1 else ""
        if sid not in ARCHETYPES:
            continue
        if len(row) >= col0 and row[col0 - 1].strip():
            continue
        updates.append({"range": _range(r, col0, 3), "values": [gen_post_fields(sid)]})
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"PostAssessment: {len(updates)} demo rows filled")

    # --- LessonAssessment (new cols G:J) ------------------------------------
    ws = orp.gc.open("LessonAssessment").sheet1
    col0, added = _ensure_headers(ws, LESSON_HEADERS)
    print(f"LessonAssessment: +{added} headers")
    updates = []
    seen = {}
    for r, row in enumerate(ws.get_all_values()[1:], start=2):
        group = row[1].strip() if len(row) > 1 else ""
        if group not in ("ΜΓ1", "ΜΔ2"):  # only demo-group climate rows
            continue
        idx = seen.get(group, 0)
        seen[group] = idx + 1
        if len(row) >= col0 and row[col0 - 1].strip():
            continue
        values = gen_lesson_fields(group, row[2] or "3", idx)
        updates.append({"range": _range(r, col0, 4), "values": [values]})
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"LessonAssessment: {len(updates)} demo rows filled")


if __name__ == "__main__":
    main()
