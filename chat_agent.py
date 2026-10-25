"""Bright E.V.A. — agentic chat (ReAct loop over OpenRouter tool-calling).

The chat model decides which tools to call; each tool grounds its answer in
the real sheets (L0), the saved reports (L1) or the insight cards (L2), and
in the lesson-plans Drive folder. The final answer is token-streamed to the
browser over SSE.

Privacy: tools return IDs and pseudonyms only — never real names (the sheet
itself is anonymized anyway).
"""
import io
import json
import re
from datetime import date as _date

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import openai_reports as orp  # sheet handles are set lazily — always use orp.X
import pipeline_trace as pt
from openai_reports import (
    get_client, MODEL, gc, _connect_sheets,
    scrub_all_students, parse_flexible_date,
    search_insights,
    ChildrenAssessemnt, classAssessment, LessonAssessment,
)

MAX_STEPS = 6
DRIVE_ROOT_FOLDER = "12zoXQXphYhy0J-9lGF7YUPAKbOpUW-TT"  # "STEM & ΡΟΜΠΟΤΙΚΗ" lesson plans

SYSTEM_PROMPT = """You are E.V.A. (Evaluation Virtual Assistant), the AI assistant of a robotics \
and STEM school. You answer educators' questions about students, class groups, lessons and \
teaching quality using the school's data tools.

Rules:
- Ground every factual claim in tool results. Never invent scores, dates or observations.
- Refer to students by ID only. Never ask for, guess or use real names (GDPR).
- For one student: get_student_overview, then search_insights for deeper history.
- For a class group: get_class_climate. For comparisons: compare_students.
- For lesson content/design questions: get_lesson_plan (track = 2-letter lesson prefix).
- Use generate_report ONLY when the user explicitly asks for a full fresh report \
(it takes about a minute). Warn that it is slow before calling it.
- Answer in English only, always — even if the user writes in Greek or tool \
results contain Greek, translate and reply in English. Never output Greek text.
- Be concise. Use short headings and bullets when it helps."""


# ---------------------------------------------------------------------------
# Tool implementations — sheets (L0/L1/L2)
# ---------------------------------------------------------------------------

def _avg(values):
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 2) if nums else None


def _to_float(v):
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


_FO_DIMS = ["Participation in class (1-5)", "Concept comprehension (1-5)",
            "Build completion (1-5)", "Programming skills (1-5)",
            "Cooperation (1-5)"]
_FO_DIM_EN = {"Participation in class (1-5)": "participation",
              "Concept comprehension (1-5)": "comprehension",
              "Build completion (1-5)": "build",
              "Programming skills (1-5)": "programming",
              "Cooperation (1-5)": "collaboration"}


def _student_score_summary(sid):
    """Averages + trend of the 5 formative dimensions for one student."""
    _connect_sheets()
    header = orp.FoAssesment.row_values(1)
    i_id = header.index("Student ID")
    i_ts = header.index("Timestamp")
    i_notes = header.index("Teacher observations")
    dims = {d: [] for d in _FO_DIMS}
    dates, notes = [], []
    for row in orp.FoAssesment.get_all_values()[1:]:
        if len(row) <= i_id or row[i_id].strip() != sid:
            continue
        for d in _FO_DIMS:
            v = _to_float(row[header.index(d)]) if len(row) > header.index(d) else None
            if v is not None:
                dims[d].append(v)
        try:
            dates.append(parse_flexible_date(row[i_ts]))
        except Exception:
            pass
        if len(row) > i_notes and row[i_notes].strip():
            notes.append(scrub_all_students(row[i_notes].strip()))
    if not dates:
        return None
    avg = {_FO_DIM_EN[d]: _avg(v) for d, v in dims.items()}
    # trend = mean of last 3 minus mean of first 3 (overall, across dims)
    flat_first = [v for d in dims.values() for v in d[:3]]
    flat_last = [v for d in dims.values() for v in d[-3:]]
    trend = None
    if flat_first and flat_last:
        trend = round(_avg(flat_last) - _avg(flat_first), 2)
    return {
        "assessments": len(dates),
        "first": min(dates).isoformat(),
        "last": max(dates).isoformat(),
        "averages": avg,
        "trend_last3_minus_first3": trend,
        "recent_teacher_notes": notes[-3:],
    }


