# Agent rules

Shared rules for all AI coding tools (Claude Code imports this via `CLAUDE.md`; Antigravity reads it directly).

## Language
- **Everything in English**: code, comments, docs, commit messages, PR titles/descriptions, UI text.
- This is a public repository for the Google Cloud AI Builder Cup 2026. Only code written during the contest belongs here.

## Stack
| Layer | Tech | Location |
|---|---|---|
| Frontend | Vite + React + TypeScript, Firebase Auth (Google + anonymous) | `frontend/` |
| Hosting | Firebase Hosting; `/api/**` is rewritten to Cloud Run | `firebase.json` |
| Backend | Python 3.12 + FastAPI on Cloud Run (`asia-northeast1`, service `api`) | `backend/` |
| AI | Gemini via Vertex AI (`google-genai`, `location="global"`) | `backend/app/gemini.py` |
| Database | Firestore (Native mode), accessed only by the backend | `backend/app/store.py` |
| Infra | gcloud scripts | `infra/` |
| CI/CD | GitHub Actions + Workload Identity Federation | `.github/workflows/` |

## Security
- **No API keys or service account keys.** The backend authenticates with Application Default Credentials as `app-runtime@<PROJECT_ID>.iam.gserviceaccount.com`; CI uses Workload Identity Federation.
- Every backend endpoint except `/api/healthz` must depend on `get_current_user` (Firebase ID token verification).
- Clients never access Firestore directly (`firestore.rules` denies everything).
- The Firebase web config in `frontend/.env.*` is public by design; never put real secrets there.

## Commands
```bash
# Backend (requires uv)
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .
GOOGLE_CLOUD_PROJECT=<PROJECT_ID> uv run uvicorn app.main:app --reload --port 8080

# Frontend (Node 24, see frontend/.nvmrc)
cd frontend
npm ci
npm run dev     # proxies /api to localhost:8080
npm run lint
npm run build
```

## Conventions
- Backend: routes live under `/api/*`; external services are wrapped in small classes exposed via FastAPI dependencies (`get_gemini`, `get_store`) so tests can override them. Never call Gemini or Firestore in tests.
- Firestore collections: lowerCamelCase plural (`generations`); fields: lowerCamelCase.
- The Hosting -> Cloud Run rewrite times out after 60 s. Long-running work (e.g. video analysis) must be asynchronous: create a job document, process it, and let the client poll.
- Config comes from environment variables (`backend/app/config.py`), not hard-coded values.

## Ownership and workflow
- Claude Code: `backend/`, `infra/`, `.github/`, tests.
- Antigravity: `frontend/` UI and in-browser verification.
- Work on short-lived branches (or separate git worktrees) and merge small PRs often. Propose a plan before implementing non-trivial changes.
- `main` deploys automatically (backend first, then frontend). Keep it green.
