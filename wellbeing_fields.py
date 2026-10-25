# -*- coding: utf-8 -*-
"""Well-being & collaboration fields for FoAssessment (formative, per session).

Single source of truth for the 10 columns added 2026-10-21 (cols 9-18),
grounded in: Leuven Well-being & Involvement scales (Laevers), the Mood
Meter's energy axis (RULER/Yale), the PISA 2015 collaborative-problem-solving
competencies, CASEL relationship/self-management skills, and Fredricks'
cognitive engagement. Each scale is paired with observer free text — the
number says WHERE the child is, the text says WHY.

`generate_fields()` produces demo values consistent with each seed profile's
arc so the demo cohort (demo01-12) tells a coherent story. It derives scores
from the EXISTING 1-5 row scores, so it works both for fresh seeds and for
backfilling the already-seeded sheet.

GDPR/AI-Act note: these fields capture OBSERVABLE BEHAVIOUR ONLY — never a
diagnosis. Optional by design; everything passes the PII anonymizer before
any LLM call, like the rest of the sheet.
"""
import random

NEW_HEADERS = [
    "Emotional mood (1-5)",
    "Energy in class (1-5)",
    "Communication & shared understanding (1-5)",
    "Contribution & teamwork (1-5)",
    "Deep engagement & persistence (1-5)",
    "Initiative & autonomy (1-5)",
    "Observed signals",
    "Mood & well-being note",
    "Collaboration note",
    "Standout moment",
]

# demo id -> behavioural archetype (mirrors the profiles in seed_demo_data.py)
ARCHETYPES = {
    "demo01": "excelling", "demo02": "growth", "demo03": "average",
    "demo04": "decline", "demo05": "social_weak", "demo06": "social_strong",
    "demo07": "late_bloomer", "demo08": "erratic", "demo09": "disengaged",
    "demo10": "anxious", "demo11": "hidden_star", "demo12": "dip_recovery",
}

GROUP_OF = {**{f"demo0{i}": "ΜΓ1" for i in range(1, 7)},
            **{f"demo{i:02d}": "ΜΔ2" for i in range(7, 13)}}

# Session topics per group (match the 8 seeded sessions, in order) — used to
# anchor the "Standout moment" anecdote in the actual session.
TOPICS = {
    "ΜΓ1": ["the Milo build intro", "motor parameters & movement", "gear transmission",
            "the tilt sensor experiments", "the motion sensor + sound combo", "the pulley build",
            "rover programming", "the final project & presentations"],
    "ΜΔ2": ["the Spike intro program", "precise movement in degrees", "the color sensor",
            "obstacle avoidance", "the line follower", "the robotic arm",
            "loops & conditions", "the final track challenge & presentations"],
}

_SIG_POS = ["smiling / laughter", "enthusiasm", "pride in work", "calm focus"]
_SIG_MID = ["calm focus", "quiet participation"]
_SIG_NEG = ["anxiety", "frustration", "isolation", "fatigue", "tension with a peer", "boredom"]

_MOOD_NOTE = {
    "excelling":    {"low": "Brief disappointment when a test failed — recovered within a minute and tried again.",
                     "high": "Hummed while building; left the room saying it was the best part of the day."},
    "growth":       {"low": "Hesitant at the start; needed encouragement before touching the kit.",
                     "high": "Visibly proud — showed the build to a classmate unprompted."},
    "average":      {"low": "Flat but cooperative; no visible highs or lows.",
                     "high": "Relaxed and content; smiled when the build worked as expected."},
    "decline":      {"low": "Withdrew after the first failure — 'I don't get these' — and turned away.",
                     "high": "A brief spark of interest when the model moved, then it faded."},
    "social_weak":  {"low": "Irritated when asked to share the tablet; chose the corner spot.",
                     "high": "Deeply satisfied during solo building; relaxed when left to work alone."},
    "social_strong": {"low": "Distracted and chatty; hard to settle on the task.",
                      "high": "Pure joy — turned the session into a small celebration for the whole table."},
    "late_bloomer": {"low": "Very quiet, avoided eye contact; watched more than acted.",
                     "high": "Stayed after the bell to finish — a first; left with a small smile."},
    "erratic":      {"low": "Restless, changed seats repeatedly, couldn't settle.",
                     "high": "Bounced with excitement; the whole room could feel today's win."},
    "disengaged":   {"low": "Asked 'when are we done?' twice; body present, mind elsewhere.",
                     "high": "Brief genuine engagement at the start, then drifted."},
    "anxious":      {"low": "Nearly teared up over a minor error; needed repeated reassurance.",
                     "high": "Calm and precise — though still re-checked the work four times."},
    "hidden_star":  {"low": "Shy and reserved; worked silently at the edge of the table.",
                     "high": "Smiled openly when praised — confidence visibly growing."},
    "dip_recovery": {"low": "Tired and disoriented today; struggled to find the thread.",
                     "high": "Full of energy again — the pre-absence rhythm is back."},
}

