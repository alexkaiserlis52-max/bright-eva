"""Guide mechanics section: page renders, anchors renumbered, inline SVGs well-formed."""
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

from app import app

c = app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})
r = c.get("/guide")
assert r.status_code == 200, r.status_code
html = r.get_data(as_text=True)

# new section + renumbered anchors
for anchor in ("g-mech", "g-what", "g-data", "g-pipeline", "g-anon",
               "g-ai", "g-memory", "g-tools", "g-safety", "g-glossary"):
    assert f'id="{anchor}"' in html, f"missing anchor {anchor}"
for chip in ("4 · How each feature works", "5 · Anonymization", "10 · Glossary"):
    assert chip in html, f"missing TOC/section text: {chip}"

# five figures, unique marker ids, figure/figcaption/aria wiring
svgs = [s for s in re.findall(r"<svg.*?</svg>", html, re.S) if 'role="img"' in s]
assert len(svgs) == 5, f"expected 5 figure SVGs, got {len(svgs)}"
for i, s in enumerate(svgs):
    assert "aria-label" in s, f"svg {i} missing a11y attrs"
    ET.fromstring(s)  # raises on malformed markup
    assert f"arw{chr(65 + i)}" in s, f"svg {i} missing its marker id"
assert html.count("<figcaption>") == 5
assert html.count('class="fig-h"') == 5
print("guide: 200, 10 anchors, 5 well-formed SVG figures (A-E), captions + legend OK")

# old numbering must be gone
assert "9 · Glossary" not in html
assert ">4 · Anonymization" not in html
print("renumbering clean")
print("OK")
