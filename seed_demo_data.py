# -*- coding: utf-8 -*-
"""Seed synthetic demo data into all Bright E.V.A. sheets (AI sandbox testbed).

12 fake students (demo01..demo12) across 2 real groups (ΜΓ1 Junior, ΜΔ2 Advanced)
with 12 deliberately DIVERSE profiles covering every dimension of the forms:
  - cognitive: concept comprehension, programming skill, build completion
  - soft skills: participation, collaboration
  - affective: student self-perception (incl. mismatches with teacher scores)
  - stakeholder triangulation: parent pre/post vs teacher formative
  - classroom climate: per-group LessonAssessment arcs

APPEND-ONLY. Never touches existing rows. Idempotent: aborts if demo01 exists.
Run:  .venv/Scripts/python.exe seed_demo_data.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
import gspread

from wellbeing_fields import (generate_fields, gen_lesson_fields,
                              gen_post_fields, gen_pre_fields, gen_self_fields)

GROUP_J = "ΜΓ1"  # Ρομποτική Junior — Mondays 18:00-19:30
GROUP_A = "ΜΔ2"  # Ρομποτική Advanced — Fridays 16:30-18:00
LESSON_J = "Ρομποτική Junior"
LESSON_A = "Ρομποτική Advanced"

# Real weekdays in 2026 (verified): Mondays & Fridays up to 20/10/2026
J_DATES = ["31/08/2026", "07/09/2026", "14/09/2026", "21/09/2026",
           "28/09/2026", "05/10/2026", "12/10/2026", "19/10/2026"]
A_DATES = ["28/08/2026", "04/09/2026", "11/09/2026", "18/09/2026",
           "25/09/2026", "02/10/2026", "09/10/2026", "16/10/2026"]
J_ISO = [d[6:] + "-" + d[3:5] + "-" + d[0:2] for d in J_DATES]
A_ISO = [d[6:] + "-" + d[3:5] + "-" + d[0:2] for d in A_DATES]

def ts(date, hm, mer):
    """Google-Forms style Greek timestamp, e.g. 31/08/2026 06:15:00 μ.μ."""
    return f"{date} {hm}:00 {mer}"

J_FO_TS = [ts(d, "06:15", "μ.μ.") for d in J_DATES]      # 18:15
A_FO_TS = [ts(d, "05:15", "μ.μ.") for d in A_DATES]      # 17:15
PRE_TS = ts("26/08/2026", "10:30", "π.μ.")

# ---------------------------------------------------------------------------
# The 12 profiles. arc = 8 rows of [participation, comprehension, build,
# programming, collaboration]. notes = teacher note per session (no names —
# real per-student forms never name other children).
# ---------------------------------------------------------------------------
STUDENTS = [
    # ---------------- ΜΓ1 — Ρομποτική Junior ----------------
    dict(id="demo01", name="Άρης", surname="Βλαχόπουλος", age="8 χρον.",
         parent="Μαρία Βλαχοπούλου", group=GROUP_J, lesson=LESSON_J,
         profile="excelling all-rounder",
         arc=[[4,4,4,4,4],[4,5,4,4,5],[5,4,5,4,4],[4,5,4,5,5],
              [5,5,5,4,5],[5,5,5,5,5],[5,5,5,5,5],[5,5,5,5,5]],
         notes=[
             "Πρώτη επαφή με το kit· ολοκλήρωσε το Milo γρήγορα και βοήθησε τον διπλανό του με τη σύνδεση",
             "Άλλαξε μόνος του τις παραμέτρους του μοτέρ· πρότεινε ιδέα για ταχύτερη κίνηση",
             "Κατανόησε άμεσα τη μετάδοση με γρανάζια· την εξήγησε στο ζευγάρι του με παράδειγμα",
             "Πειραματίστηκε με τον αισθητήρα κλίσης πέρα από την άσκηση· τεκμηρίωσε τις δοκιμές του",
             "Συνδύασε αισθητήρα κίνησης με ήχο· η πιο ολοκληρωμένη δουλειά του τμήματος",
             "Σχεδίασε τροχαλία με σωστή αναλογία· ηγήθηκε του ζευγαριού χωρίς να επιβάλλεται",
             "Ο ρόβερ του άλλαξε κατεύθυνση με ακρίβεια· ζήτησε extra πρόκληση",
             "Παρουσίασε το project του μπροστά στο τμήμα με άνεση· έδωσε σχόλια στους άλλους",
         ]),
    dict(id="demo02", name="Ελένη", surname="Παπαδάκη", age="7 χρον.",
         parent="Νίκος Παπαδάκης", group=GROUP_J, lesson=LESSON_J,
         profile="steady improver (flagship growth arc)",
         arc=[[2,2,3,2,3],[3,2,3,2,4],[3,3,3,3,4],[3,3,4,3,4],
              [4,4,4,3,4],[4,4,4,4,5],[4,5,4,4,5],[5,5,4,4,5]],
         notes=[
             "Πρώτη επαφή· δυσκολεύτηκε με τη σύνδεση του Smarthub, χρειάστηκε καθοδήγηση βήμα-βήμα",
             "Ολοκλήρωσε το Milo με βοήθεια· χάρηκε πολύ όταν κινήθηκε — πρώτη θετική έκρηξη",
             "Με τα γρανάζια μπερδεύτηκε στην αρχή, αλλά με οπτικό παράδειγμα τα κατάφερε",
             "Ο αισθητήρας κλίσης της φάνηκε «μαγικός»· αρχίζει να ρωτάει «γιατί»",
             "Ολοκλήρωσε την άσκηση σχεδόν μόνη της· σημαντική βελτίωση στην αυτονομία",
             "Στην τροχαλία έδειξε επιμονή μετά από 2 αποτυχίες — δεν τα παράτησε όπως παλιά",
             "Προγραμμάτισε τον ρόβερ με ελάχιστη υποστήριξη· αυτοπεποίθηση εμφανώς αυξημένη",
             "Παρουσίασε το project της με λίγο άγχος αλλά ολοκληρωμένα· αξιέπαινη πορεία 8 εβδομάδων",
         ]),
    dict(id="demo03", name="Ορέστης", surname="Νικολάου", age="8 χρον.",
         parent="Άννα Νικολάου", group=GROUP_J, lesson=LESSON_J,
         profile="average stable",
         arc=[[3,3,3,3,3],[3,3,3,3,4],[3,3,3,3,3],[4,3,3,3,3],
              [3,3,4,3,4],[3,3,3,3,3],[3,4,3,3,3],[3,3,3,3,4]],
         notes=[
             "Σταθερή δουλειά· ολοκλήρωσε τα βασικά του Milo χωρίς εκπλήξεις",
             "Ακολούθησε τις οδηγίες πιστά· δεν επιχείρησε τροποποιήσεις",
             "Τα γρανάζια τα κατάλαβε σε βασικό επίπεδο· χρειάζεται ερώτηση-κλειδί για να τα εξηγήσει",
             "Με τον αισθητήρα κλίσης δούλεψε τυπικά· ολοκλήρωσε την άσκηση",
             "Καλή συνεργασία στο ζευγάρι· τήρησε τον ρόλο του",
             "Η τροχαλία λειτούργησε μετά από διόρθωση· σταθερός ρυθμός",
             "Ο ρόβερ ολοκληρώθηκε με τις βασικές λειτουργίες· καμία έξτρα δοκιμή",
             "Παρουσίαση σύντομη αλλά σωστή· σταθερό μέτριο επίπεδο σε όλο τον κύκλο",
         ]),
    dict(id="demo04", name="Μαρίλια", surname="Καραγιάννη", age="7 χρον.",
         parent="Πέτρος Καραγιάννης", group=GROUP_J, lesson=LESSON_J,
         profile="struggling / declining",
         arc=[[3,2,3,2,3],[2,2,2,2,3],[3,2,2,2,2],[2,2,2,1,2],
              [2,1,2,1,2],[2,1,1,1,2],[1,1,1,1,2],[2,1,1,1,2]],
         notes=[
             "Ξεκίνησε με διάθεση αλλά μπερδεύτηκε με τα εξαρτήματα· ζήτησε να ζωγραφίσει αντί να χτίσει",
             "Δυσκολία να ακολουθήσει τη σειρά των βημάτων· αποσπάστηκε αρκετές φορές",
             "Τα γρανάζια την απογοήτευσαν· είπε «δεν τα καταλαβαίνω αυτά» και αποσύρθηκε",
             "Αρνήθηκε να δοκιμάσει τον αισθητήρα χωρίς τον εκπαιδευτικό δίπλα της",
             "Μισή συμμετοχή· προτιμούσε να παρακολουθεί τους άλλους",
             "Αποχώρησε από το ζευγάρι της στη μέση της άσκησης· εκνευρίστηκε με την τροχαλία",
             "Ελάχιστη εμπλοκή με τον ρόβερ· ολοκλήρωσε μόνο τη βάση με υποστήριξη",
             "Δεν ήθελε να παρουσιάσει· συμμετείχε μόνο ως ακροατής. Προτείνεται συζήτηση με γονείς",
         ]),
    dict(id="demo05", name="Φοίβος", surname="Αντωνίου", age="8 χρον.",
         parent="Ειρήνη Αντωνίου", group=GROUP_J, lesson=LESSON_J,
         profile="cognitive-strong / soft-skill-weak",
         arc=[[3,4,4,4,2],[3,5,4,4,2],[4,5,4,5,2],[3,5,4,5,2],
              [3,5,5,5,3],[4,5,4,5,2],[3,5,5,5,2],[4,5,5,5,3]],
         notes=[
             "Ολοκλήρωσε το Milo σε μισό χρόνο και ζήτησε «το επόμενο»· αρνήθηκε να δουλέψει σε ζευγάρι",
             "Προγραμμάτισε σύνθετη ακολουθία κινήσεων μόνος του· ενοχλήθηκε όταν του ζητήθηκε να μοιραστεί το tablet",
             "Κατανόησε πλήρως τα γρανάζια και υπολόγισε αναλογίες· δεν εξήγησε σε κανέναν, «ας τα βρουν μόνοι τους»",
             "Πείραμα με τον αισθητήρα κλίσης επιπέδου advanced· απομονώθηκε σε γωνία",
             "Συνδύασε δύο αισθητήρες σε ένα πρόγραμμα — εντυπωσιακό· στην ομαδική δουλειά κυριάρχησε και μετά αποσύρθηκε",
             "Έλυσε την τροχαλία μαθηματικά σωστά· διαφώνησε έντονα με το ζευγάρι και συνέχισε μόνος",
             "Ο ρόβερ του είχε την πιο σύνθετη λογική του τμήματος· αρνήθηκε ρόλο στην κοινή παρουσίαση",
             "Γνωστικά εξαιρετικό project· στην παρουσίαση μίλησε μόνο για τη δική του κατασκευή. Στόχος: κοινωνικές δεξιότητες",
         ]),
    dict(id="demo06", name="Ζωή", surname="Μακρή", age="8 χρον.",
         parent="Στέφανος Μακρής", group=GROUP_J, lesson=LESSON_J,
         profile="social-strong / cognitive-weak",
         arc=[[5,2,3,2,5],[5,2,2,2,5],[4,2,3,2,5],[5,2,2,2,4],
              [5,3,3,2,5],[4,2,3,2,5],[5,2,2,2,5],[5,3,3,2,5]],
         notes=[
             "Ενθουσιασμός 100%· έκανε το μάθημα γιορτή, αλλά το Milo έμεινε μισοτελειωμένο",
             "Οργάνωσε τα ζευγάρια και φρόντισε να μιλήσουν όλοι· το δικό της πρόγραμμα χρειάστηκε πολύ βοήθεια",
             "Τα γρανάζια δεν τα κατάλαβε· αντ' αυτού ετοίμασε «παρουσίαση» για το τι έκαναν οι άλλοι",
             "Απόλαυσε τον αισθητήρα κλίσης ως παιχνίδι· δεν συνέδεσε την έννοια με τον κώδικα",
             "Κορυφαία συνεργάτρια — κράτησε το ηθικό του τμήματος· η άσκησή της ολοκληρώθηκε από το ζευγάρι",
             "Δοκίμασε την τροχαλία με χαρά αλλά μπερδεύτηκε στις συνδέσεις· ζήτησε βοήθεια ανοιχτά (θετικό)",
             "Ο ρόβερ λειτούργησε με σημαντική υποστήριξη· ανέλαβε το σχόλιο της παρουσίασης",
             "Λαμπρή παρουσιάστρια του group project· γνωστικά παραμένει πίσω — χρειάζεται στοχευμένη ενίσχυση",
         ]),
    # ---------------- ΜΔ2 — Ρομποτική Advanced ----------------
    dict(id="demo07", name="Ιάσονας", surname="Ρήγας", age="11 χρον.",
         parent="Κατερίνα Ρήγα", group=GROUP_A, lesson=LESSON_A,
         profile="late bloomer",
         arc=[[2,2,2,2,3],[2,2,3,2,3],[2,2,2,2,2],[3,2,3,2,3],
              [3,3,3,3,3],[4,4,4,3,4],[4,4,4,4,4],[5,4,5,4,4]],
         notes=[
             "Πολύ ήσυχος· παρακολουθούσε χωρίς να δοκιμάζει· ολοκλήρωσε τη βάση του Spike με αβεβαιότητα",
             "Δούλεψε αργά αλλά μεθοδικά· δεν ρώτησε τίποτα — χρειάζεται προσωπική πρόσκληση",
             "Ο αισθητήρας χρώματος τον κέντρισε· πρώτη φορά έμεινε μετά το τέλος για να τελειώσει",
             "Αποφυγή εμποδίων: ακολούθησε σωστά τα βήματα· αρχίζει να σηκώνει το βλέμμα",
             "Line follower: έκανε τις πρώτες του ερωτήσεις! «Γιατί κολλάει στη γραμμή;»",
             "Στον βραχίονα έδειξε απροσδόκητη ακρίβεια στις κινήσεις· το ζευγάρι τον εμπιστεύτηκε",
             "Κατανόησε loops και conditions με δικό του παράδειγμα· αισθητή αλλαγή στάσης",
             "Ολοκλήρωσε το challenge της πίστας στον 2ο καλύτερο χρόνο· μίλησε πρώτος στην παρουσίαση. Εκρηκτικό δεύτερο μισό",
         ]),
    dict(id="demo08", name="Δάφνη", surname="Σπανού", age="11 χρον.",
         parent="Λευτέρης Σπανός", group=GROUP_A, lesson=LESSON_A,
         profile="erratic / inconsistent",
         arc=[[2,4,3,2,4],[5,2,5,4,2],[3,3,2,3,5],[2,5,4,2,3],
              [4,2,5,3,4],[5,4,2,5,2],[2,3,4,2,4],[4,5,3,4,3]],
         notes=[
             "Μέρα εκτός τόπου· δεν συγκεντρώθηκε, άλλαξε 3 φορές θέση",
             "Εκπληκτική μέρα! Ολοκλήρωσε την κίνηση με μοίρες πριν από όλους και βοήθησε άλλους",
             "Ο αισθητήρας χρώματος δεν την κέρδισε· διέκοπτε συνέχεια τους διπλανούς",
             "Μέτρια μέρα· ξεκίνησε δυνατά την αποφυγή εμποδίων, κόπηκε στη μέση",
             "Line follower: φαινόμενο! Το ρομπότ της έμεινε στη γραμμή από την πρώτη δοκιμή",
             "Άσχημη μέρα ξανά· τσακώθηκε με το ζευγάρι, δεν ολοκλήρωσε τον βραχίονα",
             "Loops: τα κατάλαβε αστραπιαία αλλά βαρέθηκε την εξάσκηση",
             "Στο τελικό challenge ξεκίνησε χαμένη και βρήκε λύση στο τέλος. Τεράστιο ταλέντο, μηδέν σταθερότητα — πρόταση: ρόλος-στόχος ανά μάθημα",
         ]),
    dict(id="demo09", name="Αχιλλέας", surname="Μόσχος", age="12 χρον.",
         parent="Ολυμπία Μόσχου", group=GROUP_A, lesson=LESSON_A,
         profile="disengaged decline (early-warning case)",
         arc=[[4,3,3,3,4],[3,3,3,3,3],[3,2,3,2,3],[2,2,2,2,2],
              [2,2,2,1,2],[1,1,2,1,2],[1,1,1,1,1],[1,1,1,1,1]],
         notes=[
             "Ξεκίνησε καλά με το Spike· ολοκλήρωσε το βασικό πρόγραμμα, αλλά χωρίς ενθουσιασμό",
             "Ολοκλήρωσε την κίνηση με μοίρες, αλλά ρώτησε «πότε τελειώνουμε;» δύο φορές",
             "Αδιαφορία για τον αισθητήρα χρώματος· έκανε τα ελάχιστα",
             "Δεν ήθελε να συμμετάσχει στην αποφυγή εμποδίων· κάθισε στο πλάι — ρωτήθηκε, είπε «βαριέμαι»",
             "Line follower: μισή προσπάθεια· άφηνε το ρομπότ και αποσπάστηκε με το κινητό (το παρέδωσε)",
             "Δεν συνεργάστηκε στον βραχίονα· είπε στο ζευγάρι «κάντο εσύ»",
             "Αρνήθηκε τα loops· ελάχιστη παρουσία στο μάθημα παρά τη φυσική παρουσία",
             "Δεν συμμετείχε στο τελικό challenge. Σοβαρό σήμα αποσύνδεσης — ενημέρωση γονέων και εξατομικευμένη προσέγγιση άμεσα",
         ]),
    dict(id="demo10", name="Ιφιγένεια", surname="Λαμπροπούλου", age="11 χρον.",
         parent="Γιώργος Λαμπρόπουλος", group=GROUP_A, lesson=LESSON_A,
         profile="anxious perfectionist (teacher 4s / self feels failure)",
         arc=[[4,4,4,4,3],[4,4,4,4,3],[5,4,4,4,4],[4,5,4,4,3],
              [4,4,5,4,4],[5,4,4,4,4],[4,5,4,5,4],[5,5,5,4,4]],
         notes=[
             "Ολοκλήρωσε το Spike intro άψογα· ξαναέλεγξε τη δουλειά της 4 φορές πριν τη δείξει",
             "Ακρίβεια κίνησης τέλεια· στεναχωρήθηκε που χρειάστηκε 2η δοκιμή — υπερβολική αυτοκριτική",
             "Αισθητήρας χρώματος: άριστη δουλειά, αλλά ζήτησε διαβεβαίωση 3 φορές «έτσι είναι σωστό;»",
             "Αποφυγή εμποδίων: πολύ καλή· σχεδόν δάκρυσε όταν το ρομπότ ακούμπησε ελαφρώς το εμπόδιο",
             "Line follower: ο καλύτερος χρόνος του τμήματος· εκείνη εστίασε στη μία στροφή που «δεν ήταν τέλεια»",
             "Βραχίονας: μεθοδικότατη· δεν δοκιμάζει χωρίς να είναι σίγουρη — χάνει χρόνο",
             "Loops & conditions: άριστη κατανόηση· αρνείται να δείχνει δουλειά που θεωρεί «ημιτελή»",
             "Τελικό challenge: εξαιρετικό αποτέλεσμα· στην παρουσίαση αυτομειώθηκε («τυχαίο ήταν»). Δυνατή γνωστικά — χρειάζεται δουλειά στην αυτοπεποίθηση",
         ]),
    dict(id="demo11", name="Οδυσσέας", surname="Φωτίου", age="10 χρον.",
         parent="Αθηνά Φωτίου", group=GROUP_A, lesson=LESSON_A,
         profile="parent blindspot (low expectations / actual excellence)",
         arc=[[4,4,3,3,4],[4,4,4,4,4],[5,4,4,4,4],[4,5,4,4,5],
              [5,5,5,4,4],[5,5,4,5,5],[5,5,5,5,5],[5,5,5,5,5]],
         notes=[
             "Παρά την «έλλειψη εμπειρίας» που δήλωσε ο γονέας: πρώτος ολοκλήρωσε το Spike intro· φυσικό ταλέντο",
             "Κίνηση με μοίρες: άμεση κατανόηση· βοήθησε διακριτικά τη διπλανή του",
             "Αισθητήρας χρώματος: πειραματίστηκε πέρα από την άσκηση· ντροπαλός αλλά μεθοδικός",
             "Αποφυγή εμποδίων: εξαιρετική λογική ακολουθίας· μιλάει περισσότερο πια στο ζευγάρι του",
             "Line follower: 2η καλύτερη επίδοση· χαμογέλασε όταν επευφημήθηκε — κερδίζει αυτοπεποίθηση",
             "Βραχίονας: πρότεινε βελτίωση στο grip· το τμήμα τον άκουσε",
             "Loops: τους χρησιμοποίησε δημιουργικά για pattern χρωμάτων",
             "Τελικό challenge: ολοκλήρωσε με άριστα. Ο ντροπαλός «αδύναμος» μαθητής της αρχικής δήλωσης είναι από τους κορυφαίους του τμήματος",
         ]),
    dict(id="demo12", name="Περσεφόνη", surname="Δελή", age="11 χρον.",
         parent="Χρήστος Δελής", group=GROUP_A, lesson=LESSON_A,
         profile="mid-cycle dip & recovery (illness)",
         arc=[[4,4,4,3,4],[4,4,4,4,4],[4,3,4,3,4],[1,1,1,1,2],
              [2,1,1,1,2],[3,3,3,2,3],[4,4,4,3,4],[4,4,4,4,4]],
         notes=[
             "Δυναμικό ξεκίνημα· ολοκλήρωσε το intro και πρόσθεσε ήχους",
             "Κίνηση με μοίρες: πολύ καλή· συνεργάστηκε άψογα",
             "Αισθητήρας χρώματος: σταθερή· λίγο κουρασμένη σήμερα",
             "ΑΠΟΥΣΙΑ (ασθένεια — ενημέρωσε η μητέρα)",
             "Επέστρεψε αλλά αποπροσανατολισμένη· δύσκολο μάθημα — έχασε το νήμα μετά την απουσία",
             "Βραχίονας: σταδιακή επανεκκίνηση· το ζευγάρι την βοήθησε να ξαναμπεί στο κλίμα",
             "Loops: επέστρεψε στο επίπεδο πριν την απουσία· ξαναβρήκε τον ρυθμό της",
             "Τελικό challenge: πλήρης επιστροφή! Ολοκλήρωσε την πίστα και παρουσίασε με χαρά",
         ]),
]

# ---------------------------------------------------------------------------
# Parent PreAssessment (26/08/2026) — expectations / prior experience /
# strengths / improvement wishes, matched to each profile.
# ---------------------------------------------------------------------------
PRE = {
    "demo01": ["Να εμβαθύνει στον προγραμματισμό και να παίρνει πρωτοβουλίες",
               "Έχει δουλέψει Scratch και λίγο Lego Spike στο σπίτι",
               "Λογική σκέψη, οργάνωση, βοηθάει τους συμμαθητές του",
               "Να μάθει να δουλεύει και υπό χρονοπίεση"],
    "demo02": ["Να αποκτήσει αυτοπεποίθηση με την τεχνολογία",
               "Σχεδόν καμία — μόνο tablet games",
               "Επιμονή και πολύ καλή συμπεριφορά",
               "Να μην αποθαρρύνεται εύκολα όταν κάτι δεν βγαίνει"],
    "demo03": ["Να περνάει καλά και να μαθαίνει τα βασικά",
               "Λίγο Scratch στο σχολείο",
               "Σταθερότητα, ακολουθεί οδηγίες",
               "Πρωτοβουλία και φαντασία"],
    "demo04": ["Να της αρέσει η ρομποτική όσο της αρέσουν τα παραμύθια",
               "Καμία",
               "Φαντασία και ζωγραφική",
               "Συγκέντρωση — αποσπάται πολύ εύκολα"],
    "demo05": ["Να προκληθεί γνωστικά, βαριέται τα εύκολα",
               "Arduino kit στο σπίτι με τον πατέρα του, βασική Python",
               "Καταπληκτική λογική, μαθαίνει τα πάντα μόνος του",
               "Συνεργασία — θέλει να τα κάνει όλα μόνος του"],
    "demo06": ["Να κάνει φίλους και να διασκεδάσει",
               "Καμία τεχνική, αλλά λατρεύει τα Lego",
               "Κοινωνικότητα, ενθουσιασμός, χιούμορ",
               "Να καταλαβαίνει τι ακριβώς ζητάει η άσκηση"],
    "demo07": ["Να βρει κάτι που να τον ενθουσιάζει",
               "Λίγο Minecraft, τίποτα άλλο",
               "Ήσυχος παρατηρητής, μεθοδικός",
               "Να εκφράζεται περισσότερο στην ομάδα"],
    "demo08": ["Να διοχετεύσει την ενέργειά της δημιουργικά",
               "Scratch Jr περιστασιακά",
               "Ενέργεια, ιδέες, τολμάει",
               "Συνέπεια — άλλη μέρα πετάει, άλλη όχι"],
    "demo09": ["Να συνεχίσει όσο καλά πήγε στα περσινά δοκιμαστικά",
               "Παρακολούθησε 3 δοκιμαστικά μαθήματα την άνοιξη",
               "Γρήγορη αντίληψη",
               "Τον βλέπουμε λιγότερο ενθουσιώδη τελευταία — ελπίζουμε να ξαναβρεί το κέφι του"],
    "demo10": ["Να απολαμβάνει τη διαδικασία, όχι μόνο το αποτέλεσμα",
               "Scratch, άριστη μαθήτρια στο σχολείο",
               "Επιμέλεια, ακρίβεια, εργατικότητα",
               "Να μην αγχώνεται όταν κάτι δεν βγαίνει τέλειο"],
    "demo11": ["Είναι ντροπαλός, δεν περιμένουμε πολλά — κυρίως να κοινωνικοποιηθεί",
               "Καμία, δεν έχει δείξει ιδιαίτερο ενδιαφέρον",
               "Ήσυχος, καλό παιδί",
               "Αυτοπεποίθηση"],
    "demo12": ["Σταθερή πρόοδος και καλή διάθεση",
               "Lego WeDo πέρυσι, της άρεσε πολύ",
               "Κατανόηση μηχανισμών, συνεργασία",
               "Τίποτα ιδιαίτερο — ας συνεχίσει έτσι"],
}

# SelfAssessment: weeks 3, 5, 8 -> (feeling, difficulty, enjoyment)
SELF = {
    "demo01": [("Τέλεια! Τα γρανάζια ήταν εύκολα για μένα", "Τίποτα, ίσως το να το εξηγήσω στους άλλους", "Που βοήθησα τον φίλο μου"),
               ("Πολύ καλά, θέλω πιο δύσκολα πράγματα", "Τίποτα ιδιαίτερο", "Ο αισθητήρας κίνησης!"),
               ("Υπέροχα! Η παρουσίαση ήταν η καλύτερη", "Να μιλήσω μπροστά σε όλους, λιγάκι", "Το τελικό μας όχημα")],
    "demo02": [("Λίγο μπερδεμένη αλλά χαρούμενη", "Τα γρανάζια στην αρχή", "Που κατάλαβα επιτέλους πώς δουλεύει"),
               ("Καλά! Τα κατάφερα σχεδόν μόνη μου", "Λίγο ακόμα οι συνδέσεις", "Που δεν χρειάστηκα βοήθεια"),
               ("Περήφανη! Ήμουν νευρική στην παρουσίαση αλλά τα είπα όλα", "Το άγχος της παρουσίασης", "Που όλοι χειροκρότησαν")],
    "demo03": [("Καλά, κανονικά", "Τα γρανάζια λιγάκι", "Το ρομπότ που κινείται"),
               ("Μια χαρά", "Ο αισθητήρας λίγο", "Η ομαδική δουλειά"),
               ("Ωραία τελείωσε", "Η παρουσίαση με ζόρισε λίγο", "Που τελείωσε το project")],
    "demo04": [("Δεν μου άρεσε πολύ σήμερα", "Τα γρανάζια, είναι δύσκολα", "Η ζωγραφική στο τέλος"),
               ("Βαρετά", "Όλα λίγο πολύ", "Που κοιτούσα τους άλλους"),
               ("Δεν ήθελα να έρθω", "Δεν καταλαβαίνω τι να κάνω", "Τίποτα σήμερα")],
    "demo05": [("Εύκολο, θέλω πιο δύσκολα", "Τίποτα — τα ξέρω ήδη", "Που το έλυσα πρώτος"),
               ("Καλά, αλλά μου ζήτησαν να δουλέψω με άλλον και μου χάλασε τον ρυθμό", "Να περιμένω τους άλλους", "Το πρόγραμμα με τους δύο αισθητήρες"),
               ("Το project μου ήταν το καλύτερο", "Η ομαδική παρουσίαση — γιατί να μιλήσω για δουλειά άλλων;", "Η λογική του ρόβερ")],
    "demo06": [("Τέλεια! Αγαπώ αυτό το μάθημα", "Ο κώδικας με μπερδεύει", "Που γελάσαμε όλοι μαζί"),
               ("Σούπερ! Βοήθησα την ομάδα", "Οι συνδέσεις στα καλώδια", "Που οργάνωσα την ομάδα μου"),
               ("Η καλύτερη μέρα! Παρουσίασα για όλους", "Η τεχνική μεριά ακόμα με ζορίζει", "Η παρουσίαση!!!")],
    "demo07": [("Καλά νομίζω, δεν είμαι σίγουρος", "Να καταλάβω τι ζητάει η άσκηση", "Ο αισθητήρας χρώματος ήταν ωραίος"),
               ("Καλύτερα από άλλες φορές", "Η γραμμή μερικές φορές χανόταν", "Που ρώτησα και έμαθα γιατί κολλάει στη γραμμή"),
               ("Πολύ καλά! Τα κατάφερα μόνος μου", "Η αρχή με άγχωσε λίγο", "Που τελείωσα 2ος στην πίστα!")],
    "demo08": [("Βαρετά σήμερα", "Δεν ξέρω, δεν πρόσεχα ίσως", "Τίποτα"),
               ("ΤΕΛΕΙΑ! Το ρομπότ μου ήταν ο θεός", "Τίποτα!!", "Το line follower!!"),
               ("Μπερδεμένα — άσχημα στην αρχή, τέλεια στο τέλος", "Η αρχή, πάντα η αρχή", "Που βρήκα λύση στο τέλος")],
    "demo09": [("Κανονικά, τίποτα ιδιαίτερο", "Ο αισθητήρας ήταν βαρετός", "Το τέλος του μαθήματος"),
               ("Βαριέμαι", "Όλα", "Που κάθισα μόνος μου"),
               ("Δεν θέλω να έρθω ξανά", "Δεν μου αρέσει πια", "Τίποτα")],
    "demo10": [("Καλά αλλά θα μπορούσα καλύτερα", "Έκανα λάθος στη 2η δοκιμή", "Που τελικά ήταν σωστό"),
               ("Αγχωμένη — δεν ήμουν η καλύτερη σήμερα (ήμουν;)", "Η μία στροφή που δεν βγήκε τέλεια", "Που η δασκάλα είπε μπράβο"),
               ("Πήγε καλά, αλλά τύχη ήταν νομίζω", "Δεν είμαι σίγουρη αν άξιζε η βαθμολογία", "Το αποτέλεσμα, αν είναι πραγματικά καλό")],
    "demo11": [("Ντρεπόμουν λίγο αλλά πήγε καλά", "Να μιλήσω στην τάξη", "Που το έκανα πρώτος"),
               ("Καλά! Βοήθησα και τη φίλη μου", "Η στροφή στη γραμμή", "Που χαμογέλασα όταν μου είπαν μπράβο"),
               ("Τέλεια, τα κατάφερα!", "Τίποτα σήμερα", "Που ολοκλήρωσα όλη την πίστα")],
    "demo12": [("Καλά αλλά λίγο κουρασμένη", "Ο αισθητήρας χρώματος λιγάκι", "Που το κατάφερα"),
               ("Μόλις γύρισα από ίωση, μπερδεύτηκα", "Που έχασα τα προηγούμενα μαθήματα", "Που με βοήθησε η ομάδα μου"),
               ("Τέλεια! Επέστρεψα για τα καλά", "Τίποτα πια", "Που τελείωσα την πίστα μετά την αρρώστια!")],
}

# Parent PostAssessment (end of cycle) — progress / changes at home / comments
POST = {
    "demo01": ["Απόλυτη πρόοδος — μιλάει για ρομποτική ασταμάτητα",
               "Οργανώνει τα Lego του με «αναλογίες γραναζιών» και μας εξηγεί πώς δουλεύουν",
               "Εξαιρετική δουλειά, ευχαριστούμε"],
    "demo02": ["Ναι! Από το «δεν μπορώ» πήγε στο «κοίτα τι έφτιαξα»",
               "Πιο επιμελής και στα μαθήματά της, μεγαλύτερη επιμονή γενικά",
               "Η αλλαγή στην αυτοπεποίθησή της είναι εμφανής — συγχαρητήρια"],
    "demo03": ["Μια σταθερή, καλή πορεία",
               "Τίποτα αρνητικό, τίποτα συγκλονιστικό — σταθερός",
               "Θα ήθελα να τον προκαλέσετε περισσότερο στον επόμενο κύκλο"],
    "demo04": ["Δυστυχώς όχι — έχασε το ενδιαφέρον της",
               "Δεν μιλάει πια για το μάθημα, ζήτησε να σταματήσει",
               "Ίσως δεν ήταν αυτό που της ταίριαζε — θέλουμε να το συζητήσουμε μαζί σας"],
    "demo05": ["Γνωστικά εντυπωσιακός, αλλά...",
               "Μας εξηγεί κυκλώματα στο τραπέζι, αλλά αρνείται να φτιάξει τίποτα μαζί με τον αδερφό του",
               "Παρακαλώ δουλέψτε τη συνεργασία του"],
    "demo06": ["Ως κοινωνική εμπειρία άψογη — γνωστικά δεν ξέρω",
               "Λατρεύει τα μαθήματα και τους φίλους της, αλλά δεν μπορεί να μας εξηγήσει τι έφτιαξε",
               "Μήπως χρειάζεται εξατομικευμένη βοήθεια στις έννοιες;"],
    "demo07": ["Ναι, κυρίως στο δεύτερο μισό!",
               "Από σιωπηλός, τώρα μας διηγείται τι έκανε στο μάθημα",
               "Ευχαριστούμε που τον βοηθήσατε να βγει από το καβούκι του"],
    "demo08": ["Πάνω-κάτω, όπως πάντα",
               "Άλλες εβδομάδες μιλάει με πάθος, άλλες ξεχνάει ότι έχει μάθημα",
               "Αν βρείτε τρόπο να τη σταθεροποιήσετε, θα είναι φοβερή"],
    "demo09": ["Όχι, και ανησυχούμε",
               "Δεν θέλει να έρθει ξανά, κλείνεται στο δωμάτιό του",
               "Θα θέλαμε συνάντηση μαζί σας — κάτι δεν πάει καλά φέτος"],
    "demo10": ["Τεχνικά ναι, συναισθηματικά ανησυχούμε",
               "Κλαίει όταν κάτι δεν βγαίνει «τέλειο» και δεν αναγνωρίζει τις επιτυχίες της",
               "Πώς τη βοηθάμε να ηρεμεί με τα λάθη;"],
    "demo11": ["Είμαστε έκπληκτοι! Δεν το περιμέναμε καθόλου",
               "Ο ντροπαλός μας μιλάει για αισθητήρες και μας δείχνει κατασκευές",
               "Προφανώς τον υποτιμήσαμε — συνεχίστε έτσι!"],
    "demo12": ["Ναι, παρά την απουσία της με την ίωση",
               "Φοβόμασταν ότι θα μείνει πίσω αλλά επέστρεψε δυνατά",
               "Ευχαριστούμε για την υποστήριξη μετά την ασθένειά της"],
}

# ---------------------------------------------------------------------------
# LessonAssessment (classroom climate) — 8 sessions per group
# ---------------------------------------------------------------------------
LESSON_ROWS = []
_lesson_J = [
    ("3", "65", "Πρώτη γνωριμία με τα kits — αργό ξεκίνημα, αρκετοί δεν ολοκλήρωσαν τη βάση",
     "Νέο τμήμα, χρειάζεται χρόνος προσαρμογής· να μπει ρουτίνα ζευγαριών"),
    ("3", "70", "Συνδέσεις Smarthub-bluetooth σε 2 tablets",
     "Βοηθός για το pairing τα πρώτα λεπτά"),
    ("4", "75", "Τα γρανάζια μπέρδεψαν τους μισούς — χρειάστηκε οπτικό demo στον πίνακα",
     "Το demo με τα μεγάλα γρανάζια δούλεψε άψογα"),
    ("4", "80", "Ο αισθητήρας κλίσης ενθουσίασε· καθυστέρηση στη φόρτιση 3 hubs",
     "Να φορτίζονται τα hubs από το προηγούμενο βράδυ"),
    ("4", "85", "Ομαλή ροή· ένα ζευγάρι μάλωσε για το tablet",
     "Κανόνας εναλλαγής tablet κάθε 10 λεπτά"),
    ("5", "90", "Οι τροχαλίες πήγαν εξαιρετικά — ζήτησαν παράταση",
     "Το τμήμα ωριμάζει· να ανέβει η δυσκολία"),
    ("5", "90", "Οι ρόβερ ολοκληρώθηκαν σχεδόν από όλους",
     "Έναρξη προετοιμασίας τελικού project"),
    ("5", "95", "Τελικές παρουσιάσεις — υψηλή ενέργεια, μία μαθήτρια αρνήθηκε να παρουσιάσει",
     "Εξαιρετικό κλίμα· σημείο προσοχής η αποσύνδεση μιας μαθήτριας"),
]
_lesson_A = [
    ("4", "80", "Τα Spike kits νέα για αρκετούς — χρόνος εξοικείωσης",
     "Γρήγορη προσαρμογή για προχωρημένο τμήμα"),
    ("4", "85", "Οι μοίρες/περιστροφές χρειάστηκαν εξήγηση στον πίνακα",
     "Καλή σύνδεση με τα μαθηματικά της τάξης"),
    ("4", "85", "Ο αισθητήρας χρώματος είχε θέμα βαθμονόμησης στον φωτισμό της αίθουσας",
     "Calibration στην αρχή του μαθήματος από εδώ και πέρα"),
    ("5", "90", "Η αποφυγή εμποδίων τους ενθουσίασε — ανταγωνιστικό πνεύμα",
     "Προσοχή: ένας μαθητής αποσυνδέθηκε — δείτε την ατομική του αξιολόγηση"),
    ("2", "55", "Αναπληρωτής εκπαιδευτικός — αναταραχή, το line follower δεν βγήκε στους περισσότερους",
     "Να επαναληφθεί η έννοια στο επόμενο μάθημα"),
    ("4", "85", "Ο βραχίονας πήγε καλά· επιτυχής επανάληψη του line follower",
     "Το τμήμα ανέκτησε ρυθμό"),
    ("4", "85", "Loops & conditions: οι μισοί τα εφάρμοσαν, οι υπόλοιποι αντέγραψαν",
     "Να δοθεί mini-quiz επανάληψης"),
    ("5", "90", "Τελικό challenge πίστας — υψηλή ενέργεια και επίπεδο",
     "Ισχυρό τμήμα στο σύνολό του· 2 ατομικές περιπτώσεις χρειάζονται παρακολούθηση"),
]
for i, (d, (resp, pct, diff, note)) in enumerate(zip(J_ISO, _lesson_J)):
    LESSON_ROWS.append([d, GROUP_J, resp, pct, diff, note,
                        *gen_lesson_fields(GROUP_J, resp, i)])
for i, (d, (resp, pct, diff, note)) in enumerate(zip(A_ISO, _lesson_A)):
    LESSON_ROWS.append([d, GROUP_A, resp, pct, diff, note,
                        *gen_lesson_fields(GROUP_A, resp, i)])

# ---------------------------------------------------------------------------
# 3 hand-written English sample reports for instant ASK ME testing
# (already anonymized — pseudonyms only, exactly like real output).
# ---------------------------------------------------------------------------
REPORT_STUDENT_DEMO02 = """STUDENT PROGRESS REPORT — Student demo02
Reporting period: 31/08/2026 – 19/10/2026 (8 sessions, Robotics Junior / group ΜΓ1)

