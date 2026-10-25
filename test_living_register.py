import os
import sys

sys.dont_write_bytecode = True

import app as a
import risk_notes as rn

TRACE = "224b4560a245"
MARKER = "TEST-NOTE living-register roundtrip"

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})

# 1 · register an observation via the trace form
r = c.post(f"/pipeline/{TRACE}/risk-note", data={
    "stage": "llm", "ref": "r2", "severity": "warn",
    "author": "test-bot", "comment": MARKER,
})
print("POST note:", r.status_code, "->", r.headers.get("Location", ""))
assert r.status_code == 302

notes = [n for n in rn.list_notes(TRACE, force=True) if MARKER in n["comment"]]
assert len(notes) == 1, f"note not found in sheet: {notes}"
note = notes[0]
print("note stored:", {k: note[k] for k in ("row", "stage", "ref", "severity", "author", "status")})

# 2 · visible on the trace page
html = c.get(f"/pipeline/{TRACE}").get_data(as_text=True)
for probe in ["risk-notes", "register-risk", MARKER, "Register a risk",
              "Human risk observations", "register an observation at this stage"]:
    assert probe in html, f"MISSING on trace page: {probe}"
print("trace page: all sections present")

# 3 · triage: confirm it
r = c.post(f"/risk-note/{note['row']}/status",
           data={"status": "confirmed", "back": "/risk-register#r2"})
print("POST status:", r.status_code, "->", r.headers.get("Location", ""))
assert r.status_code == 302 and r.headers["Location"].endswith("#r2")
note2 = [n for n in rn.list_notes(TRACE, force=True) if MARKER in n["comment"]][0]
assert note2["status"] == "confirmed", note2["status"]
print("triage: status -> confirmed")

# 4 · visible on the living register, grouped under r2, stats right
html = c.get("/risk-register").get_data(as_text=True)
for probe in ["Living Risk Register", MARKER, "candidates", 'id="r2"', 'id="r10"',
              "1 confirmed", "observation"]:
    assert probe in html, f"MISSING on register: {probe}"
print("register page: observation listed, stats updated")

# 5 · a 'new' candidate note
r = c.post(f"/pipeline/{TRACE}/risk-note", data={
    "stage": "save", "ref": "new", "severity": "info",
    "author": "", "comment": MARKER + " candidate",
})
assert r.status_code == 302
html = c.get("/risk-register").get_data(as_text=True)
assert MARKER + " candidate" in html and "anonymous reviewer" in html
print("candidate note: listed under reviewer-identified risks")

# cleanup — remove both test rows from the sheet
ws = rn._ws()
for n in [n for n in rn.list_notes(TRACE, force=True) if MARKER in n["comment"]]:
    ws.delete_rows(n["row"])
    rn._cache["ts"] = 0
left = [n for n in rn.list_notes(TRACE, force=True) if MARKER in n["comment"]]
assert not left, "cleanup failed"
print("cleanup: test rows deleted")
print("OK")
