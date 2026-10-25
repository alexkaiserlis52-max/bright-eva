from openai import OpenAI
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
import os
import re
from textwrap import dedent
import json
import time
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

import pipeline_trace as pt

load_dotenv()

# ---------------------------------------------------------------------------
# Anonymization (GDPR — the Students sheet holds data of MINORS).
# Rule: nothing that identifies a child may leave our systems towards the LLM.
# The sheet keeps the real data (the school needs it for contact), but every
# prompt is scrubbed first: names -> [Student]/[Parent], emails -> [email],
# phones -> [phone]. Only the pseudonymous student ID ever reaches the model.
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
_PHONE_RE = re.compile(r'(?<!\d)\+?\d[\d\s().\-]{7,}\d(?!\d)')
# Greek nominative endings — a name's stem catches genitive forms too
# (e.g. "Γιάννης" -> stem "Γιάνν" matches "του Γιάννη").
_GREEK_NOM_SUFFIXES = ("ής", "ής", "ος", "ας", "ές", "ης")

# Tokens that are common nouns, not names — never masked (a real registry
# entry was literally named "Μαθητής", which masked the word "student"
# everywhere and tripped the critic's PII detector on every Greek report).
_SCRUB_STOPWORDS = {"μαθητής", "μαθητή", "μαθητές", "μαθητών", "student", "parent", "γονέας"}


def _pii_patterns(token):
    """Compiled match patterns for one PII token (direct + Greek genitive stem).

    Latin tokens match CASE-SENSITIVELY: names are capitalized in prose, so
    this avoids masking common words that collide with names (the fake-name
    registry contains e.g. "Foster" — "foster independence" is not a name).
    Greek tokens stay case-insensitive (the pre-migration backup names are
    the ones that actually matter for privacy).
    """
    pats = []
    if token.isascii():
        pats.append(re.compile(r'\b' + re.escape(token) + r'\b'))
    else:
        pats.append(re.compile(r'(?i)\b' + re.escape(token) + r'\b'))
        if len(token) >= 5 and token.endswith(_GREEK_NOM_SUFFIXES):
            pats.append(re.compile(r'(?i)\b' + re.escape(token[:-2]) + r'\w*'))
    return pats


def make_pii_scrubber(student_name="", student_surname="", parent_name="", stats=None):
    """Build a scrub(text) function replacing known PII tokens with placeholders.

    stats: optional dict that accumulates mask counts per placeholder (for the
    pipeline trace). Honours the sandbox guardrail switch — with scrubbing
    relaxed it is the identity function (dry-run experiments only).
    """
    pairs = []
    for token, placeholder in ((student_name, "[Student]"),
                               (student_surname, "[Student]"),
                               (parent_name, "[Parent]")):
        token = (token or "").strip()
        if len(token) >= 2 and token.lower() not in _SCRUB_STOPWORDS:
            pairs.append((_pii_patterns(token), placeholder, len(token)))
    pairs.sort(key=lambda p: p[2], reverse=True)  # longest first

    def _count(stats, placeholder, n):
        if stats is not None and n:
            stats[placeholder] = stats.get(placeholder, 0) + n

    def scrub(text):
        if not text:
            return text
        text = str(text)
        if not pt.scrub_enabled():
            if stats is not None:
                stats["disabled"] = stats.get("disabled", 0) + 1
            return text
        for patterns, placeholder, _len in pairs:
            for pat in patterns:
                text, n = pat.subn(placeholder, text)
                _count(stats, placeholder, n)
        text, n = _EMAIL_RE.subn("[email]", text)
        _count(stats, "[email]", n)
        text, n = _PHONE_RE.subn("[phone]", text)
        _count(stats, "[phone]", n)
        return text

    return scrub


def scrub_text(text, stats=None):
    """Scrub generic PII (emails, phones) when no per-student context exists."""
    if not text:
        return text
    if not pt.scrub_enabled():
        if stats is not None:
            stats["disabled"] = stats.get("disabled", 0) + 1
        return str(text)
    text, n1 = _EMAIL_RE.subn("[email]", str(text))
    text, n2 = _PHONE_RE.subn("[phone]", text)
    if stats is not None:
        if n1:
            stats["[email]"] = stats.get("[email]", 0) + n1
        if n2:
            stats["[phone]"] = stats.get("[phone]", 0) + n2
    return text


_students_scrubber_cache = {"scrub": None}


