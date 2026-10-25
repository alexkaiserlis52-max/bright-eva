import os
import time
import uuid
import contextlib
from datetime import datetime
import requests
from flask import Flask, render_template, request, session, jsonify, redirect, url_for, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

from openai_reports import *
from chat_agent import run_chat_stream, SYSTEM_PROMPT
import pipeline_trace as pt
import risk_notes as rn
import sandbox as sb

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-insecure-key-change-me")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure cookie in production (Cloud Run terminates HTTPS). Local dev runs plain HTTP.
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_DEBUG", "1") != "1",
)

# ---------------------------------------------------------------------------
# Access control — MANDATORY before any public/cloud exposure (minors' data,
# GDPR). Set APP_PASSWORD in the environment to enable the login gate.
# When APP_PASSWORD is empty (local dev), the gate is disabled.
# ---------------------------------------------------------------------------
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# Risk Lab (sandbox experiments): on by default in local dev; in production it
# must be enabled explicitly with SANDBOX_MODE=1 (it IS the AIED demo).
SANDBOX_MODE = os.environ.get(
    "SANDBOX_MODE", "1" if os.environ.get("FLASK_DEBUG", "1") == "1" else "0") == "1"

# Educator Override: when on, reports requested with "save" are generated
# under a dry-run and staged for an explicit approve/edit/reject decision
# before anything is written to the school's sheets.
REQUIRE_APPROVAL = os.environ.get("REQUIRE_APPROVAL", "0") == "1"


@app.context_processor
def inject_auth_state():
    """Templates use auth_enabled to show/hide the logout link."""
    return {"auth_enabled": bool(APP_PASSWORD), "sandbox_enabled": SANDBOX_MODE}


@app.before_request
def require_login():
    if not APP_PASSWORD:
        return  # gate disabled for local development
    if request.endpoint in ("login", "static"):
        return
    if not session.get("authed"):
        return redirect(url_for("login", next=request.path))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if APP_PASSWORD and request.form.get('password') == APP_PASSWORD:
            session['authed'] = True
            return redirect(request.args.get('next') or url_for('intro'))
        error = "Wrong password. Please try again."
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Shown if the live OpenRouter model list cannot be fetched (e.g. no key yet)
FALLBACK_MODELS = [
    "openai/gpt-5-nano",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.3-70b-instruct",
]

_models_cache = {"ts": 0, "models": None}


@app.route('/api/models')
def list_models():
    """Available OpenRouter models + the currently selected one (for the UI picker)."""
    now = time.time()
    if _models_cache["models"] is None or now - _models_cache["ts"] > 300:
        try:
            r = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
            r.raise_for_status()
            _models_cache["models"] = sorted(m["id"] for m in r.json().get("data", []))
        except Exception:
            _models_cache["models"] = FALLBACK_MODELS
        _models_cache["ts"] = now
    return jsonify({
        "models": _models_cache["models"],
        "current": session.get('model', MODEL),
    })


_options_cache = {"ts": 0, "data": None}


@app.route('/api/options')
def form_options():
    """Students / lessons / class groups for the UI dropdown pickers.

    Names are served only here — the authenticated teacher UI — never to the LLM.
    Cached for 5 min; on sheet errors the UI falls back to plain text inputs.
    """
    now = time.time()
    if _options_cache["data"] is None or now - _options_cache["ts"] > 300:
        try:
            _options_cache["data"] = {
                "students": get_student_options(),
                "lessons": get_lesson_options(),
                "groups": get_group_options(),
            }
            # Entities with actual data (assessments/reports) — the UI hides
            # the rest as dead ends. Fail-open: if this breaks, no key is sent
            # and the UI simply shows everything.
            try:
                workable = get_workable_sets()
                _options_cache["data"]["workable"] = {k: sorted(v) for k, v in workable.items()}
            except Exception as e:
                print(f"Could not compute workable sets: {e}")
            _options_cache["ts"] = now
        except Exception as e:
            print(f"Could not load form options: {e}")
            if _options_cache["data"] is None:
                return jsonify({"students": [], "lessons": [], "groups": [], "error": str(e)})
    return jsonify(_options_cache["data"])


@app.route('/set_model', methods=['POST'])
def set_model():
    data = request.get_json(silent=True) or request.form
    model = data.get('model')
    if model:
        session['model'] = model
    return jsonify({"ok": True, "model": session.get('model', MODEL)})

