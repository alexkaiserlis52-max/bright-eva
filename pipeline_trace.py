"""Glass-box pipeline tracing.

Every report generation or chat run can carry a TraceRecorder (held in a
contextvar, so it is safe under threaded Flask / gunicorn workers). Each stage
of the pipeline records a structured event: what data was fetched from where,
what the anonymizer masked, the exact prompt that went to the LLM, what came
back, what the critic said, what was saved.

Traces are stored as local JSON files under traces/ — no third-party
observability service ever sees this data. Built for the AIED expert sandbox:
transparency means *show*, not *tell*.

Instrumentation call sites use `record(...)` which is a no-op when no trace is
active, so normal (untraced) runs pay virtually nothing.
"""

import contextvars
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

TRACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
MAX_STORED_TRACES = 300
MAX_SAMPLES = 8

_current = contextvars.ContextVar("bright_eva_trace", default=None)
_guardrails = contextvars.ContextVar("bright_eva_guardrails", default=None)
_writes_blocked = contextvars.ContextVar("bright_eva_writes_blocked", default=False)

# Display order for the viewer's flow strip.
STAGE_ORDER = ["fetch", "scrub", "llm", "critic", "regenerate",
               "insight", "early_warning", "save", "tool", "note", "error"]

_write_lock = threading.Lock()
_run_id_re = re.compile(r"^[0-9a-f]{12}$")