_COLLAB_NOTE = {
    "excelling":    {"low": "Worked fine alongside the pair but stayed focused on the own build.",
                     "high": "Led the pair quietly — guided a classmate's wiring without taking over."},
    "growth":       {"low": "Followed the partner's lead; needed prompting to voice opinions.",
                     "high": "Listens carefully and now explains steps to the partner."},
    "average":      {"low": "Quiet in the pair; did what was asked, nothing more.",
                     "high": "Kept the assigned role reliably; fair turn-taking."},
    "decline":      {"low": "Left the pair mid-task; irritated with the shared build.",
                     "high": "Short but real moments of teamwork when the task felt safe."},
    "social_weak":  {"low": "Refused to share the tablet; worked in isolation by choice.",
                     "high": "Tolerated the pair today and even handed over pieces when asked."},
    "social_strong": {"low": "So busy socializing that the own task stalled.",
                      "high": "Organized the pairs and made sure everyone spoke — the group's morale engine."},
    "late_bloomer": {"low": "Silent partner; answered only when addressed directly.",
                     "high": "The pair trusted them with the precise assembly — a visible shift."},
    "erratic":      {"low": "Argued with the partner and continued alone.",
                     "high": "Helped others with genuine generosity today."},
    "disengaged":   {"low": "Told the partner 'you do it'; no joint work.",
                     "high": "Participated briefly when the task touched a personal interest."},
    "anxious":      {"low": "Wouldn't show 'unfinished' work to the partner; perfectionism blocks sharing.",
                     "high": "Shared methods with the partner once confident they were correct."},
    "hidden_star":  {"low": "Too shy to claim a role; worked on whatever was left.",
                     "high": "Discreetly helped the neighbour; the team adopted the suggested improvement."},
    "dip_recovery": {"low": "The pair carried them gently back into the routine.",
                     "high": "Full teammate again — shared pieces, ideas and laughs."},
}

_HIGHLIGHT = {
    "excelling":    ["During {topic}: proposed an improvement nobody asked for — and it worked.",
                     "During {topic}: presented with ease and gave thoughtful feedback to peers."],
    "growth":       ["During {topic}: persisted after two failures — didn't give up like before.",
                     "During {topic}: completed the task almost unaided; an autonomy milestone."],
    "average":      ["During {topic}: steady, correct, no surprises — a reliable rhythm.",
                     "During {topic}: answered the key question correctly after prompting."],
    "decline":      ["During {topic}: a flicker of the old interest when the model first moved.",
                     "During {topic}: agreed to try once more after a long pause."],
    "social_weak":  ["During {topic}: produced the most advanced solution of the class — alone.",
                     "During {topic}: explained nothing to anyone, but the code was remarkable."],
    "social_strong": ["During {topic}: prepared a spontaneous 'show' of everyone's work.",
                      "During {topic}: openly asked for help — a healthy first."],
    "late_bloomer": ["During {topic}: asked the first spontaneous question of the term.",
                     "During {topic}: the pair handed over the tricky step — trust earned."],
    "erratic":      ["During {topic}: finished before everyone and helped two classmates.",
                     "During {topic}: found a working solution at the very last minute."],
    "disengaged":   ["During {topic}: completed the basics — the most effort in weeks.",
                     "During {topic}: a short burst of genuine focus before drifting."],
    "anxious":      ["During {topic}: best result of the class, yet fixated on one imperfect detail.",
                     "During {topic}: dared to show work without the usual four re-checks."],
    "hidden_star":  ["During {topic}: first to finish — the 'inexperienced' label keeps dissolving.",
                     "During {topic}: the class adopted their suggested improvement."],
    "dip_recovery": ["During {topic}: back at pre-absence level — rhythm restored.",
                     "During {topic}: full return; presented with real joy."],
}


def _clamp(v):
    return str(max(1, min(5, int(round(v)))))


