import {
  GoogleAuthProvider,
  linkWithPopup,
  onAuthStateChanged,
  signInAnonymously,
  signInWithPopup,
  type User,
} from 'firebase/auth'
import { type FormEvent, useEffect, useState } from 'react'
import {
  createJob,
  getJob,
  type Job,
  type JobSummary,
  listJobs,
  listVideos,
  type Video,
} from './api'
import { auth } from './firebase'
import { JobView } from './JobView'

const EXAMPLES: Record<string, string[]> = {
  'tears-of-steel': [
    'A 20-second TikTok of the robot attack for gamers in Brazil',
    'Instagram Reels teaser of the most intense moment for fans in Saudi Arabia',
    'YouTube Shorts clip with the funniest line for viewers in Indonesia',
  ],
  sintel: [
    'A Reels clip of Sintel meeting the baby dragon for families in the UAE',
    'TikTok of the most emotional moment for anime fans in Japan',
    'A Shorts teaser of the dragon fight for young gamers in Thailand',
  ],
}

function formatDuration(seconds: number) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [videoId, setVideoId] = useState('tears-of-steel')
  const [prompt, setPrompt] = useState('')
  const [jobs, setJobs] = useState<JobSummary[]>([])
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

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

  // Poll the open job until it finishes.
  const activeId = job && (job.status === 'queued' || job.status === 'running') ? job.id : null
  useEffect(() => {
    if (!activeId) return
    const timer = setInterval(async () => {
      try {
        const next = await getJob(activeId)
        setJob(next)
        if (next.status === 'done' || next.status === 'failed') {
          setJobs(await listJobs())
        }
      } catch (e) {
        setError((e as Error).message)
      }
    }, 2000)
    return () => clearInterval(timer)
  }, [activeId])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const { id } = await createJob(videoId, prompt)
      setJob(await getJob(id))
      setJobs(await listJobs())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  async function openJob(id: string) {
    setError('')
    try {
      setJob(await getJob(id))
    } catch (err) {
      setError((err as Error).message)
    }
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

  const busy = submitting || activeId !== null

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
          <h1>One request. A localized, culture-checked short.</h1>
          <p className="muted">
            Pick a film, describe the clip you need and the market it is for. Gemini finds the
            scene, cuts a vertical clip, subtitles it in the local language, checks it for cultural
            risks and drafts the post.
          </p>

          <form onSubmit={onSubmit}>
            <h2>1. Source</h2>
            <div className="videos">
              {videos.map((v) => (
                <button
                  type="button"
                  key={v.id}
                  className={`video ${v.id === videoId ? 'selected' : ''}`}
                  onClick={() => setVideoId(v.id)}
                >
                  <img src={`/posters/${v.id}.jpg`} alt="" />
                  <span className="video-title">
                    {v.title} <small>{formatDuration(v.duration)}</small>
                  </span>
                  <span className="video-synopsis">{v.synopsis}</span>
                </button>
              ))}
            </div>

            <h2>2. Request</h2>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. A 20-second TikTok of the robot attack for gamers in Brazil"
              rows={3}
            />
            <div className="chips">
              {(EXAMPLES[videoId] ?? []).map((ex) => (
                <button type="button" key={ex} className="chip" onClick={() => setPrompt(ex)}>
                  {ex}
                </button>
              ))}
            </div>
            <button type="submit" className="primary" disabled={!user || busy || prompt.trim().length < 3}>
              {busy ? 'Agent is working…' : 'Run agent'}
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
                      className={j.id === job?.id ? 'active' : ''}
                      onClick={() => openJob(j.id)}
                    >
                      <span className={`dot ${j.status}`} />
                      <span className="history-text">
                        <strong>{j.videoTitle}</strong> {j.request}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="panel result">
          {job ? (
            <JobView job={job} />
          ) : (
            <div className="empty">
              <p>Your clip, subtitles, cultural review and post will appear here.</p>
            </div>
          )}
        </section>
      </main>

      <footer className="credits">
        {videos.map((v) => (
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
