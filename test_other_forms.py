import sys

sys.dont_write_bytecode = True

import openai_reports as orp
from wellbeing_fields import (
    ARCHETYPES, LESSON_HEADERS, POST_HEADERS, PRE_HEADERS, SELF_HEADERS,
    gen_lesson_fields, gen_post_fields, gen_pre_fields, gen_self_fields,
)


def check_sheet(title, headers, key_col, demo_ids, expect_demo_rows, filled_cols):
    ws = orp.gc.open(title).sheet1
    header = ws.row_values(1)
    for h in headers:
        assert h in header, f"{title}: missing header '{h}'"
    rows = ws.get_all_values()[1:]
    demo_filled = demo_total = real_touched = 0
    for row in rows:
        key = row[key_col].strip() if len(row) > key_col else ""
        if key in demo_ids:
            demo_total += 1
            if all(len(row) > c and row[c].strip() for c in filled_cols):
                demo_filled += 1
        elif key and key != "test1" and any(len(row) > c and row[c].strip() for c in filled_cols):
            real_touched += 1
    assert demo_filled == expect_demo_rows, f"{title}: {demo_filled}/{expect_demo_rows} demo rows filled"
    assert real_touched == 0, f"{title}: {real_touched} real rows touched!"
    print(f"{title}: {demo_filled} demo rows filled, schema OK, real rows untouched")


DEMO_IDS = set(ARCHETYPES)
check_sheet("SelfAssessment", SELF_HEADERS, 1, DEMO_IDS, 36, (5, 6, 7))
check_sheet("PreAssessment", PRE_HEADERS, 1, DEMO_IDS, 12, (6, 7, 8))
check_sheet("PostAssessment", POST_HEADERS, 1, DEMO_IDS, 12, (5, 6, 7))
check_sheet("LessonAssessment", LESSON_HEADERS, 1, {"ΜΓ1", "ΜΔ2"}, 16, (6, 7, 8, 9))

# generator sanity -------------------------------------------------------------
# demo10 anxious: teacher view ~4.3, self-efficacy must be notably lower (the gap)
v = gen_self_fields("demo10", [4, 4, 4, 4, 3], 5)
assert int(v[0]) <= 3, f"anxious self-efficacy should lag teacher view, got {v[0]}"
# demo06 social_strong overestimates a weak cognitive session
v = gen_self_fields("demo06", [5, 2, 2, 2, 5], 4)
assert int(v[0]) >= 3, f"social-strong self-view should overestimate, got {v[0]}"
# demo11 parent blindspot: high post scores despite low pre expectations
assert int(gen_post_fields("demo11")[1]) >= 4
# the chaos session is pinned at 2s
v = gen_lesson_fields("ΜΔ2", "2", 4)
assert v[:3] == ["2", "2", "2"] and "Substitute" in v[3]
# every lesson moment exists
for g in ("ΜΓ1", "ΜΔ2"):
    for i in range(8):
        assert gen_lesson_fields(g, "4", i)[3], (g, i)
print("generators: anxious gap, over-estimation, blindspot, chaos session — all coherent")

# prompt guides ----------------------------------------------------------------
p_self = orp.generatePrompt("Self", "x", "n", 1, 1, "d", "q", "r", "Student demo99")
p_post = orp.generatePrompt("Post Parent", "x", "n", 1, 1, "d", "q", "r", "Student demo99")
p_lesson = orp.generatePromptLesson("Lesson", "c", "x", "n", 1, 1, "d", "q", "r", "L")
p_class = orp.generatePromptClass("Class", "x", "n", 1, 1, "d", "q", "r", "L")
assert "OWN view" in p_self and "help-seeking" in p_self
assert "TRANSFER" in p_post
assert "CLASS framework" in p_lesson and "CLASS framework" in p_class
print("prompts: Self / Post / Lesson / Class interpretation guides wired")

print("OK")
