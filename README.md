# ClipVoyage — Global Promo Clip Agent

> **One request in, a localized and culture-checked short out.**
> "Make a 20-second TikTok of the robot attack for gamers in Brazil" → ClipVoyage finds the scene, cuts a vertical clip, subtitles it in Brazilian Portuguese, reviews it for cultural risks in Brazil, and drafts the post and cover image.

**Live demo:** https://abc2026-supiki.web.app (guest mode — no sign-up required)

## The problem

Game and anime publishers reuse memorable scenes from their titles for trailers and social posts in dozens of markets. Tools such as Bandai Namco's *ClipSearch* (built with Gemini) already make it fast to **find** a scene in hours of footage. Everything after that is still manual, and it is repeated for every market:

1. Cut the moment and reformat it to 9:16 for TikTok, Reels or Shorts
2. Transcribe the dialogue and translate it for each market
3. Check the clip for cultural and regulatory risks: gestures, religion, violence and weapons, symbols, colors and numbers, slang
4. Write a local caption and hashtags, and make a cover image

ClipVoyage automates the steps that come **after** search, so a marketer can go from an idea to a localized, reviewed draft in about a minute.

## How it works

```
Request ─▶ 1 Plan ─▶ 2 Search ─▶ 3 Cut ─▶ 4 Subtitles ─▶ 5 Cultural check ─▶ 6 Render ─▶ 7 Assets
           Gemini     Gemini      ffmpeg    Gemini           Gemini               ffmpeg      ffmpeg + Gemini image
```

| Step | What happens | Model |
|---|---|---|
| Plan | Turns the free-text request into a brief: market, language, platform, length, tone | `gemini-4-argon` |
| Search | Picks the best moment from a scene index of the film (start, end, dialogue, characters, mood). The index is built once per film from the video itself, then cached in Firestore | `gemini-3.8-flash` (index), `gemini-4-argon` (selection) |
| Cut | Cuts the moment and converts it to 9:16 over a blurred background | ffmpeg on Cloud Run |
| Subtitles | Transcribes each spoken line from the clip with timings and translates it for the market | `gemini-3.8-flash` (video input) |
| Cultural check | Watches the clip with its subtitles and reports market-specific risks with time, severity and a fix. It rewrites subtitle lines that need it, writes the caption and hashtags, and picks the thumbnail frame | `gemini-4-argon` (video input) |
| Render | Burns the reviewed subtitles into the clip (Noto fonts for Latin, CJK, Arabic, Thai, and more) | ffmpeg |
| Assets | Exports the chosen keyframe and generates a localized 9:16 cover with the title in the local language | `gemini-3.1-flash-image` |

Every step reports its progress, so the UI shows the agent working in real time. If an optional step fails (for example, thumbnail generation), the job still delivers the clip.

## How we use Google Cloud

| Service | Usage |
|---|---|
| **Gemini (Vertex AI)** | The core of the agent. It plans the brief, understands video to build the scene index and transcribe dialogue, selects the scene, translates, reviews cultural risk from the video and subtitles together, and generates the cover image. All calls use structured JSON output (Pydantic schemas) through the `google-genai` SDK on the global endpoint, with no API keys. |
| **Cloud Run** | Hosts the FastAPI backend and the ffmpeg media pipeline. Jobs run in the background (CPU always allocated), and the service runs as a least-privilege service account. |
| **Firestore** | Stores job state and per-step progress (`users/{uid}/jobs`), which the UI polls, and caches each film's scene index (`library/{videoId}`) so search is fast after the first run. |
| **Firebase** | Hosting serves the React app and routes `/api/**` to Cloud Run on the same origin. Authentication provides Google sign-in and anonymous guest mode, so judges can try the app instantly. |
| **Cloud Storage** | Source films and generated outputs, delivered to the browser through short-lived signed URLs. |

CI/CD: GitHub Actions deploys Cloud Run and Firebase Hosting on every push to `main`, using Workload Identity Federation (no service account keys).

## Architecture

```
Browser (React, Firebase Auth: Google or guest)
  │
  ▼
Firebase Hosting ── /api/** ──▶ Cloud Run (FastAPI + ffmpeg)
                                  │ verifies Firebase ID token
                                  ├──▶ Gemini on Vertex AI (global): plan, index, search, subtitles, review, image
                                  ├──▶ Cloud Storage: library/ (sources), outputs/ (clips, images)
                                  └──▶ Firestore: jobs + progress, scene index cache
```

## Repository layout

```
backend/    FastAPI app: pipeline.py (agent steps), gemini.py, media.py (ffmpeg + GCS), store.py, tests
frontend/   Vite + React + TypeScript UI
infra/      bootstrap.sh (project), github-wif.sh (CI auth), media-setup.sh (bucket + source films)
.github/    CI and deploy workflows
```

## Run it yourself

```bash
# Google Cloud setup (once, e.g. in Cloud Shell)
PROJECT_ID=<id> BILLING_ACCOUNT_ID=<id> TEAMMATE_EMAIL=<email> bash infra/bootstrap.sh
PROJECT_ID=<id> GITHUB_REPO=<owner>/<repo> bash infra/github-wif.sh
PROJECT_ID=<id> bash infra/media-setup.sh
```

In the Firebase console, add Firebase to the project, enable **Google** and **Anonymous** sign-in, and register a web app. Put its config in `frontend/.env.*` and the project ID in `.firebaserc`. Then set the repository variables printed by `github-wif.sh` and push to `main`.

Local development:

```bash
gcloud auth application-default login
cd backend && uv sync && uv run pytest
cd frontend && npm ci && npm run dev   # proxies /api to localhost:8080
```

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/healthz` | Health check (no auth) |
| GET | `/api/library` | Available source films |
| POST | `/api/jobs` | `{ "videoId", "request" }` → starts the agent (one active job per user) |
| GET | `/api/jobs` | The caller's recent jobs |
| GET | `/api/jobs/{id}` | Job progress and results, with signed URLs for outputs |

All endpoints except `/api/healthz` require a Firebase ID token.

## Credits

Source footage is from Blender Foundation open movies, used under Creative Commons Attribution 3.0:

- *Tears of Steel* — (CC) Blender Foundation | mango.blender.org
- *Sintel* — (CC) Blender Foundation | durian.blender.org

## License

MIT
