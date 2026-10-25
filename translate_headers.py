# -*- coding: utf-8 -*-
"""Bright E.V.A. — one-time header translation: Greek -> English (2026-10-21).

The user asked for English sheet headers so the spreadsheets can be presented.
Headers are DATA KEYS: the code locates columns by header text, so this script
and the code edits ship together. What stays Greek: cell VALUES (π.μ./μ.μ.
date markers, group codes like ΜΓ1, free-text notes).

Flow:
  1. FULL JSON backup of the 7 affected sheets (git+dockerignored).
  2. Verify the backup was written.
  3. Rename row 1 of each sheet via HEADER_MAP (idempotent: already-English
     headers are skipped; unknown headers are left alone with a warning).
  4. Re-read row 1 of every sheet and print it for verification.

Run:  .venv\\Scripts\\python.exe translate_headers.py
"""
import json
import os
from datetime import datetime

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
_sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
if _sa_json:
    creds = Credentials.from_service_account_info(json.loads(_sa_json), scopes=SCOPES)
else:
    creds = Credentials.from_service_account_file(
        os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "insudies-e24d0d9618d5.json"),
        scopes=SCOPES)
gc = gspread.authorize(creds)

BACKUP_FILE = "backup_headers_translation_2026-10-21.json"

# Greek header -> English header. One global map applied to every sheet's row 1
# (each sheet only contains its own subset).
HEADER_MAP = {
    # common
    "Χρονική σήμανση": "Timestamp",
    "Κωδικός Μαθητή": "Student ID",
    "Κωδικός μαθητή": "Student ID",   # Fo had a lowercase μ — unified
    "Ημερομηνία": "Date",
    "Κωδικός Μαθήματος": "Group code",
    # Students
    "Ηλικία/Τάξη": "Age/Grade",
    "Γονέας": "Parent",
    "Τηλέφωνο": "Phone",
    "Μάθημα": "Lesson",
    # Lessons (tab1 + tab2)
    "Τίτλος": "Title",
    "Περιγραφή": "Description",
    "Σημειώσεις": "Notes",
    "lesson": "Group code",
    "ΗΜΕΡΟΜΗΝΙΑ": "Schedule",
    "ΤΙΜΗ": "Price",
    # PreAssessment
    "Τι προσδοκίες έχετε από το μάθημα;": "What are your expectations from the lessons?",
    "Προηγούμενη εμπειρία με ρομποτική/προγραμματισμό;": "Previous experience with robotics/programming?",
    "Ποια είναι τα δυνατά σημεία του παιδιού;": "What are the child's strengths?",
    "Τι θα θέλατε να βελτιώσει το παιδί;": "What would you like the child to improve?",
    "Διαχείριση απογοήτευσης στο σπίτι (1-5)": "Handling frustration at home (1-5)",
    "Συνεργασία με άλλα παιδιά εκτός σχολείου (1-5)": "Cooperation with children outside school (1-5)",
    "Τι ενθουσιάζει / τι αποφεύγει το παιδί;": "What excites / what does the child avoid?",
    # FoAssessment (base + well-being)
    "Συμμετοχή στο μάθημα (1-5)": "Participation in class (1-5)",
    "Κατανόηση εννοιών (1-5)": "Concept comprehension (1-5)",
    "Ολοκλήρωση κατασκευής (1-5)": "Build completion (1-5)",
    "Δεξιότητες προγραμματισμού (1-5)": "Programming skills (1-5)",
    "Συνεργασία (1-5)": "Cooperation (1-5)",
    "Παρατηρήσεις εκπαιδευτικού": "Teacher observations",
    "Συναισθηματική διάθεση (1-5)": "Emotional mood (1-5)",
    "Ενέργεια στο μάθημα (1-5)": "Energy in class (1-5)",
    "Επικοινωνία & κοινή κατανόηση (1-5)": "Communication & shared understanding (1-5)",
    "Συνεισφορά & ομαδικότητα (1-5)": "Contribution & teamwork (1-5)",
    "Εμβάθυνση & επιμονή (1-5)": "Deep engagement & persistence (1-5)",
    "Πρωτοβουλία & αυτονομία (1-5)": "Initiative & autonomy (1-5)",
    "Σήματα που παρατηρήθηκαν": "Observed signals",
    "Παρατήρηση διάθεσης & ψυχολογίας": "Mood & well-being note",
    "Παρατήρηση συνεργασίας": "Collaboration note",
    "Στιγμή που ξεχώρισε": "Standout moment",
    # SelfAssessment
    "Πώς ένιωσες στο σημερινό μάθημα;": "How did you feel in today's lesson?",
    "Τι δυσκολεύτηκες περισσότερο;": "What was the hardest part?",
    "Τι απόλαυσες περισσότερο;": "What did you enjoy most?",
    "Αυτοεκτίμηση επίδοσης (1-5)": "Self-rated performance (1-5)",
    "Ζήτησα βοήθεια όταν τη χρειάστηκα (1-5)": "I asked for help when I needed it (1-5)",
    "Πώς νιώθω μετά το μάθημα (1-5)": "How I feel after the lesson (1-5)",
    # PostAssessment
    "Είδατε πρόοδο στο παιδί;": "Have you seen progress in the child?",
    "Τι αλλαγές παρατηρήσατε στο σπίτι;": "What changes have you noticed at home?",
    "Σχόλια": "Comments",
    "Μιλάει αυθόρμητα στο σπίτι για τα μαθήματα; (1-5)": "Talks spontaneously at home about lessons (1-5)",
    "Αλλαγή στην αυτοπεποίθησή του; (1-5)": "Change in self-confidence (1-5)",
    "Θα συνιστούσατε το πρόγραμμα; (1-5)": "Would you recommend the program? (1-5)",
    # LessonAssessment
    "Πώς ανταποκρίθηκε το τμήμα; (1-5)": "How did the class respond? (1-5)",
    "Ποσοστό ολοκλήρωσης δραστηριότητας (%)": "Activity completion rate (%)",
    "Δυσκολίες που παρουσιάστηκαν": "Difficulties encountered",
    "Συναισθηματικό κλίμα τμήματος (1-5)": "Class emotional climate (1-5)",
    "Οργάνωση & ροή συνεδρίας (1-5)": "Session organization & flow (1-5)",
    "Ποιότητα ανατροφοδότησης & ερωτήσεων (1-5)": "Feedback & questioning quality (1-5)",
    "Στιγμή που χαρακτήρισε το τμήμα": "The moment that defined the class",
}