def tool_get_student_overview(student_id):
    sid = str(student_id).strip()
    _connect_sheets()
    header = orp.Students.row_values(1)
    row = next((r for r in orp.Students.get_all_values()[1:] if r and r[0] == sid), None)
    if row is None:
        return json.dumps({"error": f"Student {sid} not found."}, ensure_ascii=False)
    i_l1 = header.index("Lesson ID 1")
    groups = [g.strip() for g in row[i_l1:i_l1 + 4] if g.strip()]
    info = {
        "student_id": sid,
        "age_class": row[header.index("Age/Grade")] if "Age/Grade" in header else "",
        "groups": groups,
    }
    scores = _student_score_summary(sid)
    info["formative_summary"] = scores or "no formative assessments yet"
    cards = search_insights(sid, limit=1)
    if cards:
        c = cards[-1]
        info["latest_insight"] = {
            "date": c[3], "trajectory": c[4], "cognitive": c[5],
            "soft_skills": c[6], "risk_flags": c[7], "alert": c[8], "takeaway": c[10],
        }
    return json.dumps(info, ensure_ascii=False)


def tool_search_insights(query="", entity_id="", limit=8):
    rows = search_insights(entity_id.strip() or None, limit=200)
    if query.strip():
        terms = [t.lower() for t in query.split() if len(t) > 2]
        if terms:
            rows = [r for r in rows if any(t in " ".join(r).lower() for t in terms)]
    rows = rows[-int(limit):]
    if not rows:
        return "No insight cards match."
    out = []
    for r in rows:
        out.append(f"[{r[1]} {r[2]} | {r[3]}] trajectory={r[4]} | cognitive: {r[5]} | "
                   f"soft: {r[6]} | risks: {r[7]} | alert: {r[8]} | takeaway: {r[10]}")
    return "\n".join(out)


def tool_get_class_climate(group_code):
    code = str(group_code).strip()
    less = gc.open('LessonAssessment').sheet1
    header = less.row_values(1)
    i_code = header.index("Group code")
    i_date = header.index("Date")
    i_resp = header.index("How did the class respond? (1-5)")
    i_pct = header.index("Activity completion rate (%)")
    i_diff = header.index("Difficulties encountered")
    i_notes = header.index("Notes")
    resps, pcts, dates, diffs, notes = [], [], [], [], []
    for row in less.get_all_values()[1:]:
        if len(row) <= i_code or row[i_code].strip() != code:
            continue
        r, p = _to_float(row[i_resp]), _to_float(row[i_pct])
        if r is not None:
            resps.append(r)
        if p is not None:
            pcts.append(p)
        try:
            dates.append(parse_flexible_date(row[i_date]))
        except Exception:
            pass
        if row[i_diff].strip():
            diffs.append(f"{row[i_date]}: {row[i_diff].strip()}")
        if row[i_notes].strip():
            notes.append(f"{row[i_date]}: {row[i_notes].strip()}")
    _connect_sheets()
    sh_ = orp.Students.row_values(1)
    i_l1 = sh_.index("Lesson ID 1")
    members = [r[0] for r in orp.Students.get_all_values()[1:]
               if r and any(g.strip() == code for g in r[i_l1:i_l1 + 4])]
    info = {
        "group": code,
        "students_in_group": len(members),
        "student_ids": members,
        "sessions_assessed": len(dates),
        "avg_response_1_5": _avg(resps),
        "avg_completion_pct": _avg(pcts),
        "date_range": [min(dates).isoformat(), max(dates).isoformat()] if dates else None,
        "recent_difficulties": diffs[-3:],
        "recent_notes": notes[-3:],
    }
    cards = search_insights(code, limit=1)
    if cards:
        c = cards[-1]
        info["latest_insight"] = {"date": c[3], "trajectory": c[4], "alert": c[8], "takeaway": c[10]}
    return json.dumps(info, ensure_ascii=False)


def tool_compare_students(student_ids):
    ids = [s.strip() for s in re.split(r"[,\s]+", str(student_ids)) if s.strip()]
    if len(ids) < 2:
        return json.dumps({"error": "Provide at least two student IDs."})
    table = {}
    for sid in ids[:8]:
        s = _student_score_summary(sid)
        cards = search_insights(sid, limit=1)
        table[sid] = {
            "formative": ({"assessments": s["assessments"], "averages": s["averages"],
                           "trend": s["trend_last3_minus_first3"]} if s else "no data"),
            "latest_trajectory": cards[-1][4] if cards else "no insight yet",
        }
    return json.dumps(table, ensure_ascii=False)


