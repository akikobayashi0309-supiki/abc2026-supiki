#!/usr/bin/env bash
# =============================================================
# AI Builder Cup 2026 - Google Cloud project bootstrap
# Stack: Firebase (Hosting/Auth) + Cloud Run + Firestore + Gemini (Vertex AI)
#
# Usage (Cloud Shell) - pass values as environment variables:
#   gcloud billing accounts list
#   PROJECT_ID=my-team-abc2026 \
#   BILLING_ACCOUNT_ID=XXXXXX-XXXXXX-XXXXXX \
#   TEAMMATE_EMAIL=friend@gmail.com \
#   bash bootstrap.sh
# =============================================================
set -euo pipefail

# ---- Values (override with environment variables) ----------
PROJECT_ID="${PROJECT_ID:-abc2026-yourteam}"                 # Globally unique, 6-30 chars, cannot be changed later
PROJECT_NAME="${PROJECT_NAME:-AI Builder Cup 2026}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-000000-000000-000000}"
TEAMMATE_EMAIL="${TEAMMATE_EMAIL:-teammate@gmail.com}"
REGION="${REGION:-asia-northeast1}"                          # Tokyo (asia-southeast1 = Singapore)
BUDGET_AMOUNT="${BUDGET_AMOUNT:-10000JPY}"                   # Currency must match the billing account
# ------------------------------------------------------------

echo "==> 0/8 Preflight checks"
fail=0
if [[ "$PROJECT_ID" == "abc2026-yourteam" ]]; then
  echo "    ERROR: PROJECT_ID is still the placeholder. Choose your own (default Firebase URL becomes <PROJECT_ID>.web.app)."
  fail=1
elif [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo "    ERROR: PROJECT_ID must be 6-30 chars, lowercase letters/digits/hyphens, start with a letter."
  fail=1
fi
if [[ "$BILLING_ACCOUNT_ID" == "000000-000000-000000" ]]; then
  echo "    ERROR: BILLING_ACCOUNT_ID is still the placeholder. Open billing accounts you can use:"
  gcloud billing accounts list --filter=open=true || true
  fail=1
fi
if [[ "$TEAMMATE_EMAIL" == "teammate@gmail.com" ]]; then
  echo "    ERROR: TEAMMATE_EMAIL is still the placeholder (it would grant Editor to a stranger)."
  fail=1
fi
if [[ $fail -ne 0 ]]; then
  echo "    Fix the values above and re-run. Nothing was changed."
  exit 1
fi
echo "    OK: project=${PROJECT_ID} billing=${BILLING_ACCOUNT_ID} teammate=${TEAMMATE_EMAIL}"

echo "==> 1/8 Create project"
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  echo "    Project $PROJECT_ID already exists, skipping."
else
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"
fi
gcloud config set project "$PROJECT_ID"

echo "==> 2/8 Link billing account"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID"

echo "==> 3/8 Enable APIs (takes 1-2 minutes)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  firebase.googleapis.com \
  firebasehosting.googleapis.com \
  identitytoolkit.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  billingbudgets.googleapis.com

echo "==> 4/8 Create Firestore database (Native mode)"
if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  echo "    Firestore (default) already exists, skipping."
else
  gcloud firestore databases create --location="$REGION" --type=firestore-native
fi

echo "==> 5/8 Create Artifact Registry repository"
if gcloud artifacts repositories describe app --location="$REGION" >/dev/null 2>&1; then
  echo "    Repository 'app' already exists, skipping."
else
  gcloud artifacts repositories create app \
    --repository-format=docker \
    --location="$REGION" \
    --description="Container images for Cloud Run"
fi

echo "==> 6/8 Create Cloud Run runtime service account"
RUNTIME_SA="app-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1; then
  echo "    Service account already exists, skipping."
else
  gcloud iam service-accounts create app-runtime --display-name="Cloud Run runtime"
  sleep 15  # wait for IAM propagation
fi

# Least-privilege roles for the backend: Gemini, Firestore, secrets, logs
for ROLE in \
  roles/aiplatform.user \
  roles/datastore.user \
  roles/secretmanager.secretAccessor \
  roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="$ROLE" --condition=None >/dev/null
  echo "    Granted $ROLE to app-runtime"
done

echo "==> 7/8 Grant build permissions and add teammate"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Needed for `gcloud run deploy --source .` on newer projects
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/cloudbuild.builds.builder" --condition=None >/dev/null
echo "    Granted Cloud Build builder role to default compute SA"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:${TEAMMATE_EMAIL}" \
  --role="roles/editor" --condition=None >/dev/null
echo "    Added ${TEAMMATE_EMAIL} as Editor"

echo "==> 8/8 Create budget alert (50% / 90% / 100%)"
# Note: re-running this step creates a duplicate budget
gcloud billing budgets create \
  --billing-account="$BILLING_ACCOUNT_ID" \
  --display-name="${PROJECT_ID}-budget" \
  --budget-amount="$BUDGET_AMOUNT" \
  --filter-projects="projects/${PROJECT_ID}" \
  --threshold-rule=percent=0.5 \
  --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0

cat <<EOF

============================================================
Done. Project: ${PROJECT_ID}  Region: ${REGION}

Manual steps remaining:
  1. Firebase console -> Add project -> select "${PROJECT_ID}"
  2. Firebase console -> Authentication -> enable Google sign-in
     and Anonymous sign-in (guest mode for judges)
  3. In the backend, call Gemini via Vertex AI with
     location="global" and the runtime SA (no API keys)
  4. Deploy Cloud Run with:
     --service-account=${RUNTIME_SA}
============================================================
EOF
