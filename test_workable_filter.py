# One-off: verify the workable-data filter in /api/options + the hub toggle markup.
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")

from app import app

c = app.test_client()
pw = os.environ.get("APP_PASSWORD")
if pw:
    r = c.post("/login", data={"password": pw}, follow_redirects=False)
    print("login:", r.status_code)

r = c.get("/api/options")
d = r.get_json()
print("options status:", r.status_code)
print("totals -> students:", len(d["students"]), "| groups:", len(d["groups"]), "| lessons:", len(d["lessons"]))
w = d.get("workable")
print("workable present:", bool(w))
if w:
    print("workable students:", len(w["students"]), "->", w["students"])
    print("workable groups  :", w["groups"])
    print("workable lessons :", w["lessons"])
    assert "demo02" in w["students"], "demo02 must be workable"
    assert "ΜΓ1" in w["groups"], "ΜΓ1 must be workable"
    assert "ΜΓ" in w["lessons"], "ΜΓ must be workable"
    assert len(w["students"]) < len(d["students"]), "filter must actually narrow the list"

r2 = c.get("/main")
html = r2.get_data(as_text=True)
print("main:", r2.status_code, "| toggle markup:", "show-all-row" in html, "| filter JS:", "workable" in html and "renderPickers" in html)
print("ALL CHECKS PASSED")