def scrub_all_students(text, stats=None):
    """Scrub using the names of EVERY student in the registry (cached per process).

    Used for texts that may mention arbitrary children (e.g. old saved reports
    fed back to the LLM by the ASK ME flows). Honours the sandbox guardrail
    switch; `stats` accumulates mask counts for the pipeline trace.
    """
    if not pt.scrub_enabled():
        if stats is not None and text:
            stats["disabled"] = stats.get("disabled", 0) + 1
        return str(text) if text else text
    if _students_scrubber_cache["scrub"] is None:
        names, surnames, parents = [], [], []
        try:
            _connect_sheets()
            header = Students.row_values(1)
            rows = Students.get_all_values()[1:]
            i_name = header.index("Name") if "Name" in header else None
            i_surname = header.index("Surname") if "Surname" in header else None
            i_parent = header.index("Parent") if "Parent" in header else None
            for row in rows:
                if i_name is not None and len(row) > i_name:
                    names.append(row[i_name])
                if i_surname is not None and len(row) > i_surname:
                    surnames.append(row[i_surname])
                if i_parent is not None and len(row) > i_parent:
                    parents.append(row[i_parent])
        except Exception as e:
            print(f"Anonymization warning: could not load student registry ({e})")
        # The sheet was anonymized on 2026-10-20 (real names replaced by fake
        # English ones). Older assessment rows may still mention the REAL names,
        # so we also scrub against the pre-migration backup list when present.
        # The backup never leaves this machine - it is only scrub vocabulary.
        try:
            import csv
            backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "students_backup_real_names_2026-10-20.csv")
            with open(backup_path, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            if rows:
                h = rows[0]
                for row in rows[1:]:
                    for col in ("Name", "Surname", "Γονέας"):
                        if col in h and len(row) > h.index(col):
                            names.append(row[h.index(col)])
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Anonymization warning: could not load legacy-name list ({e})")
        pairs = [(n, "[Student]") for n in names + surnames]
        pairs += [(p, "[Parent]") for p in parents]
        pairs = [(t.strip(), ph) for t, ph in pairs
                 if t and len(t.strip()) >= 2 and t.strip().lower() not in _SCRUB_STOPWORDS]
        pairs = [(_pii_patterns(t), ph, len(t)) for t, ph in pairs]
        pairs.sort(key=lambda p: p[2], reverse=True)

        def _scrub(text, _pairs=pairs, _stats=None):
            if not text:
                return text
            text = str(text)
            for patterns, placeholder, _len in _pairs:
                for pat in patterns:
                    text, n = pat.subn(placeholder, text)
                    if _stats is not None and n:
                        _stats[placeholder] = _stats.get(placeholder, 0) + n
            text, n = _EMAIL_RE.subn("[email]", text)
            if _stats is not None and n:
                _stats["[email]"] = _stats.get("[email]", 0) + n
            text, n = _PHONE_RE.subn("[phone]", text)
            if _stats is not None and n:
                _stats["[phone]"] = _stats.get("[phone]", 0) + n
            return text

        _students_scrubber_cache["scrub"] = _scrub
    return _students_scrubber_cache["scrub"](text, _stats=stats)

# OpenRouter: one OpenAI-compatible API, many models, switchable on the fly.
# Set OPENROUTER_API_KEY in .env (never hardcode it here).
# The client is created lazily so the app can boot even before a key is set.
_client = None
_tracing_client = None


def _traceable_messages(messages):
    """Compact, clipped copy of the messages payload for the pipeline trace."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            m = m.model_dump(exclude_none=True) if hasattr(m, "model_dump") else {"role": "?", "content": str(m)}
        entry = {"role": m.get("role"), "content": m.get("content")}
        if entry["content"] is not None and not isinstance(entry["content"], str):
            entry["content"] = "<structured content>"
        if m.get("tool_calls"):
            entry["tool_calls"] = [
                {"name": (tc.get("function") or {}).get("name"),
                 "args": (tc.get("function") or {}).get("arguments")}
                for tc in m["tool_calls"] if isinstance(tc, dict)]
        if m.get("name"):
            entry["name"] = m.get("name")
        out.append(entry)
    return out


class _TracingStream:
    """Wraps a streamed completion: accumulates the answer and records one
    'llm' trace event when the stream is exhausted (or closed)."""

    def __init__(self, stream, meta, t0):
        self._stream = stream
        self._meta = meta
        self._t0 = t0
        self._parts = []
        self._done = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._flush()
            raise
        try:
            delta = chunk.choices[0].delta.content if chunk.choices else None
        except Exception:
            delta = None
        if delta:
            self._parts.append(delta)
        return chunk

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def close(self):
        self._flush()
        if hasattr(self._stream, "close"):
            self._stream.close()

    def _flush(self):
        if self._done:
            return
        self._done = True
        pt.record("llm", **self._meta, response="".join(self._parts),
                  streamed=True, latency_ms=int((time.time() - self._t0) * 1000))


class _TracingCompletions:
    def __init__(self, real):
        self._real = real

    def create(self, **kwargs):
        t0 = time.time()
        try:
            resp = self._real.create(**kwargs)
        except Exception as e:
            pt.record("error", where="llm_call", model=kwargs.get("model"),
                      message=str(e)[:500])
            raise
        if pt.current_trace() is None:
            return resp
        meta = {
            "model": kwargs.get("model"),
            "messages": _traceable_messages(kwargs.get("messages")),
            "max_tokens": kwargs.get("max_tokens"),
            "tools": bool(kwargs.get("tools")),
        }
        if kwargs.get("tool_choice") not in (None, "auto"):
            meta["tool_choice"] = kwargs.get("tool_choice")
        if kwargs.get("stream"):
            return _TracingStream(resp, meta, t0)
        latency_ms = int((time.time() - t0) * 1000)
        msg = resp.choices[0].message if resp.choices else None
        tool_calls = []
        if msg is not None and getattr(msg, "tool_calls", None):
            tool_calls = [{"name": tc.function.name,
                           "args": tc.function.arguments}
                          for tc in msg.tool_calls]
        usage = getattr(resp, "usage", None)
        pt.record("llm", **meta,
                  response=(msg.content if msg else "") or "",
                  tool_calls=tool_calls,
                  prompt_tokens=getattr(usage, "prompt_tokens", None),
                  completion_tokens=getattr(usage, "completion_tokens", None),
                  latency_ms=latency_ms)
        return resp


class _TracingChat:
    def __init__(self, real):
        self.completions = _TracingCompletions(real.completions)


class _TracingClient:
    """Pass-through proxy: only chat.completions.create is intercepted."""

    def __init__(self, real):
        self._real = real
        self.chat = _TracingChat(real.chat)

    def __getattr__(self, name):
        return getattr(self._real, name)


def get_client():
    global _client, _tracing_client
    if _client is None:
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            default_headers={
                "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost:5000"),
                "X-Title": "Bright E.V.A.",
            },
        )
        _tracing_client = _TracingClient(_client)
    return _tracing_client

# Default model as an OpenRouter id (e.g. "anthropic/claude-sonnet-4.5").
# Override the default in .env (OPENROUTER_MODEL) or per request from the UI picker.
MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-5-nano")

# Hard output-language rule: source data may contain Greek (legacy notes,
# π.μ./μ.μ. date markers, group codes). Every LLM-facing output must be
# English regardless — this sentence is prepended to every prompt and
# appended to every system role.
ENGLISH_ONLY = ("IMPORTANT: Write your entire response in English only, regardless "
                "of the language of the source data. If any source content is in "
                "Greek, translate it — never output Greek text.")

# Per-assessment summarization calls are independent of each other, so they run
# concurrently (the old N+1 serial loop). Same number of calls, same order of
# results — wall-clock drops from sum(latencies) to max(latencies).
LLM_MAX_PARALLEL = int(os.environ.get("LLM_MAX_PARALLEL", "8"))


def _chat_text(messages, max_tokens, model, retries=2):
    """chat.completions.create with retries and null-content safety.

    Under parallel load providers occasionally return choices with
    content=null (transient edge). Retry briefly, then degrade to a
    placeholder instead of crashing the whole report.
    """
    for attempt in range(retries + 1):
        try:
            resp = get_client().chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens)
            content = resp.choices[0].message.content if resp.choices else None
            if content and content.strip():
                return content.strip()
            print(f"LLM call attempt {attempt + 1}: empty content")
        except Exception as e:
            print(f"LLM call attempt {attempt + 1} failed: {e}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    pt.record("note", kind="warning",
              message="LLM returned empty content after retries — placeholder used")
    return "(No summary could be generated for this assessment.)"


def _run_parallel(fn, count):
    """Run fn(i) for i in range(count) concurrently, preserving result order.

    Each worker thread gets its OWN copy of the current contextvars context, so
    the active pipeline trace and the guardrail/dry-run flags propagate into
    the threads (TraceRecorder itself is lock-guarded).
    """
    if count <= 0:
        return []
    if count == 1 or LLM_MAX_PARALLEL <= 1:
        return [fn(i) for i in range(count)]
    with ThreadPoolExecutor(max_workers=min(LLM_MAX_PARALLEL, count)) as ex:
        futures = [ex.submit(contextvars.copy_context().run, fn, i)
                   for i in range(count)]
        return [f.result() for f in futures]

# Authenticate with Google Sheets API using your service account credentials.
# Cloud: put the whole JSON into GOOGLE_SERVICE_ACCOUNT_JSON.
# Local: point GOOGLE_SERVICE_ACCOUNT_FILE at the JSON file.
scopes = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
_sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if _sa_json:
    credentials = Credentials.from_service_account_info(json.loads(_sa_json), scopes=scopes)
else:
    SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "insudies-e24d0d9618d5.json")
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=scopes
    )


def parse_flexible_date(date_string):
    """Parse dates coming from Google Forms/Sheets and the HTML forms.

    Greek locale markers: π.μ. = AM, μ.μ. = PM (they were swapped before).
    Returns a datetime.date so comparisons are chronological, not lexicographic.
    """
    date_string = str(date_string).strip().replace("π.μ.", "AM").replace("μ.μ.", "PM")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                "%d/%m/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M:%S %p"):
        try:
            return datetime.strptime(date_string, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {date_string!r}")

gc = gspread.authorize(credentials)

# Sheet handles open lazily (on first report request) so the app can boot
# before the sheets exist/are shared — a missing sheet must not kill the server.
PreAssesment = None
FoAssesment = None
SelfAssessment = None
Lessons = None
Students = None
PostAssessment = None
sh = None
_sheets_connected = False

def _connect_sheets():
    global PreAssesment, FoAssesment, SelfAssessment, Lessons, Students, PostAssessment, sh, _sheets_connected
    if _sheets_connected:
        return
    # Pre is for PreAssesment from the parent. Fo is from the teacher (can contain multiple assessments)
    PreAssesment = gc.open('PreAssessment').sheet1
    FoAssesment = gc.open('FoAssessment').sheet1
    SelfAssessment = gc.open('SelfAssessment').sheet1
    Lessons = gc.open('Lessons').get_worksheet(1)
    Students = gc.open('Students').sheet1
    PostAssessment = gc.open('PostAssessment').sheet1
    sh = gc.open('ReportsFile')
    _sheets_connected = True


#The function that produces the report for the students
def ChildrenAssessemnt(StudID, date, AssesType, role, save, model=None):
    model = model or MODEL
    _connect_sheets()
    # Open The sheets. Pre is for PreAssesment from the parent. Fo is from the teacher (can contain multiple assessments)

    headerPre = PreAssesment.row_values(1)
    headerFo = FoAssesment.row_values(1)
    headerSelf = SelfAssessment.row_values(1)
    headerPost = PostAssessment.row_values(1)
    headerLessons = Lessons.row_values(1)
    headerStudents = Students.row_values(1)

    PreAssesment_column_index = headerPre.index("Student ID") + 1
    FoAssesment_column_index = headerFo.index("Student ID") + 1
    PostAssesment_column_index = headerPost.index("Student ID") + 1
    headerLessons_column_index = headerLessons.index("Group code") + 1
    headerLessons_column_Description = headerLessons.index("Description")
    headerStudents_index = headerStudents.index("ID") + 1
    SelfAssesment_column_index = headerSelf.index("Student ID") + 1
    PreAssesment_date_index = headerPre.index("Timestamp") + 1
    FoAssesment_date_index = headerFo.index("Timestamp") + 1
    SelfAssesment_date_index = headerSelf.index("Timestamp") + 1
    PostAssesment_date_index = headerPost.index("Timestamp") + 1

    # Search for the matching row for Student
    matching_rows_for_Student = -1
    for row in Students.get_all_values()[1:]:
        if row[headerStudents_index - 1] == StudID:
            matching_rows_for_Student = row
            break
    if matching_rows_for_Student == -1:
        return "Student not found.", "none", "none"

    # Search for the matching rows
    matching_rows_for_Pre = []
    matching_rows_for_Fo = []
    matching_rows_for_Self = []
    matching_rows_for_Post = []

    target_date = parse_flexible_date(date)

    for row in PreAssesment.get_all_values()[1:]:
        if row[PreAssesment_column_index - 1] == StudID:
            matching_rows_for_Pre.append(row)

    for row in FoAssesment.get_all_values()[1:]:
        assessment_date = parse_flexible_date(row[FoAssesment_date_index - 1])
        if row[FoAssesment_column_index - 1] == StudID and assessment_date < target_date:
            matching_rows_for_Fo.append(row)

    for row in SelfAssessment.get_all_values()[1:]:
        if row[SelfAssesment_column_index - 1] == StudID:
            matching_rows_for_Self.append(row)

    for row in PostAssessment.get_all_values()[1:]:
        if row[PostAssesment_column_index - 1] == StudID:
            matching_rows_for_Post.append(row)

    # Creating a report on the Descriptions of the Lessons the Student Participates
    if matching_rows_for_Student != -1:
        StuLessons = []
        LessonDescrptions = []
        LessonsinString = "Description of the class the student attends. "
        StuLessonID1_index = headerStudents.index("Lesson ID 1")
        for i in range(4):
            if matching_rows_for_Student[StuLessonID1_index + i] != "":
                StuLessons.append(matching_rows_for_Student[StuLessonID1_index + i])
        name = matching_rows_for_Student[1] if matching_rows_for_Student[1] != "" else ""
        surname = matching_rows_for_Student[2] if matching_rows_for_Student[2] != "" else ""
        parent_name = ""
        if "Parent" in headerStudents:
            _pi = headerStudents.index("Parent")
            if len(matching_rows_for_Student) > _pi:
                parent_name = matching_rows_for_Student[_pi]
        # GDPR: the LLM never sees real names — scrub everything we send.
        scrub_stats = {}
        scrub = make_pii_scrubber(name, surname, parent_name, stats=scrub_stats)
        pseudonym = f"Student {StudID}"
        if not StuLessons:
            return "Student is not enrolled in any lesson.", "none", "none"
        for Lesson in StuLessons:
            i = 1
            for row in Lessons.get_all_values()[1:]:
                if row[headerLessons_column_index - 1] == Lesson:
                    LessonsinString += f"Lesson {i}: {row[headerLessons_column_Description]}. "
                    i += 1

    number_of_Pre_Assessments = len(matching_rows_for_Pre)
    number_of_Fo_Assessments = len(matching_rows_for_Fo)
    number_of_Self_Assessments = len(matching_rows_for_Self)
    number_of_Post_Assessments = len(matching_rows_for_Post)
    print(number_of_Post_Assessments)
    print(number_of_Pre_Assessments)
    print(number_of_Fo_Assessments)
    print(number_of_Self_Assessments)
    pt.record("fetch", entity=StudID, sources=[
        {"sheet": "Students", "rows": 1, "filter": f"ID = {StudID}"},
        {"sheet": "PreAssessment", "rows": number_of_Pre_Assessments, "filter": f"student = {StudID}"},
        {"sheet": "FoAssessment", "rows": number_of_Fo_Assessments, "filter": f"student = {StudID}, date < {date}"},
        {"sheet": "SelfAssessment", "rows": number_of_Self_Assessments, "filter": f"student = {StudID}"},
        {"sheet": "PostAssessment", "rows": number_of_Post_Assessments, "filter": f"student = {StudID}"},
        {"sheet": "Lessons", "rows": len(StuLessons), "filter": "student's lesson IDs"},
    ])


    # Initialize lists to store dictionaries for each row
    FoAssesments_list = []
    PreAssesments_list = []
    SelfAssesments_list = []
    PostAssesments_list = []
    PostAssesments_dates = []
    FoAssesment_dates = []
    SelfAssesment_dates =[]

    def append_to_assessment_list(matching_rows, header, assessments_list):
        for row in matching_rows:
            row_data = {header[i]: scrub(cell_value) for i, cell_value in enumerate(row)}
            assessments_list.append(row_data)
            if pt.current_trace() is not None:
                for i, cell_value in enumerate(row):
                    if str(cell_value) != str(row_data[header[i]]):
                        pt.add_sample(header[i], cell_value, row_data[header[i]])
                        break  # one before/after pair per row is enough

    append_to_assessment_list(matching_rows_for_Fo, headerFo, FoAssesments_list)
    append_to_assessment_list(matching_rows_for_Pre, headerPre, PreAssesments_list)
    append_to_assessment_list(matching_rows_for_Self, headerSelf, SelfAssesments_list)
    append_to_assessment_list(matching_rows_for_Post, headerPost, PostAssesments_list)
    pt.record("scrub", context=f"student {StudID} (+ registry backup names)",
              masks=scrub_stats,
              rows=number_of_Fo_Assessments + number_of_Pre_Assessments
                   + number_of_Self_Assessments + number_of_Post_Assessments)

    key_value_string = ""

    The_foassems_in_String = []
    for row_data in FoAssesments_list:
        for key, value in row_data.items():
            if key == "Timestamp":
                key_value_string += f"Date the assessment taken: {value} --- "
                FoAssesment_dates.append(value)
            key_value_string += f"{key}: {value} --- "
        The_foassems_in_String.append(key_value_string)
        key_value_string = ""

    The_postassems_in_String = []
    for row_data in PostAssesments_list:
        for key, value in row_data.items():
            if key == "Timestamp":
                PostAssesments_dates.append(value)
                key_value_string += f"Date the assessment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_postassems_in_String.append(key_value_string)
        key_value_string = ""

    
    The_selfassems_in_String = []
    for row_data in SelfAssesments_list:
        for key, value in row_data.items():
            if key == "Timestamp":
                SelfAssesment_dates.append(value)
                key_value_string += f"Date the assessment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_selfassems_in_String.append(key_value_string)
        key_value_string = ""

    json_foass = json.dumps(FoAssesments_list, indent=2, ensure_ascii=False)
    json_selfass = json.dumps(SelfAssesments_list, indent=2, ensure_ascii=False)
    json_postass = json.dumps(PostAssesments_list, indent=2, ensure_ascii=False)

    print(json_postass)

    #Getting the per-assessment summaries___________________________________________
    #-----------------------------------------------------------------------------------
    # Parent-pre, formative, self and post summaries are all independent of each
    # other — build one task list and run ALL of them in a single parallel wave
    # (this replaces the old four serial N+1 loops). Result order is preserved.
    print(number_of_Pre_Assessments)
    print(number_of_Fo_Assessments)
    print(number_of_Self_Assessments)

    def _summarize_pre(i):
        prompt = (f"{ENGLISH_ONLY}\nquestions/fields separated by ---"
                  f"Summarize Parent Assessment (max 250 words): {PreAssesments_list[i]}")
        message = [
            {"role": "system", "content": f"You are an insightful Teacher. {ENGLISH_ONLY}"},
            {"role": "user", "content": prompt},
        ]
        text = _chat_text(message, 800, model)
        print(f"--- pre {i + 1}/{len(PreAssesments_list)} done ---")
        return text

    def _summarize_fo(i):
        prompt = generatePrompt("Student", The_foassems_in_String[i], "none yet", i + 1, number_of_Fo_Assessments, FoAssesment_dates[i], AssesType, role, pseudonym)
        message = [
            {"role": "system", "content": f"You are an expert producing reports. {ENGLISH_ONLY}"},
            {"role": "user", "content": f"{prompt}"},
        ]
        text = _chat_text(message, 800, model)
        print(f"--- fo {i + 1}/{number_of_Fo_Assessments} done ---")
        return text

    def _summarize_self(i):
        prompt = generatePrompt("Self", The_selfassems_in_String[i], "none yet", i + 1, number_of_Self_Assessments, SelfAssesment_dates[i], AssesType, role, pseudonym)
        message = [
            {"role": "system", "content": f"You are an expert producing reports. {ENGLISH_ONLY}"},
            {"role": "user", "content": f"{prompt}"},
        ]
        text = _chat_text(message, 800, model)
        print(f"--- self {i + 1}/{number_of_Self_Assessments} done ---")
        return text

    def _summarize_post(i):
        prompt = generatePrompt("Post Parent", The_postassems_in_String[i], "none yet", i + 1, number_of_Post_Assessments, PostAssesments_dates[i], AssesType, role, pseudonym)
        message = [
            {"role": "system", "content": f"You are an expert producing reports. {ENGLISH_ONLY}"},
            {"role": "user", "content": f"{prompt}"},
        ]
        text = _chat_text(message, 800, model)
        print(f"--- post {i + 1}/{number_of_Post_Assessments} done ---")
        return text

    _fn = {"pre": _summarize_pre, "fo": _summarize_fo,
           "self": _summarize_self, "post": _summarize_post}
    _tasks = ([("pre", i) for i in range(len(PreAssesments_list))]
              + [("fo", i) for i in range(number_of_Fo_Assessments)]
              + [("self", i) for i in range(number_of_Self_Assessments)]
              + [("post", i) for i in range(number_of_Post_Assessments)])

    def _run_task(t):
        kind, i = _tasks[t]
        return _fn[kind](i)

    _results = _run_parallel(_run_task, len(_tasks))
    pre_results  = [r for (k, _), r in zip(_tasks, _results) if k == "pre"]
    foresponces  = [r for (k, _), r in zip(_tasks, _results) if k == "fo"]
    self_results = [r for (k, _), r in zip(_tasks, _results) if k == "self"]
    post_results = [r for (k, _), r in zip(_tasks, _results) if k == "post"]

    preass_reports = list(reversed(pre_results)) + ["no preassessment yet"]
    if pre_results:
        print("Pre Assessment:-----------------------")
        print(preass_reports[0])
    formass_reports = ["none yet"] + foresponces
    json_foass = json.dumps(foresponces, indent=2, ensure_ascii=False)
    print(json_foass)
    selfass_reports = ["none yet"] + self_results
    print(selfass_reports)
    postass_reports = ["none yet"] + post_results
    print(postass_reports)

    #Getting The Final Prompt
    #--------------------------------------------------------------------------------------------
    if number_of_Fo_Assessments != 0:
        print("----------THE FINAL-----------------------------")
        prompt = finalChildPrompt(json_foass, selfass_reports, postass_reports, preass_reports[0], LessonsinString, AssesType, role)
        content = f"{role} {ENGLISH_ONLY}"
        message = [
            {
                "role": "system",
                "content": content
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
        # Make an API request to generate the report (retry + null-safe)
        response_message = _chat_text(message, 1500, model)
        print(f"Finale Report Assessment:----------------------")
    elif number_of_Pre_Assessments != 0:
        response_message = "Only Pre assessment found. Here is the Report:\n"
        response_message += preass_reports[0]
    else:
        response_message = "No Student Found."
    
    if save:
        if number_of_Fo_Assessments != 0:
            ok, feedback = critic_check(AssesType, response_message, model)
            if not ok:
                print(f"Critic gate: regenerating once ({feedback})")
                response_message = _regenerate_with_feedback(prompt, role, feedback, model)
        write_to_reports_file(response_message, "Student", StudID, date, AssesType, role, StuLessons[0])
        reflect_and_store("Student", StudID, date, AssesType, response_message, model)
    #print(response_message)
    return response_message, name, surname

#The function that produces the report for the Lessons
def LessonAssessment(LessID,date,AssesType,role,save,model=None):
    model = model or MODEL
    LessAssessment = gc.open('LessonAssessment').sheet1
    Lessons = gc.open('Lessons').sheet1


    headerLess = LessAssessment.row_values(1)
    LessAssesment_column_index = headerLess.index("Group code") + 1
    LessAssesment_date_index = headerLess.index("Date") + 1
    headerLessons= Lessons.row_values(1)
    headerLessons_column_index = headerLessons.index("ID") + 1
    headerLessons_column_Description = headerLessons.index("Description")
    
    matching_rows_for_Lessons = -1
    for row in Lessons.get_all_values()[1:]:
        if row[headerLessons_column_index - 1] == LessID:
            matching_rows_for_Lessons = row
            break
    if  matching_rows_for_Lessons == -1:
        return "Lesson not found."
    
    Lesson_Description = matching_rows_for_Lessons[headerLessons_column_Description]

    matching_rows_for_Less = []
    seen_classes = set()
        
    target_date = parse_flexible_date(date)
    for row in LessAssessment.get_all_values()[1:]:
        date_string = row[LessAssesment_date_index - 1]
        first_item = row[LessAssesment_column_index - 1]
        if first_item == "":
            continue           #We pass empty values so it wont break the code
        if len(first_item) < 2:
            continue           #Skip IDs too short to have a lesson prefix (first_letter was unbound here)
        first_letter = first_item[:2]
        if first_letter == LessID and parse_flexible_date(date_string) < target_date:
            seen_classes.add(first_item)
            matching_rows_for_Less.append(row)
    
    number_of_Less_Assessments = len(matching_rows_for_Less)
    pt.record("fetch", entity=LessID, sources=[
        {"sheet": "Lessons", "rows": 1, "filter": f"ID = {LessID}"},
        {"sheet": "LessonAssessment", "rows": number_of_Less_Assessments,
         "filter": f"lesson prefix = {LessID}, date < {date}"},
    ])

    LessAssesments_list = []
    LessAssesments_dates = []
    LessAssesments_ClassID = []
    scrub_stats = {}

    if number_of_Less_Assessments>0:
        for row in matching_rows_for_Less:
            row_data = {}  # Initialize a dictionary for the row
            for i, cell_value in enumerate(row):
                column_name = headerLess[i]
                # GDPR: teacher notes may mention a student by name — scrub.
                row_data[column_name] = scrub_all_students(cell_value, stats=scrub_stats)
                if column_name== "Date":
                    LessAssesments_dates.append(cell_value)
                if column_name== "Group code":
                    LessAssesments_ClassID.append(cell_value)
            LessAssesments_list.append(row_data)  # Append the dictionary to the list
        key_value_string = ""
    pt.record("scrub", context=f"lesson {LessID} (whole-registry scrubber)",
              masks=scrub_stats, rows=number_of_Less_Assessments)
        
    The_Lessassems_in_String = []
    for row_data in LessAssesments_list:
        # Iterate through key-value pairs in the dictionary
        for key, value in row_data.items():
            if key == "Date:":
                key_value_string += f"Date the assesment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_Lessassems_in_String.append(key_value_string)
        key_value_string = ""
        
    
    Lessass_reports = ["none yet"]

    def _summarize_lesson(i):
        prompt = generatePromptLesson("Class", LessAssesments_ClassID, The_Lessassems_in_String[i], "none yet", i + 1, number_of_Less_Assessments, LessAssesments_dates[i], AssesType, role, Lesson_Description)
        message=[   {"role": "system", "content": f"{role} {ENGLISH_ONLY}"},
            {"role": "system", "content": f"You are an expert producing reports. {ENGLISH_ONLY}"},
            {"role": "user", "content": f"{prompt}"},
        ]
        text = _chat_text(message, 400, model)
        print(f"--- lesson {i + 1}/{number_of_Less_Assessments} done ---")
        return text

    Lessass_reports.extend(_run_parallel(_summarize_lesson, number_of_Less_Assessments))
    json_lesass = json.dumps(Lessass_reports, indent=2,ensure_ascii=False)
    if(number_of_Less_Assessments!=0):
        print("----------THE FINAL-----------------------------")
        prompt = finalLessonPrompt(json_lesass,Lesson_Description,AssesType,role,seen_classes)
        content = f"{role} {ENGLISH_ONLY}"
        message=[
            {
            "role": "system",
            "content": content
            },
            {
            "role": "user",
            "content": prompt
            }
        ]
        # # Make an API request to generate the report (retry + null-safe)
        response_message = _chat_text(message, 1000, model)
        print(f"Finale Report Assessment:----------------------")
    else:
        response_message = "No Lesson Found."
    print(f"++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    print(f"++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    if save:
        if number_of_Less_Assessments != 0:
            ok, feedback = critic_check(AssesType, response_message, model)
            if not ok:
                print(f"Critic gate: regenerating once ({feedback})")
                response_message = _regenerate_with_feedback(prompt, role, feedback, model, max_tokens=1000)
        write_to_reports_file(response_message, "Lesson", LessID, date, AssesType, role,"")
        reflect_and_store("Lesson", LessID, date, AssesType, response_message, model)
    return response_message

#The function that produces the report for the Classes
def classAssessment(classID,date,AssesType,role,save,model=None):
    model = model or MODEL
    LessAssessment = gc.open('LessonAssessment').sheet1
    Classrooms = gc.open('Lessons').get_worksheet(1)

    headerLess = LessAssessment.row_values(1)
    LessAssesment_column_index = headerLess.index("Group code") + 1
    LessAssesment_date_index = headerLess.index("Date") + 1
    headerLessons= Classrooms.row_values(1)
    headerLessons_column_index = headerLessons.index("Group code") + 1  # group codes (ΜΒ1…) live in the 'Group code' column
    headerLessons_column_Description = headerLessons.index("Description")  # long description
    headerLessons_column_title = headerLessons.index("Title")
    
    matching_rows_for_Lessons = -1
    for row in Classrooms.get_all_values()[1:]:
        if row[headerLessons_column_index - 1] == classID:
            matching_rows_for_Lessons = row
    if  matching_rows_for_Lessons == -1:
        return "Class not found."
    
    Class_Description = matching_rows_for_Lessons[headerLessons_column_Description]
    Class_Lesson_Title = matching_rows_for_Lessons[headerLessons_column_title]
    matching_rows_for_Less = []


    target_date = parse_flexible_date(date)
    for row in LessAssessment.get_all_values()[1:]:
        date_string =  row[LessAssesment_date_index - 1]
        first_item = row[LessAssesment_column_index - 1]
        if first_item=="":
            continue           #We check for empty values so it wont break the code
        if first_item == classID and parse_flexible_date(date_string) < target_date:
            matching_rows_for_Less.append(row)
            print(first_item)
        

    number_of_Less_Assessments = len(matching_rows_for_Less)
    pt.record("fetch", entity=classID, sources=[
        {"sheet": "Lessons (groups)", "rows": 1, "filter": f"lesson = {classID}"},
        {"sheet": "LessonAssessment", "rows": number_of_Less_Assessments,
         "filter": f"group = {classID}, date < {date}"},
    ])

    LessAssesments_list = []
    LessAssesments_dates = []
    scrub_stats = {}

    if number_of_Less_Assessments>0:
        for row in matching_rows_for_Less:
            row_data = {}  # Initialize a dictionary for the row
            for i, cell_value in enumerate(row):
                column_name = headerLess[i]
                # GDPR: teacher notes may mention a student by name — scrub.
                row_data[column_name] = scrub_all_students(cell_value, stats=scrub_stats)
                if column_name== "Date":
                    LessAssesments_dates.append(cell_value)
            LessAssesments_list.append(row_data)  # Append the dictionary to the list
        key_value_string = ""
    pt.record("scrub", context=f"class {classID} (whole-registry scrubber)",
              masks=scrub_stats, rows=number_of_Less_Assessments)
        
    The_Lessassems_in_String = []
    for row_data in LessAssesments_list:
        # Iterate through key-value pairs in the dictionary
        for key, value in row_data.items():
            if key == "Date:":
                key_value_string += f"Date the assesment taken: {value} --- "
            key_value_string += f"{key}: {value} --- "
        The_Lessassems_in_String.append(key_value_string)
        key_value_string = ""
        

    Lessass_reports = ["none yet"]
    print(number_of_Less_Assessments)

    def _summarize_class(i):
        prompt = generatePromptClass("Class", The_Lessassems_in_String[i], "none yet", i + 1, number_of_Less_Assessments, LessAssesments_dates[i], AssesType, role, Class_Lesson_Title)
        message=[   {"role": "system", "content": f"{role} {ENGLISH_ONLY}"},
            {"role": "system", "content": f"You are an expert producing reports. {ENGLISH_ONLY}"},
            {"role": "user", "content": f"{prompt}"},
        ]
        text = _chat_text(message, 400, model)
        print(f"--- class {i + 1}/{number_of_Less_Assessments} done ---")
        return text

    Lessass_reports.extend(_run_parallel(_summarize_class, number_of_Less_Assessments))
    json_lesass = json.dumps(Lessass_reports, indent=2,ensure_ascii=False)
    if(number_of_Less_Assessments!=0):
        print("----------THE FINAL-----------------------------")
        prompt = finalClassPrompt(json_lesass,Class_Lesson_Title,AssesType,role)
        content = f"{role} {ENGLISH_ONLY}"
        message=[
            {
            "role": "system",
            "content": content
            },
            {
            "role": "user",
            "content": prompt
            }
        ]
        # # Make an API request to generate the report (retry + null-safe)
        response_message = _chat_text(message, 2000, model)
        print(f"Finale Report Assessment:----------------------")
    else:
        response_message = "No Lesson Found."
    print(f"++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    print(f"++++++++++++++++++++++++++++++++++++++++++++++++++++++")
    if save:
        if number_of_Less_Assessments != 0:
            ok, feedback = critic_check(AssesType, response_message, model)
            if not ok:
                print(f"Critic gate: regenerating once ({feedback})")
                response_message = _regenerate_with_feedback(prompt, role, feedback, model, max_tokens=2000)
        write_to_reports_file(response_message, "Class", classID, date, AssesType, role,"")
        reflect_and_store("Class", classID, date, AssesType, response_message, model)
    return response_message

# ---------------------------------------------------------------------------
# ASK ME — smart query over the saved-reports archive.
# The educator writes a free-form request ("create a lesson plan targeting
# the class's biggest weaknesses", "adapt the lesson for this class", ...).
# A cheap LLM ROUTER picks the pipeline unless the educator overrides the
# action manually. The scope pickers (class group / lesson / students) are
# all OPTIONAL — empty means "search everything in the archive", and a picked
# class group narrows the evidence to that class's reports and its students
# before anything is summarized.
# ---------------------------------------------------------------------------
ASKME_ACTIONS = ("create_lesson_plan", "modify_lesson_plan", "find_solution", "general_query")


def _student_group_map():
    """{student_id: set(group_codes)} from the Students registry (Lesson ID 1..4)."""
    _connect_sheets()
    header = Students.row_values(1)
    i_id = header.index("ID")
    i_l1 = header.index("Lesson ID 1") if "Lesson ID 1" in header else None
    out = {}
    for row in Students.get_all_values()[1:]:
        if len(row) <= i_id or not row[i_id].strip():
            continue
        groups = set()
        if i_l1 is not None:
            groups = {g.strip() for g in row[i_l1:i_l1 + 4] if g.strip()}
        out[row[i_id].strip()] = groups
    return out


def _route_askme(question, model=None):
    """Classify a free-form ASK ME request into one of ASKME_ACTIONS.

    Returns (action, target_student_id, reason). Falls back to general_query
    whenever the router's answer is missing or malformed.
    """
    model = model or MODEL
    prompt = dedent(f"""\
        You route an educator's request to exactly one internal pipeline.
        Pipelines:
        - create_lesson_plan: build a NEW lesson plan from the saved reports (e.g. targeting weaknesses, goals, a topic or a class).
        - modify_lesson_plan: adapt or adjust an EXISTING lesson plan.
        - find_solution: diagnose ONE specific student's difficulty, using the other students as comparison context.
        - general_query: anything else — questions, comparisons, patterns or summaries over the saved reports.

        Educator's request: "{question}"

        Reply with JSON only:
        {{"action": "one of the pipeline ids above", "target_student_id": "the student ID if the request clearly names one, else null", "reason": "max 12 words"}}""")
    try:
        # Generous token budget: reasoning models (e.g. gpt-5-nano) spend most
        # of max_tokens on hidden reasoning before emitting the tiny JSON.
        text = _chat_text([
            {"role": "system", "content": "You are a precise routing classifier. Reply in JSON only, in English."},
            {"role": "user", "content": prompt},
        ], 900, model)
        data = _extract_json(text) or {}
    except Exception:
        data = {}
    action = str(data.get("action") or "").strip()
    if action not in ASKME_ACTIONS:
        action = "general_query"
    target = data.get("target_student_id")
    target = str(target).strip() if target else None
    reason = str(data.get("reason") or "").strip()
    pt.record("note", kind="askme_route", action=action, target=target,
              reason=reason, auto=True)
    return action, target, reason


def askmeForm(choice, ids, date, AssesType, role, save, group=None, lesson=None, model=None):
    """Smart query over the ReportsFile archive.

    choice: one of ASKME_ACTIONS, or 'auto' — an LLM router reads the request
            and picks the action itself.
    ids:    optional comma-separated student IDs. For find_solution the first
            is the student under examination and the rest form the comparison
            group; for every other action they simply narrow the evidence.
            Empty = use everything in scope.
    group / lesson: optional scope filters — a picked class group narrows the
            evidence to that class's reports and its students' reports.
    """
    model = model or MODEL
    ReportsFile = gc.open('ReportsFile').sheet1

    headerReports = ReportsFile.row_values(1)
    AssessmentTypeIndex = headerReports.index("Assessment type") + 1
    IDIndex = headerReports.index("ID") + 1

    student_reports = []
    lesson_reports = []
    class_reports = []

    # Keep the raw rows; summarize only the compiled strings, once per request.
    for row in ReportsFile.get_all_values()[1:]:
        assessment_type = row[AssessmentTypeIndex - 1]
        if assessment_type == "Student":
            student_reports.append(row)
        elif assessment_type == "Lesson":
            lesson_reports.append(row)
        elif assessment_type == "Class":
            class_reports.append(row)

    # --- scope filters (all optional) --------------------------------------
    if group:
        class_reports = [r for r in class_reports if r[IDIndex - 1] == group]
        members = {sid for sid, grps in _student_group_map().items() if group in grps}
        student_reports = [r for r in student_reports if r[IDIndex - 1] in members]
        if not lesson:
            # Group codes extend their lesson id (ΜΒ1 -> ΜΒ): keep its lessons.
            lesson_reports = [r for r in lesson_reports if group.startswith(r[IDIndex - 1])]
    if lesson:
        lesson_reports = [r for r in lesson_reports if r[IDIndex - 1] == lesson]
    pt.record("note", kind="askme_scope",
              scope={"group": group or "", "lesson": lesson or "", "students": ids or ""},
              found={"student": len(student_reports), "lesson": len(lesson_reports),
                     "class": len(class_reports)})

    # --- action routing ------------------------------------------------------
    target_from_text = None
    auto_routed = choice == "auto"
    if auto_routed:
        choice, target_from_text, reason = _route_askme(AssesType, model)
        print(f"ASK ME router -> {choice} ({reason})")
    if choice not in ASKME_ACTIONS:
        return "Invalid action choice selected."

    id_list = [s.strip() for s in str(ids).split(',') if s.strip()]
    # Picked students narrow the evidence for every action except find_solution
    # (there they define the target/comparison split instead).
    if id_list and choice != "find_solution":
        student_reports = [r for r in student_reports if r[IDIndex - 1] in id_list]

    _no_scope_data = ("No saved reports found for the selected scope. "
                      "Widen the scope (or clear the filters) and try again.")

    def _summarized(rows):
        return summarize_text(compile_reports(rows), role, 1000, model=model) if rows else "none yet"

    def _general_query():
        if not (student_reports or lesson_reports or class_reports):
            return _no_scope_data
        answer = answer_over_reports(AssesType,
                                     _summarized(student_reports),
                                     _summarized(lesson_reports),
                                     _summarized(class_reports),
                                     role, model=model)
        if save:
            write_to_reports_file(answer, "Ask Me", "SmartQuery", date, AssesType, role, "")
        return answer

    if choice == 'create_lesson_plan':
        if not (student_reports or lesson_reports or class_reports):
            return _no_scope_data
        # Summarize reports if they are too long
        summarized_student_report = _summarized(student_reports)
        summarized_lesson_report = _summarized(lesson_reports)
        summarized_class_report = _summarized(class_reports)
        final_combined_report = generate_combined_report(summarized_student_report, summarized_lesson_report, summarized_class_report, AssesType, role, model=model)
        if save:
            write_to_reports_file(final_combined_report, "Ask Me", "LessonCreate", date, AssesType, role, "")

        return final_combined_report

    elif choice == 'modify_lesson_plan':
        if not class_reports:
            return _no_scope_data
        summarized_class_report = _summarized(class_reports)

        # Generate the new lesson plan from the class reports
        final_lesson_plan = create_new_lesson_plan(summarized_class_report, AssesType, role, model=model)

        if save:
            write_to_reports_file(final_lesson_plan, "Ask Me", "LessonModify", date, AssesType, role, "")

        return final_lesson_plan

    elif choice == 'find_solution':
        # The first ID is the student under examination; the rest (or, if only
        # one is given, everyone else in scope) form the comparison group. With
        # auto-routing the target may come from the request text itself.
        if target_from_text and not id_list:
            id_list = [target_from_text]
        if not id_list:
            # Auto mode picked find_solution but no student is identifiable —
            # degrade gracefully to a general grounded answer instead of a
            # dead-end message. (Manual choice keeps the explicit guidance.)
            if auto_routed:
                pt.record("note", kind="askme_route", action="general_query",
                          target=None, auto=True,
                          reason="find_solution had no identifiable student — degraded to general answer")
                return _general_query()
            return ("Find Solution needs a student under examination — pick one in "
                    "the Students field, or name the student ID in your request.")
        target_id = id_list[0]
        comparison_ids = id_list[1:]

        specific_student_data = [row for row in student_reports if row[IDIndex - 1] == target_id]
        if comparison_ids:
            other_students_data = [row for row in student_reports if row[IDIndex - 1] in comparison_ids]
        else:
            other_students_data = [row for row in student_reports if row[IDIndex - 1] != target_id]

        if not specific_student_data:
            return f"No saved reports found for student ID: {target_id}"

        specific_student_report = _summarized(specific_student_data)
        other_students_report = _summarized(other_students_data)

        # Generate the conclusion based on the data sets
        final_conclusion = find_solution(specific_student_report, other_students_report, AssesType, role, model=model)

        if save:
            write_to_reports_file(final_conclusion, "Ask Me", "FindSolution", date, AssesType, role, "")

        return final_conclusion

    elif choice == 'general_query':
        return _general_query()

    else:
        return "Invalid action choice selected."


def answer_over_reports(question, student_reports, lesson_reports, class_reports, role, model=None):
    """General smart query: answer any educator question grounded in the (scoped) saved reports."""
    model = model or MODEL
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        You are given summarized evidence from the school's saved assessment reports.

        Student reports:
        {student_reports}

        Lesson reports:
        {lesson_reports}

        Class reports:
        {class_reports}

        The educator asks: {question}

        To successfully complete the prompt:
        - Answer ONLY from the evidence above; if the evidence is not enough, say so plainly and suggest what to assess next.
        - Be concrete: refer to Student IDs, class groups and dates whenever they support a point.
        - Give the response in English, addressed to a reader with the role of: {role}.
        - End with a short "Suggested next step" for the educator.
        - Do not add sensitive content such as names to the final response. Replace it, if there is any, with Student ID.
    """)
    message = [
        {"role": "system", "content": f"{role} {ENGLISH_ONLY}"},
        {"role": "user", "content": prompt},
    ]
    return _chat_text(message, 2000, model)

