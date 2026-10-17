import {
  GoogleAuthProvider,
  linkWithPopup,
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  type User,
} from 'firebase/auth'
import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from 'react'
import {
  createJob,
  getBatch,
  getJob,
  type Job,
  type JobSummary,
  listJobs,
  listVideos,
  uploadVideo,
  type Video,
} from './api'
import { BatchView } from './BatchView'
import { auth } from './firebase'
import { JobView } from './JobView'

const AUTO = 'auto'

const EXAMPLES: Record<string, string[]> = {
  [AUTO]: [
    'A heartwarming friendship moment for families in the UAE',
    'The most chaotic, meme-able scene for Gen Z gamers in the US',
    'An emotional teaser for anime fans in Japan',
  ],
  'pepper-and-carrot': [
    'A TikTok of the potion contest climax for anime fans in Japan',
    'Instagram Reels of Pepper meeting her rivals for teens in South Korea',
    'A YouTube Shorts teaser of the funniest moment for families in Saudi Arabia',
  ],
  'tears-of-steel': [
    'Instagram Reels of the breakup on the bridge for anime fans in Japan',
    'A 20-second TikTok of the moment the simulation goes wrong, for teens in Indonesia',
    'A YouTube Shorts teaser of the robot attack for gamers in Brazil',
  ],
  sintel: [
    'A Reels clip of Sintel meeting the baby dragon for families in the UAE',
    'TikTok of the most emotional moment for anime fans in Japan',
    'A Shorts teaser of the dragon fight for young gamers in Thailand',
  ],
}

const COMPARE_EXAMPLE = 'A 30-second TikTok of the most exciting moment'

const MARKETS = [
  'Japan',
  'Saudi Arabia',
  'Brazil',
  'United States',
  'South Korea',
  'Indonesia',
  'Germany',
  'India',
]

const PENDING = new Set(['uploading', 'queued', 'processing', 'indexing'])

