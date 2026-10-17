import type { Job } from './api'

const VERDICTS = {
  ready: 'Ready to post',
  needs_changes: 'Needs changes',
  not_recommended: 'Not recommended',
}

const STEP_COUNT = 8

export function BatchView({ jobs, onOpen }: { jobs: Job[]; onOpen: (id: string) => void }) {
  const leader = jobs[0]
  const range = leader?.clipRange
  return (
    <div className="batch">
      <div className="job-head">
        <span className="status">Market comparison</span>
        <p>
          <strong>{leader?.videoTitle}</strong> — {leader?.request}
        </p>
        <p className="muted">
          Same scene for every market
          {range ? ` (${range.start.toFixed(1)}s – ${range.end.toFixed(1)}s)` : ''}; each market
          gets its own trends, subtitles, cultural review and post.
        </p>
      </div>
      <div className="compare">
        {jobs.map((j) => {
          const done = Object.values(j.steps ?? {}).filter((s) =>
            ['done', 'skipped', 'failed'].includes(s.status),
          ).length
          const video = j.urls.final ?? j.urls.clip
          const c = j.culture
          return (
            <article key={j.id} className="market">
              <header>
                <h3>{j.market}</h3>
                <span className={`status ${j.status}`}>{j.status}</span>
              </header>
              {video ? (
                <video src={video} controls playsInline loop />
              ) : (
                <div className="placeholder">
                  <div className="bar">
                    <span style={{ width: `${(done / STEP_COUNT) * 100}%` }} />
                  </div>
                  <small>
                    {done}/{STEP_COUNT} steps
                  </small>
                </div>
              )}
              {c && (
                <div className={`verdict ${c.verdict}`}>
                  <strong>{VERDICTS[c.verdict]}</strong>
                  <span>
                    {c.issues.length} issue{c.issues.length === 1 ? '' : 's'}
                    {c.revisions.length > 0 && ` · ${c.revisions.length} subtitle fixes`}
                  </span>
                  <ul>
                    {c.issues.slice(0, 3).map((issue, i) => (
                      <li key={i} className={issue.severity}>
                        <span className="badge">{issue.severity}</span>
                        {issue.issue}
                      </li>
                    ))}
                  </ul>
                  <p className="caption">{c.caption}</p>
                  <p className="hashtags">{c.hashtags.join(' ')}</p>
                </div>
              )}
              {j.error && <p className="error">{j.error}</p>}
              <button type="button" className="ghost" onClick={() => onOpen(j.id)}>
                Details
              </button>
            </article>
          )
        })}
      </div>
    </div>
  )
}