def find_solution(specific_student_report, other_students_report, AssesType, role, model=None):
    model = model or MODEL
    # Prompt for the OpenAI API
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the following reports:

        Students Reports:
        {specific_student_report}


        You have to answer the following question: {AssesType}

        To successfully complete the prompt:
        - Compare the Students Reports between them.
        - Use your expertise you have with the role you where given.
        - Give the response in English.
        - Take your time to produce the response that might seem more appropriate.
        - Keep the response at a minimum number of tokens.
        - Try to answer only what has been asked in the question.
        - Keep in mind that the person that will be given the answer will have the role of: {role}.
        - Provide a good solution based on the given reports.
        --Do not add sensitive content such as names to the final responce. Replace it, if there is any, with Student ID.
    """)

    # OpenAI API call
    message = [
        {
            "role": "system",
            "content": f"{role} {ENGLISH_ONLY}"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    response = get_client().chat.completions.create(
        model=model,
        messages=message,
        max_tokens=3000  # Adjust the max tokens based on your summarization needs
    )

    # Extract and return the generated questions from the OpenAI response
    generated_solution = response.choices[0].message.content.strip()
    return generated_solution

def create_new_lesson_plan(summarized_class_report, AssesType, role, model=None):
    model = model or MODEL
    # Define the path to the JSON file containing the lesson plan template
    file_path = 'real_lesson_plan.json'  # Replace with the actual file path

    # Open and load the JSON file
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            lesson_plan_template = json.load(file)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        lesson_plan_template = {}

    # Prompt for the OpenAI API
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the following summarized class report:
        
        {summarized_class_report}

        You have to do what the following prompt says: {AssesType}

        To successfully complete the prompt:
        - Give the response in English.
        - Keep the original lesson plan theme, but modify it where necessery.
        - Take your time to produce the response that might seem more appropriate.
        - Try to answer only what has been asked in the question.
        - The materials could be based on the reports and your knowledge as the role given to you.
        - You can be creative.
        - Keep in mind that the person that will be given the answer will have the role of: {role}.
        - Give a good solution in the modification  of the original lesson plan.
        - inside <> is the original lesson plan to modify: 
        <{json.dumps(lesson_plan_template, indent=4)}>
        - use a paragpraph format for the final responce.
        - Keep the original main Title.
        - Keep the original lenght and exa
        - when done, note what changes you've made to the original lesson plan.
        - give specific guides on what the teacher should do.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.
    """)

    # OpenAI API call
    message = [
        {
            "role": "system",
            "content": f"{role} {ENGLISH_ONLY}"
        },
        {
            "role": "user",
            "content": prompt
        }
    ]

    # _chat_text: retries + null-content safety (reasoning models can return
    # content=None when the whole budget went to hidden reasoning).
    return _chat_text(message, 3000, model)

