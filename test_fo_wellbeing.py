import sys

sys.dont_write_bytecode = True

import openai_reports as orp
from wellbeing_fields import ARCHETYPES, NEW_HEADERS, generate_fields

# 1) sheet schema: 18 columns, new headers present in order
ws = orp.gc.open("FoAssessment").sheet1
header = ws.row_values(1)
assert len(header) >= 18, f"expected >= 18 cols, got {len(header)}"
for i, h in enumerate(NEW_HEADERS):
    assert header[8 + i] == h, f"col {9 + i}: expected '{h}', got '{header[8 + i]}'"
print("schema: 10 new columns in place (cols 9-18)")

# 2) data: all 96 demo rows filled, real-student rows untouched
rows = ws.get_all_values()[1:]
demo_filled = demo_total = 0
real_touched = 0
for row in rows:
    sid = row[1].strip() if len(row) > 1 else ""
    if sid in ARCHETYPES:
        demo_total += 1
        if len(row) > 8 and row[8].strip():
            demo_filled += 1
    elif sid and sid != "test1" and len(row) > 8 and row[8].strip():
        real_touched += 1
assert demo_filled == demo_total == 96, (demo_filled, demo_total)
assert real_touched == 0, f"{real_touched} real-student rows were modified!"
print("data: 96/96 demo rows filled, 0 real-student rows touched")

# 3) generator sanity: values in range, coherence with archetype
for sid in ARCHETYPES:
    for idx in range(8):
        vals = generate_fields(sid, [3, 3, 3, 3, 3], idx)
        assert len(vals) == 10
        for v in vals[:6]:
            if v:
                assert v in "12345", (sid, idx, v)
demo9_last = generate_fields("demo09", [1, 1, 1, 1, 1], 7)
assert demo9_last[0] in ("1", "2"), "disengaged finale should have low mood"
assert "no participation" in demo9_last[9]
demo12_abs = generate_fields("demo12", [1, 1, 1, 1, 2], 3)
assert "absent" in demo12_abs[6] and "Absent" in demo12_abs[7]
print("generator: ranges valid, disengaged/absence narratives coherent")

# 4) prompt: the FORMATIVE interpretation guide is wired into the formative
# extractor; its content must not leak into the Self prompt (Self has its own
# guide since the other-forms work).
p_student = orp.generatePrompt("Student", "x", "none yet", 1, 1, "d", "q", "r", "Student demo99")
p_self = orp.generatePrompt("Self", "x", "none yet", 1, 1, "d", "q", "r", "Student demo99")
assert "Interpretation guide" in p_student
assert "Leuven" in p_student and "never as a diagnosis" in p_student
assert "Leuven" not in p_self and "diagnosis" not in p_self
print("prompt: well-being interpretation guide wired into the formative extractor only")

print("OK")
