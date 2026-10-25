# ============================================================
# Bright E.V.A. → Google Cloud Run — one-command deploy
# Run from the project folder in PowerShell:
#     powershell -ExecutionPolicy Bypass -File .\deploy.ps1
# Prerequisites: Google Cloud SDK installed (https://cloud.google.com/sdk/docs/install)
# ============================================================
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$PROJECT = "insudies"
$REGION  = "europe-west1"
$SERVICE = "bright-eva"
$SECRET  = "eva-service-account"
$SA_FILE = "insudies-e24d0d9618d5.json"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ---------- 0. gcloud present? ----------
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "gcloud not found. Install Google Cloud SDK first:" -ForegroundColor Red
    Write-Host "  winget install -e --id Google.CloudSDK"
    Write-Host "  (then open a NEW PowerShell window and rerun this script)"
    exit 1
}

# ---------- 1. Read secrets from .env (never hardcoded here) ----------
Step "Reading .env"
$envVars = @{}
Get-Content .env | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq '' -or $line.StartsWith('#') -or $line -notmatch '=') { return }
    $k, $v = $line -split '=', 2
    $envVars[$k.Trim()] = $v.Trim()
}
foreach ($k in 'OPENROUTER_API_KEY','OPENROUTER_MODEL','FLASK_SECRET_KEY','APP_PASSWORD') {
    if (-not $envVars[$k]) { Write-Host "Missing $k in .env" -ForegroundColor Red; exit 1 }
}
Write-Host "OK: OPENROUTER_API_KEY, OPENROUTER_MODEL, FLASK_SECRET_KEY, APP_PASSWORD"

# ---------- 2. Auth + project ----------
Step "Google account"
# NOTE (PS 5.1): never redirect a native command's stderr (2>$null / 2>&1) —
# it wraps stderr in ErrorRecords (NativeCommandError) and kills the script.
$account = gcloud auth list --format="value(account)"
if (-not $account) {
    Write-Host "Opening browser for Google login..."
    gcloud auth login | Out-Host
    $account = gcloud auth list --format="value(account)"
}
Write-Host "Account: $account"
gcloud config set project $PROJECT | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "Could not set project $PROJECT (does it exist / billing enabled?)." -ForegroundColor Red; exit 1 }

# ---------- 3. Enable APIs ----------
Step "Enabling Google APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "Could not enable APIs - check that billing is active on project $PROJECT." -ForegroundColor Red; exit 1 }

# ---------- 4. Service-account JSON as a Secret ----------
Step "Secret: $SECRET"
$existing = gcloud secrets list --filter="name~$SECRET" --format="value(name)"
if ($existing) {
    gcloud secrets versions add $SECRET --data-file=$SA_FILE | Out-Host
    Write-Host "Secret exists - new version added."
} else {
    gcloud secrets create $SECRET --data-file=$SA_FILE | Out-Host
    Write-Host "Secret created."
}

# ---------- 5. Let Cloud Run read the secret ----------
Step "IAM: secret accessor for Cloud Run runtime"
$PROJECT_NUMBER = gcloud projects describe $PROJECT --format="value(projectNumber)"
$RUNTIME_SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding $SECRET --member="serviceAccount:$RUNTIME_SA" --role="roles/secretmanager.secretAccessor" | Out-Host
# Cloud Build now builds as the default compute SA — it needs builder + storage rights.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$RUNTIME_SA" --role="roles/cloudbuild.builds.builder" | Out-Host
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$RUNTIME_SA" --role="roles/storage.objectAdmin" | Out-Host

# ---------- 6. Deploy (builds from source via Cloud Build) ----------
Step "Deploying $SERVICE to $REGION (first build takes a few minutes)"
$ENV_STRING = "OPENROUTER_API_KEY=$($envVars['OPENROUTER_API_KEY']),OPENROUTER_MODEL=$($envVars['OPENROUTER_MODEL']),FLASK_SECRET_KEY=$($envVars['FLASK_SECRET_KEY']),APP_PASSWORD=$($envVars['APP_PASSWORD']),FLASK_DEBUG=0"
gcloud run deploy $SERVICE --source . --region $REGION --allow-unauthenticated --set-env-vars $ENV_STRING --set-secrets "GOOGLE_SERVICE_ACCOUNT_JSON=${SECRET}:latest" | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed." -ForegroundColor Red; exit 1 }

# ---------- 7. Point OPENROUTER_SITE_URL at the real URL ----------
Step "Final touches"
$URL = gcloud run services describe $SERVICE --region $REGION --format="value(status.url)"
gcloud run services update $SERVICE --region $REGION --update-env-vars "OPENROUTER_SITE_URL=$URL" | Out-Host

Write-Host "`n============================================" -ForegroundColor Green
Write-Host " DEPLOYED: $URL" -ForegroundColor Green
Write-Host " Login password: (the APP_PASSWORD value in .env)" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