def summarize_text(text, role, tokens, model=None):
    model = model or MODEL
  # Ensure text is a string
    if isinstance(text, list):
        text = "\t".join(map(str, text))

    # Estimate the token length of the text
    token_length = len(text.split())
    max_context_length = 16385 // 4  # A rough estimate assuming average 4 characters per token

    # Check if the text exceeds the model's maximum context length
    if token_length > max_context_length:
        print(f"Skipping summarization. Text length {token_length} exceeds maximum context length of {max_context_length}.")
        return "Text too long to summarize." 
    
    prompt = f"Please summarize the following text:\n\n{text}"
    message = [
        {"role": "system", "content": f"{role}"},
        {"role": "system", "content": "You are an expert in summarizing reports. Reply concisely. " + ENGLISH_ONLY},
        {"role": "user", "content": prompt}
    ]

    # _chat_text: retries + null-content safety.
    return _chat_text(message, tokens, model)

def read_lesson_plan_file(file_path):
    with open(file_path, 'r') as file:
        lesson_plan_text = file.read()
    return lesson_plan_text

def compile_reports(reports):
    report_strings = []
    for report in reports:
        report_string = "\t".join(map(str, report))  # Join report values with a tab
        report_strings.append(report_string)
    # Old saved reports may still contain real names — scrub before any LLM call.
    return scrub_all_students("\n".join(report_strings))