def tool_generate_report(entity_type, entity_id, question=""):
    etype = str(entity_type).strip().lower()
    eid = str(entity_id).strip()
    q = question.strip() or "Overall progress and key recommendations"
    role = "An experienced robotics educator summarizing for colleagues"
    today = _date.today().isoformat()
    if etype == "student":
        report, _n, _s = ChildrenAssessemnt(eid, today, q, role, None)
    elif etype == "class":
        report = classAssessment(eid, today, q, role, None)
    elif etype == "lesson":
        report = LessonAssessment(eid, today, q, role, None)
    else:
        return json.dumps({"error": "entity_type must be student, class or lesson."})
    return report[:6000]


# ---------------------------------------------------------------------------
# Tool: lesson plans from the Drive folder
# ---------------------------------------------------------------------------

_drive = None
_drive_listing_cache = {}

# lesson prefix -> candidate track-folder names in the Drive folder
_TRACK_FOLDERS = {
    "ΜΒ": ["προσχολικη"],
    "ΜΓ": ["jr 1", "jr 2"],
    "ΜΔ": ["advanced 1", "advanced 2"],
    "ΜΕ": ["expert 0.5", "expert 1"],
    "ΜΛ": ["minecraft"],
}


def _get_drive():
    global _drive
    if _drive is None:
        from openai_reports import credentials
        _drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return _drive


def _drive_list(folder_id):
    if folder_id in _drive_listing_cache:
        return _drive_listing_cache[folder_id]
    files, token = [], None
    while True:
        resp = _get_drive().files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id,name,mimeType)",
            pageSize=200, pageToken=token,
        ).execute()
        files.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    _drive_listing_cache[folder_id] = files
    return files


def _drive_download_text(file):
    """Download a Drive file as text (Google-native docs are exported)."""
    srv = _get_drive()
    if file["mimeType"].startswith("application/vnd.google-apps."):
        data = srv.files().export_media(fileId=file["id"], mimeType="text/plain").execute()
        return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, srv.files().get_media(fileId=file["id"]))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    if file["name"].lower().endswith(".docx"):
        from docx import Document
        doc = Document(fh)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return fh.read().decode("utf-8", errors="replace")


def tool_get_lesson_plan(track, lesson_no):
    prefix = str(track).strip()[:2]
    try:
        n = int(str(lesson_no).strip())
    except ValueError:
        return json.dumps({"error": "lesson_no must be a number."})
    candidates = _TRACK_FOLDERS.get(prefix)
    if not candidates:
        return json.dumps({"error": f"No lesson-plan track known for {prefix}. "
                                    f"Available: {sorted(_TRACK_FOLDERS)}"})
    root = _drive_list(DRIVE_ROOT_FOLDER)
    track_dirs = [f for f in root
                  if f["mimeType"] == "application/vnd.google-apps.folder"
                  and any(c in f["name"].lower() for c in candidates)]
    # Lesson folders are named inconsistently ("ΜΑΘΗΜΑ 26", "22 ΜΑΘΗΜΑ - ΑΠΟΚΡΙΕΣ",
    # "18ο ΜΑΘΗΜΑ") — match by the first number in the folder name.
    def _lesson_no(name):
        m = re.search(r"\d+", name)
        return int(m.group(0)) if m else None

    for td in track_dirs:
        lesson_dir = next((f for f in _drive_list(td["id"])
                           if f["mimeType"] == "application/vnd.google-apps.folder"
                           and _lesson_no(f["name"]) == n), None)
        if not lesson_dir:
            continue
        files = [f for f in _drive_list(lesson_dir["id"]) if not f["name"].startswith("~$")]
        plan = next((f for f in files if "περίγραμμα" in f["name"].lower()), None)
        if not plan:
            return json.dumps({"error": f"Lesson folder '{lesson_dir['name']}' has no ΠΕΡΙΓΡΑΜΜΑ file.",
                               "files_present": [f["name"] for f in files]}, ensure_ascii=False)
        text = _drive_download_text(plan)
        return json.dumps({"track": td["name"], "lesson": lesson_dir["name"],
                           "file": plan["name"], "content": text[:4000]}, ensure_ascii=False)
    return json.dumps({"error": f"Lesson {n} not found in track(s) for {prefix} "
                                f"(looked in: {[t['name'] for t in track_dirs]})."},
                      ensure_ascii=False)


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------

TOOL_FUNCS = {
    "get_student_overview": lambda a: tool_get_student_overview(a.get("student_id", "")),
    "search_insights": lambda a: tool_search_insights(a.get("query", ""), a.get("entity_id", ""), a.get("limit", 8)),
    "get_class_climate": lambda a: tool_get_class_climate(a.get("group_code", "")),
    "compare_students": lambda a: tool_compare_students(a.get("student_ids", "")),
    "generate_report": lambda a: tool_generate_report(a.get("entity_type", ""), a.get("entity_id", ""), a.get("question", "")),
    "get_lesson_plan": lambda a: tool_get_lesson_plan(a.get("track", ""), a.get("lesson_no", "")),
}

