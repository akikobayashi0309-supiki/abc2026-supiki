# ClipVoyage — Global Promo Clip Agent

> **One request in, a localized, trend-aware and culture-checked short out.**
> "A TikTok of the potion contest climax for anime fans in Japan" → ClipVoyage researches what is trending in Japan right now, finds the scene, cuts a vertical clip, subtitles it in Japanese, reviews it for cultural risks, and drafts the post and cover image. Pick several markets and it compares them side by side on the same scene.

**Live demo:** https://abc2026-supiki.web.app (guest mode — no sign-up required)

## The problem

Game and anime publishers reuse memorable scenes from their titles for trailers and social posts in dozens of markets. Tools such as Bandai Namco's *ClipSearch* (built with Gemini) already make it fast to **find** a scene in hours of footage. Everything after that is still manual, and it is repeated for every market:

1. Cut the moment and reformat it to 9:16 for TikTok, Reels or Shorts
2. Transcribe the dialogue and translate it for each market
3. Check the clip for cultural and regulatory risks: gestures, religion, violence and weapons, symbols, colors and numbers, slang
4. Write a local caption and hashtags, and make a cover image

ClipVoyage automates the steps that come **after** search, so a marketer can go from an idea to a localized, reviewed draft in a few minutes, for any footage they upload.

## How it works

```
Request ─▶ Plan ─▶ Trends ─▶ Search ─▶ Subtitles ─▶ Cut ─▶ Cultural check ─▶ Render ─▶ Assets
           Gemini   Gemini +   Gemini    Gemini       ffmpeg   Gemini            ffmpeg     ffmpeg +
                    Google                                                                  Gemini image
                    Search
```

| Step | What happens | Model |
|---|---|---|
| Plan | Turns the free-text request into a brief: market, language, platform, length, tone | `gemini-4-argon` |
| Trends | Researches what is trending right now on the platform in the target market (seasonal topics, formats, hooks, hashtags) with Google Search grounding, and shows the sources | `gemini-4-argon` + Google Search |
| Search | Picks the best moment from a scene index (start, end, dialogue, characters, mood), favoring what fits current trends. The index is built once per video from the video itself and cached in Firestore. With **Agent picks**, it searches every video in the library | `gemini-4-argon` (video + text) |
| Cut | Cuts the moment and converts it to 9:16 over a blurred background | ffmpeg on Cloud Run |
| Subtitles | Transcribes each spoken line around the scene with timings, snaps the clip onto real dialogue, and translates it for the market | `gemini-4-argon` (video input) |
| Cultural check | Watches the clip with its subtitles and reports market-specific risks with time, severity and a fix. It rewrites subtitle lines that need it, writes the caption and hashtags, and picks the thumbnail frame | `gemini-4-argon` (video input) |
| Render | Burns the reviewed subtitles into the clip (Noto fonts for Latin, CJK, Arabic, Thai, and more) | ffmpeg |
| Assets | Exports the chosen keyframe and generates a localized 9:16 cover with the title in the local language | `gemini-nano-banana-2.1` |

Every step uses the latest Gemini model and falls back automatically to a stable model (`gemini-3.8-flash`, `gemini-3.1-flash-image`) on quota or availability errors; the UI shows which model served each step. Every step reports its progress, so the UI shows the agent working in real time. If an optional step fails (for example, thumbnail generation), the job still delivers the clip.

### More ways to use it

- **Upload your own footage**: MP4, MOV or WebM up to 15 minutes. The browser uploads straight to Cloud Storage with a signed URL; the backend validates, normalizes and indexes it. Uploads are deleted after 7 days.
- **Agent picks**: describe a topic ("a heartwarming friendship moment") and the agent chooses the video and the scene.
- **Compare markets**: choose 2-4 markets. All markets review the same scene, each with its own trends, subtitles, cultural review and post, shown side by side.

## How we use Google Cloud

| Service | Usage |
|---|---|
| **Gemini (Vertex AI)** | The core of the agent. It plans the brief, researches trends with Google Search grounding, understands video to build the scene index and transcribe dialogue, selects the scene, translates, reviews cultural risk from the video and subtitles together, and generates the cover image. Calls use structured JSON output (Pydantic schemas) through the `google-genai` SDK on the global endpoint, with no API keys. Every step runs on the latest model (`gemini-4-argon`, `gemini-nano-banana-2.1`) with automatic fallback to stable models. |
| **Cloud Run** | Hosts the FastAPI backend and the ffmpeg media pipeline. Jobs run in the background (CPU always allocated), and the service runs as a least-privilege service account. |
| **Firestore** | Stores job state and per-step progress (`users/{uid}/jobs`), which the UI polls, uploaded videos (`users/{uid}/videos`), and each video's cached scene index (`library/{videoId}`) so search is fast after the first run. |
| **Firebase** | Hosting serves the React app and routes `/api/**` to Cloud Run on the same origin. Authentication provides Google sign-in and anonymous guest mode, so judges can try the app instantly. |
| **Cloud Storage** | Source films, user uploads (direct browser upload via signed URLs) and generated outputs, delivered through short-lived signed URLs, with lifecycle rules that delete uploads after 7 days. |

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
| POST | `/api/uploads` | `{ "title", "contentType", "size" }` → signed upload URL |
| POST | `/api/uploads/{id}/complete` | Validates, normalizes and indexes the uploaded video |
| POST | `/api/jobs` | `{ "videoId" \| "auto", "request", "markets"? }` → starts the agent; 2-4 markets start a comparison batch |
| GET | `/api/batches/{id}` | All jobs of a market comparison |
| GET | `/api/jobs` | The caller's recent jobs |
| GET | `/api/jobs/{id}` | Job progress and results, with signed URLs for outputs |

All endpoints except `/api/healthz` require a Firebase ID token.

## Credits

Source footage is used under Creative Commons licenses:

- *Pepper&Carrot Motion Comic, Episode 6: The Potion Contest* — Morevna Project (morevnaproject.org), based on the webcomic *Pepper&Carrot* by David Revoy (peppercarrot.com). CC BY-SA 4.0. Clips generated from it are shared under the same license.
- *Tears of Steel* — (CC) Blender Foundation | mango.blender.org. CC BY 3.0.
- *Sintel* — (CC) Blender Foundation | durian.blender.org. CC BY 3.0.

## License

MIT