def generate_combined_report(student_reports, lesson_reports, class_reports, class_question, role, model=None):
    model = model or MODEL
    # Modern STEM / project-based template (Markdown). The old JSON template
    # made the model mirror JSON in its answer — the Markdown structure reads
    # like a real lesson plan and formats beautifully in the report page.
    try:
        with open('lesson_plan_template.md', "r", encoding="utf-8") as file:
            lesson_plan_template = file.read()
    except OSError as e:
        print(f"Could not read lesson_plan_template.md: {e}")
        lesson_plan_template = "(template unavailable — use a standard 5E STEM lesson structure)"
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the following summarized reports:\n\nStudent Reports:\n{student_reports}\n\nLesson Reports:\n{lesson_reports}\n\nClass Reports:\n{class_reports}\n\n
        Design a complete lesson plan that answers this request: {class_question}

        To successfully complete the prompt:
        - Follow the template structure inside <> EXACTLY — same sections, same headings, same order.
        - Output clean Markdown ONLY. Never JSON, never code fences around the whole plan.
        - Replace every {{placeholder}} and every guidance line with real, concrete content. No placeholder text may survive in the final answer.
        - Ground the plan in the evidence: pick objectives, scaffolds and pacing that target the weaknesses and strengths visible in the reports (refer to Student IDs where relevant, never names).
        - Keep the 5E × project-based flow with realistic timings that sum to the lesson's duration.
        - Materials should match what a robotics/STEM school actually has (kits, sensors, tablets).
        - Keep in mind that the person reading it has the role of: {role}.
        - Do not add sensitive content such as names to the final response. Replace it, if there is any, with Student ID.

        Template (everything between the --- lines):
        ---
        {lesson_plan_template}
        ---
    """)

    message=[
        {
        "role": "system",
        "content": f"{role} {ENGLISH_ONLY}"
        },
        {
        "role": "user",
        "content": prompt
        }
    ]
    # _chat_text: retries + null-content safety. Generous budget: reasoning
    # models spend most of max_tokens on hidden reasoning before the plan.
    text = _chat_text(message, 6000, model)
    # The model sometimes echoes the template's --- fences at the edges.
    lines = text.splitlines()
    while lines and lines[0].strip() == '---':
        lines.pop(0)
    while lines and lines[-1].strip() == '---':
        lines.pop()
    return '\n'.join(lines).strip()


def write_to_reports_file(response_message,typeo, classID, date, AssesType, role,LessonID):
    # Sandbox hard rule: with any guardrail relaxed or an explicit dry-run
    # active, nothing is written back to the school's sheets.
    if pt.writes_blocked():
        pt.record("save", blocked=True, sheet="ReportsFile", type=typeo,
                  entity=classID,
                  reason="dry-run (guardrails relaxed or educator preview) — nothing written")
        print("Dry-run: report NOT saved to ReportsFile.")
        return
    # Open the Google Sheet
    _connect_sheets()
    worksheet = sh.sheet1  # Assuming you're using the first sheet

    # Get the current date
    current_date = datetime.today().strftime('%Y-%m-%d %H:%M:%S')

    # Create a row of data
    data = [current_date, date, typeo, LessonID, classID, AssesType, role, response_message]

    # Append the data to the sheet
    worksheet.append_row(data)
    pt.record("save", sheet="ReportsFile", type=typeo, entity=classID,
              lesson=LessonID, date=str(date),
              report_chars=len(response_message), report=response_message)


# ---------------------------------------------------------------------------
# L2 SMART MEMORY — Insights layer ("double aggregated thinking").
# Raw assessments (L0) -> reports in ReportsFile (L1) -> distilled insight
# cards in InsightsMemory (L2). Each saved report passes a REFLECTION pass
# (cheap LLM call) producing a structured card: trajectory, cognitive and
# soft-skill trends, risk flags, evidence, takeaway. Searching happens over
# these small cards first; full reports are pulled only when needed.
#
# Two guards around saving:
#  - CRITIC GATE: a reviewer pass checks the report answers the question, is
#    grounded and leaks no PII — one regeneration attempt if it fails.
#  - EARLY WARNING: the new card is compared with the entity's previous card
#    and an alert is stored when the trajectory worsens or new risks appear.
# ---------------------------------------------------------------------------

def _extract_json(text):
    """Parse the first {...} block of an LLM answer; None on failure."""
    match = re.search(r'\{.*\}', text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def critic_check(question, report, model=None):
    """Quality gate before a report is saved to ReportsFile.

    Returns (ok, feedback). Checks: (1) no real names leaked (free, via the
    anonymizer as a detector), (2) an LLM reviewer confirms the report answers
    the question and its claims look grounded. On any failure the caller
    regenerates once with the feedback.
    """
    model = model or MODEL
    if not pt.critic_enabled():
        pt.record("critic", verdict="skipped",
                  reason="critic guardrail disabled (sandbox experiment)")
        return (True, "")
    issues = []
    pii_leak = scrub_all_students(report) != report
    if pii_leak:
        issues.append("the report contains a real student/parent name — remove it, use IDs only")
    prompt = dedent(f"""\
        You are a strict reviewer of an educational assessment report.
        The report was requested to answer this question: {question}

        Report:
        <{report}>

        Check ONLY these two things:
        1) Does the report actually answer the question above?
        2) Do its claims look grounded (specific, internally consistent, no invented scores or dates)?
        Reply with JSON only:
        {{"answers_question": true/false, "grounded": true/false, "issues": "short explanation or empty"}}""")
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a meticulous quality reviewer. Reply in JSON only, in English."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
        )
        verdict = _extract_json(resp.choices[0].message.content.strip()) or {}
    except Exception as e:
        print(f"Critic gate warning ({e}) — passing by default")
        verdict = {}
    if verdict.get("answers_question") is False:
        issues.append("it does not answer the question that was asked")
    if verdict.get("grounded") is False:
        issues.append(f"it contains ungrounded claims ({verdict.get('issues', '')})")
    pt.record("critic", verdict="pass" if not issues else "fail",
              pii_leak_detected=pii_leak, issues=issues,
              reviewer_verdict=verdict, question=str(question)[:300])
    return (not issues, "; ".join(issues))


def _regenerate_with_feedback(prompt, role, feedback, model=None, max_tokens=1500):
    """Single retry after a failed critic gate: same prompt + the critic's feedback."""
    model = model or MODEL
    pt.record("regenerate", feedback=feedback, max_tokens=max_tokens)
    message = [
        {"role": "system", "content": f"{role} {ENGLISH_ONLY}"},
        {"role": "user", "content": prompt},
        {"role": "user", "content": f"A quality reviewer found these problems in your previous answer: {feedback}. Produce a corrected final answer, in English."},
    ]
    resp = get_client().chat.completions.create(model=model, messages=message, max_tokens=max_tokens)
    return resp.choices[0].message.content.strip()


