# AIED Demo Scenarios — Bright E.V.A. Glass-Box Sandbox

**Κοινό:** AIED experts (Council of Europe, Παρίσι 28–29/10) · **Συνολικός χρόνος:** ~10 λεπτά
**Ιδέα:** δεν δείχνουμε slides — **χρησιμοποιούμε την εφαρμογή σαν κανονικός εκπαιδευτικός** (Student Report, ASK ME, Chat) και μετά **ανοίγουμε το glass box (Pipeline trace) του run που μόλις έτρεξε**. Τα ρίσκα ανακαλύπτονται ζωντανά, πάνω σε πραγματική εκτέλεση.

**Χρυσοί κανόνες (πες τους στην αρχή):**
1. Όλοι οι μαθητές είναι **100% synthetic** (demo01–demo12) — γι' αυτό μπορεί να υπάρχει δημόσιο risk sandbox.
2. Κάθε run καταγράφεται σε **pipeline trace** — αυτό θα ανοίγουμε μετά από κάθε βήμα.
3. Ό,τι χαλαρώνει guardrails τρέχει πάντα σε **dry-run** — τίποτα δεν γράφεται στα sheets.

---

## 📋 Prep — 5 λεπτά, την προηγούμενη μέρα

- [ ] Login στο live URL → τρέξε **μία φορά** το Σενάριο 1 ακριβώς όπως παρακάτω (με Save ON + Approve). Έτσι: ζεσταίνεται το cache, υπάρχει **έτοιμο trace** ως fallback, και υπάρχει trace με `educator_decision` για το βήμα 3.
- [ ] Τρέξε μία φορά το chat ερώτημα του Σεναρίου 2 (ώστε να υπάρχει και chat trace).
- [ ] Άνοιξε `/pipeline` και σημείωσε τα 2-3 πιο πρόσφατα traces — αυτά είναι το plan B σου.
- [ ] **No-wifi fallback:** η ίδια ροή τρέχει τοπικά: `.venv\Scripts\python.exe app.py` → `http://localhost:5000`. Backup screen-recording = τελευταίο δίχτυ ασφαλείας.

---

## 🎬 Σενάριο 1 — «Μία αναφορά για παιδί… και μετά ανοίγουμε το κουτί» (~6')

*Student Report → Educator Override → Pipeline trace. Ρίσκα: **R1** (PII), **R2** (hallucination), **R3** (automation bias), **R4** (silent decline), **R10** (accountability).*