function formatDuration(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

const isActive = (j: { status: string }) => j.status === 'queued' || j.status === 'running'

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [videoId, setVideoId] = useState('pepper-and-carrot')
  const [prompt, setPrompt] = useState('')
  const [markets, setMarkets] = useState<string[]>([])
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [batch, setBatch] = useState<Job[] | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [upload, setUpload] = useState<number | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  // Guest mode: sign in anonymously so judges can try the app without an account.
  useEffect(
    () =>
      onAuthStateChanged(auth, (u) => {
        if (u) setUser(u)
        else signInAnonymously(auth).catch((e: Error) => setError(e.message))
      }),
    [],
  )

  useEffect(() => {
    if (!user) return
    listVideos()
      .then(setVideos)
      .catch((e: Error) => setError(e.message))
    listJobs()
      .then(setJobs)
      .catch((e: Error) => setError(e.message))
  }, [user])

  // Refresh the library while an upload is being processed.
  const processing = videos.some((v) => PENDING.has(v.status))
  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => listVideos().then(setVideos).catch(() => {}), 4000)
    return () => clearInterval(timer)
  }, [processing])

  // Poll the open job or batch until it finishes.
  const activeJob = job && !batch && isActive(job) ? job.id : null
  const activeBatch = batch && batch.some(isActive) ? batch[0].batchId : null
  useEffect(() => {
    if (!activeJob && !activeBatch) return
    const timer = setInterval(async () => {
      try {
        if (activeBatch) {
          const next = await getBatch(activeBatch)
          setBatch(next)
          if (!next.some(isActive)) setJobs(await listJobs())
        } else if (activeJob) {
          const next = await getJob(activeJob)
          setJob(next)
          if (!isActive(next)) setJobs(await listJobs())
        }
      } catch (e) {
        setError((e as Error).message)
      }
    }, 2500)
    return () => clearInterval(timer)
  }, [activeJob, activeBatch])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const res = await createJob(videoId, prompt, markets.length >= 2 ? markets : [])
      if (res.batchId) {
        setJob(null)
        setBatch(await getBatch(res.batchId))
      } else {
        setBatch(null)
        setJob(await getJob(res.id))
      }
      setJobs(await listJobs())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  async function openJob(summary: JobSummary) {
    setError('')
    try {
      if (summary.batchId) {
        setJob(null)
        setBatch(await getBatch(summary.batchId))
      } else {
        setBatch(null)
        setJob(await getJob(summary.id))
      }
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function openBatchMember(id: string) {
    setBatch(null)
    setJob(await getJob(id))
  }

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError('')
    setUpload(0)
    try {
      const id = await uploadVideo(file, setUpload)
      setVideos(await listVideos())
      setVideoId(id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUpload(null)
    }
  }

  function toggleMarket(m: string) {
    setMarkets((cur) =>
      cur.includes(m) ? cur.filter((x) => x !== m) : cur.length < 4 ? [...cur, m] : cur,
    )
  }

  async function signInWithGoogle() {
    const provider = new GoogleAuthProvider()
    try {
      // Upgrade the guest account so its history is kept.
      if (user?.isAnonymous) await linkWithPopup(user, provider)
      else await signInWithPopup(auth, provider)
      setUser(auth.currentUser)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const selected = videos.find((v) => v.id === videoId)
  const selectable = videoId === AUTO || selected?.status === 'ready'
  const comparing = markets.length >= 2
  const busy = submitting || activeJob !== null || activeBatch !== null
  const examples = comparing
    ? [COMPARE_EXAMPLE]
    : (EXAMPLES[videoId] ?? ['A 30-second teaser of the best moment for fans in Japan'])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">▶</span>
          <div>
            <strong>ClipVoyage</strong>
            <small>Global promo clip agent</small>
          </div>
        </div>
        <div className="account">
          <span>{user?.isAnonymous ? 'Guest mode' : user?.email}</span>
          {user?.isAnonymous && (
            <button type="button" className="ghost" onClick={signInWithGoogle}>
              Sign in with Google
            </button>
          )}
        </div>
      </header>

      <main className="layout">
        <section className="panel compose">
          <h1>One request. A localized, trend-aware, culture-checked short.</h1>
          <p className="muted">
            Pick a video or upload your own, describe the clip and the market. Gemini researches
            what is trending, finds the scene, cuts a vertical clip, subtitles it, checks it for
            cultural risks and drafts the post.
          </p>

          <form onSubmit={onSubmit}>
            <h2>1. Source</h2>
            <div className="videos">
              <button
                type="button"
                className={`video auto ${videoId === AUTO ? 'selected' : ''}`}
                onClick={() => setVideoId(AUTO)}
              >
                <span className="auto-art">✦</span>
                <span className="video-title">Agent picks</span>
                <span className="video-synopsis">Search every video for the best scene</span>
              </button>
              {videos.map((v) => (
                <button
                  type="button"
                  key={v.id}
                  className={`video ${v.id === videoId ? 'selected' : ''}`}
                  onClick={() => setVideoId(v.id)}
                  disabled={v.status === 'failed'}
                  title={v.error ?? v.synopsis}
                >
                  {v.posterUrl ? (
                    <img src={v.posterUrl} alt="" />
                  ) : (
                    <span className="auto-art">{v.status === 'failed' ? '✕' : '…'}</span>
                  )}
                  <span className="video-title">
                    {v.title} {v.duration > 0 && <small>{formatDuration(v.duration)}</small>}
                  </span>
                  <span className="video-synopsis">
                    {v.status === 'ready'
                      ? v.synopsis || v.credit
                      : v.status === 'failed'
                        ? (v.error ?? 'Failed')
                        : `${v.status}…`}
                  </span>
                </button>
              ))}
              <button
                type="button"
                className="video upload"
                onClick={() => fileInput.current?.click()}
                disabled={upload !== null}
              >
                <span className="auto-art">{upload === null ? '＋' : `${Math.round(upload * 100)}%`}</span>
                <span className="video-title">Upload your video</span>
                <span className="video-synopsis">MP4, MOV or WebM · up to 15 min · kept 7 days</span>
              </button>
              <input
                ref={fileInput}
                type="file"
                accept="video/mp4,video/quicktime,video/webm"
                hidden
                onChange={onFile}
              />
            </div>

            <h2>2. Request</h2>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                comparing
                  ? 'Describe the clip; the markets below are added for you'
                  : 'e.g. A TikTok of the potion contest climax for anime fans in Japan'
              }
              rows={3}
            />
            <div className="chips">
              {examples.map((ex) => (
                <button type="button" key={ex} className="chip" onClick={() => setPrompt(ex)}>
                  {ex}
                </button>
              ))}
            </div>

            <h2>3. Compare markets (optional, pick 2–4)</h2>
            <div className="chips markets">
              {MARKETS.map((m) => (
                <button
                  type="button"
                  key={m}
                  className={`chip ${markets.includes(m) ? 'on' : ''}`}
                  onClick={() => toggleMarket(m)}
                >
                  {m}
                </button>
              ))}
            </div>

            <button
              type="submit"
              className="primary"
              disabled={!user || busy || !selectable || prompt.trim().length < 3}
            >
              {busy
                ? 'Agent is working…'
                : comparing
                  ? `Run agent for ${markets.length} markets`
                  : 'Run agent'}
            </button>
          </form>

          {error && <p className="error">{error}</p>}

          {jobs.length > 0 && (
            <>
              <h2>History</h2>
              <ul className="history">
                {jobs.map((j) => (
                  <li key={j.id}>
                    <button
                      type="button"
                      className={j.id === job?.id || (j.batchId && j.batchId === batch?.[0]?.batchId) ? 'active' : ''}
                      onClick={() => openJob(j)}
                    >
                      <span className={`dot ${j.status}`} />
                      <span className="history-text">
                        <strong>{j.videoTitle}</strong>
                        {j.market && <em> · {j.market}</em>} {j.request}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="panel result">
          {batch ? (
            <BatchView jobs={batch} onOpen={openBatchMember} />
          ) : job ? (
            <JobView job={job} />
          ) : (
            <div className="empty">
              <p>Your clip, trends, cultural review and post will appear here.</p>
            </div>
          )}
        </section>
      </main>

      <footer className="credits">
        {videos
          .filter((v) => !v.uploaded)
          .map((v) => (
            <span key={v.id}>
              {v.title}: {v.credit}
            </span>
          ))}
        <span>Built with Gemini on Vertex AI, Cloud Run, Firestore and Firebase.</span>
      </footer>
    </div>
  )
}

export default App