TRAJECTORY_RANK = {"improving": 4, "recovering": 3, "steady": 2, "volatile": 1,
                   "declining": 0, "unknown": -1}


def _early_warning(insights_rows, entity_id, new_trajectory, new_flags):
    """Compare the new card with the entity's most recent previous card."""
    prev = None
    for row in insights_rows:
        if len(row) > 2 and row[2] == entity_id:
            prev = row  # rows are appended chronologically; last match wins
    if not prev:
        return "—"
    old_t = prev[4] if len(prev) > 4 else "unknown"
    old_flags = prev[7] if len(prev) > 7 else "none"
    alerts = []
    if TRAJECTORY_RANK.get(new_trajectory, -1) < TRAJECTORY_RANK.get(old_t, -1):
        alerts.append(f"TRAJECTORY WORSENED ({old_t} -> {new_trajectory})")
    if old_t == "declining" and new_trajectory == "declining":
        alerts.append("DECLINE CONTINUES")
    if new_flags and old_flags in ("none", ""):
        alerts.append(f"NEW RISK FLAGS: {', '.join(new_flags)}")
    return " | ".join(alerts) if alerts else "—"


def reflect_and_store(entity_type, entity_id, date, question, report, model=None):
    """Distil a saved report into a structured insight card in InsightsMemory."""
    model = model or MODEL
    prompt = dedent(f"""\
        You are the long-term memory of an educational assessment system.
        Distil the report below into a structured insight card for the {entity_type} with ID: {entity_id}.
        The report answered this question: {question}

        Report:
        <{report}>

        Use ONLY information present in the report. English only. Never include real names — IDs only.
        Reply with JSON only:
        {{
            "trajectory": one of "improving" | "steady" | "declining" | "volatile" | "recovering" | "unknown",
            "cognitive_trend": "one short sentence on comprehension/building/programming trend",
            "soft_skill_trend": "one short sentence on participation/collaboration trend",
            "risk_flags": ["short flags, e.g. disengagement, anxiety, score decline"] or [],
            "evidence": "the 2-3 concrete data points (scores/observations) backing the above",
            "takeaway": "one sentence: the single most important thing to remember about this entity"
        }}""")
    card = None
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You write precise, structured memory cards. JSON only, in English."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=450,
        )
        card = _extract_json(resp.choices[0].message.content.strip())
    except Exception as e:
        print(f"Reflection warning ({e})")
    if not card:
        print("Reflection skipped — no valid insight card produced.")
        pt.record("insight", entity_type=entity_type, entity_id=entity_id,
                  stored=False, reason="no valid card produced")
        return
    pt.record("insight", entity_type=entity_type, entity_id=entity_id, card=card)

    # Sandbox hard rule: dry-run — no sheet writes.
    if pt.writes_blocked():
        pt.record("early_warning", entity_id=entity_id, skipped=True,
                  reason="dry-run — nothing written to InsightsMemory")
        return

    try:
        ws = gc.open('InsightsMemory').sheet1
        existing = ws.get_all_values()[1:]
        flags = card.get("risk_flags") or []
        alert = _early_warning(existing, entity_id, card.get("trajectory", "unknown"), flags)
        pt.record("early_warning", entity_id=entity_id, alert=alert,
                  fired=alert != "—",
                  trajectory=card.get("trajectory", "unknown"),
                  risk_flags=flags)
        row = [
            datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
            entity_type, entity_id, str(date),
            card.get("trajectory", "unknown"),
            card.get("cognitive_trend", ""),
            card.get("soft_skill_trend", ""),
            ", ".join(flags) if flags else "none",
            alert,
            card.get("evidence", ""),
            card.get("takeaway", ""),
        ]
        ws.append_row(row, value_input_option="RAW")
        print(f"Insight stored: {entity_type} {entity_id} -> trajectory={row[4]}, alert={alert}")
    except Exception as e:
        print(f"Could not store insight ({e})")
        pt.record("error", where="reflect_store", message=str(e)[:500])


def search_insights(entity_id=None, limit=50):
    """Read L2 insight cards, newest last. Optionally filter to one entity."""
    ws = gc.open('InsightsMemory').sheet1
    rows = ws.get_all_values()[1:]
    if entity_id:
        rows = [r for r in rows if len(r) > 2 and r[2] == entity_id]
    return rows[-limit:]

