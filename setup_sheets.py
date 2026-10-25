"""
Bright E.V.A. — One-time Google Sheets bootstrap.

Creates the 8 spreadsheets the app needs (with the EXACT English headers the
code looks up — headers were translated Greek -> English on 2026-10-21),
fills in demo data so the app can be tested end-to-end, and optionally
shares everything with your Google account:

    .venv\\Scripts\\python.exe setup_sheets.py [your@gmail.com]

Safe to re-run: existing spreadsheets are reused, not duplicated.
"""
import sys

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]

creds = Credentials.from_service_account_file(
    os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "insudies-e24d0d9618d5.json"),
    scopes=SCOPES,
)
gc = gspread.authorize(creds)

SHARE_EMAIL = sys.argv[1] if len(sys.argv) > 1 else None

created_or_found = []


def get_or_create(title):
    try:
        sh = gc.open(title)
        print(f"  found:    {title}")
    except gspread.SpreadsheetNotFound:
        sh = gc.create(title)
        print(f"  CREATED:  {title}")
    created_or_found.append(sh)
    return sh


def set_headers(ws, headers):
    current = ws.row_values(1)
    if current != headers:
        ws.update(range_name="A1", values=[headers])
        print(f"    headers set on '{ws.title}'")


def add_rows(ws, rows):
    existing = len(ws.get_all_values())
    if existing <= 1:  # only the header row
        for row in rows:
            ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"    {len(rows)} demo row(s) added to '{ws.title}'")
    else:
        print(f"    '{ws.title}' already has data — left untouched")


print("== 1/8 Students ==")
students = get_or_create('Students')
set_headers(students.sheet1, ["ID", "Name", "Surname", "Age/Grade", "Parent", "Email",
                              "Phone", "Lesson", "Lesson ID 1", "Lesson ID 2",
                              "Lesson ID 3", "Lesson ID 4"])
add_rows(students.sheet1, [["test1", "Τεστ", "Μαθητής", "10 χρον.", "-", "-", "-",
                            "Demo Lesson", "AB1", "", "", ""]])

print("== 2/8 Lessons (2 tabs) ==")
lessons = get_or_create('Lessons')
# Tab1: ID = 2-letter lesson prefix (e.g. ΜΒ), Description = long description
set_headers(lessons.sheet1, ["ID", "Title", "Description", "Notes"])
add_rows(lessons.sheet1, [["AB", "Demo Lesson",
                           "Milo the Science Rover — WeDo 2.0: κατασκευή και προγραμματισμός ρόβερ με αισθητήρες κλίσης και κίνησης",
                           "demo"]])
try:
    classes_ws = lessons.get_worksheet(1)
except gspread.WorksheetNotFound:
    classes_ws = lessons.add_worksheet(title="Classes", rows=100, cols=10)
# Tab2: Group code (e.g. ΑΒ1), Description = long description
set_headers(classes_ws, ["Group code", "Title", "Description", "Schedule", "Price"])
add_rows(classes_ws, [["AB1", "Demo Lesson", "Τμήμα AB1 — αρχάριοι WeDo 2.0 (Δημοτικό)", "Δευτέρα 17:00-18:00", "50"]])

print("== 3/8 PreAssessment ==")
pre = get_or_create('PreAssessment')
from wellbeing_fields import (LESSON_HEADERS, POST_HEADERS, PRE_HEADERS,
                              SELF_HEADERS)
set_headers(pre.sheet1, ["Timestamp", "Student ID",
                         "What are your expectations from the lessons?",
                         "Previous experience with robotics/programming?",
                         "What are the child's strengths?",
                         "What would you like the child to improve?"] + PRE_HEADERS)
add_rows(pre.sheet1, [["15/10/2026 10:30:00 π.μ.", "test1",
                       "Να μάθει να σκέφτεται αλγοριθμικά και να διασκεδάζει",
                       "Καμία, μόνο λίγο Scratch στο σχολείο",
                       "Φαντασία και επιμονή",
                       "Υπομονή όταν κάτι δεν βγαίνει με την πρώτη",
                       "3", "4",
                       "Loves drawing and building with blocks; avoids being rushed."]])

print("== 4/8 FoAssessment ==")
fo = get_or_create('FoAssessment')
from wellbeing_fields import NEW_HEADERS as FO_WB_HEADERS
set_headers(fo.sheet1, ["Timestamp", "Student ID",
                        "Participation in class (1-5)",
                        "Concept comprehension (1-5)",
                        "Build completion (1-5)",
                        "Programming skills (1-5)",
                        "Cooperation (1-5)",
                        "Teacher observations"] + FO_WB_HEADERS)
