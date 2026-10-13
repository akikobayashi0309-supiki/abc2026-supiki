# AI Builder Cup 2026

> Project name and pitch TBD. This repository currently contains the end-to-end foundation:
> Firebase Hosting -> Cloud Run -> Gemini (Vertex AI) -> Firestore.

**Live demo:** https://abc2026-supiki.web.app (guest mode: no sign-up required)

## Architecture

```
Browser (React)
  │  Firebase Auth: Google sign-in or anonymous guest
  ▼
Firebase Hosting ── /api/** rewrite ──▶ Cloud Run (FastAPI, asia-northeast1)
                                          │  verifies Firebase ID token
                                          ├──▶ Gemini on Vertex AI (global endpoint)
                                          └──▶ Firestore (Native mode)
```

## How we use Google Cloud

| Service | Usage |
|---|---|
| **Firebase** | Hosting serves the React app and routes `/api/**` to Cloud Run on the same origin. Auth provides Google sign-in plus anonymous guest mode so judges can try the app instantly. |
| **Firestore** | Stores each user's generations (`generations` collection). Only the backend accesses it; client access is denied by security rules. |
| **Cloud Run** | Hosts the FastAPI backend. It runs as a dedicated least-privilege service account and calls Gemini and Firestore with no API keys. |
| **Gemini** | Called through Vertex AI with the `google-genai` SDK. *(Core feature description TBD.)* |

## Repository layout

```
backend/    FastAPI app, tests, Dockerfile
frontend/   Vite + React + TypeScript app
infra/      bootstrap.sh (project setup), github-wif.sh (CI auth)
.github/    CI and deploy workflows
```

## Getting started

### 1. Google Cloud setup (once)
```bash
# Cloud Shell
PROJECT_ID=<id> BILLING_ACCOUNT_ID=<id> TEAMMATE_EMAIL=<email> bash infra/bootstrap.sh
PROJECT_ID=<id> GITHUB_REPO=<owner>/<repo> bash infra/github-wif.sh
```
Then in the Firebase console: add Firebase to the project, enable **Google** and **Anonymous** sign-in, and register a web app. Put its config into `frontend/.env.production` / `.env.development`, and the project ID into `.firebaserc`.

Set the repository variables printed by `github-wif.sh`: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`.

### 2. Local development
```bash
gcloud auth application-default login

cd backend && uv sync
GOOGLE_CLOUD_PROJECT=<id> uv run uvicorn app.main:app --reload --port 8080

cd frontend && npm ci && npm run dev   # http://localhost:5173
```

### 3. Deploy
Push to `main`. GitHub Actions builds the backend image, deploys it to Cloud Run, then deploys Firebase Hosting and Firestore rules, authenticating via Workload Identity Federation (no keys).

## API

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/healthz` | none | Health check |
| POST | `/api/generate` | Firebase ID token | `{ "prompt": "..." }` -> Gemini output, saved to Firestore |
| GET | `/api/generations` | Firebase ID token | The caller's recent generations |

## License

MIT