# ---------------------------------------------------------------------------
# REPORT STYLE — gold exemplars + user style profiles ("StyleMemory").
# The final synthesis prompts (student/lesson/class) receive a STYLE BLOCK:
# either a compact style spec distilled from a user-supplied sample report
# (stored in the StyleMemory sheet, latest row per report type wins) or, by
# default, a built-in "gold" exemplar that pins structure, tone and detail.
# User samples are scrubbed with the whole-registry scrubber BEFORE the
# distillation call, and the distilled spec is scrubbed again before storage —
# an old real report pasted as a sample must never leak a name to the LLM.
# ---------------------------------------------------------------------------
DEFAULT_STYLE_EXEMPLARS = {
    "student": dedent("""\
        Progress Report — Student demo02 (period: October 2026)

        Overall picture
        Student demo02 has made steady progress this period. Across four sessions,
        participation stayed consistently high and the student completed every core
        build, most recently a tilting-sensor rover that they extended with their
        own program parameters.

        Strengths
        - Comprehension: moved from following guided steps to explaining why a sensor threshold matters.
        - Programming: now edits motor parameters independently; debugging attempts are methodical.
        - Collaboration: regularly helps peers pair their hubs without taking over their builds.

        Areas for growth
        - Patience under failure: after two failed runs the student rushes reassembly; short planned pauses help.

        Alignment with home
        Parent observations match the classroom picture: the student talks about the
        rover daily and tries to "program" household devices.

        Recommendations
        1. Introduce open-ended challenges with a single explicit constraint.
        2. Ask the student to demo their build to the group once per month."""),
    "lesson": dedent("""\
        Lesson Report — Junior Robotics (period: October 2026)

        Overview
        The lesson ran in two groups with eight sessions in total. Completion of the
        core activity averaged 88% and engagement stayed high across both groups.

        What worked
        - The build-then-extend structure: finishing the base model early left room for creative extensions, which the groups used fully.
        - Pair work: pairing newer students with experienced ones cut setup time roughly in half.

        Difficulties encountered
        - Bluetooth pairing failures consumed the first 10 minutes of two sessions.
        - The advanced group finished 15 minutes early twice; no extension material was ready.

        Recommendations
        1. Prepare a printed pairing checklist and pre-pair tablets before sessions.
        2. Keep one open challenge per unit ready for fast finishers.
        3. Re-run the sensor-threshold explanation; it was the most-missed concept across groups."""),
    "class": dedent("""\
        Class Report — Group MJ1 (Junior Robotics, period: October 2026)

        Overall picture
        Group MJ1 is progressing well. Across the period the group completed all
        planned activities, with participation stable and no disengagement signals.

        Engagement and collaboration
        Students arrive motivated and settle quickly. Collaboration is a strength of
        this group: peer help happens spontaneously, and stronger students support
        others without dominating.

        Skill progression
        - Construction: all students now assemble the base models without guidance.
        - Programming: the group has moved from copying blocks to modifying parameters; about half attempt their own sequences.
        - Conceptual grasp: sensor logic is understood by most; conditional loops still need reinforcement.

        Suggestions
        1. Add one paired challenge per session to channel the group's collaborative strength.
        2. Devote 10 minutes weekly to conditional-logic mini-exercises.
        3. Offer an optional extension task for the two fastest finishers."""),
}

_style_cache = {"ts": 0, "profiles": None}


_sheet_links_cache = {"ts": 0, "links": None, "ttl": 600}

SHEET_TITLES = ("Students", "Lessons", "PreAssessment", "FoAssessment",
                "SelfAssessment", "PostAssessment", "LessonAssessment",
                "ReportsFile", "InsightsMemory", "StyleMemory", "RiskNotes")


def sheet_links():
    """{sheet title: Google Sheets URL} for every data store — used to link
    the Guide's data-layer table and the pipeline Databases panel to the real
    spreadsheets. ONE Drive API call for the whole list (gc.open per title was
    11 calls — slow, and one failure wiped them all). Resolved live so links
    survive sheet re-creation; cached 10 min, retried after 1 min on error;
    on error returns {} so pages render plain names instead of links."""
    now = time.time()
    if (_sheet_links_cache["links"] is not None
            and now - _sheet_links_cache["ts"] < _sheet_links_cache["ttl"]):
        return dict(_sheet_links_cache["links"])
    links, ttl = {}, 600
    try:
        by_title = {f["name"]: f["id"] for f in gc.list_spreadsheet_files()}
        for title in SHEET_TITLES:
            sid = by_title.get(title)
            if sid:
                links[title] = f"https://docs.google.com/spreadsheets/d/{sid}"
    except Exception as e:
        print(f"Could not resolve sheet URLs ({e})")
        ttl = 60  # negative-cache briefly so pages stay fast while it heals
    _sheet_links_cache.update(ts=now, links=links, ttl=ttl)
    return dict(links)


def list_style_profiles():
    """{report_type: style spec} from the StyleMemory sheet, latest row per type wins.

    A row with an empty spec is an explicit RESET to the built-in default.
    Cached for 5 min; on any sheet error the built-in exemplars are used.
    """
    now = time.time()
    if _style_cache["profiles"] is not None and now - _style_cache["ts"] < 300:
        return dict(_style_cache["profiles"])
    profiles = {}
    try:
        ws = gc.open('StyleMemory').sheet1
        for row in ws.get_all_values()[1:]:
            if len(row) < 2 or not row[1].strip():
                continue
            rtype = row[1].strip()
            spec = row[2].strip() if len(row) > 2 else ""
            if spec:
                profiles[rtype] = spec
            else:
                profiles.pop(rtype, None)  # explicit reset row
    except Exception as e:
        print(f"StyleMemory unavailable ({e}) — default style exemplars in use")
        profiles = {}
    _style_cache["profiles"] = profiles
    _style_cache["ts"] = now
    return dict(profiles)


def load_style_profile(report_type):
    return list_style_profiles().get(report_type)


def get_style_block(report_type):
    """The style block injected into the final synthesis prompts."""
    profile = load_style_profile(report_type)
    if profile:
        pt.record("style", report_type=report_type, source="custom profile (StyleMemory)")
        return ("Style rules for this report — follow this structure, tone and "
                "formatting; the wording and content remain yours:\n<" + profile + ">")
    exemplar = DEFAULT_STYLE_EXEMPLARS.get(report_type, "")
    pt.record("style", report_type=report_type, source="default exemplar")
    return ("Style example — match this structure, tone and level of detail, but "
            "write ONLY about this report's data; invent nothing from the example:"
            "\n<" + exemplar + ">")


def distill_style(report_type, sample, instructions, model=None):
    """One-shot distillation: sample report and/or free-text instructions -> a
    compact, reusable style spec (what gets stored and injected, NOT the sample).
    """
    model = model or MODEL
    stats = {}
    safe_sample = scrub_all_students(sample, stats=stats) if sample else ""
    pt.record("style_distill", report_type=report_type, sample_chars=len(sample),
              has_instructions=bool(instructions), scrub_masks=stats)
    pieces = []
    if safe_sample:
        pieces.append("Example report (its facts are irrelevant — only its STYLE "
                      f"matters):\n<{safe_sample}>")
    if instructions:
        pieces.append(f"Style instructions from the user:\n<{instructions}>")
    prompt = dedent(f"""\
        You are configuring the house style of an educational assessment report generator.
        Distil the material below into a compact style specification for the "{report_type}" report.

        {chr(10).join(pieces)}

        Cover concisely, as concrete rules:
        - tone and voice (e.g. warm-professional, parent-facing)
        - structure: the sections, in order
        - approximate length and formatting (headings, bullets vs paragraphs)
        - how evidence (scores, dates, observations) is cited
        - anything to avoid

        Rules:
        - English only. Max 250 words. Plain rules, no preamble, no commentary.
        - Never carry over names or facts from the example — style only.""")
    resp = get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You write precise style specifications. English only."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=500,
    )
    spec = resp.choices[0].message.content.strip()
    # The spec itself must not quote a name either — scrub before it is stored.
    return scrub_all_students(spec)


def save_style_profile(report_type, spec, source):
    """Append the (already scrubbed, user-reviewed) spec to StyleMemory. Latest wins."""
    try:
        ws = gc.open('StyleMemory').sheet1
        ws.append_row([datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                       report_type, spec, source], value_input_option="RAW")
        _style_cache["ts"] = 0  # invalidate cache
        return f"Style profile for '{report_type}' saved — it applies to the next reports."
    except Exception as e:
        return f"Could not save to StyleMemory: {e}"


def reset_style_profile(report_type):
    """Reset one report type back to the built-in exemplar (empty-spec row)."""
    try:
        ws = gc.open('StyleMemory').sheet1
        ws.append_row([datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                       report_type, "", "reset"], value_input_option="RAW")
        _style_cache["ts"] = 0
        return f"Style for '{report_type}' reset to the built-in default."
    except Exception as e:
        return f"Could not reset: {e}"


def generatePrompt(type,theassessment, previousassessments, num, nums, date, question, role1, pseudonym):
    print(f"{num} of total {nums}")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the {type} assessment separated by <>, extract useful information.
        The information you have to extract is based on the following question: {question}
        Format your response with the following structure:
        {{
            "date": {date},
            "student": {pseudonym},
            "response_to_question": Response to question
        }}
        To effectively complete the summarization, follow these steps:
        - There are a total of {nums} assessments, so that will be the number of objects.
        - For every response_to_question, keep the same format as the first one.
        - Give the response in English.
        - Take your time to produce the first response that might seem more appropriate.
        - Keep the response_to_question at a minimum number of tokens.
        - The date of the current assessment is {date}.
        - Try to answer only what has been asked in the question.
        - Keep in mind that the person that will present the summarization will have the role of: {role1}.
        --Do not add senseitive content such as names to the final responce.

        <{theassessment}>
    """)
    if type == "Student":  # formative rows carry well-being + collaboration fields
        prompt += dedent("""\
            Interpretation guide for this formative assessment:
            - Emotional mood and Energy in class describe the child's psychological
              state (Leuven well-being + energy axis): 1 = distress/apathy, 5 = joy/alertness.
            - Communication & shared understanding and Contribution & teamwork break down
              collaboration (shared understanding vs. contribution to the team).
            - Deep engagement & persistence and Initiative & autonomy capture deep involvement
              and self-directed initiative.
            - The observer notes (Mood & well-being note, Collaboration note, Standout
              moment) are the EVIDENCE behind the numbers — weave them in; a number
              without its observation is weak.
            - Treat emotional content as observed behaviour, never as a diagnosis.
        """)
    elif type == "Self":
        prompt += dedent("""\
            Interpretation guide for this self-assessment:
            - Self-rated performance is the child's OWN view of how well they did —
              a marked gap against the teacher's formative scores is itself a finding
              (under-confidence or over-confidence), mention it.
            - I asked for help when I needed it captures help-seeking — a strength, not a weakness.
            - How I feel after the lesson is the child's own mood check-in (1-5).
        """)
    elif type == "Post Parent":
        prompt += dedent("""\
            Interpretation guide for this parent post-assessment:
            - Talks spontaneously at home about lessons measures TRANSFER — spontaneous
              talk about lessons at home is the strongest sign of genuine interest.
            - Change in self-confidence is the parent's perceived confidence change
              (1 = declined, 5 = greatly improved).
            - Compare the parent's home view with the classroom evidence when relevant.
        """)

    return prompt

def generatePromptClass(type,theassessment, previousassessments, num, nums, date, question, role1, LessonId):
    print(f"{num} of total {nums}")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the class assessment separated by <>, extract useful information. 
        The information you have to extract is based on the following question: {question}
        Format your response with the following structure:
        {{
            "date": {date},
            "ClassID": {LessonId},
            "response_to_question": Response to question
        }}
        To effectively complete the summarization, follow these steps:
        - There are a total of {nums} assessments, so that will be the number of objects.
        - For every response_to_question, keep the same format as the first one.
        - Give the response in English.
        - Take your time to produce the first response that might seem more appropriate.
        - Keep the response_to_question at a minimum number of tokens.
        - The date of the current assessment is {date}.
        - Try to answer only what has been asked in the question.
        - Keep in mind that the person that will present the summarization will have the role of: {role1}.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.

        <{theassessment}>
    """)
    prompt += CLASS_CLIMATE_GUIDE

    return prompt

