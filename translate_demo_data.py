"""One-off: translate all remaining Greek free-text cells to English.

Scope: ONLY whitelisted free-text columns. Data keys are never touched:
sheet headers, ID columns, group codes (ΜΓ1...), timestamps (π.μ./μ.μ.),
dates, scores, prices-as-numbers, lesson prefixes.

A full local JSON backup of every affected sheet is written first, so the
operation is reversible.
"""
import json
import re
import time
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import openai_reports as orp

GREEK = re.compile(r"[Α-Ωα-ωΆ-ώΪΫϊϋΰΐ]")

# sheet -> (worksheet index, {columns allowed to translate})
TARGETS = {
    "Students": (0, {"Μάθημα", "Ηλικία/Τάξη"}),
    "PreAssessment": (0, {"Τι προσδοκίες έχετε από το μάθημα;",
                          "Προηγούμενη εμπειρία με ρομποτική/προγραμματισμό;",
                          "Ποια είναι τα δυνατά σημεία του παιδιού;",
                          "Τι θα θέλατε να βελτιώσει το παιδί;"}),
    "FoAssessment": (0, {"Παρατηρήσεις εκπαιδευτικού"}),
    "SelfAssessment": (0, {"Πώς ένιωσες στο σημερινό μάθημα;",
                           "Τι δυσκολεύτηκες περισσότερο;",
                           "Τι απόλαυσες περισσότερο;"}),
    "PostAssessment": (0, {"Είδατε πρόοδο στο παιδί;",
                           "Τι αλλαγές παρατηρήσατε στο σπίτι;", "Σχόλια"}),
    "LessonAssessment": (0, {"Δυσκολίες που παρουσιάστηκαν", "Σημειώσεις"}),
    "ReportsFile": (0, {"Responce", "Question", "Role"}),
    "Lessons": (0, {"Τίτλος", "Περιγραφή", "Σημειώσεις"}),
    "Lessons#2": (1, {"Τίτλος", "Περιγραφή", "ΗΜΕΡΟΜΗΝΙΑ", "ΤΙΜΗ"}),
}

BATCH = 25


def translate_batch(texts, model):
    """Translate a list of Greek strings to English via the cheap model."""
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    resp = orp.get_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": (
                "You are a precise Greek-to-English translator for a school "
                "assessment system. Translate each numbered item to natural "
                "English. Keep all numbers, dates, times, IDs, emails, scores "
                "and bracketed tokens unchanged. For Greek weekday names use "
                "the English weekday. Reply with a JSON array of strings only, "
                "same order, same length.")},
            {"role": "user", "content": numbered},
        ],
        max_tokens=4000,
    )
    out = resp.choices[0].message.content.strip()
    m = re.search(r"\[.*\]", out, re.S)
    arr = json.loads(m.group(0))
    if len(arr) != len(texts):
        raise ValueError(f"length mismatch: sent {len(texts)}, got {len(arr)}")
    return [str(x) for x in arr]


def main():
    orp._connect_sheets()
    model = orp.MODEL

    # ---- 1. backup ----
    backup = {}
    for name, (widx, _cols) in TARGETS.items():
        real = name.split("#")[0]
        ws = orp.gc.open(real).get_worksheet(widx)
        backup[name] = ws.get_all_values()
    bpath = f"backup_pre_translation_{datetime.today().strftime('%Y-%m-%d_%H%M')}.json"
    with open(bpath, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=1)
    print(f"backup written: {bpath}")

    # ---- 2. collect cells ----
    total = 0
    for name, (widx, cols) in TARGETS.items():
        real = name.split("#")[0]
        ws = orp.gc.open(real).get_worksheet(widx)
        rows = ws.get_all_values()
        header = rows[0]
        col_idx = {h: i for i, h in enumerate(header)}
        todo = []  # (row1based, col1based, text)
        for ri, row in enumerate(rows[1:], start=2):
            for col in cols:
                ci = col_idx.get(col)
                if ci is None or ci >= len(row):
                    continue
                cell = row[ci]
                if cell and GREEK.search(cell):
                    todo.append((ri, ci + 1, cell))
        print(f"{name}: {len(todo)} cells to translate")
        if not todo:
            continue
        total += len(todo)

        # ---- 3. translate in batches ----
        translated = []
        for off in range(0, len(todo), BATCH):
            chunk = todo[off:off + BATCH]
            texts = [t[2] for t in chunk]
            for attempt in (1, 2):
                try:
                    outs = translate_batch(texts, model)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise
                    print(f"  retry batch at {off} ({e})")
                    time.sleep(2)
            translated.extend(outs)
            print(f"  {min(off + BATCH, len(todo))}/{len(todo)}")
            time.sleep(0.4)

        # ---- 4. write back ----
        from gspread import Cell
        cells = [Cell(row=r, col=c, value=v)
                 for (r, c, _old), v in zip(todo, translated)]
        ws.update_cells(cells, value_input_option="RAW")
        print(f"  written back: {len(cells)}")

    print(f"DONE — {total} cells translated")


if __name__ == "__main__":
    main()
