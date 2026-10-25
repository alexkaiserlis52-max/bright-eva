"""One-off migration on the live Students sheet (backup already taken):

1. Replace ALL student names/surnames with unique fake ENGLISH names
   (parent names too - same fake surname, otherwise kids stay identifiable).
2. Fill missing group assignments (Lesson ID 1) using age/class and the
   free-text Mathima column, balancing group sizes; fix the 'ΜΑ10' typo.
3. Fill empty/'-' Mathima cells with the canonical lesson title.

Prints only ASCII-safe summaries (no names to console - cp1252).
"""
import re
from openai_reports import gc

DRY_RUN = False  # set True to preview without writing

ws = gc.open('Students').sheet1
rows = ws.get_all_values()
header = rows[0]
body = [list(r) + [""] * (12 - len(r)) for r in rows[1:]]  # pad to 12 cols

I_ID, I_NAME, I_SUR, I_AGE, I_PAR, I_MATH, I_L1 = 0, 1, 2, 3, 4, 7, 8

# Canonical lesson titles (Lessons tab1)
lessons_ws = gc.open('Lessons').sheet1
lh = lessons_ws.row_values(1)
i_lid, i_ltitle = lh.index("ID"), lh.index("Τίτλος")
TITLES = {}
for r in lessons_ws.get_all_values()[1:]:
    if len(r) > i_lid and r[i_lid].strip():
        TITLES[r[i_lid].strip()] = r[i_ltitle].strip() if len(r) > i_ltitle else ""

# Valid group codes (Lessons tab2)
groups_ws = gc.open('Lessons').get_worksheet(1)
gh = groups_ws.row_values(1)
i_gcode = gh.index("lesson")
VALID_GROUPS = {r[i_gcode].strip() for r in groups_ws.get_all_values()[1:] if len(r) > i_gcode and r[i_gcode].strip()}

# ---------------- fake English names (unique) ----------------
FIRST = ["Liam","Noah","Oliver","Elijah","James","William","Benjamin","Lucas","Henry","Theodore",
         "Jack","Levi","Alexander","Owen","Asher","Samuel","Ethan","Leo","Mason","Ezra",
         "Julian","Hudson","Leo","Nathan","Isaac","Ryan","Caleb","Luke","Christian","Hunter",
         "Emma","Olivia","Ava","Isabella","Sophia","Mia","Charlotte","Amelia","Harper","Evelyn",
         "Luna","Camila","Ella","Aria","Scarlett","Grace","Chloe","Lily","Nora","Zoey",
         "Stella","Aurora","Naomi","Maya","Elena","Sarah","Alice","Ruby","Eva","Iris",
         "Lydia","Clara","Violet","Hazel","Audrey","Naia","Ivy","Emilia","Stella","Freya"]
LAST = ["Parker","Bennett","Hayes","Sullivan","Brooks","Reed","Morgan","Carter","Ellis","Foster",
        "Griffin","Hughes","Jenkins","Keller","Lawson","Mercer","Nolan","Quinn","Rhodes","Sawyer",
        "Turner","Vaughn","Walsh","Abbott","Barrett","Caldwell","Dalton","Emerson","Fleming","Garner",
        "Holloway","Ingram","Jennings","Kirk","Langley","Monroe","Norris","Osborne","Prescott","Radcliffe",
        "Sinclair","Thornton","Underwood","Vance","Webster","York","Ashford","Blake","Donovan","Grayson",
        "Harrington","Irving","Jackson","Kensington","Lancaster","Middleton","Spencer","Whitfield","Yates","Dalton"]
PARENT_FIRST = ["Jordan","Alex","Casey","Taylor","Morgan","Jamie","Robin","Sam","Chris","Pat",
                "Dana","Kelly","Lee","Jessie","Robin","Ariel","Charlie","Frankie","Hilary","Lou"]

used_names = set()
def fake_name(i):
    for shift in range(len(LAST)):
        cand = (FIRST[i % len(FIRST)], LAST[(i + shift) % len(LAST)])
        if cand not in used_names:
            used_names.add(cand)
            return cand
    raise RuntimeError("name pool exhausted")

# ---------------- age / bucket inference ----------------
def parse_age(text):
    t = text.lower().replace(",", ".")
    if "γυμν" in t:
        return 14.0
    m = re.search(r"(\d)\s*η\s*δημ", t) or re.search(r"(\d)ηδημ", t) or re.search(r"(\d)\s*α\s*δημ", t) or re.search(r"(\d)αδημ", t)
    if m:
        return float(m.group(1)) + 5.0   # N-th primary grade ≈ N+5 years old
    if "νηπιο" in t or "νηπειο" in t or "προνηπιο" in t:
        return 5.0
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if m:
        v = float(m.group(1))
        if 3 <= v <= 18:
            return v
    return None

