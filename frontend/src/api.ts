import { auth } from './firebase'

export type Video = {
  id: string
  title: string
  duration: number
  synopsis: string
  credit: string
}

export type StepStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'
export type Step = { status: StepStatus; detail?: string }

export type SubtitleLine = {
  start: number
  end: number
  original: string
  translated: string
}

export type Issue = {
  time: number
  category: string
  severity: 'low' | 'medium' | 'high'
  issue: string
  suggestion: string
}

export type Culture = {
  verdict: 'ready' | 'needs_changes' | 'not_recommended'
  summary: string
  issues: Issue[]
  revisions: { index: number; translated: string }[]
  caption: string
  hashtags: string[]
  thumbnailTitle: string
  highlightTime: number
}

export type Plan = {
  sceneQuery: string
  market: string
  language: string
  languageName: string
  platform: string
  maxSeconds: number
  tone: string
}

export type JobSummary = {
  id: string
  videoId: string
  videoTitle: string
  request: string
  status: 'queued' | 'running' | 'done' | 'failed'
  createdAt: string
}

export type Job = JobSummary & {
  steps: Record<string, Step>
  plan?: Plan
  selection?: { start: number; end: number; reason: string }
  subtitles?: SubtitleLine[]
  finalSubtitles?: SubtitleLine[]
  culture?: Culture
  urls: Partial<Record<'clip' | 'final' | 'keyframe' | 'thumbnail', string>>
  error?: string
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const user = auth.currentUser
  if (!user) throw new Error('Not signed in')
  const token = await user.getIdToken()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `Request failed (${res.status})`)
  }
  return res.json() as Promise<T>
}

export const listVideos = () => request<Video[]>('/api/library')
export const listJobs = () => request<JobSummary[]>('/api/jobs')
export const getJob = (id: string) => request<Job>(`/api/jobs/${id}`)
export const createJob = (videoId: string, prompt: string) =>
  request<{ id: string }>('/api/jobs', {
    method: 'POST',
    body: JSON.stringify({ videoId, request: prompt }),
  })
