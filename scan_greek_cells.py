"""One-off: scan all sheets for cells containing Greek characters."""
import re
from dotenv import load_dotenv
load_dotenv()

import openai_reports as orp

orp._connect_sheets()
GREEK = re.compile(r"[Α-Ωα-ωΆ-ώΪΫήϊϋΰΐ]")

for name in ("Students", "PreAssessment", "FoAssessment", "SelfAssessment",
             "PostAssessment", "LessonAssessment", "ReportsFile", "InsightsMemory"):
    try:
        ws = orp.gc.open(name).sheet1
    except Exception as e:
        print(f"{name}: cannot open ({e})")
        continue
    rows = ws.get_all_values()
    if not rows:
        continue
    header = rows[0]
    counts = {}
    for r in rows[1:]:
        for i, cell in enumerate(r):
            if cell and GREEK.search(cell):
                col = header[i] if i < len(header) else f"col{i}"
                counts[col] = counts.get(col, 0) + 1
    print(f"{name} ({len(rows)-1} rows): {counts}")

# Lessons has two tabs
try:
    ls = orp.gc.open("Lessons")
    for ti in (0, 1):
        ws = ls.get_worksheet(ti)
        rows = ws.get_all_values()
        header = rows[0]
        counts = {}
        for r in rows[1:]:
            for i, cell in enumerate(r):
                if cell and GREEK.search(cell):
                    col = header[i] if i < len(header) else f"col{i}"
                    counts[col] = counts.get(col, 0) + 1
        print(f"Lessons tab{ti+1} ({len(rows)-1} rows): {counts}")
except Exception as e:
    print(f"Lessons: {e}")