CLASS_CLIMATE_GUIDE = dedent("""\
    Interpretation guide for class-climate fields (CLASS framework):
    - Class emotional climate = emotional support: positive climate,
      warmth, teacher sensitivity to needs (1 = cold/tense, 5 = warm/safe).
    - Session organization & flow = classroom organization: behaviour management,
      productivity of time (1 = chaotic, 5 = smooth).
    - Feedback & questioning quality = instructional support: feedback
      that pushes thinking, concept development (1 = rote, 5 = thought-provoking).
    - The moment that defined the class is the defining anecdote — quote it.
""")

def generatePromptLesson(type,ClassID, theassessment, previousassessments, num, nums, date, question, role1, LessonId):
    print(f"{num} of total {nums}")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        Given the lesson assessment from a class separated by <>, extract useful information. 
        The information you have to extract is based on the following question: {question}
        Format your response with the following structure:
        {{
            "date": {date},
            "Lesson Description": {LessonId},
            "ClassID assessment taken": {ClassID},
            "response_to_question": Response to question
        }}
        To effectively complete the summarization, follow these steps:
        - There are a total of {nums} assessments, so that will be the number of objects.
        - For every response_to_question, keep the same format as the first one.
        - Give the response in English.
        - Take your time to produce the first response that might seem more appropriate.
        - Keep the response_to_question at a minimum number of tokens.
        - The date of the current assessment is {date}.
        - Try to answer only what has been asked in the question.
        - Keep in mind that the person that will present the summarization will have the role of: {role1}.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.

        <{theassessment}>
    """)
    prompt += CLASS_CLIMATE_GUIDE

    return prompt

def finalChildPrompt(foass, selfass, postass, parentass, Descrip, question, role1):
    print(question)
    style = get_style_block("student")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        {style}
        Given a child assessments from various types, answer the following question and just that: {question}
        You will be given the formative assessments, self assessments, and post assessments separated by <>, in JSON format.
        Extract useful information from the "response_to_question" of the JSON object.
        The format is the following:
        {{
            "date": the date of the assessment,
            "student": the anonymized pseudonym of the child being assessed,
            "response_to_question": Here is the assessment of the lesson for the child
        }}
        In this JSON, each object is an assessment of a different lesson.
        You will also be given the parent assessment, separated by &&.
        To effectively complete the summarization, follow these steps:
        - Give the response in English.
        - Take your time to produce the response that might seem more appropriate.
        - Try to answer fully what has been asked to the question.
        - Make the report about 2000 tokens.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.
        Formative Assessments: <{foass}>
        Self Assessments from the student: <{selfass}>
        Post Assessments from the parent: <{postass}>
        This is the parent pre assessment: &{parentass}&
    """)

    print(prompt)

    return prompt

def finalClassPrompt(lesass, LessonTitle, question, role1):
    print(question)
    style = get_style_block("class")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        {style}
        Given a Class assessments, answer the following question and just that: {question}
        You will be given the assessments of the classrrom, separated by <>, in JSON format.
        Extract useful information from the "response_to_question" of the JSON object.
        The lesson of the classroom is: {LessonTitle}
        The format is the following:
        {{
            "date": the date of the assessment,
            "ClassID": the class ID,
            "response_to_question": Here is the assessment of the class
        }}
        In this JSON, each object is an assessment of a different classroom lesson.
        To effectively complete the summarization, follow these steps:
        - Give the response in English.
        - Take your time to produce the response that might seem more appropriate.
        - Try to answer fully what has been asked to the question.
        - Make the report about 1000 tokens.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.
        <{lesass}>
    """)

    print(prompt)

    return prompt
def finalLessonPrompt(lesass, LessonTitle, question, role1,seenclasses):
    print(question)
    style = get_style_block("lesson")
    prompt = dedent(f"""\
        {ENGLISH_ONLY}
        {style}
        Given a Lesson assessments across various classes, answer the following question and just that: {question}
        You will be given the assessments of the lesssons across various classes, separated by <>, in JSON format.
        Extract useful information from the "response_to_question" of the JSON object.
        The lesson  is: {LessonTitle}
        The format is the following:
        {{
            "date": the date of the assessment,
            "Lesson Description": The lesson Description,
            "ClassID assessment taken": the class id the assessment was taken,
            "response_to_question": Here is the assessment of the lesson
        }}
        In this JSON, each object is an assessment of different lesson curriculums in different classrooms.
        To effectively complete the summarization, follow these steps:
        - Give the response in English.
        - Take your time to produce the response that might seem more appropriate.
        - Try to answer fully what has been asked to the question.
        - Make the report about 1000 tokens.
        - The classes in this lesson are in the following python set: {seenclasses}.
        --Do not add senseitive content such as names to the final responce. Replace it, if there is any, with Student ID.
        <{lesass}>
    """)

    print(prompt)

    return prompt

def generate_html_report(report_text, model=None):
    model = model or MODEL
    prompt = f"""
    Please format the following text into structured HTML sections with appropriate headings and paragraphs:

    {report_text}

    Ensure the HTML is well-structured, with sections separated by headings and content within paragraphs. Add any necessary styling to make the report visually appealing.
    """

    message=[
        {
            "role": "system", "content": f"You are a helpful assistant. Keep all visible text in English. {ENGLISH_ONLY}"},
        {
        "role": "user", "content": prompt
        }
    ]
    response = get_client().chat.completions.create(
        model=model,
        messages=message,
        max_tokens=2000
    )

    formatted_report = response.choices[0].message.content.strip()
    return formatted_report


def get_unique_student_ids_from_fo_assessment():
    # Open the FoAssesment sheet
    _connect_sheets()

    # Get the header row
    headerFo = FoAssesment.row_values(1)
    
    # Get the index of the "Student ID" column
    FoAssesment_column_index = headerFo.index("Student ID") + 1
    
    # Initialize a set to store unique student IDs
    unique_student_ids = set()
    
    # Iterate through each row in the sheet, starting from the second row
    for row in FoAssesment.get_all_values()[1:]:
        student_id = row[FoAssesment_column_index - 1]
        unique_student_ids.add(student_id)
    
    # Convert the set to a list and return it
    return list(unique_student_ids)

# ---------------------------------------------------------------------------
# Option lists for the UI dropdown pickers (students / lessons / class groups),
# so nobody has to memorise IDs. Names appear ONLY in the authenticated
# teacher UI — they are never sent to the LLM.
# ---------------------------------------------------------------------------
LESSON_EN = {
    "ΜΑ": "National Team",
    "ΜΒ": "Preschool STEM",
    "ΜΓ": "Junior Robotics",
    "ΜΔ": "Advanced Robotics",
    "ΜΕ": "Advanced Robotics 2",
    "ΜΖ": "Spike Prime Robotics",
    "ΜΛ": "Minecraft",
    "ΜΩ": "Competition Robotics",
    "ΜΘ": "PBR",
}


def lesson_label_en(code):
    """English label for a lesson prefix or group code ('ΜΓ1' -> 'Junior Robotics')."""
    return LESSON_EN.get(str(code).strip()[:2], "")


def get_student_options():
    """[{id, label}] from the Students sheet: 'demo02 — Name Surname · ΜΓ1'."""
    _connect_sheets()
    header = Students.row_values(1)
    i_id = header.index("ID")
    i_name = header.index("Name")
    i_surname = header.index("Surname")
    i_lesson1 = header.index("Lesson ID 1") if "Lesson ID 1" in header else None
    options = []
    for row in Students.get_all_values()[1:]:
        if len(row) <= i_id:
            continue
        sid = row[i_id].strip()
        if not sid:
            continue
        name = row[i_name].strip() if len(row) > i_name else ""
        surname = row[i_surname].strip() if len(row) > i_surname else ""
        groups = []
        if i_lesson1 is not None:
            groups = [g.strip() for g in row[i_lesson1:i_lesson1 + 4] if g.strip()]
        label = sid
        full = f"{name} {surname}".strip()
        if full:
            label += f" — {full}"
        if groups:
            label += f" · {', '.join(groups)}"
        options.append({"id": sid, "label": label})
    options.sort(key=lambda o: o["id"])
    return options


def get_lesson_options():
    """[{id, label}] from Lessons tab1: 'ΜΓ — Junior Robotics' (English label)."""
    lessons_ws = gc.open('Lessons').sheet1
    header = lessons_ws.row_values(1)
    i_id = header.index("ID")
    options = []
    for row in lessons_ws.get_all_values()[1:]:
        if len(row) <= i_id:
            continue
        lid = row[i_id].strip()
        if not lid:
            continue
        en = lesson_label_en(lid)
        options.append({"id": lid, "label": f"{lid} — {en}" if en else lid})
    return options


def get_group_options():
    """[{id, label}] from Lessons tab2: 'ΜΓ1 — Junior Robotics (Δευτέρα 18:00-19:30)'."""
    _connect_sheets()  # the global `Lessons` handle is tab2 (class groups)
    header = Lessons.row_values(1)
    i_lesson = header.index("Group code")
    # Schedule holds day+time ("Δευτέρα 18:00-19:30"); Price is not shown.
    i_day = header.index("Schedule") if "Schedule" in header else None
    options = []
    for row in Lessons.get_all_values()[1:]:
        if len(row) <= i_lesson:
            continue
        code = row[i_lesson].strip()
        if not code:
            continue
        en = lesson_label_en(code)
        schedule = row[i_day].strip() if i_day is not None and len(row) > i_day else ""
        label = code
        if en:
            label += f" — {en}"
        if schedule:
            label += f" ({schedule})"
        options.append({"id": code, "label": label})
    return options


def process_all_students(student_name,date, AssesType, role, save, model=None):
    model = model or MODEL
    # Get unique student IDs
    student_ids = [student_id.strip() for student_id in student_name.split(',')]
    unique_student_ids = get_unique_student_ids_from_fo_assessment()

    # Process each student, excluding those in the student_ids list
    for i, student_id in enumerate(unique_student_ids):
        if student_id not in student_ids:  # Skip students in the student_ids list
            report, name, surname = ChildrenAssessemnt(student_id, date, AssesType, role, save, model=model)
            print(f"Processed student ID: {student_id}")  # no names in logs (GDPR)
            print(report)
            
            # Add a 1-second delay between each student to meet per-user quota
            time.sleep(1)
            
            # Every 5 students, add an additional delay to meet per-project quota
            if (i + 1) % 5 == 0:
                time.sleep(5)
