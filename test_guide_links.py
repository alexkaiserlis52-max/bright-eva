import os
import sys

sys.dont_write_bytecode = True

import app as a
import openai_reports as orp

c = a.app.test_client()
c.post("/login", data={"password": os.environ.get("APP_PASSWORD", "")})

links = orp.sheet_links()
print("resolved:", len(links), "sheet URLs")
assert len(links) == 11, links

html = c.get("/guide").get_data(as_text=True)
n = html.count("docs.google.com/spreadsheets")
print("guide page links:", n)
assert n >= 11, "expected at least 11 sheet links on the guide page"
for name in ["Students", "PreAssessment", "FoAssessment", "SelfAssessment",
             "PostAssessment", "LessonAssessment", "Lessons", "ReportsFile",
             "InsightsMemory", "StyleMemory", "RiskNotes"]:
    assert f">{name} ↗</a>" in html, f"missing link for {name}"
print("all 11 sheets linked on the guide page")
print("OK")
