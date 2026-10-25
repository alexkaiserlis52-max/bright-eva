import os
import sys

sys.dont_write_bytecode = True

import app as a

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})

PAGES = ["/", "/main", "/chat", "/pipeline", "/sandbox", "/style",
         "/risk-register", "/guide"]

for p in PAGES:
    r = c.get(p)
    html = r.get_data(as_text=True)
    tips = html.count("data-tip=")
    print(f"{p:32} status={r.status_code}  tooltips={tips}")

# guide content probes
g = c.get("/guide").get_data(as_text=True)
for probe in ["The E.V.A. Guide", "g-what", "g-data", "g-pipeline", "g-anon",
              "g-ai", "g-memory", "g-tools", "g-safety", "g-glossary",
              "ReportsFile", "InsightsMemory", "StyleMemory", "OpenRouter",
              "Quasi-identifier", "Educator Override", "Early warning",
              "Gold exemplar", "ENGLISH_ONLY", "π.μ.", "ΜΓ1"]:
    assert probe in g, f"MISSING in /guide: {probe}"
print("guide probes: all present")

# tooltip infra present on every app page (intro "/" is a standalone landing, no base.html)
for p in PAGES[1:]:
    html = c.get(p).get_data(as_text=True)
    assert "eva.css" in html
css = open("static/css/eva.css", encoding="utf-8").read()
for probe in ["[data-tip]::after", '.tip {', '[data-tip-pos="east"]',
              '[data-tip-pos="bottom"]', '[data-tip-pos="west"]',
              "a.chat-tool-chip"]:
    assert probe in css, f"MISSING in eva.css: {probe}"
print("css probes: all present")

# guide nav link visible
m = c.get("/main").get_data(as_text=True)
assert "/guide" in m, "Guide link missing from nav"
print("nav guide link: present")
print("OK")
