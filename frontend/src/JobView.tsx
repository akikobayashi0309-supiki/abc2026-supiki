import { useState } from 'react'
import type { Job, StepStatus } from './api'

const STEP_LABELS: Record<string, string> = {
  plan: 'Understand the request',
  search: 'Find the scene',
  subtitles: 'Transcribe & translate',
  cut: 'Cut a vertical clip',
  culture: 'Cultural check',
  render: 'Burn in subtitles',
  assets: 'Keyframe & thumbnail',
}

const ICONS: Record<StepStatus, string> = {
  pending: '○',
  running: '◐',
  done: '●',
  failed: '✕',
  skipped: '–',
}

const VERDICTS = {
  ready: 'Ready to post',
  needs_changes: 'Needs changes',
  not_recommended: 'Not recommended',
}

function time(seconds: number) {
  const s = Math.max(0, seconds)
  return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`
}

export function JobView({ job }: { job: Job }) {
  const [copied, setCopied] = useState(false)
  const culture = job.culture
  const finalLines = job.finalSubtitles ?? job.subtitles ?? []
  const revised = new Set(culture?.revisions.map((r) => r.index))
  const videoUrl = job.urls.final ?? job.urls.clip

  async function copyPost() {
    if (!culture) return
    await navigator.clipboard.writeText(`${culture.caption}\n\n${culture.hashtags.join(' ')}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="job">
      <div className="job-head">
        <span className={`status ${job.status}`}>{job.status}</span>
        <p>
          <strong>{job.videoTitle}</strong> — {job.request}
        </p>
        {job.plan && (
          <p className="tags">
            <span>{job.plan.platform}</span>
            <span>{job.plan.market}</span>
            <span>{job.plan.languageName}</span>
            <span>≤ {job.plan.maxSeconds}s</span>
            <span>{job.plan.tone}</span>
          </p>
        )}
      </div>

      <ol className="steps">
        {Object.keys(STEP_LABELS).map((name) => {
          const step = job.steps?.[name] ?? { status: 'pending' }
          return (
            <li key={name} className={step.status}>
              <span className="icon">{ICONS[step.status]}</span>
              <span className="label">{STEP_LABELS[name]}</span>
              {step.detail && <span className="detail">{step.detail}</span>}
              {step.model && <span className="model">{step.model}</span>}
            </li>
          )
        })}
      </ol>

      {job.error && <p className="error">{job.error}</p>}

      {job.selection && (
        <p className="muted reason">
          <strong>Why this scene:</strong> {job.selection.reason} ({time(job.selection.start)} –{' '}
          {time(job.selection.end)})
        </p>
      )}

      <div className="outputs">
        {videoUrl && (
          <figure className="phone">
            <video key={videoUrl} src={videoUrl} controls playsInline loop />
            <figcaption>
              <a href={videoUrl} target="_blank" rel="noreferrer">
                Open video
              </a>
            </figcaption>
          </figure>
        )}

        <div className="details">
          {culture && (
            <div className={`card verdict ${culture.verdict}`}>
              <h3>Cultural check · {VERDICTS[culture.verdict]}</h3>
              <p>{culture.summary}</p>
              {culture.issues.length > 0 && (
                <ul className="issues">
                  {culture.issues.map((issue, i) => (
                    <li key={i} className={issue.severity}>
                      <span className="badge">{issue.severity}</span>
                      <span className="when">
                        {time(issue.time)} · {issue.category.replace('_', ' ')}
                      </span>
                      <p>{issue.issue}</p>
                      <p className="fix">→ {issue.suggestion}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {culture && (
            <div className="card">
              <h3>Post</h3>
              <p className="caption">{culture.caption}</p>
              <p className="hashtags">{culture.hashtags.join(' ')}</p>
              <button type="button" className="ghost" onClick={copyPost}>
                {copied ? 'Copied' : 'Copy caption'}
              </button>
            </div>
          )}

          {finalLines.length > 0 && (
            <div className="card">
              <h3>Subtitles</h3>
              <table className="subs">
                <tbody>
                  {finalLines.map((line, i) => (
                    <tr key={i}>
                      <td className="when">{time(line.start)}</td>
                      <td>{line.original}</td>
                      <td>
                        {line.translated}
                        {revised.has(i) && <span className="badge revised">revised</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {(job.urls.keyframe || job.urls.thumbnail) && (
            <div className="card">
              <h3>Image assets</h3>
              <div className="assets">
                {job.urls.thumbnail && (
                  <a href={job.urls.thumbnail} target="_blank" rel="noreferrer">
                    <img src={job.urls.thumbnail} alt="AI thumbnail" className="thumb" />
                    <span>AI cover</span>
                  </a>
                )}
                {job.urls.keyframe && (
                  <a href={job.urls.keyframe} target="_blank" rel="noreferrer">
                    <img src={job.urls.keyframe} alt="Keyframe" />
                    <span>Keyframe</span>
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