def mathima_bucket(text):
    t = text.lower()
    if not t or t == "-":
        return None
    if "junior" in t: return "ΜΓ"
    if "advanced 2" in t: return "ΜΕ"
    if "advanced" in t: return "ΜΔ"
    if "προσχ" in t or "ρομποτ,προσχ" in t: return "ΜΒ"
    if "spike" in t: return "ΜΖ"
    if "minecraft" in t: return "ΜΛ"
    if "εθνική" in t: return "ΜΑ"
    if "διαγωνιστική" in t: return "ΜΩ"
    if "pbr" in t: return "ΜΘ"
    if "ρομποτ" in t: return "ΜΓ"   # generic robotics -> junior
    return None

def age_bucket(age):
    if age is None: return None
    if age < 7: return "ΜΒ"
    if age < 10: return "ΜΓ"
    if age < 13: return "ΜΔ"
    return "ΜΕ"

POOLS = {
    "ΜΒ": ["ΜΒ3", "ΜΒ5", "ΜΒ2", "ΜΒ1"],
    "ΜΓ": ["ΜΓ2", "ΜΓ3", "ΜΓ1"],
    "ΜΔ": ["ΜΔ4", "ΜΔ1", "ΜΔ2"],
    "ΜΕ": ["ΜΕ1"],
    "ΜΖ": ["ΜΖ1", "ΜΖ2"],
    "ΜΛ": ["ΜΛ1"],
    "ΜΑ": ["ΜΑ1"],
    "ΜΩ": ["ΜΩ1"],
    "ΜΘ": ["ΜΘ1"],
}
FALLBACK = ["ΜΓ2", "ΜΓ3", "ΜΔ4", "ΜΔ1"]  # no age & no mathima -> elementary groups

# current group sizes (existing assignments count)
size = {g: 0 for g in VALID_GROUPS}
for r in body:
    g = r[I_L1].strip()
    if g == "ΜΑ10":
        g = "ΜΑ1"
    if g in size:
        size[g] += 1

def pick_group(bucket):
    pool = POOLS.get(bucket) or FALLBACK
    return min(pool, key=lambda g: (size.get(g, 0), pool.index(g)))

# ---------------- build the new rows ----------------
changes = {"renamed": 0, "parents": 0, "assigned": 0, "kept_group": 0, "typo_fixed": 0, "mathima_filled": 0}
assign_log = []
for idx, r in enumerate(body):
    first, last = fake_name(idx)
    r[I_NAME], r[I_SUR] = first, last
    changes["renamed"] += 1
    if r[I_PAR].strip():
        r[I_PAR] = f"{PARENT_FIRST[idx % len(PARENT_FIRST)]} {last}"
        changes["parents"] += 1

    g = r[I_L1].strip()
    if g == "ΜΑ10":
        g = "ΜΑ1"
        r[I_L1] = g
        changes["typo_fixed"] += 1
    if g and g in VALID_GROUPS:
        changes["kept_group"] += 1
    else:
        bucket = mathima_bucket(r[I_MATH])
        age = parse_age(r[I_AGE])
        ab = age_bucket(age)
        # Refine conflicts between the declared lesson and the kid's age:
        if bucket == "ΜΓ" and ab in ("ΜΔ", "ΜΕ"):
            bucket = ab                    # generic/Junior robotics but teenager
        elif bucket in ("ΜΔ", "ΜΕ") and age is not None and age < 9:
            bucket = "ΜΓ"                  # Advanced declared but too young
        if bucket is None:
            bucket = ab                    # no lesson info -> age decides
        g = pick_group(bucket)
        r[I_L1] = g
        size[g] += 1
        changes["assigned"] += 1
        assign_log.append((r[I_ID], g, ascii(r[I_AGE]), ascii(r[I_MATH])[:60]))

    prefix = g[:2]
    if r[I_MATH].strip() in ("", "-") and prefix in TITLES:
        r[I_MATH] = TITLES[prefix]
        changes["mathima_filled"] += 1

print("CHANGES:", changes)
print("final group sizes:", sorted((ascii(k), v) for k, v in size.items() if v))
print("new assignments (id -> group):")
for a in assign_log:
    print("  ", a)

if DRY_RUN:
    print("DRY RUN - nothing written")
else:
    n = len(body)
    ws.batch_update([
        {"range": f"B2:B{n+1}", "values": [[r[I_NAME]] for r in body]},
        {"range": f"C2:C{n+1}", "values": [[r[I_SUR]] for r in body]},
        {"range": f"E2:E{n+1}", "values": [[r[I_PAR]] for r in body]},
        {"range": f"H2:H{n+1}", "values": [[r[I_MATH]] for r in body]},
        {"range": f"I2:I{n+1}", "values": [[r[I_L1]] for r in body]},
    ], value_input_option="RAW")
    print("WRITTEN to sheet.")
