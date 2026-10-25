import json
import os
import sys
import tempfile

sys.dont_write_bytecode = True

import app as a
import pipeline_trace as pt

# Never touch the real traces dir — patch it to a temp sandbox for this test.
pt.TRACES_DIR = tempfile.mkdtemp(prefix="eva-traces-test-")

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})

# seed 3 dummy traces (ids match the ^[0-9a-f]{12}$ validator)
def seed(rid, kind):
    with open(os.path.join(pt.TRACES_DIR, f"{rid}.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": rid, "kind": kind, "label": f"cleanup test {kind}",
                   "model": "test", "started": "2026-10-21", "status": "ok",
                   "summary": None, "events": [], "samples": []}, f)

for rid, kind in [("deadbeef0001", "report"), ("deadbeef0002", "sandbox"),
                  ("deadbeef0003", "chat")]:
    seed(rid, kind)
assert pt.load_trace("deadbeef0001") is not None

# 1 · list shows the housekeeping card
html = c.get("/pipeline").get_data(as_text=True)
for probe in ["Clean up", "Housekeeping", "/pipeline/clear"]:
    assert probe in html, f"MISSING on list: {probe}"
print("list page: cleanup card present")

# 2 · delete a single trace via its detail page button
html = c.get("/pipeline/deadbeef0001").get_data(as_text=True)
assert "Delete trace" in html and "/pipeline/deadbeef0001/delete" in html
r = c.post("/pipeline/deadbeef0001/delete")
assert r.status_code == 302
assert pt.load_trace("deadbeef0001") is None
print("single delete: trace deadbeef0001 removed")

# 3 · clear only sandbox runs
r = c.post("/pipeline/clear", data={"kind": "sandbox"})
assert r.status_code == 302
assert pt.load_trace("deadbeef0002") is None
assert pt.load_trace("deadbeef0003") is not None  # chat survived the filter
print("filtered clear: sandbox gone, chat kept")

# 4 · notice flashes on the list page
html = c.get("/pipeline").get_data(as_text=True)
assert "Removed 1 trace (kind: sandbox)." in html
print("notice: flashed correctly")

# 5 · clear everything left (temp dir only — real traces untouched)
r = c.post("/pipeline/clear", data={"kind": ""})
assert pt.load_trace("deadbeef0003") is None
print("clear all: done")

# 6 · path-traversal junk is rejected
assert not pt.delete_trace("../app")
assert not pt.delete_trace("NOT-HEX!")
print("validation: junk ids rejected")
print("OK")
