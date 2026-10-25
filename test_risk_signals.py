import os
import sys

sys.dont_write_bytecode = True

import pipeline_trace as pt

# find a sandbox trace with scrub disabled
for f in os.listdir("traces"):
    t = pt.load_trace(f[:-5])
    if not t:
        continue
    for e in t.get("events", []):
        if e["stage"] == "scrub" and (e.get("masks") or {}).get("disabled"):
            vx = pt.run_resources(t)
            sigs, _ = pt.detect_risk_signals(t, vx)
            print("sandbox trace", t["run_id"], "->", [s["title"] for s in sigs])
            break
    else:
        continue
    break

import app as a

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})
r = c.get("/pipeline/224b4560a245")
print("status:", r.status_code)
html = r.get_data(as_text=True)
for probe in ["Risk signals in this run", "Controls observed working", "Est. cost",
              "Estimated run cost", "Where the time went", "timing-bar",
              "Risk lens at this stage", "Human decision recorded", "#r2"]:
    print(f"{probe!r:38}", probe in html)

r2 = c.get("/risk-register")
h2 = r2.get_data(as_text=True)
print("register anchors:", all(f'id="r{i}"' in h2 for i in range(1, 11)))

import re
print("cost chips:", re.findall(r"~\$[0-9.]+", html))
print("bar widths:", re.findall(r'timing-bar" style="width: ([0-9.]+)%', html))
print("lens links:", re.findall(r"risk-register.#(r\d+)", html)[:10])
