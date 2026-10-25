"""
Human risk annotations — the LIVING risk register.

While inspecting a pipeline trace, a reviewer (educator, auditor, AIED
researcher) can register a risk observation: a category (one of the curated
R1–R10, or "new" for something the register does not list yet), a severity, a
free-text comment, and optionally the pipeline stage it concerns.

Notes are stored in the RiskNotes Google Sheet — the same store as everything
else in the system — so they are durable, shared between reviewers, and visible
to the school. This is what turns the static risk register into a co-created,
living document: baseline risks + what real humans observed in real traces.

Sheet schema (row 1 headers):
    Timestamp | Trace ID | Stage | Ref | Severity | Author | Comment | Status
"""
import time
from datetime import datetime

import openai_reports as orp  # reuses the authorized gspread client (orp.gc)

SEVERITIES = ("danger", "warn", "info")
STATUS_VALUES = ("open", "confirmed", "dismissed")
BASELINE_REFS = tuple(f"r{i}" for i in range(1, 11))  # r1..r10
VALID_REFS = BASELINE_REFS + ("new",)

# Short titles for the baseline categories — used by the observation form
# and the living register page.
REF_TITLES = {
    "r1": "PII leakage to a third-party LLM",
    "r2": "Hallucinated / ungrounded reports",
    "r3": "Automation bias (rubber-stamping AI)",
    "r4": "Silent decline goes unnoticed",
    "r5": "Safeguards misfire (over/under-masking)",
    "r6": "Prompt injection via assessment notes",
    "r7": "Vendor / model dependency",
    "r8": "Re-identification via quasi-identifiers",
    "r9": "Function creep",
    "r10": "Accountability gaps",
    "new": "New, unlisted risk (candidate for the register)",
}

_CACHE_TTL = 60  # notes are human input — keep reasonably fresh
_cache = {"ts": 0, "rows": None}


def _ws():
    return orp.gc.open("RiskNotes").sheet1


def list_notes(trace_id=None, force=False):
    """All notes as dicts (including their sheet row number), newest first.

    With trace_id, only that run's notes. On sheet errors returns [] — the
    pipeline viewer must never break because the register is unreachable.
    """
    now = time.time()
    if force or _cache["rows"] is None or now - _cache["ts"] > _CACHE_TTL:
        rows = []
        try:
            raw = _ws().get_all_values()
            for i, r in enumerate(raw[1:], start=2):  # row 1 = headers
                r = list(r) + [""] * (8 - len(r))
                if not any(c.strip() for c in r[1:7]):
                    continue  # blank row
                rows.append({
                    "row": i,
                    "ts": r[0].strip(),
                    "trace_id": r[1].strip(),
                    "stage": r[2].strip() or "whole run",
                    "ref": r[3].strip().lower() if r[3].strip().lower() in VALID_REFS else "new",
                    "severity": r[4].strip() if r[4].strip() in SEVERITIES else "info",
                    "author": r[5].strip() or "anonymous reviewer",
                    "comment": r[6].strip(),
                    "status": r[7].strip() if r[7].strip() in STATUS_VALUES else "open",
                })
        except Exception as e:
            print(f"RiskNotes unavailable ({e})")
            rows = []
        rows.reverse()  # newest first
        _cache.update(ts=now, rows=rows)
    rows = _cache["rows"]
    if trace_id:
        return [n for n in rows if n["trace_id"] == trace_id]
    return list(rows)


def add_note(trace_id, stage, ref, severity, author, comment):
    """Append one observation. Caller validates inputs (routes do)."""
    _ws().append_row(
        [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         trace_id, stage, ref, severity, author, comment, "open"],
        value_input_option="RAW")
    _cache["ts"] = 0  # invalidate


def set_status(row, status):
    """Triage one note: open / confirmed / dismissed. row = sheet row number."""
    if status not in STATUS_VALUES:
        return False
    _ws().update_cell(row, 8, status)
    _cache["ts"] = 0
    return True