### Βήμα 1 · DO (~1') — Τρέξε αναφορά για τον **demo09**
`Home → Student Report`:
- **Student:** `demo09` · **Question:** `Overall progress, engagement and any concerns`
- **Role:** `An experienced robotics educator addressing parents`
- **Save:** ON → *Generate Report* (~40-60", μίλα πάνω στα stages του overlay)

> 🗣️ *"This is the everyday action: a teacher asks for a progress report. Watch what the system does before it is allowed to save anything."*

### Βήμα 2 · SHOW (~1') — Educator Override
Με `REQUIRE_APPROVAL=1` η αναφορά **δεν αποθηκεύεται** — εμφανίζεται η οθόνη έγκρισης: **Approve / Edit (re-critic) / Reject**. Πάτα **Approve**.

> 🗣️ *"Human-in-the-loop is not a promise — it is a blocking step. Nothing about a child is archived without an educator's explicit decision."* (AI Act Άρθρο 14)

### Βήμα 3 · SHOW (~2') — Άνοιξε το Pipeline trace του run
Από τη σελίδα της αναφοράς → **trace link**. Δείξε με τη σειρά:
- **Resources panel:** ποια Google Sheets άγγιξε (4 assessment sheets + Students + ReportsFile), ποιο μοντέλο, **εκτιμώμενο κόστος**, πόσα masks έκανε ο anonymizer.
- **Scrub step:** το before/after sample — *"the model never saw a name, email or phone"* (**R1**).
- **Critic gate:** η κρίση πριν την αποθήκευση — *"every claim must be grounded in the real scores"* (**R2**).
- **Insight card + EARLY WARNING:** ο demo09 έχει ήδη αποθηκευμένη κάρτα `declining` → το νέο run πυροδοτεί **«DECLINE CONTINUES»**.

> 🗣️ *"The system noticed a child silently declining. Powerful — but an automated alert about a child is itself a risk: what if it is wrong? Who acts on it?"* (**R4 + R3**)

### Βήμα 4 · SHOW (~1') — Risk signals & risk lens
Στο ίδιο trace: τα **αυτόματα risk signals** (π.χ. *early-warning fired*, *quasi-identifier triad: ID+date+group*) και το **🔍 risk lens** κάτω από κάθε βήμα — το εργαλείο ελέγχει τον εαυτό του. Κάθε signal κάνει deep-link στο Risk Register.

### Βήμα 5 · DO (~1') — Καταχώρησε ρίσκο ζωντανά
Στο trace → **«Register a risk»** → γράψε 1 πρόταση (π.χ. *"Alert wording could label the child if shared verbatim with parents"*) → submit. Άνοιξε `/risk-register` — η παρατήρηση είναι ήδη εκεί.

> 🗣️ *"The sandbox does not just find risks — it documents them. The register is fed by the system itself, and by reviewers like you."*

---

## 🎬 Σενάριο 2 — «Ρώτα ελεύθερα… και μετά κάνε audit την απάντηση» (~4-5')

*ASK ME ή Chat → Pipeline trace. Ρίσκα: **R2** (grounding), **R3** (automation bias), **R6** (injection μέσω δεδομένων), **R10** (accountability).*

### Επιλογή Α · ASK ME (~2') — lesson plan από αδυναμίες τάξης
`Home → ASK ME`:
- **Request:** `Create a lesson plan that works on the children's biggest weakness`
- **Action:** Auto · **Class group:** `ΜΓ1` → *Run*

Η E.V.A. δρομολογεί αυτόματα σε *create lesson plan*, τραβά ως αποδεικτικά **μόνο** τις αποθηκευμένες αναφορές του ΜΓ1 (class report + αναφορές μαθητών του τμήματος) και βγάζει πλάνο με το 5E×PBL template.

### Επιλογή Β · Chat (~1-2') — σύγκριση μαθητών
`/chat`:
- `How is demo02 progressing?` → βλέπεις ζωντανά τα **tool chips** (`get_student_overview`, `search_insights`)
- Follow-up: `Compare them with demo07` → `compare_students`

### Βήμα κοινό · SHOW (~2') — Άνοιξε το trace
- **ASK ME trace:** το routing decision (`askme_route` note: γιατί διάλεξε αυτό το pipeline), **ακριβώς ποια reports** τροφοδότησαν την απάντηση (grounding — **R2**), το scrub πριν το prompt.
- **Chat trace:** κάθε tool call καταγραμμένο — και τονίζεις την **boundedness**:

> 🗣️ *"These six tools are pure local Python — no AI inside. The model can only pick a tool and compose the answer; it can never touch the database directly, and its report tool is a dry-run that can never save."*

- Κλείσιμο στο **Risk Register**: δείξε ότι οι παρατηρήσεις από το Σενάριο 1 είναι ήδη κάτω από τα αντίστοιχα ρίσκα — *"the register grew during this talk"*.

> 🗣️ *"Every answer you saw can be audited back to the exact rows, prompts and verdicts that produced it. That is what 'glass box' means."*

---

## 🧪 Bonus — αν οι experts θέλουν hands-on (~2' έκαστο)

Στο **`/sandbox`** (Risk Lab) υπάρχουν 5 έτοιμα πειράματα — ιδανικά για Q&A:
| Πείραμα | Ερώτηση που απαντά |
|---|---|
| **Prompt-injection probe** | Μπορεί σημείωση μαθητή να «χακάρει» το μοντέλο; (βάλε έναν expert να γράψει τη δική του επίθεση!) |
| **Guardrails ON vs OFF** | Τι θα διέρρεε *χωρίς* anonymizer+critic; (side-by-side, dry-run) |
| **Critic gate vs hallucination** | Πιάνει η πύλη κατασκευασμένη αναφορά; |

---

## 🆘 Plan B (αν κάτι πάει στραβά on stage)

1. **Αργεί το μοντέλο;** → άνοιξε τα **pre-baked traces** από `/pipeline` (τα έτρεξες στο prep) και κάνε την περιήγηση εκεί — η ουσία είναι το glass box, όχι η αναμονή.
2. **Πέφτει το internet;** → localhost (`.\.venv\Scripts\python.exe app.py`) — ίδιες ροές.
3. **Καταστροφικό σενάριο;** → το backup video.

## 🗒️ Cheat sheet

| Χρειάζεσαι | Τι βάζεις |
|---|---|
| Μαθητής με declining story | `demo09` (early warning armed) |
| Μαθητής με πολλά reports (ASK ME/chat) | `demo02` (8 αποθηκευμένες αναφορές) |
| Τμήμα με class report | `ΜΓ1` (Junior Robotics) |
| Μάθημα με lesson report | `ΜΓ` |
| Live URL | https://bright-eva-alhhjx2c3a-ew.a.run.app |
| Pipeline | `/pipeline` · Risk Register `/risk-register` · Risk Lab `/sandbox` |
