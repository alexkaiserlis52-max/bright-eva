# Bright E.V.A. → Google Cloud Run (οδηγός deploy)

## Γρήγορος τρόπος (συνιστάται): `deploy.ps1`

Το script κάνει ΟΛΑ αυτόματα: auth check, ενεργοποίηση APIs, Secret με το
service-account JSON, IAM binding, deploy, και στήσιμο του `OPENROUTER_SITE_URL`.

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

**Προαπαιτούμενα (μία φορά):**

1. Εγκατάσταση Google Cloud SDK:
   ```powershell
   winget install -e --id Google.CloudSDK
   ```
   (ή installer από https://cloud.google.com/sdk/docs/install)
2. Άνοιξε **νέο** PowerShell (για να φορτώσει το PATH) και τρέξε το script.
   Στην πρώτη εκτέλεση θα ανοίξει browser για `gcloud auth login`.
3. Το project `insudies` πρέπει να έχει ενεργό billing (αλλιώς το deploy
   θα αποτύχει με μήνυμα για billing — ενεργοποιείται από
   https://console.cloud.google.com/billing).

**Τι κάνει το script βήμα-βήμα:**

| Βήμα | Ενέργεια |
|---|---|
| 1 | Διαβάζει τα μυστικά από το `.env` (OPENROUTER_API_KEY, MODEL, FLASK_SECRET_KEY, APP_PASSWORD) |
| 2 | `gcloud auth login` (browser, μόνο αν δεν είσαι ήδη συνδεδεμένος) + `config set project insudies` |
| 3 | Ενεργοποιεί `run`, `artifactregistry`, `cloudbuild`, `secretmanager` APIs |
| 4 | Δημιουργεί/ενημερώνει το Secret `eva-service-account` από το `insudies-e24d0d9618d5.json` |
| 5 | Δίνει στον Cloud Run runtime service account ρόλο `secretmanager.secretAccessor` |
| 6 | `gcloud run deploy bright-eva --source . --region europe-west1 --allow-unauthenticated` |
| 7 | Θέτει `OPENROUTER_SITE_URL` στο πραγματικό URL του service |

> ⚠️ `--allow-unauthenticated` σημαίνει «δημόσιο URL» — γι' αυτό το
> `APP_PASSWORD` στο `.env` είναι **υποχρεωτικό**. Το `FLASK_DEBUG=0`
> μπαίνει αυτόματα στο cloud (secure session cookie).

## Χειροκίνητος τρόπος (ισοδύναμος)

```powershell
gcloud auth login
gcloud config set project insudies
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

gcloud secrets create eva-service-account --data-file=insudies-e24d0d9618d5.json

gcloud run deploy bright-eva `
  --source . `
  --region europe-west1 `
  --allow-unauthenticated `
  --set-env-vars "OPENROUTER_API_KEY=...,OPENROUTER_MODEL=openai/gpt-4o-mini,FLASK_SECRET_KEY=...,APP_PASSWORD=...,FLASK_DEBUG=0" `
  --set-secrets "GOOGLE_SERVICE_ACCOUNT_JSON=eva-service-account:latest"
```

## Env vars

| Μεταβλητή | Περιγραφή |
|---|---|
| `OPENROUTER_API_KEY` | Το OpenRouter key |
| `OPENROUTER_MODEL` | Default μοντέλο (αλλάζει και από το UI) |
| `OPENROUTER_SITE_URL` | Το δημόσιο URL (το θέτει αυτόματα το script) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Ως Secret `eva-service-account` |
| `FLASK_SECRET_KEY` | Μακρύ τυχαίο string (sessions) |
| `APP_PASSWORD` | Κωδικός εισόδου στην εφαρμογή |
| `FLASK_DEBUG` | `0` στο cloud |

## Updates

Κάθε αλλαγή στον κώδικα: ξανατρέχεις `.\deploy.ps1`.
Το κόστος με scale-to-zero είναι ~0€ όταν δεν χρησιμοποιείται.