OVERALL TRAJECTORY: STRONGLY IMPROVING
Student demo02 shows the clearest growth arc in the group. Formative scores rose
from 2/5 across most dimensions in week 1 to 4-5/5 by week 8.

COGNITIVE DIMENSIONS
- Concept comprehension: 2 -> 5. Early difficulty with gears (week 3) resolved
  after visual demonstration; by week 7 she programmed the exploration rover with
  minimal support.
- Build completion: stable 3 -> 4. Finished every build from week 5 onward.
- Programming skills: 2 -> 4. Started with guided sequences; ended writing her
  own motor-parameter adjustments.

SOFT SKILLS
- Participation: 2 -> 5. From passive observer to active presenter.
- Collaboration: consistently strong (4-5). Works well in her pair.
- Persistence: the standout change — in week 6 she failed twice at the pulley
  task and kept going, unlike her early sessions.

STAKEHOLDER TRIANGULATION
- Parent pre-assessment: child with persistence but no tech experience; goal was
  confidence, not skill. Goal fully met.
- Self-assessment: mirrors the teacher view ("Περήφανη!" — proud) with realistic
  nervousness about presenting. No self/other mismatch.
- Parent post-assessment: "From 'I can't' to 'look what I made'"; persistence
  transferred to homework at home.

RISK FLAGS: none. Mild presentation anxiety, age-appropriate.

