import React, { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../services/api'
import RepositoryArchitecture from './RepositoryArchitecture'
import ChangeImpact from './ChangeImpact'

const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

export default function RepositoryReview({ workspaceId, canWrite }) {
  const [url, setUrl] = useState('')
  const [file, setFile] = useState(null)
  const [reviews, setReviews] = useState([])
  const [selected, setSelected] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [comparison, setComparison] = useState(null)
  const generation = useRef(0)
  const endpoint = `${base}/v1/workspaces/${encodeURIComponent(workspaceId)}`
  useEffect(() => {
    const ticket = ++generation.current
    setReviews([]); setSelected(''); setComparison(null); setBusy(false); setError(''); setFile(null); setUrl('')
    apiFetch(`${endpoint}/repository-reviews`).then(async response => {
      if (!response.ok) throw new Error('Could not load repository history.')
      return response.json()
    }).then(data => { if (ticket === generation.current) { setReviews(data.reviews); setSelected(data.reviews[0]?.id || '') } })
      .catch(e => { if (ticket === generation.current) setError(e.message) })
    return () => { generation.current++ }
  }, [endpoint])
  const current = reviews.find(item => item.id === selected)
  async function scan(event) {
    event.preventDefault()
    const ticket = ++generation.current
    setBusy(true); setError(''); setComparison(null)
    const body = new FormData()
    if (file) body.append('file', file)
    else body.append('github_url', url)
    try {
      const response = await apiFetch(`${endpoint}/repository-reviews`, { method: 'POST', body })
      const data = await response.json()
      if (!response.ok) throw new Error(data.message || data.detail || 'Repository review failed.')
      if (ticket === generation.current) { setReviews(previous => [data, ...previous].slice(0, 20)); setSelected(data.id) }
    } catch (e) { if (ticket === generation.current) setError(e.message) }
    finally { if (ticket === generation.current) setBusy(false) }
  }
  async function compare() {
    const ticket = generation.current
    setError('')
    try {
      const response = await apiFetch(`${endpoint}/repository-comparison?before=${reviews[1].id}&after=${reviews[0].id}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.message || data.detail || 'Comparison failed.')
      if (ticket === generation.current) setComparison(data)
    } catch (e) { if (ticket === generation.current) setError(e.message) }
  }
  function download() {
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(current, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = 'aegisgraph-repository-review.json'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
  return <section className="repo-review" aria-label="Repository investigation">
    <h2>Understand your code’s security findings</h2>
    <p>Inspect source → review evidence → verify the risk → rescan after changes.</p>
    <p>Passive review with five narrow rules. No code runs. An empty result does not mean the repository is secure.</p>
    {canWrite && <form onSubmit={scan}>
      <label>Public GitHub repository URL<input type="url" value={url} onChange={e => { setUrl(e.target.value); setFile(null) }} placeholder="https://github.com/owner/repository" disabled={busy} /></label>
      <label>Or upload a source ZIP (10 MiB maximum)<input key={workspaceId} type="file" accept=".zip" disabled={busy} onChange={e => { setFile(e.target.files?.[0] || null); setUrl('') }} /></label>
      <button disabled={busy || (!url && !file)}>{busy ? 'Reviewing source…' : 'Review repository'}</button>
    </form>}
    {error && <p role="alert">{error}</p>}
    {reviews.length > 0 && <label>Review history<select value={selected} onChange={e => { setSelected(e.target.value); setComparison(null) }}>{reviews.map(r => <option key={r.id} value={r.id}>{r.created_at} · {r.commit?.slice(0, 8) || r.archive_sha256.slice(0, 8)}</option>)}</select></label>}
    {reviews.length > 1 && <button onClick={compare} disabled={busy}>Compare latest two reviews</button>}
    {comparison && <aside aria-label="Rescan comparison"><h3>What changed?</h3><p>{comparison.new.length} new · {comparison.still_present.length} still observed · {comparison.no_longer_observed.length} no longer observed.</p><p>{comparison.warning}</p><ChangeImpact impact={comparison.change_impact} /></aside>}
    {current && <>
      <h3>{current.findings.length} findings to review</h3>
      <p>{current.files_analyzed} source files analyzed · {current.files_skipped} skipped · {current.parse_errors.length} Python parsing failures.</p>
      <p>Source: {current.origin} · Version: {current.commit || current.archive_sha256}</p>
      <button onClick={download}>Download review JSON</button>
      <RepositoryArchitecture key={current.id} review={current} />
      {current.findings.length === 0 && <p>No matching patterns were found within the supported rules. Other weaknesses may exist.</p>}
      {current.findings.map(f => <article key={f.id} id={`finding-${f.id}`} className="repo-finding">
        <small>NEEDS HUMAN REVIEW · {f.rule}</small><h3>{f.title}</h3>
        <p><strong>Evidence location:</strong> {f.file}:{f.line}</p>
        {f.containing_functions?.length > 0 && <p><strong>Containing functions:</strong> {f.containing_functions.join(', ')}. Code containment does not establish attacker input flow.</p>}
        {f.route_declarations?.length > 0 && <p>This operation appears inside a function with a route declaration. Verify exposure, access controls and whether request input reaches it.</p>}
        {current.commit && <a target="_blank" rel="noopener noreferrer" href={`${current.origin}/blob/${current.commit}/${f.file.split('/').map(encodeURIComponent).join('/')}#L${f.line}`}>Inspect code at this commit</a>}
        <ol className="repo-story">{f.story.map(step => <li key={step}>{step}</li>)}</ol>
        <p><strong>What to change:</strong> {f.fix}</p>
        <p><strong>Still unknown:</strong> {f.unknowns.join('; ')}.</p>
      </article>)}
      <details><summary>Coverage and limitations</summary><ul>{current.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
    </>}
    {!current && !busy && <p>Add a repository to begin. Findings will link to source locations; unsupported attack connections will remain unknown.</p>}
  </section>
}