def _clip(value, limit=12000):
    """Keep trace files readable: clip very long strings."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"… [+{len(value) - limit} chars]"
    return value


class TraceRecorder:
    """Collects stage events for one run and persists them as one JSON file."""

    def __init__(self, kind, label="", model="", collect_samples=False):
        self.run_id = uuid.uuid4().hex[:12]
        self.kind = kind                      # "report" | "chat" | "sandbox"
        self.label = label
        self.model = model
        self.collect_samples = collect_samples
        self.started = datetime.now().isoformat(timespec="seconds")
        self._t0 = time.time()
        self._last = self._t0
        self.events = []
        self.samples = []                     # scrub before/after pairs
        self._lock = threading.Lock()         # parallel per-assessment LLM calls record from worker threads

    def record(self, stage, **payload):
        with self._lock:
            now = time.time()
            event = {
                "t": datetime.now().isoformat(timespec="milliseconds"),
                "dt_ms": int((now - self._last) * 1000),
                "stage": stage,
            }
            self._last = now
            for key, value in payload.items():
                event[key] = _clip(value)
            self.events.append(event)

    def add_sample(self, field, before, after):
        """A scrub before/after pair (only when collect_samples=True)."""
        with self._lock:
            if not self.collect_samples or len(self.samples) >= MAX_SAMPLES:
                return
            self.samples.append({
                "field": str(field),
                "before": _clip(str(before), 400),
                "after": _clip(str(after), 400),
            })

    def summary(self):
        counts = {}
        for e in self.events:
            counts[e["stage"]] = counts.get(e["stage"], 0) + 1
        alerts = [e for e in self.events
                  if e["stage"] == "early_warning" and e.get("fired")]
        critic_fails = [e for e in self.events
                        if e["stage"] == "critic" and e.get("verdict") == "fail"]
        errors = [e for e in self.events if e["stage"] == "error"]
        return {
            "counts": counts,
            "alerts": len(alerts),
            "critic_fails": len(critic_fails),
            "errors": len(errors),
            "llm_calls": counts.get("llm", 0),
            "duration_ms": int((self._last - self._t0) * 1000),
        }

    def finish(self, status="ok", note=""):
        s = self.summary()
        if s["errors"] and status == "ok":
            status = "error"
        data = {
            "run_id": self.run_id,
            "kind": self.kind,
            "label": self.label,
            "model": self.model,
            "started": self.started,
            "finished": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "note": note,
            "summary": s,
            "events": self.events,
            "samples": self.samples,
        }
        os.makedirs(TRACES_DIR, exist_ok=True)
        path = os.path.join(TRACES_DIR, f"{self.run_id}.json")
        with _write_lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            _prune_traces()
        return data


def _prune_traces():
    try:
        files = sorted(
            (os.path.join(TRACES_DIR, f) for f in os.listdir(TRACES_DIR)
             if f.endswith(".json")),
            key=os.path.getmtime)
        for stale in files[:-MAX_STORED_TRACES]:
            os.remove(stale)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Active trace handling
# ---------------------------------------------------------------------------

def start_trace(kind, label="", model="", collect_samples=False):
    rec = TraceRecorder(kind, label=label, model=model,
                        collect_samples=collect_samples)
    _current.set(rec)
    return rec


def current_trace():
    return _current.get()


def record(stage, **payload):
    """No-op-safe instrumentation hook used across the codebase."""
    rec = _current.get()
    if rec is not None:
        rec.record(stage, **payload)


def add_sample(field, before, after):
    rec = _current.get()
    if rec is not None:
        rec.add_sample(field, before, after)


def finish_trace(status="ok", note=""):
    rec = _current.get()
    _current.set(None)
    if rec is not None:
        return rec.finish(status=status, note=note)
    return None


# ---------------------------------------------------------------------------
# Guardrail switches (sandbox "what-if" experiments). When ANY guardrail is
# relaxed the run is a dry-run: the data layer refuses to write to Sheets
# (see write_to_reports_file / reflect_and_store in openai_reports.py).
# ---------------------------------------------------------------------------

def guardrails():
    g = _guardrails.get()
    return g if g is not None else {"scrub": True, "critic": True}


def scrub_enabled():
    return guardrails().get("scrub", True)


def critic_enabled():
    return guardrails().get("critic", True)


def any_guardrail_relaxed():
    g = guardrails()
    return not (g.get("scrub", True) and g.get("critic", True))


def writes_blocked():
    """True when nothing may be written back to the school's sheets —
    either a guardrail is relaxed or an explicit dry-run is active."""
    return _writes_blocked.get() or any_guardrail_relaxed()


@contextmanager
def relaxed_guardrails(scrub=True, critic=True):
    """Temporarily switch guardrails off (sandbox experiments only)."""
    token = _guardrails.set({"scrub": scrub, "critic": critic})
    try:
        yield
    finally:
        _guardrails.reset(token)


@contextmanager
def dry_run():
    """Guardrails stay ON but sheet writes are blocked (sandbox experiments,
    educator-override preview pass)."""
    token = _writes_blocked.set(True)
    try:
        yield
    finally:
        _writes_blocked.reset(token)


# ---------------------------------------------------------------------------
# Viewer metadata — plain-language stage explanations + a resource registry,
# so the pipeline page answers "what happened, using WHAT, and under which
# data terms" instead of just listing raw events.
# ---------------------------------------------------------------------------

STAGE_INFO = {
    "fetch": ("Read the source data",
              "The run pulled the raw assessment rows it needs from the school's "
              "Google Sheets — nothing has left our system yet."),
    "scrub": ("Anonymization (GDPR)",
              "Before anything reaches an AI model, real names are replaced with "
              "[Student]/[Parent], emails with [email], phones with [phone]. "
              "Only pseudonymous IDs ever travel further."),
    "llm": ("AI processing",
            "An external language model summarized the assessments and composed "
            "text. It only ever sees anonymized data."),
    "tool": ("Agent tool call",
             "The chat agent looked something up on its own (a sheet, a memory "
             "card, a lesson plan) to ground its answer."),
    "critic": ("Quality gate",
               "A second AI pass reviewed the report before saving: does it "
               "answer the question, is it grounded, does it leak any name? "
               "A failure triggers one regeneration."),
    "regenerate": ("Regeneration",
                   "The critic found problems, so the report was produced once "
                   "more with the critic's feedback attached."),
    "insight": ("Memory distillation",
                "The report was compressed into a small structured insight card "
                "(trajectory, trends, risk flags) — the system's long-term memory."),
    "early_warning": ("Early-warning check",
                      "The new insight card was compared with this entity's "
                      "previous one. An alert fires only when the trajectory "
                      "worsens or new risk flags appear — otherwise it stays quiet."),
    "save": ("Saved to the archive",
             "The final report was appended to the ReportsFile sheet. In dry-run "
             "mode this step is blocked and only simulated."),
    "note": ("Run note", "Housekeeping information about how the run was set up."),
    "error": ("Error", "Something failed — the run's other events show how far it got."),
}

SHEET_INFO = {
    "Students": "Student registry — pseudonymous IDs, names, group assignments",
    "PreAssessment": "Parent expectations form, filled before the first lesson",
    "FoAssessment": "Teacher's per-session assessments (scores 1–5 + notes)",
    "SelfAssessment": "Student self-reflections after sessions",
    "PostAssessment": "Parent follow-up — changes observed at home",
    "LessonAssessment": "Per-session class observations (response, completion %, difficulties)",
    "Lessons": "Lesson catalogue & class groups (titles, descriptions, schedule)",
    "Lessons (groups)": "Class-group catalogue (schedule, description)",
    "ReportsFile": "Archive of every generated report",
    "ReportsFile + InsightsMemory": "Report archive + Smart Memory (written together after the educator's approval)",
    "InsightsMemory": "Smart Memory — distilled insight cards per student / lesson / class",
    "StyleMemory": "Report style profiles distilled from user examples",
}

# What kind of store are these? One line for the viewer.
SHEETS_KIND = ("Google Sheets — cloud spreadsheets used as the school's database; "
               "accessed through the Google API with a service account.")

PROVIDER_INFO = {
    "openai": ("OpenAI",
               "API prompts are not used to train models (OpenAI API data-usage "
               "policy); retention up to 30 days for abuse monitoring.",
               "https://openai.com/policies/api-data-usage-policies"),
    "google": ("Google (Gemini)",
               "Paid API traffic is not used for training (Gemini API terms of service).",
               "https://ai.google.dev/gemini-api/terms"),
    "anthropic": ("Anthropic",
                  "API inputs are not used for training by default (Anthropic commercial terms).",
                  "https://www.anthropic.com/legal/commercial-terms"),
    "mistralai": ("Mistral AI",
                  "API data is not used for training (Mistral API terms).",
                  "https://mistral.ai/terms/"),
    "meta-llama": ("Meta Llama (community-hosted)",
                   "Served by independent inference providers — each applies its own data policy.",
                   "https://openrouter.ai/privacy"),
    "qwen": ("Alibaba Qwen (community-hosted)",
             "Served by independent inference providers — each applies its own data policy.",
             "https://openrouter.ai/privacy"),
    "deepseek": ("DeepSeek",
                 "Served by DeepSeek / partner providers — check the provider's data policy.",
                 "https://openrouter.ai/privacy"),
}
_DEFAULT_PROVIDER = ("External provider via OpenRouter",
                     "OpenRouter routes the prompt to the model's provider and may "
                     "log prompts operationally per its privacy policy. Bright E.V.A. "
                     "only ever sends anonymized data.",
                     "https://openrouter.ai/privacy")


def provider_info(model_id):
    prefix = str(model_id or "").split("/", 1)[0].lower()
    return PROVIDER_INFO.get(prefix, _DEFAULT_PROVIDER)


def run_resources(t):
    """Aggregate a finished trace into the resource panels for the viewer:
    which sheets were read/written, which AI models were called (and how
    much), and what the anonymizer masked in total."""
    sheets = {}
    models = {}
    masks = {}
    timing = {}
    had_blocked_save = False
    had_real_save = False
    for e in t.get("events", []):
        st_name = e.get("stage")
        # LLM stages clock true call latency; the rest use inter-event time.
        ms = e.get("latency_ms") if st_name == "llm" else e.get("dt_ms")
        if isinstance(ms, int) and st_name:
            timing[st_name] = timing.get(st_name, 0) + ms
        st = e.get("stage")
        if st == "fetch":
            for s in e.get("sources", []):
                name = s.get("sheet") or "?"
                d = sheets.setdefault(name, {"rows": 0, "ops": set()})
                d["rows"] += s.get("rows") or 0
                d["ops"].add("read")
        elif st == "save":
            if e.get("blocked"):
                had_blocked_save = True
            else:
                had_real_save = True
                d = sheets.setdefault(e.get("sheet") or "ReportsFile",
                                      {"rows": 0, "ops": set()})
                d["ops"].add("write")
        elif st == "insight" and e.get("stored") is not False:
            d = sheets.setdefault("InsightsMemory", {"rows": 0, "ops": set()})
            d["ops"].add("write")
        elif st == "early_warning" and e.get("skipped"):
            sheets.pop("InsightsMemory", None)  # dry-run — the card was never written
        elif st == "llm":
            mid = e.get("model") or "?"
            m = models.setdefault(mid, {"calls": 0, "in": 0, "out": 0, "ms": 0})
            m["calls"] += 1
            m["in"] += e.get("prompt_tokens") or 0
            m["out"] += e.get("completion_tokens") or 0
            m["ms"] += e.get("latency_ms") or 0
        elif st == "scrub":
            for k, v in (e.get("masks") or {}).items():
                if isinstance(v, int):
                    masks[k] = masks.get(k, 0) + v
    model_rows = []
    total_cost = 0.0
    cost_known = True
    for mid, stats in sorted(models.items()):
        cost = estimate_cost_usd(mid, stats["in"], stats["out"])
        if cost is None:
            cost_known = False
        else:
            total_cost += cost
        model_rows.append({"id": mid, "provider": provider_info(mid),
                           "cost_usd": cost, **stats})
    return {
        "sheets": [{"name": n, "rows": d["rows"], "ops": sorted(d["ops"]),
                    "info": SHEET_INFO.get(n, "")}
                   for n, d in sorted(sheets.items())],
        "sheets_kind": SHEETS_KIND,
        "models": model_rows,
        "total_cost_usd": total_cost if models and cost_known else None,
        "timing": sorted(timing.items(), key=lambda kv: kv[1], reverse=True),
        "masks": masks,
        # dry-run chip only when NOTHING was ever written (a blocked save later
        # approved by the educator still counts as written).
        "dry_run": had_blocked_save and not had_real_save,
    }


# ---------------------------------------------------------------------------
# Risk signals — the viewer's "second pair of eyes". Deterministic heuristics
# scan every finished trace and surface risks that are NOT obvious from the
# happy path: safeguards that were off, silent fallbacks, language-policy
# violations, possibly-invented figures, re-identification surface, missing
# human oversight. Each signal deep-links to the Risk Register (R1–R10).
# "Controls observed" are listed too — evidence that a safeguard fired.
# ---------------------------------------------------------------------------

# Which risk-register entry each stage is the battleground for (per-step lens).
STAGE_RISKS = {
    "fetch": [("Over-collection: whole rows are pulled, not just the needed fields", "r1"),
              ("Whatever bias lives in the source forms shapes everything downstream", "r2")],
    "scrub": [("Under-masking: a name the scrubber does not know would survive", "r1"),
              ("Over-masking: common words erased, degrading the evidence (the Foster case)", "r5")],
    "llm": [("Hallucination: invented scores or dates in fluent prose", "r2"),
            ("Prompt injection: teacher notes are user-controlled text inside the prompt", "r6"),
            ("Data jurisdiction: the prompt is processed on the provider's infrastructure", "r7")],
    "tool": [("Agent overreach: a tool can fetch more than the question needed", "r1")],
    "critic": [("One model judging another shares its blind spots — the gate is not proof", "r3")],
    "regenerate": [("Feedback loops can entrench the critic's own bias", "r3")],
    "insight": [("Memory poisoning: a wrong card biases every future run of this entity", "r2")],
    "early_warning": [("Silence is not safety: thresholds see trajectories, not causes", "r4"),
                      ("Alert fatigue if it fires too often — then real alerts get ignored", "r5")],
    "save": [("Quasi-identifiers: ID + date + group can re-identify a child in a small class", "r8"),
             ("Function creep: an archive invites uses beyond the original purpose", "r9"),
             ("Accountability: who approved this entering the student's record?", "r10")],
    "note": [],
    "error": [("A partial run can leave inconsistent state (report without memory card)", "r10")],
}

_GREEK_RE = re.compile("[\\u0370-\\u03ff]")  # Greek & Coptic — ENGLISH_ONLY violations
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_COMMUNITY_PROVIDERS = {"meta-llama", "qwen", "deepseek", "ibm-granite", "nex-agi"}

# Fallback prices per 1M tokens (input, output) when the live OpenRouter
# price list cannot be fetched. Deliberately covers only models we default to.
_FALLBACK_PRICES = {
    "openai/gpt-5-nano": (0.05, 0.40),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "google/gemini-2.5-flash": (0.30, 2.50),
}
_price_cache = {"ts": 0, "prices": None}


def model_price(model_id):
    """(input, output) price per 1M tokens, or None. Live OpenRouter list,
    cached 6h, static fallback for our default models."""
    now = time.time()
    if _price_cache["prices"] is None or now - _price_cache["ts"] > 6 * 3600:
        try:
            import urllib.request
            with urllib.request.urlopen("https://openrouter.ai/api/v1/models",
                                        timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            _price_cache["prices"] = {
                m["id"]: (float(m["pricing"]["prompt"]) * 1e6,
                          float(m["pricing"]["completion"]) * 1e6)
                for m in data.get("data", []) if m.get("pricing")
            }
        except Exception:
            _price_cache["prices"] = dict(_FALLBACK_PRICES)
        _price_cache["ts"] = now
    prices = _price_cache["prices"]
    return prices.get(model_id) or _FALLBACK_PRICES.get(model_id)


def estimate_cost_usd(model_id, in_tokens, out_tokens):
    price = model_price(model_id)
    if not price:
        return None
    return (in_tokens * price[0] + out_tokens * price[1]) / 1e6


def detect_risk_signals(t, vx):
    """Scan a finished trace -> (signals, controls). Each item:
    {severity: danger|warn|info, title, detail, ref (risk-register anchor)}."""
    events = t.get("events", [])
    signals, controls = [], []

    def sig(sev, title, detail, ref):
        signals.append({"severity": sev, "title": title, "detail": detail, "ref": ref})

    def ok(title, detail):
        controls.append({"title": title, "detail": detail})

    scrubs = [e for e in events if e["stage"] == "scrub"]
    llms = [e for e in events if e["stage"] == "llm"]
    critics = [e for e in events if e["stage"] == "critic"]
    saves = [e for e in events if e["stage"] == "save"]
    warns = [e for e in events if e["stage"] == "early_warning"]

    # --- anonymization state ---
    disabled = sum((e.get("masks") or {}).get("disabled", 0) for e in scrubs)
    if disabled:
        sig("danger", "Anonymization was OFF",
            f"{disabled} scrub pass(es) ran with masking disabled — raw data reached the model. "
            "Legitimate only inside a sandbox dry-run.", "r1")
    elif scrubs and vx.get("masks"):
        total = sum(vx["masks"].values())
        ok("Anonymizer active",
           f"{total} masking substitution(s) across {len(scrubs)} pass(es) before any AI call.")
        if total > 30:
            sig("info", "Heavy masking volume",
                f"{total} substitutions — check for over-masking: erasing common words "
                "degrades evidence and desensitises reviewers (the Foster case).", "r5")
    elif scrubs:
        sig("info", "Anonymizer found nothing to mask",
            "Zero substitutions. Expected only because this registry is pre-anonymized — "
            "on real (non-sandbox) data, zero masks is a red flag, not a success.", "r1")

    for e in critics:
        if e.get("pii_leak_detected"):
            sig("danger", "Critic caught a PII leak",
                "A real name survived into the final report; the anonymizer vocabulary "
                "needs that name. The report was blocked from saving as-is.", "r1")
        if e.get("verdict") == "skipped":
            sig("warn", "Quality gate disabled",
                f"The critic pass was skipped ({e.get('reason', 'guardrail off')}). "
                "Nothing verified the report before saving.", "r3")
        elif e.get("verdict") == "fail":
            ok("Critic gate fired",
               "A substandard report was caught and regenerated once with feedback.")
        elif e.get("verdict") == "pass":
            ok("Critic gate passed", "The report was reviewed before saving.")

    # --- language policy (ENGLISH_ONLY) ---
    greek_hits = sum(1 for e in llms if _GREEK_RE.search(e.get("response") or ""))
    if greek_hits:
        sig("warn", "Language policy violated",
            f"{greek_hits} model response(s) contain Greek text despite the English-only "
            "rule — source data leaks its language into outputs.", "r2")

    # --- silent reliability fallbacks ---
    fallbacks = [e for e in events if e["stage"] == "note"
                 and "empty content" in str(e.get("message", ""))]
    if fallbacks:
        sig("warn", "Silent placeholder fallback",
            f"{len(fallbacks)} AI call(s) returned empty content and were replaced by a "
            "placeholder sentence. The report looks complete but has gaps.", "r2")

    # --- possibly invented figures in the saved report ---
    prompt_text = " ".join(str(m.get("content", "")) for e in llms
                           for m in (e.get("messages") or []))
    prompt_nums = set(_NUM_RE.findall(prompt_text))
    for e in saves:
        report = e.get("report") or ""
        if not report:
            continue
        invented = [n for n in _NUM_RE.findall(report)
                    if n not in prompt_nums and len(n) > 1 or (n not in prompt_nums and "." in n)]
        invented = sorted(set(invented))[:6]
        if invented:
            sig("warn", "Figures not found in any prompt",
                "The saved report cites numbers that never appeared in the source data "
                f"(e.g. {', '.join(invented)}). They may be computed aggregates — or "
                "hallucinated. Worth a human look.", "r2")

    # --- community-hosted inference ---
    for m in vx.get("models", []):
        if m["id"].split("/", 1)[0].lower() in _COMMUNITY_PROVIDERS:
            sig("warn", "Community-hosted model",
                f"'{m['id']}' is served by independent inference providers — data-policy "
                "guarantees are weaker than first-party APIs.", "r7")

    # --- early warnings ---
    for e in warns:
        if e.get("fired"):
            sig("warn", "Early warning fired",
                f"{e.get('alert', '')} — a human should review this entity soon.", "r4")

    # --- human oversight on saves ---
    real_saves = [e for e in saves if not e.get("blocked")]
    blocked = [e for e in saves if e.get("blocked")]
    decisions = [e for e in events if e.get("educator_decision")]
    if blocked and not real_saves:
        ok("Dry-run honoured", "The data layer refused to write — writes were blocked.")
    if decisions:
        ok("Human decision recorded",
           f"An educator explicitly {decisions[-1]['educator_decision'].replace('_', ' ')} "
           "the report before it entered the record.")
    elif real_saves:
        sig("info", "Saved without human review",
            "The report entered the student's record automatically "
            "(REQUIRE_APPROVAL=0). For high-stakes use, enable the Educator Override.", "r10")

    # --- re-identification surface of a saved student report ---
    for e in real_saves:
        if (e.get("type") == "Student" and e.get("entity") and e.get("date")):
            sig("info", "Quasi-identifiers in the archive",
                f"Saved row combines ID '{e['entity']}' + date + lesson — in a small "
                "class that triangulates to a child. Pseudonyms are not anonymity.", "r8")
            break

    order = {"danger": 0, "warn": 1, "info": 2}
    signals.sort(key=lambda s: order[s["severity"]])
    return signals, controls


# ---------------------------------------------------------------------------
# Reading traces back (viewer routes)
# ---------------------------------------------------------------------------

def list_traces(limit=100):
    """Newest-first trace headers for the /pipeline index page."""
    out = []
    try:
        names = [f for f in os.listdir(TRACES_DIR) if f.endswith(".json")]
    except OSError:
        return out
    names.sort(key=lambda f: os.path.getmtime(os.path.join(TRACES_DIR, f)),
               reverse=True)
    for name in names[:limit]:
        try:
            with open(os.path.join(TRACES_DIR, name), encoding="utf-8") as f:
                data = json.load(f)
            out.append({k: data.get(k) for k in
                        ("run_id", "kind", "label", "model", "started",
                         "status", "summary")})
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_trace(run_id):
    """Full trace JSON. run_id is validated to block path traversal."""
    if not _run_id_re.match(run_id or ""):
        return None
    path = os.path.join(TRACES_DIR, f"{run_id}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def delete_trace(run_id):
    """Delete one trace file. run_id validated like load_trace. Returns True if removed."""
    if not _run_id_re.match(run_id or ""):
        return False
    path = os.path.join(TRACES_DIR, f"{run_id}.json")
    with _write_lock:
        try:
            os.remove(path)
            return True
        except OSError:
            return False


def clear_traces(kind=None):
    """Delete stored traces — all of them, or only one kind ('report', 'chat',
    'sandbox'). Returns the number of files removed."""
    removed = 0
    try:
        names = [f for f in os.listdir(TRACES_DIR) if f.endswith(".json")]
    except OSError:
        return 0
    with _write_lock:
        for name in names:
            path = os.path.join(TRACES_DIR, name)
            if kind:
                try:
                    with open(path, encoding="utf-8") as f:
                        if json.load(f).get("kind") != kind:
                            continue
                except (OSError, json.JSONDecodeError):
                    continue
            try:
                os.remove(path)
                removed += 1
            except OSError:
                continue
    return removed


def append_event(run_id, stage, **payload):
    """Append an event to a FINISHED trace (audit trail — e.g. the educator's
    approve/reject decision lands in the original run's trace)."""
    data = load_trace(run_id)
    if data is None:
        return None
    events = data.get("events", [])
    prev_dt = events[-1].get("dt_ms", 0) if events else 0
    event = {"t": datetime.now().isoformat(timespec="milliseconds"),
             "dt_ms": prev_dt, "stage": stage}
    for key, value in payload.items():
        event[key] = _clip(value)
    events.append(event)
    data["events"] = events
    # refresh the derived summary
    rec = TraceRecorder.__new__(TraceRecorder)
    rec.events = events
    rec._t0 = time.time()
    rec._last = time.time() - data.get("summary", {}).get("duration_ms", 0) / 1000
    data["summary"] = rec.summary()
    path = os.path.join(TRACES_DIR, f"{run_id}.json")
    with _write_lock:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return data