RECOMMENDATIONS
1. Enrich with open-ended challenges (she now finishes standard tasks early).
2. Give her a buddy role with a newer student to consolidate her confidence.
3. Next cycle: introduce sensors-with-conditions logic (if/then) as stretch goal.
"""

REPORT_CLASS_MG1 = """CLASS REPORT — Group ΜΓ1 (Ρομποτική Junior)
Reporting period: 31/08/2026 – 19/10/2026 (8 weekly sessions)

CLIMATE TRAJECTORY: 3 -> 5 (response), 65% -> 95% (activity completion).
A young group that needed two sessions to settle, then matured rapidly.

WHAT WORKED
- The large-gear board demo (week 3) unblocked half the class — visual-first
  explanations are the right channel for this age.
- Pair rotation with the 10-minute tablet rule (introduced week 5) ended device
  disputes completely.
- The pulley session (week 6) had the highest engagement; the group asked for
  extra time. Hands-on mechanical tasks outperform screen tasks for this cohort.

POINTS OF ATTENTION
- One student refused to present in the final showcase and teacher notes show a
  declining individual arc — early-warning case, follow up individually.
- One student is cognitively far ahead but resists pair work; the class benefits
  from his skills but he needs explicit collaboration goals.
- One student is the social engine of the class yet remains behind conceptually;
  pair her with a patient strong builder, not with the fastest one.

