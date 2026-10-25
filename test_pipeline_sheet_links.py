import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True

import app as a
import openai_reports as orp
import pipeline_trace as pt

# synthetic report trace in a temp dir (never touch the real traces)
tmp = tempfile.mkdtemp(prefix="eva-sheetlinks-test-")
pt.TRACES_DIR = tmp

run_id = "a1b2c3d4e5f6"
trace = {
    "run_id": run_id, "kind": "report", "label": "TEST synthetic",
    "model": "openai/gpt-5-nano",
    "started": "2026-10-21T10:00:00", "finished": "2026-10-21T10:00:05",
    "status": "ok", "note": "",
    "summary": {"counts": {"fetch": 1, "llm": 1, "save": 1},
                "alerts": 0, "critic_fails": 0, "errors": 0,
                "llm_calls": 1, "duration_ms": 5000},
    "events": [
        {"t": "2026-10-21T10:00:00.000", "dt_ms": 0, "stage": "fetch",
         "sources": [{"sheet": "Students", "rows": 12},
                     {"sheet": "PreAssessment", "rows": 12}]},
        {"t": "2026-10-21T10:00:01.000", "dt_ms": 1000, "stage": "scrub",
         "masks": {"name": 12}},
        {"t": "2026-10-21T10:00:02.000", "dt_ms": 1000, "stage": "llm",
         "model": "openai/gpt-5-nano", "prompt_tokens": 900,
         "completion_tokens": 300, "latency_ms": 1800},
        {"t": "2026-10-21T10:00:04.000", "dt_ms": 2000, "stage": "save",
         "sheet": "ReportsFile"},
        {"t": "2026-10-21T10:00:05.000", "dt_ms": 1000, "stage": "insight",
         "stored": True},
    ],
    "samples": [],
}
with open(os.path.join(tmp, f"{run_id}.json"), "w", encoding="utf-8") as f:
    json.dump(trace, f)

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})

orp._sheet_links_cache.update(ts=0, links=None)  # force fresh URL resolution
html = c.get(f"/pipeline/{run_id}").get_data(as_text=True)

n = html.count("docs.google.com/spreadsheets")
print("linked sheet names on trace page:", n)
# 4 sheets touched: Students, PreAssessment, ReportsFile, InsightsMemory
assert n == 4, f"expected 4 links, got {n}"
assert 'data-tip="Opens the real' in html
for name in ["Students", "PreAssessment", "ReportsFile", "InsightsMemory"]:
    assert f">{name} ↗</a>" in html, f"missing link for {name}"
assert "open the actual spreadsheets" in html
print("all 4 touched sheets linked in the Databases panel")
print("OK")