add_rows(fo.sheet1, [
    ["08/10/2026 05:15:00 μ.μ.", "test1", "4", "3", "3", "2", "4", "Πρώτη επαφή με το kit· χρειάζεται καθοδήγηση στη σύνδεση του Smarthub",
     "3", "3", "4", "4", "3", "2", "calm focus",
     "Curious but careful; relaxed once the build started responding.",
     "Followed the partner's lead; needed prompting to voice opinions.",
     "During the kit intro: first smile when the motor spun."],
    ["15/10/2026 05:20:00 μ.μ.", "test1", "5", "4", "4", "3", "5", "Ολοκλήρωσε το Milo και άλλαξε μόνος του τις παραμέτρους του μοτέρ",
     "4", "4", "5", "5", "4", "4", "smiling / laughter, pride in work",
     "Visibly proud — showed the build to a classmate unprompted.",
     "Explained the motor settings to the partner step by step.",
     "During the Milo build: changed the motor parameters unprompted."],
])

print("== 5/8 SelfAssessment ==")
self_a = get_or_create('SelfAssessment')
set_headers(self_a.sheet1, ["Timestamp", "Student ID",
                            "How did you feel in today's lesson?",
                            "What was the hardest part?",
                            "What did you enjoy most?"] + SELF_HEADERS)
add_rows(self_a.sheet1, [["15/10/2026 06:00:00 μ.μ.", "test1",
                          "Πολύ καλά, ήθελα άλλη μία ώρα",
                          "Να συνδέσω το μοτέρ στο Smarthub",
                          "Που ο Milo κινήθηκε με τον κώδικά μου",
                          "4", "4", "5"]])

print("== 6/8 PostAssessment ==")
post = get_or_create('PostAssessment')
set_headers(post.sheet1, ["Timestamp", "Student ID",
                          "Have you seen progress in the child?",
                          "What changes have you noticed at home?",
                          "Comments"] + POST_HEADERS)
add_rows(post.sheet1, [["18/10/2026 08:00:00 μ.μ.", "test1",
                        "Ναι, μιλάει συνέχεια για τον ρόβερ",
                        "Προσπαθεί να «προγραμματίσει» τη σκούπα ρομπότ",
                        "Θα ήθελα πιο συχνά μαθήματα",
                        "5", "4", "5"]])

print("== 7/8 LessonAssessment ==")
less_a = get_or_create('LessonAssessment')
set_headers(less_a.sheet1, ["Date", "Group code",
                            "How did the class respond? (1-5)",
                            "Activity completion rate (%)",
                            "Difficulties encountered",
                            "Notes"] + LESSON_HEADERS)
add_rows(less_a.sheet1, [
    ["2026-10-08", "AB1", "4", "80", "Συνδέσεις Bluetooth με τα tablets", "Χρειάζεται επιπλέον βοηθός για το pairing",
     "4", "3", "4", "Two tablets refused to pair; the class learned patience the hard way."],
    ["2026-10-15", "AB1", "5", "95", "Καμία ουσιαστική", "Το τμήμα ζήτησε επέκταση με αισθητήρα κλίσης",
     "5", "5", "4", "The class asked for extra time instead of a break."],
])

print("== 8/11 ReportsFile ==")
reports = get_or_create('ReportsFile')
set_headers(reports.sheet1, ["Creation Date", "Assessment Date", "Assessment type",
                             "Class", "ID", "Prompt", "Role", "Responce"])

print("== 9/11 InsightsMemory ==")
insights = get_or_create('InsightsMemory')
set_headers(insights.sheet1, ["Creation Date", "Entity type", "Entity ID", "Assessment Date",
                              "Trajectory", "Cognitive trend", "Soft-skill trend",
                              "Risk flags", "Alert", "Evidence", "Takeaway"])

print("== 10/11 StyleMemory ==")
style = get_or_create('StyleMemory')
set_headers(style.sheet1, ["Creation Date", "Report type", "Style spec", "Source"])

print("== 11/11 RiskNotes ==")
notes = get_or_create('RiskNotes')
set_headers(notes.sheet1, ["Timestamp", "Trace ID", "Stage", "Ref", "Severity",
                           "Author", "Comment", "Status"])

if SHARE_EMAIL:
    print(f"\nSharing all spreadsheets with {SHARE_EMAIL} (Editor)...")
    for sh in created_or_found:
        try:
            sh.share(SHARE_EMAIL, perm_type='user', role='writer')
            print(f"  shared: {sh.title}")
        except Exception as e:
            print(f"  FAILED to share {sh.title}: {e}")

print("\n=== DONE ===")
for sh in created_or_found:
    print(f"{sh.title}: {sh.url}")