LOGISTICS
- Hubs must be charged the night before (week 4 lost ~10 minutes).
- Bluetooth pairing needs an assistant for the first 10 minutes of early-cycle
  sessions.

RECOMMENDATIONS
1. Keep the visual-demo pattern for every new concept.
2. Add a final-showcase rehearsal so reluctant presenters have a safe first try.
3. Differentiate: stretch tasks for the top student, concept scaffolding for the
   weakest, collaboration targets for the isolate.
"""

REPORT_LESSON_MG = """LESSON REPORT — Ρομποτική Junior (Lesson ID ΜΓ), across groups ΜΓ1–ΜΓ3
Reporting period: September – October 2026

DELIVERY QUALITY
The Junior curriculum (WeDo 2.0: Milo rover, gears, tilt & motion sensors,
pulleys, final autonomous-vehicle project) is well-sequenced: mechanical
concepts precede their programmatic use, and each sensor session produced a
measurable engagement spike.

OBSERVED PATTERNS ACROSS GROUPS
- Gears are the universal bottleneck (all groups, week 3). The physical demo
  resolves it; plan it into the curriculum rather than improvising it.
- Tilt sensor outperforms motion sensor as the first sensor introduced — cause
  and effect is more visible to 7-8 year olds.
- Completion rates climb 65% -> 95% over a cycle; the steepest gain follows the
  pulley session, suggesting it is the motivational turning point of the course.