TOOLS = [
    {"type": "function", "function": {
        "name": "get_student_overview",
        "description": "Fast facts about one student: age/class, group(s), formative score averages (participation, comprehension, build, programming, collaboration), trend, recent teacher notes and the latest insight card.",
        "parameters": {"type": "object", "properties": {
            "student_id": {"type": "string", "description": "Student ID, e.g. demo02"}}, "required": ["student_id"]}}},
    {"type": "function", "function": {
        "name": "search_insights",
        "description": "Search the L2 insight cards (distilled memory) across students/classes/lessons. Filter by free-text query and/or an entity ID.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Keywords, e.g. 'declining collaboration'"},
            "entity_id": {"type": "string", "description": "Optional: limit to one student/group/lesson ID"},
            "limit": {"type": "integer", "description": "Max cards (default 8)"}}}}},
    {"type": "function", "function": {
        "name": "get_class_climate",
        "description": "Climate of a class group: session count, average response (1-5), average completion %, recent difficulties/notes, member IDs, latest class insight.",
        "parameters": {"type": "object", "properties": {
            "group_code": {"type": "string", "description": "Group code, e.g. ΜΓ1"}}, "required": ["group_code"]}}},
    {"type": "function", "function": {
        "name": "compare_students",
        "description": "Side-by-side comparison of 2-8 students: formative averages, trend and latest trajectory.",
        "parameters": {"type": "object", "properties": {
            "student_ids": {"type": "string", "description": "IDs separated by commas, e.g. 'demo02, demo07'"}}, "required": ["student_ids"]}}},
    {"type": "function", "function": {
        "name": "generate_report",
        "description": "SLOW (~1 minute): generate a full fresh report for one student, class group or lesson. Only when the user explicitly asks for a full report.",
        "parameters": {"type": "object", "properties": {
            "entity_type": {"type": "string", "enum": ["student", "class", "lesson"]},
            "entity_id": {"type": "string", "description": "Student ID, group code or lesson prefix"},
            "question": {"type": "string", "description": "What the report should focus on"}},
            "required": ["entity_type", "entity_id"]}}},
    {"type": "function", "function": {
        "name": "get_lesson_plan",
        "description": "Fetch the actual lesson plan (goals, phases, materials) for a lesson number of a track, from the school's Drive archive. Track = 2-letter lesson prefix (ΜΒ, ΜΓ, ΜΔ, ΜΕ, ΜΛ).",
        "parameters": {"type": "object", "properties": {
            "track": {"type": "string", "description": "Lesson prefix, e.g. ΜΓ"},
            "lesson_no": {"type": "integer", "description": "Lesson number in the track"}}, "required": ["track", "lesson_no"]}}},
]


def run_chat_stream(history, model=None):
    """Generator: runs the tool loop on `history` (mutated in place) and yields
    SSE-ready event dicts. Ends with the streamed final answer + 'done'."""
    model = model or MODEL
    client = get_client()

    for _step in range(MAX_STEPS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=history, tools=TOOLS, tool_choice="auto",
                max_tokens=1200)
        except Exception as e:
            yield {"type": "error", "text": f"Model call failed: {e}. "
                                            f"If you picked a small/custom model, try a tool-capable one (e.g. openai/gpt-4o-mini)."}
            return
        msg = resp.choices[0].message
        if not getattr(msg, "tool_calls", None):
            break  # model is ready to answer
        history.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool", "name": name, "args": args}
            func = TOOL_FUNCS.get(name)
            try:
                result = func(args) if func else f"Unknown tool {name}"
            except Exception as e:
                result = json.dumps({"error": f"Tool {name} failed: {e}"})
            pt.record("tool", name=name, args=args, result=str(result)[:4000])
            history.append({"role": "tool", "tool_call_id": call.id,
                            "name": name, "content": str(result)[:8000]})
    else:
        yield {"type": "error", "text": "Stopped after too many tool steps."}
        return

    # Final answer: force a text reply and token-stream it.
    try:
        stream = client.chat.completions.create(
            model=model, messages=history, tools=TOOLS, tool_choice="none",
            max_tokens=1500, stream=True)
        answer = []
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                answer.append(delta)
                yield {"type": "delta", "text": delta}
        history.append({"role": "assistant", "content": "".join(answer)})
    except Exception as e:
        yield {"type": "error", "text": f"Final answer failed: {e}"}
        return
    yield {"type": "done"}
