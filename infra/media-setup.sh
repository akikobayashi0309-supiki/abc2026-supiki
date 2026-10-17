#!/usr/bin/env bash
# =============================================================
# Media bucket + Creative Commons source films for the promo agent.
# Run once after bootstrap.sh (Cloud Shell or any machine with gcloud + ffmpeg).
#
# Usage:
#   PROJECT_ID=my-team-abc2026 bash media-setup.sh
# =============================================================
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-abc2026-yourteam}"
REGION="${REGION:-asia-northeast1}"
WORKDIR="${WORKDIR:-$HOME/abc2026-media}"

if [[ "$PROJECT_ID" == "abc2026-yourteam" ]]; then
  echo "ERROR: set PROJECT_ID. Nothing was changed."
  exit 1
fi
BUCKET="${PROJECT_ID}-media"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
RUNTIME_SA="app-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> 1/4 Create bucket gs://${BUCKET}"
if gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "    Bucket already exists, skipping."
else
  gcloud storage buckets create "gs://${BUCKET}" --project="$PROJECT_ID" \
    --location="$REGION" --uniform-bucket-level-access --public-access-prevention
fi

echo "==> 2/4 Grant access"
# Backend reads sources and writes outputs
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/storage.objectAdmin" >/dev/null
# Backend signs short-lived URLs through the IAM API
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" --project="$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/iam.serviceAccountTokenCreator" >/dev/null
# Gemini on Vertex AI reads gs:// video inputs as the Vertex AI service agent
gcloud beta services identity create --service=aiplatform.googleapis.com --project="$PROJECT_ID" >/dev/null 2>&1 || true
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer" >/dev/null
echo "    Done."

echo "==> 3/4 Download and prepare Creative Commons films (Blender Foundation, CC BY 3.0)"
command -v ffmpeg >/dev/null || sudo apt-get install -y ffmpeg >/dev/null
mkdir -p "$WORKDIR" && cd "$WORKDIR"
if [[ ! -f tears-of-steel.mp4 ]]; then
  curl -fL -o tos.mov https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov
  ffmpeg -v error -y -i tos.mov -map 0:v:0 -map 0:a:0 -c:v copy -c:a aac -ac 2 -b:a 128k \
    -movflags +faststart tears-of-steel.mp4
fi
if [[ ! -f sintel.mp4 ]]; then
  curl -fL -o sintel.zip https://download.blender.org/durian/movies/Sintel.2010.720p.mkv.zip
  unzip -o -q sintel.zip
  ffmpeg -v error -y -i Sintel.2010.720p.mkv -map 0:v:0 -map 0:a:0 -c:v copy -c:a aac -ac 2 \
    -b:a 128k -movflags +faststart sintel.mp4
fi

echo "==> 4/4 Upload to gs://${BUCKET}/library/"
gcloud storage cp tears-of-steel.mp4 sintel.mp4 "gs://${BUCKET}/library/" --project="$PROJECT_ID"
echo "Done."