TEACHING-QUALITY SIGNALS (from formative + classroom data)
- Sessions with a prepared visual demo score ~1 point higher on class response.
- Sessions starting with unresolved pairing/charging issues lose the first 10
  minutes and never fully recover the completion rate.

CURRICULUM RECOMMENDATIONS
1. Institutionalize the gear demo and the sensor order (tilt before motion).
2. Add one open "inventor session" between weeks 6 and 7 — several students
   finish standard tasks early and self-extend anyway.
3. Keep group size at 6: the two cases of disengagement this cycle were visible
   precisely because the teacher could track every child.
"""

REPORTS_ROWS = [
    ["2026-10-20 09:00:00", "20/10/2026", "Student", "ΜΓ1", "demo02",
     "Describe the student's overall progress",
     "You are an experienced educational psychologist writing for a teacher.",
     REPORT_STUDENT_DEMO02],
    ["2026-10-20 09:05:00", "20/10/2026", "Class", "", "ΜΓ1",
     "Assess the overall functioning of the class and suggest improvements",
     "You are an experienced educational psychologist writing for a teacher.",
     REPORT_CLASS_MG1],
    ["2026-10-20 09:10:00", "20/10/2026", "Lesson", "", "ΜΓ",
     "Evaluate the lesson's delivery and curriculum across groups",
     "You are an experienced educational psychologist writing for a teacher.",
     REPORT_LESSON_MG],
]

# ---------------------------------------------------------------------------
def main():
    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "insudies-e24d0d9618d5.json")
    gc = gspread.service_account(filename=sa_path)

    students_ws = gc.open("Students").sheet1

    # --- idempotency guard ---------------------------------------------------
    existing_ids = {r[0] for r in students_ws.get_all_values()[1:] if r}
    if "demo01" in existing_ids and "--force" not in sys.argv:
        print("Demo data already present (demo01 exists). Aborting.")
        print("Use --force to append again (NOT recommended).")
        sys.exit(1)

    # --- Students ------------------------------------------------------------
    student_rows = []
    for i, s in enumerate(STUDENTS, start=1):
        student_rows.append([
            s["id"], s["name"], s["surname"], s["age"], s["parent"],
            f"{s['id']}.parent@example.com", f"6900000{i:03d}",
            s["lesson"], s["group"], "", "", "",
        ])
    students_ws.append_rows(student_rows, value_input_option="RAW")
    print(f"Students: +{len(student_rows)} rows")

    # --- PreAssessment -------------------------------------------------------
    pre_rows = [[PRE_TS, s["id"], *PRE[s["id"]], *gen_pre_fields(s["id"])]
                for s in STUDENTS]
    gc.open("PreAssessment").sheet1.append_rows(pre_rows, value_input_option="RAW")
    print(f"PreAssessment: +{len(pre_rows)} rows")

    # --- FoAssessment --------------------------------------------------------
    fo_rows = []
    for s in STUDENTS:
        stamps = J_FO_TS if s["group"] == GROUP_J else A_FO_TS
        for idx, (stamp, scores, note) in enumerate(zip(stamps, s["arc"], s["notes"])):
            fo_rows.append([stamp, s["id"], *[str(x) for x in scores], note,
                            *generate_fields(s["id"], scores, idx)])
    gc.open("FoAssessment").sheet1.append_rows(fo_rows, value_input_option="RAW")
    print(f"FoAssessment: +{len(fo_rows)} rows")

    # --- SelfAssessment (weeks 3, 5, 8) ---------------------------------------
    self_rows = []
    for s in STUDENTS:
        if s["group"] == GROUP_J:
            stamps = [ts(J_DATES[2], "07:45", "μ.μ."), ts(J_DATES[4], "07:45", "μ.μ."),
                      ts(J_DATES[7], "07:45", "μ.μ.")]
        else:
            stamps = [ts(A_DATES[2], "06:30", "μ.μ."), ts(A_DATES[4], "06:30", "μ.μ."),
                      ts(A_DATES[7], "06:30", "μ.μ.")]
        for n, (stamp, (feel, diff, enjoy)) in enumerate(zip(stamps, SELF[s["id"]])):
            fo_idx = [2, 4, 7][n]  # weeks 3, 5, 8 -> matching formative session
            self_rows.append([stamp, s["id"], feel, diff, enjoy,
                              *gen_self_fields(s["id"], s["arc"][fo_idx], fo_idx)])
    gc.open("SelfAssessment").sheet1.append_rows(self_rows, value_input_option="RAW")
    print(f"SelfAssessment: +{len(self_rows)} rows")

    # --- PostAssessment --------------------------------------------------------
    post_rows = []
    for s in STUDENTS:
        stamp = (ts("19/10/2026", "08:30", "μ.μ.") if s["group"] == GROUP_J
                 else ts("18/10/2026", "08:00", "μ.μ."))
        post_rows.append([stamp, s["id"], *POST[s["id"]], *gen_post_fields(s["id"])])
    gc.open("PostAssessment").sheet1.append_rows(post_rows, value_input_option="RAW")
    print(f"PostAssessment: +{len(post_rows)} rows")

    # --- LessonAssessment ------------------------------------------------------
    gc.open("LessonAssessment").sheet1.append_rows(LESSON_ROWS, value_input_option="RAW")
    print(f"LessonAssessment: +{len(LESSON_ROWS)} rows")

    # --- ReportsFile (3 sample English reports for ASK ME) ----------------------
    gc.open("ReportsFile").sheet1.append_rows(REPORTS_ROWS, value_input_option="RAW")
    print(f"ReportsFile: +{len(REPORTS_ROWS)} rows")

    print("\nDONE. Seeded 12 demo students (demo01..demo12):")
    for s in STUDENTS:
        print(f"  {s['id']}  {s['group']}  {s['profile']}")


if __name__ == "__main__":
    main()
