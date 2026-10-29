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
  const [view, setView] = useState('overview')
  const [sourceMode, setSourceMode] = useState('github')
  const [showImport, setShowImport] = useState(false)
  const [loading, setLoading] = useState(true)
  const [comparing, setComparing] = useState(false)
  const generation = useRef(0)
  const endpoint = `${base}/v1/workspaces/${encodeURIComponent(workspaceId)}`
  useEffect(() => {
    const ticket = ++generation.current
    setLoading(true); setView('overview'); setShowImport(false); setComparing(false); setSourceMode('github')
    setReviews([]); setSelected(''); setComparison(null); setBusy(false); setError(''); setFile(null); setUrl('')
    apiFetch(`${endpoint}/repository-reviews`).then(async response => {
      if (!response.ok) throw new Error('Could not load repository history.')
      return response.json()
    }).then(data => { if (ticket === generation.current) { setReviews(data.reviews); setSelected(data.reviews[0]?.id || ''); setLoading(false) } })
      .catch(e => { if (ticket === generation.current) { setError(e.message); setLoading(false) } })
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
      if (ticket === generation.current) { setReviews(previous => [data, ...previous].slice(0, 20)); setSelected(data.id); setShowImport(false); setView('overview') }
    } catch (e) { if (ticket === generation.current) setError(e.message) }
    finally { if (ticket === generation.current) setBusy(false) }
  }
  async function compare() {
    const ticket = generation.current
    setError(''); setComparing(true)
    try {
      const response = await apiFetch(`${endpoint}/repository-comparison?before=${reviews[1].id}&after=${reviews[0].id}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.message || data.detail || 'Comparison failed.')
      if (ticket === generation.current) setComparison(data)
    } catch (e) { if (ticket === generation.current) setError(e.message) }
    finally { if (ticket === generation.current) setComparing(false) }
  }
  function download() {
    const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(current, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = 'aegisgraph-repository-review.json'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
  const dateLabel = value => new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  const version = current?.commit?.slice(0, 8) || current?.archive_sha256.slice(0, 8)
  return <section className="repo-review" aria-label="Repository investigation" aria-busy={busy || loading}>
    <header className="repo-heading">
      <div><span className="repo-eyebrow">SOURCE INTELLIGENCE / REPOSITORY REVIEW</span><h2>Your code, <span>in context.</span></h2><p>Follow the structure, inspect findings, and see what a change could affect.</p></div>
      {current && canWrite && <button className="repo-primary" onClick={() => setShowImport(!showImport)} aria-expanded={showImport}>{showImport ? 'Close import' : '+ New review'}</button>}
    </header>
    {error && <div className="repo-error" role="alert"><strong>Something needs attention</strong><p>{error}</p></div>}
    {loading && <p role="status" className="repo-empty"><span className="repo-spinner" /> Loading your saved reviews…</p>}
    {!loading && canWrite && (!current || showImport) && <form className="repo-import" onSubmit={scan}>
      <div className="repo-section-title"><div><span className="repo-eyebrow">START WITH A SOURCE</span><h3>What would you like to review?</h3></div><span className="repo-tag">Code is never executed</span></div>
      <div className="repo-source-choice" aria-label="Source type">
        <button type="button" aria-pressed={sourceMode === 'github'} onClick={() => { setSourceMode('github'); setFile(null) }} disabled={busy}>GitHub repository</button>
        <button type="button" aria-pressed={sourceMode === 'zip'} onClick={() => { setSourceMode('zip'); setUrl('') }} disabled={busy}>Source ZIP</button>
      </div>
      {sourceMode === 'github' ? <label>Public GitHub repository URL<input type="url" required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://github.com/owner/repository" disabled={busy} /><small>Public repositories only. Large repositories or GitHub rate limits may require a ZIP.</small></label> : <label className="repo-file-drop">Repository ZIP<input key={workspaceId} type="file" required accept=".zip" disabled={busy} onChange={e => setFile(e.target.files?.[0] || null)} /><small>{file ? `Ready: ${file.name}` : 'Choose a ZIP containing your source files. Maximum 10 MiB.'}</small></label>}
      <div className="repo-import-footer"><p>Python and JavaScript / TypeScript source · five focused review rules.</p><button className="repo-primary" disabled={busy || (!url && !file)}>{busy ? <><span className="repo-spinner" /> Reviewing source…</> : 'Review source →'}</button></div>
      {busy && <p role="status">Reading source and checking patterns. Keep this workspace open until the review finishes.</p>}
    </form>}
    {current && <>
      <div className="repo-review-bar">
        <label>Review snapshot<select value={selected} disabled={busy || comparing} onChange={e => { setSelected(e.target.value); setComparison(null); setView('overview') }}>{reviews.map(r => <option key={r.id} value={r.id}>{dateLabel(r.created_at)} · {r.commit?.slice(0, 8) || r.archive_sha256.slice(0, 8)}</option>)}</select></label>
        <button className="repo-secondary" onClick={download}>↓ Export JSON</button>
      </div>
      <nav className="repo-view-nav" aria-label="Review sections">{[['overview','Overview'],['architecture','Architecture'],['findings',`Findings · ${current.findings.length}`],['changes','Changes']].map(([id,label]) => <button key={id} id={`repo-view-${id}`} aria-current={view === id ? 'page' : undefined} onClick={() => setView(id)}>{label}</button>)}</nav>
      <div className="repo-view" aria-labelledby={`repo-view-${view}`} role="region">
        {view === 'overview' && <>
          <div className="repo-summary"><div><span className="repo-tag">Review ready</span><h3>{current.origin === 'uploaded ZIP' ? 'Your source snapshot' : current.origin.replace('https://github.com/', '')}</h3><p>{current.files_analyzed} source {current.files_analyzed === 1 ? 'file' : 'files'} reviewed. {current.findings.length ? `${current.findings.length} ${current.findings.length === 1 ? 'finding candidate needs' : 'finding candidates need'} a closer look.` : 'No patterns matched the current rules. This is not a security clearance.'}</p></div><code>{version}</code></div>
          <div className="repo-action-grid">
            <button className="repo-action-card" onClick={() => setView('architecture')}><span className="repo-eyebrow">STRUCTURE</span><strong>See how the code connects <span>↗</span></strong><p>{current.architecture?.edges.length ?? '—'} import connections · explore one component at a time.</p></button>
            <button className="repo-action-card" onClick={() => setView('findings')}><span className="repo-eyebrow">EVIDENCE</span><strong>Review potential weaknesses <span>↗</span></strong><p>File and line references, suggested fixes, and what still needs verification.</p></button>
            <button className="repo-action-card" onClick={() => setView('changes')}><span className="repo-eyebrow">CHANGE IMPACT</span><strong>Check what a change affects <span>↗</span></strong><p>Compare the latest two snapshots to find changed lines and connected files.</p></button>
          </div>
          <div className="repo-coverage"><strong>Coverage at a glance</strong><span>{current.files_skipped} files skipped</span><span>{current.parse_errors.length} Python parsing failures</span><span>{current.architecture?.routes.length ?? '—'} possible route declarations</span></div>
          <p className="repo-note">Findings and connections are review evidence. Runtime exposure, input flow and exploitability still need validation.</p>
        </>}
        {view === 'architecture' && <RepositoryArchitecture key={current.id} review={current} onSelectFinding={() => setView('findings')} />}
        {view === 'findings' && <>
          <div className="repo-section-title"><div><span className="repo-eyebrow">EVIDENCE BEFORE ASSUMPTIONS</span><h3>Potential weaknesses to review</h3></div><span className="repo-tag amber">{current.findings.length} candidates</span></div>
          {!current.findings.length && <div className="repo-empty"><h4>No matching patterns found</h4><p>The five supported rules found no matches. Other vulnerabilities or logic bugs may still exist.</p></div>}
          {current.findings.map(f => <article key={f.id} id={`finding-${f.id}`} className="repo-finding">
            <div className="repo-section-title"><span className="repo-tag amber">Needs review</span><code>{f.rule}</code></div><h3>{f.title}</h3>
            <p className="repo-location">{f.file}<strong>:{f.line}</strong></p>
            <div className="repo-fix"><span className="repo-eyebrow">SUGGESTED NEXT STEP</span><p>{f.fix}</p></div>
            <details><summary>Evidence and unresolved questions</summary>
              {f.containing_functions?.length > 0 && <p>Containing functions: {f.containing_functions.join(', ')}. Containment does not establish attacker input flow.</p>}
              {f.route_declarations?.length > 0 && <p>This function has a route declaration. Verify exposure, access controls and whether request input reaches the operation.</p>}
              {current.commit && <a target="_blank" rel="noopener noreferrer" href={`${current.origin}/blob/${current.commit}/${f.file.split('/').map(encodeURIComponent).join('/')}#L${f.line}`}>Inspect code at this commit ↗</a>}
              <ol className="repo-story">{f.story.map(step => <li key={step}>{step}</li>)}</ol><p>Still unknown: {f.unknowns.join('; ')}.</p>
            </details>
          </article>)}
        </>}
        {view === 'changes' && <>
          <div className="repo-section-title"><div><span className="repo-eyebrow">BEFORE / AFTER</span><h3>Understand the impact of a change</h3></div></div>
          {reviews.length < 2 ? <div className="repo-empty"><h4>A second snapshot unlocks comparison</h4><p>Review the same repository after a change, then compare the two versions here.</p>{canWrite && <button className="repo-primary" onClick={() => setShowImport(true)}>Add another review</button>}</div> : <>
            <p className="repo-note">Compares the latest two reviews in this workspace, regardless of the snapshot selected above. Use two versions of the same project.</p>
            <div className="repo-compare-versions"><span><small>BEFORE</small>{dateLabel(reviews[1].created_at)}</span><span aria-hidden="true">→</span><span><small>AFTER</small>{dateLabel(reviews[0].created_at)}</span><button className="repo-primary" onClick={compare} disabled={busy || comparing}>{comparing ? 'Comparing…' : 'Compare latest two reviews'}</button></div>
            {comparison && <aside aria-label="Rescan comparison"><div className="repo-comparison-summary"><strong>{comparison.new.length} new candidates</strong><span>{comparison.still_present.length} still observed</span><span>{comparison.no_longer_observed.length} no longer observed</span></div><ChangeImpact impact={comparison.change_impact} /><p className="repo-note">{comparison.warning}</p></aside>}
          </>}
        </>}
      </div>
      <details className="repo-method"><summary>Review details and coverage limits</summary><p>Source: {current.origin}</p><p className="repo-location">Version: {current.commit || current.archive_sha256}</p><ul>{current.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
    </>}
    {!current && !loading && !busy && <div className="repo-empty"><h3>{canWrite ? 'Your investigation starts with a snapshot.' : 'No repository reviews yet.'}</h3><p>{canWrite ? 'Add source above. Then explore its architecture, review findings, and compare changes—all with source locations.' : 'Ask a workspace editor to add a repository review.'}</p></div>}
  </section>
}