# ---------------------------------------------------------------------------
# Agentic chat — SSE streaming. Conversation history lives server-side
# (in-memory, per process) keyed by a small session token; only the
# 32-char id goes into the cookie.
# ---------------------------------------------------------------------------
_chat_histories = {}


@app.route('/chat')
def chat():
    return render_template('chat.html')


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get('message') or '').strip()
    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    chat_id = session.get('chat_id')
    if not chat_id or chat_id not in _chat_histories:
        chat_id = uuid.uuid4().hex
        session['chat_id'] = chat_id
        _chat_histories[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    history = _chat_histories[chat_id]
    history.append({"role": "user", "content": user_msg})
    if len(history) > 25:  # keep system + last 24 messages
        history[:] = [history[0]] + history[-24:]

    model = session.get('model', MODEL)
    trace = pt.start_trace("chat", label=user_msg[:80], model=model)
    pt.record("note", kind="user_message", message=user_msg)

    @stream_with_context
    def gen():
        try:
            for event in run_chat_stream(history, model=model):
                if event.get("type") == "done":
                    event["trace_id"] = trace.run_id
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            pt.record("error", where="chat_stream", message=str(e)[:500])
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
        finally:
            pt.finish_trace()

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/chat/reset', methods=['POST'])
def api_chat_reset():
    chat_id = session.pop('chat_id', None)
    if chat_id:
        _chat_histories.pop(chat_id, None)
    return jsonify({"ok": True})


@app.route('/')
def intro():
    return render_template('intro.html')

@app.route('/main')
def main():
    return render_template('index.html',
                           current_model=session.get('model', MODEL),
                           fallback_models=FALLBACK_MODELS)

@app.route('/view_report', methods=['POST'])
def process():
    log = []
    model = session.get('model', MODEL)  # picked on the fly from the UI model selector
    report_type = request.form.get('report-type')
    student_name = request.form.get('student-name')
    lesson_name = request.form.get('lesson-name')
    class_group = request.form.get('class-group')
    assessment_date = request.form.get('assessment-date')
    assessment_date_lesson = request.form.get('assessment-date-lesson')
    assessment_date_group = request.form.get('assessment-date-group')
    what_to_assess = request.form.get('what-to-assess')
    what_to_assess_lesson = request.form.get('what-to-assess-lesson')
    what_to_assess_group = request.form.get('what-to-assess-group')
    stu_role = request.form.get('stu_role')
    less_role = request.form.get('less_role')
    group_role = request.form.get('group_role')
    action_choice = request.form.get('action-choice')
    save = request.form.get('save_checkbox')

    entity = (student_name or lesson_name or class_group
              or request.form.get('class-question')
              or request.form.get('askme-group') or '')
    trace = pt.start_trace("report", label=f"{report_type} · {entity or 'run'}",
                           model=model,
                           collect_samples=os.environ.get("TRACE_SCRUB_SAMPLES", "1") == "1")
    pt.record("note", kind="request", report_type=report_type, entity=entity,
              save_to_sheets=bool(save),
              educator_override=REQUIRE_APPROVAL and bool(save),
              dates={"student": assessment_date, "lesson": assessment_date_lesson,
                     "group": assessment_date_group,
                     "question": request.form.get('assessment-date-question')})
    approval_required = REQUIRE_APPROVAL and bool(save)
    _dry_ctx = pt.dry_run() if approval_required else None
    if _dry_ctx is not None:
        _dry_ctx.__enter__()
    try:
        if report_type == 'stu_teacher':
            student_name = request.form.get('student-name')
            theReport, name, surname = ChildrenAssessemnt(student_name, str(assessment_date), what_to_assess, stu_role, save, model=model)
            log.append(f"Generated {report_type} report for {student_name} on {assessment_date}")
            strname = f"{name} {surname}"

            session['report_info'] = {
                'type': "Student",
                'name': strname,
                'when': assessment_date,
                'what': what_to_assess,
                'role': stu_role,
                'save': save,
                'model': model,
                'theReport': theReport,
                'trace_id': trace.run_id,
            }
            if approval_required:
                token = _stage_pending(trace.run_id, "Student", student_name,
                                       assessment_date, what_to_assess, stu_role,
                                       _first_lesson_id(student_name), theReport, model)
                pt.record("note", kind="educator_override",
                          message="Report generated under DRY-RUN and staged — awaiting the educator's decision before anything is saved.")
                return render_template("approve.html", token=token, type="Student",
                                       name=student_name, date=assessment_date,
                                       report=theReport, trace_id=trace.run_id)
            return render_template("generate_html.html", type="Student", name=student_name, date=assessment_date, report=theReport, log=log, trace_id=trace.run_id)

        elif report_type == 'all_students':
            process_all_students(student_name, str(assessment_date), what_to_assess, stu_role, save, model=model)
            log.append(f"Processed all students on {assessment_date}")
            return render_template("generate_html.html", type="All Students", name="All Students", date=assessment_date, report="Processed all students", log=log, trace_id=trace.run_id)
        elif report_type == "less_teacher":
            theReport = LessonAssessment(lesson_name, str(assessment_date_lesson), what_to_assess_lesson, less_role, save, model=model)
            log.append(f"Generated {report_type} report for {lesson_name} on {assessment_date_lesson}")

            session['report_info'] = {
                'type': "Lesson",
                'name': lesson_name,
                'when': assessment_date_lesson,
                'what': what_to_assess_lesson,
                'role': less_role,
                'save': save,
                'model': model,
                'theReport': theReport,
                'trace_id': trace.run_id,
            }
            if approval_required:
                token = _stage_pending(trace.run_id, "Lesson", lesson_name,
                                       assessment_date_lesson, what_to_assess_lesson,
                                       less_role, "", theReport, model)
                pt.record("note", kind="educator_override",
                          message="Report generated under DRY-RUN and staged — awaiting the educator's decision before anything is saved.")
                return render_template("approve.html", token=token, type="Lesson",
                                       name=lesson_name, date=assessment_date_lesson,
                                       report=theReport, trace_id=trace.run_id)
            return render_template("generate_html.html", type="Lesson", name=lesson_name, date=assessment_date_lesson, report=theReport, log=log, trace_id=trace.run_id)

        elif report_type == "group_teacher":
            theReport = classAssessment(class_group, str(assessment_date_group), what_to_assess_group, group_role, save, model=model)
            log.append(f"Generated {report_type} report for {class_group} on {assessment_date_group}")

            session['report_info'] = {
                'type': "Group",
                'name': class_group,
                'when': assessment_date_group,
                'what': what_to_assess_group,
                'role': group_role,
                'save': save,
                'model': model,
                'theReport': theReport,
                'trace_id': trace.run_id,
            }
            if approval_required:
                token = _stage_pending(trace.run_id, "Class", class_group,
                                       assessment_date_group, what_to_assess_group,
                                       group_role, "", theReport, model)
                pt.record("note", kind="educator_override",
                          message="Report generated under DRY-RUN and staged — awaiting the educator's decision before anything is saved.")
                return render_template("approve.html", token=token, type="Class",
                                       name=class_group, date=assessment_date_group,
                                       report=theReport, trace_id=trace.run_id)
            return render_template("generate_html.html", type="Group", name=class_group, date=assessment_date_group, report=theReport, log=log, trace_id=trace.run_id)

        elif report_type == "question_teacher":
            class_question = request.form.get('class-question')
            assessment_date_question = (request.form.get('assessment-date-question')
                                        or datetime.today().strftime('%Y-%m-%d'))
            what_to_assess_question = request.form.get('what-to-assess-question')
            question_role = (request.form.get('question_role') or "").strip() \
                or "An experienced educational advisor"
            askme_group = request.form.get('askme-group') or None
            askme_lesson = request.form.get('askme-lesson') or None

            theReport = askmeForm(action_choice, class_question, assessment_date_question,
                                  what_to_assess_question, question_role, save,
                                  group=askme_group, lesson=askme_lesson, model=model)
            scope_bits = [b for b in (class_question, askme_group, askme_lesson) if b]
            log.append(f"ASK ME [{action_choice}] over {', '.join(scope_bits) or 'the whole archive'} "
                       f"on {assessment_date_question}")

            session['report_info'] = {
                'type': "ASK ME",
                'name': class_question or askme_group or "smart query",
                'when': assessment_date_question,
                'what': what_to_assess_question,
                'role': question_role,
                'save': save,
                'model': model,
                'theReport': theReport,
                'trace_id': trace.run_id,
            }
            return render_template("generate_html.html", type="ASK ME", name=class_question or askme_group or "Smart Query", date=assessment_date_question, report=theReport, log=log, trace_id=trace.run_id)

        else:
            theReport = "Invalid report type selected."
            log.append(f"Error: {theReport}")
            return theReport
    except Exception as e:
        pt.record("error", where="view_report", message=str(e)[:500])
        raise
    finally:
        if _dry_ctx is not None:
            _dry_ctx.__exit__(None, None, None)
        pt.finish_trace()

# ---------------------------------------------------------------------------
# Glass-box pipeline viewer — every report/chat run leaves a trace on disk;
# these pages make the whole pipeline inspectable (AIED sandbox).
# ---------------------------------------------------------------------------
@app.route('/pipeline')
def pipeline_index():
    return render_template('pipeline_list.html', runs=pt.list_traces(),
                           notice=session.pop('pipeline_notice', None))


@app.route('/pipeline/<run_id>')
def pipeline_detail(run_id):
    data = pt.load_trace(run_id)
    if data is None:
        return "Trace not found.", 404
    vx = pt.run_resources(data)
    signals, controls = pt.detect_risk_signals(data, vx)
    return render_template('pipeline.html', t=data, vx=vx,
                           stage_info=pt.STAGE_INFO, stage_risks=pt.STAGE_RISKS,
                           signals=signals, controls=controls,
                           notes=rn.list_notes(run_id),
                           ref_titles=rn.REF_TITLES,
                           sheet_urls=sheet_links())


@app.route('/pipeline/<run_id>/risk-note', methods=['POST'])
def pipeline_risk_note(run_id):
    """Register a human risk observation on this run (living risk register)."""
    if pt.load_trace(run_id) is None:
        return "Trace not found.", 404
    ref = (request.form.get('ref') or 'new').strip().lower()
    if ref not in rn.VALID_REFS:
        ref = 'new'
    severity = (request.form.get('severity') or 'info').strip()
    if severity not in rn.SEVERITIES:
        severity = 'info'
    stage = (request.form.get('stage') or 'whole run').strip()[:40].replace('\n', ' ')
    author = (request.form.get('author') or '').strip()[:60]
    comment = (request.form.get('comment') or '').strip()[:1000]
    if comment:
        try:
            rn.add_note(run_id, stage, ref, severity, author, comment)
        except Exception as e:
            print(f"Could not save risk note: {e}")
    return redirect(url_for('pipeline_detail', run_id=run_id) + '#risk-notes')


@app.route('/pipeline/<run_id>/raw')
def pipeline_raw(run_id):
    data = pt.load_trace(run_id)
    if data is None:
        return "Trace not found.", 404
    return Response(json.dumps(data, ensure_ascii=False, indent=2),
                    mimetype='application/json',
                    headers={'Content-Disposition':
                             f'inline; filename=trace-{run_id}.json'})


@app.route('/pipeline/<run_id>/delete', methods=['POST'])
def pipeline_delete(run_id):
    """Remove one trace from the glass box (housekeeping before a demo)."""
    pt.delete_trace(run_id)
    return redirect(url_for('pipeline_index'))


@app.route('/pipeline/clear', methods=['POST'])
def pipeline_clear():
    """Bulk cleanup — all traces, or only one kind (report / chat / sandbox)."""
    kind = request.form.get('kind', '')
    removed = pt.clear_traces(kind=kind if kind in ('report', 'chat', 'sandbox') else None)
    session['pipeline_notice'] = (f"Removed {removed} trace{'s' if removed != 1 else ''}"
                                  + (f" (kind: {kind})" if kind else "") + ".")
    return redirect(url_for('pipeline_index'))


# ---------------------------------------------------------------------------
# Risk Lab — interactive experiments for the AIED expert sandbox. Each one
# pokes a real safeguard and records a full pipeline trace of what happened.
# ---------------------------------------------------------------------------
def _sandbox_off():
    return render_template('sandbox_off.html'), 404


@app.route('/sandbox')
def sandbox_page():
    if not SANDBOX_MODE:
        return _sandbox_off()
    demo_ids = [f"demo{n:02d}" for n in range(1, 13)]
    return render_template('sandbox.html', demo_ids=demo_ids,
                           result=None, active=None)


@app.route('/sandbox/pii', methods=['POST'])
def sandbox_pii():
    if not SANDBOX_MODE:
        return _sandbox_off()
    result = sb.pii_probe(request.form.get('student_id', 'demo02'),
                          request.form.get('probe_text', ''))
    return render_template('sandbox.html', demo_ids=[f"demo{n:02d}" for n in range(1, 13)],
                           result=result, active='pii')


@app.route('/sandbox/inject', methods=['POST'])
def sandbox_inject():
    if not SANDBOX_MODE:
        return _sandbox_off()
    result = sb.injection_probe(request.form.get('student_id', 'demo02'),
                                request.form.get('probe_text', ''),
                                model=session.get('model', MODEL))
    return render_template('sandbox.html', demo_ids=[f"demo{n:02d}" for n in range(1, 13)],
                           result=result, active='inject')


@app.route('/sandbox/ungrounded', methods=['POST'])
def sandbox_ungrounded():
    if not SANDBOX_MODE:
        return _sandbox_off()
    result = sb.ungrounded_demo(request.form.get('student_id', 'demo02'),
                                model=session.get('model', MODEL))
    return render_template('sandbox.html', demo_ids=[f"demo{n:02d}" for n in range(1, 13)],
                           result=result, active='ungrounded')


@app.route('/sandbox/compare', methods=['POST'])
def sandbox_compare():
    if not SANDBOX_MODE:
        return _sandbox_off()
    result = sb.guardrails_compare(request.form.get('student_id', 'demo02'),
                                   model=session.get('model', MODEL))
    return render_template('sandbox.html', demo_ids=[f"demo{n:02d}" for n in range(1, 13)],
                           result=result, active='compare')


@app.route('/sandbox/early', methods=['POST'])
def sandbox_early():
    if not SANDBOX_MODE:
        return _sandbox_off()
    result = sb.early_warning_demo(request.form.get('student_id', 'demo09'))
    return render_template('sandbox.html', demo_ids=[f"demo{n:02d}" for n in range(1, 13)],
                           result=result, active='early')


# ---------------------------------------------------------------------------
# Educator Override — human-in-the-loop gate before saving (AI Act Art. 14).
# Reports are generated under a dry-run, staged, and only an explicit
# approve/edit/reject decision (recorded in the run's trace) settles them.
# ---------------------------------------------------------------------------
_pending_reports = {}


def _first_lesson_id(student_id):
    try:
        _connect_sheets()
        header = Students.row_values(1)
        idx = header.index("Lesson ID 1")
        for row in Students.get_all_values()[1:]:
            if row and row[0] == student_id:
                return row[idx] if len(row) > idx else ""
    except Exception:
        pass
    return ""


def _stage_pending(trace_id, typeo, entity, date, what, role, lesson_id, report, model):
    token = uuid.uuid4().hex[:16]
    _pending_reports[token] = {
        "trace_id": trace_id, "typeo": typeo, "entity": entity, "date": date,
        "what": what, "role": role, "lesson_id": lesson_id,
        "report": report, "model": model,
    }
    return token


@app.route('/approve/<token>', methods=['POST'])
def approve_report(token):
    p = _pending_reports.pop(token, None)
    if p is None:
        return "This staged report has already been settled (or expired).", 404
    action = request.form.get('action', 'reject')
    edited = (request.form.get('edited_report') or '').strip()
    if action in ('approve', 'edit'):
        final_text = edited if (action == 'edit' and edited) else p['report']
        critic_note = ""
        if action == 'edit' and edited and edited != p['report']:
            # The educator's edit bypasses the earlier critic pass — re-check
            # and log the verdict; the human remains the final authority.
            ok, feedback = critic_check(p['what'], final_text, p['model'])
            critic_note = f"post-edit critic: {'PASS' if ok else 'FAIL — ' + feedback}"
        write_to_reports_file(final_text, p['typeo'], p['entity'], p['date'],
                              p['what'], p['role'], p['lesson_id'])
        reflect_and_store(p['typeo'], p['entity'], p['date'], p['what'],
                          final_text, p['model'])
        pt.append_event(p['trace_id'], "save", sheet="ReportsFile + InsightsMemory",
                        type=p['typeo'], entity=p['entity'],
                        educator_decision=("approved" if action == 'approve'
                                           else "approved_after_edit"),
                        post_edit_critic=critic_note,
                        report_chars=len(final_text))
        return render_template('approve_done.html', decision="approved",
                               edited=(action == 'edit'), critic_note=critic_note,
                               trace_id=p['trace_id'], entity=p['entity'])
    pt.append_event(p['trace_id'], "save", blocked=True, type=p['typeo'],
                    entity=p['entity'],
                    reason="Educator REJECTED the report — nothing was saved")
    pt.append_event(p['trace_id'], "note", kind="educator_override",
                    decision="rejected",
                    message="The human reviewer stopped this report from entering the record.")
    return render_template('approve_done.html', decision="rejected",
                           edited=False, critic_note="", trace_id=p['trace_id'],
                           entity=p['entity'])


# ---------------------------------------------------------------------------
# Risk Register — LIVING register: the curated baseline risks (R1–R10) plus
# every observation reviewers registered while inspecting real traces. New,
# unlisted risks gather as candidates for the next register revision.
# ---------------------------------------------------------------------------
@app.route('/risk-register')
def risk_register():
    notes = rn.list_notes()
    by_ref = {}
    for n in notes:
        by_ref.setdefault(n["ref"], []).append(n)
    stats = {
        "total": len(notes),
        "traces": len({n["trace_id"] for n in notes}),
        "candidates": len(by_ref.get("new", [])),
        "confirmed": sum(1 for n in notes if n["status"] == "confirmed"),
    }
    return render_template('risk_register.html', by_ref=by_ref, stats=stats,
                           ref_titles=rn.REF_TITLES)


@app.route('/risk-note/<int:row>/status', methods=['POST'])
def risk_note_status(row):
    """Triage a note (open / confirmed / dismissed), then go back where we were."""
    try:
        rn.set_status(row, request.form.get('status', 'open'))
    except Exception as e:
        print(f"Could not update risk note status: {e}")
    back = request.form.get('back') or url_for('risk_register')
    if not back.startswith('/'):  # open-redirect guard
        back = url_for('risk_register')
    return redirect(back)


# ---------------------------------------------------------------------------
# Guide — the full, detailed explanation of every page, safeguard and term
# ---------------------------------------------------------------------------
@app.route('/guide')
def guide():
    return render_template('guide.html', sheet_urls=sheet_links())


# ---------------------------------------------------------------------------
# Style Studio — user-defined report style. A pasted sample report and/or
# free-text instructions are distilled ONCE into a compact style spec; that
# spec (never the sample) is stored in the StyleMemory sheet and injected into
# the final report prompts. The sample is scrubbed BEFORE distillation and the
# spec again BEFORE storage — pasting an old real report cannot leak a name.
# ---------------------------------------------------------------------------
STYLE_TYPES = {"student": "Student", "lesson": "Lesson", "class": "Class"}


def _render_style(**kw):
    base = dict(types=STYLE_TYPES, profiles=list_style_profiles(),
                spec=None, rtype='student', source='', notice=None)
    base.update(kw)
    return render_template('style.html', **base)


@app.route('/style')
def style_page():
    return _render_style()


@app.route('/style/distill', methods=['POST'])
def style_distill():
    rtype = request.form.get('report_type', 'student')
    if rtype not in STYLE_TYPES:
        rtype = 'student'
    sample = (request.form.get('sample') or '').strip()
    instructions = (request.form.get('instructions') or '').strip()
    if not sample and not instructions:
        return _render_style(rtype=rtype,
                             notice="Give an example report, style instructions, or both.")
    source = ('example+instructions' if sample and instructions
              else 'example' if sample else 'instructions')
    spec = distill_style(rtype, sample, instructions,
                         model=session.get('model', MODEL))
    return _render_style(rtype=rtype, source=source, spec=spec)


@app.route('/style/save', methods=['POST'])
def style_save():
    rtype = request.form.get('report_type', 'student')
    if rtype not in STYLE_TYPES:
        rtype = 'student'
    spec = (request.form.get('spec') or '').strip()
    source = request.form.get('source', 'manual')
    notice = save_style_profile(rtype, spec, source) if spec else "Nothing to save."
    return _render_style(rtype=rtype, notice=notice)


@app.route('/style/reset', methods=['POST'])
def style_reset():
    rtype = request.form.get('report_type', 'student')
    if rtype not in STYLE_TYPES:
        rtype = 'student'
    return _render_style(rtype=rtype, notice=reset_style_profile(rtype))


@app.route('/generate_html', methods=['POST'])
def createHTML():
    report_info = session.get('report_info')
    if not report_info:
        return "No report in session. Please generate a report first.", 400
    report_type = report_info['type']
    name = report_info['name']
    date = report_info['when']
    raw_report = report_info['theReport']

    # Generate the HTML formatted report
    formatted_report = generate_html_report(raw_report, model=report_info.get('model'))

    return render_template('generated_html.html', type=report_type, name=name, date=date, report=formatted_report)

if __name__ == '__main__':
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            debug=os.environ.get("FLASK_DEBUG", "1") == "1")
