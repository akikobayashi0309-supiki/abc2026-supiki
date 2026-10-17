import { auth } from './firebase'

export type VideoStatus = 'uploading' | 'queued' | 'processing' | 'indexing' | 'ready' | 'failed'

export type Video = {
  id: string
  title: string
  duration: number
  synopsis: string
  credit: string
  status: VideoStatus
  posterUrl: string | null
  uploaded: boolean
  error?: string
}

export type StepStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'
export type Step = { status: StepStatus; detail?: string; model?: string }

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
  market?: string | null
  batchId?: string | null
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
  trends?: { summary: string; sources: { title: string; uri: string }[] }
  clipRange?: { videoId: string; start: number; end: number }
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
export const getBatch = (id: string) => request<Job[]>(`/api/batches/${id}`)
export const createJob = (videoId: string, prompt: string, markets: string[]) =>
  request<{ id: string; ids: string[]; batchId: string | null }>('/api/jobs', {
    method: 'POST',
    body: JSON.stringify({ videoId, request: prompt, markets }),
  })

/** Upload straight to Cloud Storage with a signed URL, then let the backend process it. */
export async function uploadVideo(file: File, onProgress: (ratio: number) => void) {
  const contentType = file.type || 'video/mp4'
  const { id, uploadUrl } = await request<{ id: string; uploadUrl: string }>('/api/uploads', {
    method: 'POST',
    body: JSON.stringify({ title: file.name, contentType, size: file.size }),
  })
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', uploadUrl)
    xhr.setRequestHeader('Content-Type', contentType)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () =>
      xhr.status < 300 ? resolve() : reject(new Error(`Upload failed (${xhr.status})`))
    xhr.onerror = () => reject(new Error('Upload failed'))
    xhr.send(file)
  })
  await request(`/api/uploads/${id}/complete`, { method: 'POST' })
  return id
}