# Headers that were already English before the migration (skipped silently).
ALREADY_ENGLISH = {"ID", "Name", "Surname", "Email",
                   "Lesson ID 1", "Lesson ID 2", "Lesson ID 3", "Lesson ID 4"}

# (spreadsheet title, worksheet index) pairs to migrate.
TARGETS = [
    ("Students", 0),
    ("Lessons", 0),
    ("Lessons", 1),
    ("PreAssessment", 0),
    ("FoAssessment", 0),
    ("SelfAssessment", 0),
    ("PostAssessment", 0),
    ("LessonAssessment", 0),
]


def open_ws(title, index):
    sh = gc.open(title)
    return sh.sheet1 if index == 0 else sh.get_worksheet(index)


def main():
    # ---- 1. full backup ----------------------------------------------------
    print("== 1/4 Backing up all affected sheets ==")
    backup = {"taken_at": datetime.now().isoformat(timespec="seconds"),
              "sheets": {}}
    for title, idx in TARGETS:
        ws = open_ws(title, idx)
        key = f"{title}#{idx}"
        backup["sheets"][key] = {
            "tab_title": ws.title,
            "values": ws.get_all_values(),
        }
        print(f"  {key:22} tab '{ws.title}'  rows={len(backup['sheets'][key]['values'])}")
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)

    # ---- 2. verify backup --------------------------------------------------
    print("\n== 2/4 Verifying backup ==")
    with open(BACKUP_FILE, encoding="utf-8") as f:
        check = json.load(f)
    assert check["sheets"].keys() == backup["sheets"].keys(), "backup incomplete!"
    total_rows = sum(len(s["values"]) for s in check["sheets"].values())
    assert total_rows > 0, "backup is empty!"
    print(f"  OK — {BACKUP_FILE} ({total_rows} rows across {len(check['sheets'])} tabs)")

    # ---- 3. rename headers -------------------------------------------------
    print("\n== 3/4 Renaming row 1 headers ==")
    for title, idx in TARGETS:
        ws = open_ws(title, idx)
        row1 = ws.row_values(1)
        new_row, renamed, unknown = [], 0, []
        for h in row1:
            if h in HEADER_MAP:
                new_row.append(HEADER_MAP[h])
                renamed += 1
            else:
                new_row.append(h)
                if h and h not in ALREADY_ENGLISH and h not in HEADER_MAP.values():
                    unknown.append(h)
        if renamed:
            ws.update(range_name="A1", values=[new_row], value_input_option="RAW")
        print(f"  {title}#{idx}: {renamed} renamed"
              + (f"  ⚠ left as-is (unknown): {unknown}" if unknown else ""))

    # ---- 4. verify live headers --------------------------------------------
    print("\n== 4/4 Live row 1 after migration ==")
    greek_left = 0
    for title, idx in TARGETS:
        ws = open_ws(title, idx)
        row1 = ws.row_values(1)
        greek = [h for h in row1
                 if any('Ͱ' <= ch <= 'Ͽ' or 'ἀ' <= ch <= '῿' for ch in h)]
        greek_left += len(greek)
        print(f"  {title}#{idx}: {row1}")
        if greek:
            print(f"    ⚠ still Greek: {greek}")
    print("\nDONE." + ("  ⚠ some Greek headers remain — review above." if greek_left
                       else "  All headers are English."))


if __name__ == "__main__":
    main()
