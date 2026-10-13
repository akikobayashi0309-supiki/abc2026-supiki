#!/usr/bin/env bash
# =============================================================
# GitHub Actions -> Google Cloud via Workload Identity Federation
# (no service account keys). Run after bootstrap.sh.
#
# Usage (Cloud Shell):
#   PROJECT_ID=my-team-abc2026 \
#   GITHUB_REPO=owner/repo \
#   bash github-wif.sh
# =============================================================
set -euo pipefail

# ---- Values (override with environment variables) ----------
PROJECT_ID="${PROJECT_ID:-abc2026-yourteam}"
GITHUB_REPO="${GITHUB_REPO:-owner/repo}"                     # Only this repository may deploy
POOL_ID="${POOL_ID:-github}"
PROVIDER_ID="${PROVIDER_ID:-github-actions}"
DEPLOY_SA_NAME="${DEPLOY_SA_NAME:-github-deployer}"
# ------------------------------------------------------------

echo "==> 0/5 Preflight checks"
fail=0
if [[ "$PROJECT_ID" == "abc2026-yourteam" ]]; then
  echo "    ERROR: PROJECT_ID is still the placeholder."
  fail=1
fi
if [[ "$GITHUB_REPO" == "owner/repo" || ! "$GITHUB_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "    ERROR: GITHUB_REPO must be set as <owner>/<repo>."
  fail=1
fi
if [[ $fail -ne 0 ]]; then
  echo "    Fix the values above and re-run. Nothing was changed."
  exit 1
fi
gcloud config set project "$PROJECT_ID"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
DEPLOY_SA="${DEPLOY_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="app-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
echo "    OK: project=${PROJECT_ID} (${PROJECT_NUMBER}) repo=${GITHUB_REPO}"

echo "==> 1/5 Create deployer service account"
if gcloud iam service-accounts describe "$DEPLOY_SA" >/dev/null 2>&1; then
  echo "    Service account already exists, skipping."
else
  gcloud iam service-accounts create "$DEPLOY_SA_NAME" --display-name="GitHub Actions deployer"
  sleep 15  # wait for IAM propagation
fi

echo "==> 2/5 Grant deploy roles"
# Cloud Run deploy, image push, Firebase Hosting + Firestore rules deploy
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.writer \
  roles/firebasehosting.admin \
  roles/firebaserules.admin \
  roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOY_SA}" \
    --role="$ROLE" --condition=None >/dev/null
  echo "    Granted $ROLE to ${DEPLOY_SA_NAME}"
done

# Allow the deployer to run Cloud Run as app-runtime (and nothing else)
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/iam.serviceAccountUser" >/dev/null
echo "    Granted serviceAccountUser on app-runtime to ${DEPLOY_SA_NAME}"

echo "==> 3/5 Create Workload Identity pool"
if gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1; then
  echo "    Pool already exists, skipping."
else
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global --display-name="GitHub Actions"
fi

echo "==> 4/5 Create OIDC provider (restricted to ${GITHUB_REPO})"
if gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
    --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1; then
  echo "    Provider already exists, skipping."
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="GitHub Actions OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'"
fi

echo "==> 5/5 Allow the repository to impersonate the deployer"
POOL_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SA" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_REPO}" >/dev/null
echo "    Granted workloadIdentityUser to ${GITHUB_REPO}"

cat <<EOT

============================================================
Done. Set these GitHub repository variables
(Settings -> Secrets and variables -> Actions -> Variables):

  GCP_PROJECT_ID   = ${PROJECT_ID}
  GCP_WIF_PROVIDER = ${POOL_NAME}/providers/${PROVIDER_ID}
  GCP_DEPLOY_SA    = ${DEPLOY_SA}

Or with the gh CLI:
  gh variable set GCP_PROJECT_ID   --repo ${GITHUB_REPO} --body "${PROJECT_ID}"
  gh variable set GCP_WIF_PROVIDER --repo ${GITHUB_REPO} --body "${POOL_NAME}/providers/${PROVIDER_ID}"
  gh variable set GCP_DEPLOY_SA    --repo ${GITHUB_REPO} --body "${DEPLOY_SA}"
============================================================
EOT