def _band(value, low=2, high=4):
    v = int(value)
    return "low" if v <= low else ("high" if v >= high else "mid")


def generate_fields(student_id, scores, session_idx):
    """10 values (as strings) in NEW_HEADERS order for one FoAssessment row.

    scores: the row's existing [participation, comprehension, build,
    programming, collaboration] as ints. Deterministic per (student, session).
    """
    rng = random.Random(f"wb:{student_id}:{session_idx}")
    arch = ARCHETYPES.get(student_id, "average")
    group = GROUP_OF.get(student_id, "ΜΓ1")
    part, _compr, _build, prog, collab = [int(s) for s in scores]

    # demo12 session 4 (idx 3) was an illness absence in the seed narrative
    if arch == "dip_recovery" and session_idx == 3:
        return ["1", "1", "", "", "1", "1", "absent — illness",
                "Absent (illness — mother informed).", "—", "—"]

    noise = lambda: rng.uniform(-0.49, 0.49)
    erratic_noise = lambda: rng.uniform(-1.0, 1.0) if arch == "erratic" else 0.0

    mood_off = {"excelling": 1.0, "hidden_star": 0.5, "social_strong": 1.0,
                "late_bloomer": -0.5, "decline": -0.5, "disengaged": -1.0,
                "anxious": -0.5}.get(arch, 0.0)
    energy_off = {"social_strong": 1.0, "excelling": 0.5, "disengaged": -1.0,
                  "anxious": -0.5, "decline": -0.5}.get(arch, 0.0)
    comm_off = {"social_weak": -1.5, "social_strong": 1.0, "excelling": 0.5,
                "hidden_star": 0.3, "disengaged": -1.0}.get(arch, 0.0)
    contrib_off = {"social_weak": -1.5, "social_strong": 0.5,
                   "disengaged": -1.0}.get(arch, 0.0)
    inv_off = {"excelling": 0.5, "social_strong": -0.5,
               "disengaged": -0.5}.get(arch, 0.0)
    aut_off = {"excelling": 1.0, "hidden_star": 0.5, "average": -0.5,
               "social_strong": -1.0, "anxious": -0.5, "decline": -0.5,
               "disengaged": -1.0}.get(arch, 0.0)

    if arch == "dip_recovery" and session_idx == 4:  # the hard comeback lesson
        mood_off -= 1.0
        energy_off -= 1.0

    mood = _clamp(0.6 * part + 0.4 * collab + mood_off + noise() + erratic_noise())
    energy = _clamp(part + energy_off + noise() + erratic_noise())
    comm = _clamp(collab + comm_off + noise() + erratic_noise())
    contrib = _clamp(collab + contrib_off + noise() + erratic_noise())
    involv = _clamp(part + inv_off + noise() + erratic_noise())
    autonomy = _clamp(prog + aut_off + noise() + erratic_noise())

    # signals checklist — driven by the mood band, flavoured by archetype
    b = _band(mood)
    if b == "high":
        picks = rng.sample(_SIG_POS, k=rng.choice((1, 2)))
    elif b == "low":
        picks = rng.sample(_SIG_NEG, k=rng.choice((1, 2)))
    else:
        picks = [rng.choice(_SIG_MID)]
    if arch == "anxious" and "asked for reassurance repeatedly" not in picks:
        picks.append("asked for reassurance repeatedly")
    if arch == "disengaged" and b != "high" and "boredom" not in picks:
        picks[0] = "boredom"
    signals = ", ".join(dict.fromkeys(picks))

    mood_note = _MOOD_NOTE[arch][_band(mood) if _band(mood) != "mid" else rng.choice(("low", "high"))]
    collab_band = _band((int(comm) + int(contrib)) // 2)
    collab_note = _COLLAB_NOTE[arch][collab_band if collab_band != "mid" else rng.choice(("low", "high"))]
    topic = TOPICS[group][min(session_idx, 7)]
    if arch in ("disengaged", "decline") and int(involv) <= 2:
        highlight = f"During {topic}: almost no participation — monitoring continues."
    elif arch == "dip_recovery" and session_idx == 4:
        highlight = f"During {topic}: struggled to reconnect after the absence — needed extra time."
    else:
        highlight = rng.choice(_HIGHLIGHT[arch]).format(topic=topic)

    return [mood, energy, comm, contrib, involv, autonomy,
            signals, mood_note, collab_note, highlight]


# ===========================================================================
# The OTHER four forms (2026-10-21) — same philosophy: a scale never travels
# without its framework anchor; demo values stay consistent with each profile.
# ===========================================================================

# --- SelfAssessment (student voice; Panorama SEL + kid Mood Meter) ----------
SELF_HEADERS = [
    "Self-rated performance (1-5)",
    "I asked for help when I needed it (1-5)",
    "How I feel after the lesson (1-5)",
]

# How far the child's self-view sits from the teacher's view (the GAP is the
# signal: the anxious perfectionist scores -2; the social star overestimates).
_SELF_EFFICACY_GAP = {
    "excelling": 0.0, "growth": 0.0, "average": 0.0, "decline": -1.0,
    "social_weak": 0.5, "social_strong": 1.0, "late_bloomer": 0.0,
    "erratic": 0.0, "disengaged": -1.0, "anxious": -2.0,
    "hidden_star": -0.5, "dip_recovery": 0.0,
}
_HELP_SEEKING_BASE = {
    "excelling": 4.5, "growth": 4.0, "average": 3.5, "decline": 2.0,
    "social_weak": 1.5, "social_strong": 4.5, "late_bloomer": 3.5,
    "erratic": 3.0, "disengaged": 1.5, "anxious": 2.0,
    "hidden_star": 3.5, "dip_recovery": 4.0,
}


def gen_self_fields(student_id, scores, session_idx):
    """3 values in SELF_HEADERS order. scores = the SAME session's formative
    arc row, so the self-view vs teacher-view gap stays profile-consistent."""
    rng = random.Random(f"self:{student_id}:{session_idx}")
    arch = ARCHETYPES.get(student_id, "average")
    teacher_view = sum(int(s) for s in scores) / len(scores)
    gap = _SELF_EFFICACY_GAP[arch]
    # growth arcs start underestimating and close the gap by the end
    if arch in ("growth", "late_bloomer", "hidden_star") and session_idx < 4:
        gap -= 1.0
    if arch == "erratic":
        gap += rng.uniform(-1.5, 1.5)
    self_efficacy = _clamp(teacher_view + gap + rng.uniform(-0.3, 0.3))

    help_base = _HELP_SEEKING_BASE[arch]
    if arch == "late_bloomer":
        help_base += 1.0 if session_idx >= 4 else -1.0  # learns to ask
    help_seeking = _clamp(help_base + rng.uniform(-0.49, 0.49))

    mood_teacher = int(generate_fields(student_id, scores, session_idx)[0])
    mood_gap = -1 if arch == "anxious" else 0  # kids feel it harsher than it looks
    mood_self = _clamp(mood_teacher + mood_gap + rng.uniform(-0.49, 0.49))

    return [self_efficacy, help_seeking, mood_self]


# --- PreAssessment (parent intake; CASEL family partnership) ----------------
PRE_HEADERS = [
    "Handling frustration at home (1-5)",
    "Cooperation with children outside school (1-5)",
    "What excites / what does the child avoid?",
]

_PRE_BASE = {  # arch: (frustration tolerance at home, collaboration outside school)
    "excelling": (4, 4), "growth": (2, 4), "average": (3, 3),
    "decline": (2, 3), "social_weak": (3, 2), "social_strong": (4, 5),
    "late_bloomer": (3, 3), "erratic": (3, 4), "disengaged": (3, 3),
    "anxious": (2, 3), "hidden_star": (3, 2), "dip_recovery": (4, 4),
}
_PRE_INTERESTS = {
    "demo01": "Loves building anything with moving parts; avoids repetitive worksheets.",
    "demo02": "Loves drawing and stories; avoids situations where she might get it wrong in front of others.",
    "demo03": "Loves football and board games; avoids open-ended tasks without clear steps.",
    "demo04": "Loves drawing and storytelling; avoids puzzles and anything with tiny parts.",
    "demo05": "Loves circuits and programming alone; avoids team games and sharing materials.",
    "demo06": "Loves friends, music and organizing games; avoids sitting still with instructions.",
    "demo07": "Loves Minecraft and quiet observation; avoids speaking in groups.",
    "demo08": "Loves excitement and anything new; avoids repetition and waiting her turn.",
    "demo09": "Loves video games; lately avoids most group activities.",
    "demo10": "Loves tidy notebooks and correct answers; avoids being seen making a mistake.",
    "demo11": "Loves quiet play and helping at home; avoids being the centre of attention.",
    "demo12": "Loves mechanisms and figuring out how things work; avoids being rushed.",
}


def gen_pre_fields(student_id):
    rng = random.Random(f"pre:{student_id}")
    arch = ARCHETYPES.get(student_id, "average")
    fr, co = _PRE_BASE[arch]
    return [_clamp(fr + rng.uniform(-0.4, 0.4)),
            _clamp(co + rng.uniform(-0.4, 0.4)),
            _PRE_INTERESTS.get(student_id, "")]


# --- PostAssessment (parent reflection; transfer into the home) -------------
POST_HEADERS = [
    "Talks spontaneously at home about lessons (1-5)",
    "Change in self-confidence (1-5)",
    "Would you recommend the program? (1-5)",
]

_POST_BASE = {  # arch: (spontaneous talk, confidence change, recommend)
    "excelling": (5, 4, 5), "growth": (4, 5, 5), "average": (3, 3, 4),
    "decline": (1, 2, 2), "social_weak": (3, 3, 4), "social_strong": (5, 4, 5),
    "late_bloomer": (4, 5, 5), "erratic": (3, 3, 4), "disengaged": (1, 1, 2),
    "anxious": (3, 2, 4), "hidden_star": (4, 5, 5), "dip_recovery": (4, 4, 5),
}


def gen_post_fields(student_id):
    rng = random.Random(f"post:{student_id}")
    arch = ARCHETYPES.get(student_id, "average")
    tk, cf, rec = _POST_BASE[arch]
    return [_clamp(tk + rng.uniform(-0.3, 0.3)),
            _clamp(cf + rng.uniform(-0.3, 0.3)),
            _clamp(rec + rng.uniform(-0.3, 0.3))]


# --- LessonAssessment (class-level climate; CLASS framework / Pianta) -------
LESSON_HEADERS = [
    "Class emotional climate (1-5)",
    "Session organization & flow (1-5)",
    "Feedback & questioning quality (1-5)",
    "The moment that defined the class",
]

_LESSON_MOMENTS = {
    ("ΜΓ1", 0): "First contact with the kits — wide eyes, slow start, lots of 'how does this connect?'",
    ("ΜΓ1", 1): "Two tablets refused to pair; the class learned patience the hard way.",
    ("ΜΓ1", 2): "The big-gear demo on the board turned confusion into a collective 'aaah!'.",
    ("ΜΓ1", 3): "The tilt sensor stole the show — one table kept tilting it just to hear it click.",
    ("ΜΓ1", 4): "One pair argued over the tablet; the 10-minute swap rule was born.",
    ("ΜΓ1", 5): "The pulleys clicked for everyone — the class asked for extra time instead of a break.",
    ("ΜΓ1", 6): "Nearly every rover finished; the room had real momentum.",
    ("ΜΓ1", 7): "Final presentations, high energy; one student declined to present and the class respected it.",
    ("ΜΔ2", 0): "New Spike kits — quick adaptation for an advanced group.",
    ("ΜΔ2", 1): "Degrees and rotations needed board work; the link to school math landed well.",
    ("ΜΔ2", 2): "The color sensor's calibration issue became an impromptu physics mini-lesson.",
    ("ΜΔ2", 3): "Obstacle avoidance sparked a healthy competitive streak across the room.",
    ("ΜΔ2", 4): "Substitute session — visible disruption; the line follower defeated most pairs today.",
    ("ΜΔ2", 5): "The robotic arm rebuilt the group's rhythm; the line-follower recap paid off.",
    ("ΜΔ2", 6): "Loops & conditions split the room: half applied them, half copied.",
    ("ΜΔ2", 7): "Final track challenge — high level and energy; two students need individual follow-up.",
}


def gen_lesson_fields(group, resp_score, session_idx):
    """4 values in LESSON_HEADERS order. resp_score = the form's existing
    'How did the class respond? (1-5)' for that session."""
    rng = random.Random(f"lesson:{group}:{session_idx}")
    if (group, session_idx) == ("ΜΔ2", 4):  # the substitute-teacher chaos session
        return ["2", "2", "2", _LESSON_MOMENTS[(group, session_idx)]]
    base = int(resp_score)
    climate = _clamp(base + rng.uniform(-0.5, 0.5))
    organization = _clamp(base + rng.uniform(-1.0, 0.3))  # org usually lags climate
    feedback = _clamp(base + rng.uniform(-0.8, 0.4))
    moment = _LESSON_MOMENTS.get((group, session_idx), "")
    return [climate, organization, feedback, moment]
