import React, { useEffect, useRef, useState } from 'react'
import { apiFetch } from '../services/api'

const empty = { name: '', criticality: 'unknown', exposure: 'unknown', owner: '', notes: '', expected_version: 0, expected_token: null }

export default function AssetInventory({ workspaceId, canWrite, onSelectChunk }) {
  const [assets, setAssets] = useState([])
  const [form, setForm] = useState(empty)
  const [entry, setEntry] = useState('')
  const [assessment, setAssessment] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showForm, setShowForm] = useState(true)
  const scope = useRef(0)
  const base = `${(import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')}/v1/workspaces/${encodeURIComponent(workspaceId)}`

  async function call(path, options) {
    const response = await apiFetch(base + path, options)
    const data = await response.json()
    if (!response.ok) throw new Error(data.message || 'Could not complete the asset action. Refresh and try again.')
    return data
  }

  useEffect(() => {
    const generation = ++scope.current
    setForm(empty); setAssessment(null); setError(''); setAssets([]); setBusy(false); setEntry(''); setShowForm(true)
    call('/assets').then(data => { if (generation === scope.current) setAssets(data.assets) })
      .catch(reason => { if (generation === scope.current) setError(reason.message) })
    return () => { scope.current++ }
  }, [workspaceId])

  async function action(work) {
    const generation = ++scope.current
    setBusy(true); setError('')
    try {
      const result = await work()
      if (generation === scope.current) return result
    } catch (reason) { if (generation === scope.current) setError(reason.message) }
    finally { if (generation === scope.current) setBusy(false) }
    return null
  }

  async function save(event) {
    event.preventDefault()
    const data = await action(async () => {
      await call('/assets', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      return call('/assets')
    })
    if (data) { setAssets(data.assets); setForm(empty); setAssessment(null); setShowForm(false) }
  }

  async function remove(asset) {
    const data = await action(async () => {
      await call(`/assets/${asset.id}?expected_version=${asset.version}&expected_token=${asset.revision_token}`, { method: 'DELETE' })
      return call('/assets')
    })
    if (data) { setAssets(data.assets); setAssessment(null) }
  }

  async function assess(event) {
    event.preventDefault()
    const data = await action(() => call(`/route-assessment?entry_point=${encodeURIComponent(entry.trim())}`))
    if (data) setAssessment(data)
  }

  return <section className="glass-card" aria-label="Asset inventory">
    <h3>Asset context</h3>
    <p style={{fontSize:'0.8rem',color:'var(--text-muted)'}}>Use exact names from your evidence graph. Criticality and exposure are your assessments, not verified facts.</p>
    {error && <p role="alert">{error}</p>}
    {canWrite && !showForm && <button className="btn-primary" onClick={() => {setForm(empty); setShowForm(true)}}>Add asset context</button>}
    {canWrite && showForm && <form onSubmit={save} style={{display:'grid',gap:8}}>
      <label>Asset name<input className="chat-input" value={form.name} maxLength={160} required readOnly={form.expected_version > 0}
        onChange={event => setForm({...form, name:event.target.value})} /></label>
      <label>Business criticality<select className="chat-input" value={form.criticality} onChange={event => setForm({...form,criticality:event.target.value})}>
        {['unknown','low','medium','high','critical'].map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Exposure<select className="chat-input" value={form.exposure} onChange={event => setForm({...form,exposure:event.target.value})}>
        {['unknown','internet','internal','isolated'].map(value => <option key={value}>{value}</option>)}
      </select></label>
      <label>Owner<input className="chat-input" value={form.owner} maxLength={120} onChange={event => setForm({...form,owner:event.target.value})} /></label>
      <label>Notes<textarea className="chat-input" value={form.notes} maxLength={2000} onChange={event => setForm({...form,notes:event.target.value})} /></label>
      <div><button className="btn-primary" disabled={busy}>{form.expected_version ? 'Save changes' : 'Add asset'}</button>
        {form.expected_version > 0 && <button type="button" className="topic-chip" onClick={() => setForm(empty)} disabled={busy}>Cancel edit</button>}</div>
    </form>}
    <p>{assets.length} saved assets</p>
    <button className="topic-chip" disabled={busy} onClick={async () => { const data = await action(() => call('/assets')); if (data) { setAssets(data.assets); setForm(empty); setAssessment(null) } }}>Refresh inventory</button>
    {assets.map(asset => <article key={asset.id} style={{borderTop:'1px solid var(--border)',padding:'10px 0'}}>
      <strong>{asset.name}</strong><div>{asset.criticality} impact · {asset.exposure} exposure</div>
      <small>{asset.graph_match ? 'Matched by name to graph evidence' : 'No matching graph entity yet'} · analyst supplied</small>
      {asset.owner && <div>Owner: {asset.owner}</div>}
      {canWrite && <div><button className="topic-chip" disabled={busy} onClick={() => {setShowForm(true); setForm({name:asset.name,criticality:asset.criticality,exposure:asset.exposure,owner:asset.owner,notes:asset.notes,expected_version:asset.version,expected_token:asset.revision_token})}}>Edit {asset.name}</button>
        <button className="topic-chip" disabled={busy} onClick={() => remove(asset)}>Remove context for {asset.name}</button></div>}
    </article>)}
    <h3>Review route priority</h3>
    <form onSubmit={assess} style={{display:'grid',gap:8}}>
      <label>Entry asset or CVE<input className="chat-input" value={entry} maxLength={160} required onChange={event => setEntry(event.target.value)} /></label>
      <button className="btn-primary" disabled={busy || !entry.trim()}>Prioritize supported routes</button>
    </form>
    {assessment && <div aria-label="Route priorities">
      <p style={{fontSize:'0.8rem',color:'var(--accent-amber)'}}>{assessment.limitations}</p>
      {!assessment.routes.length && <p>No supported routes found. This does not certify the environment as safe.</p>}
      {assessment.routes.map(route => <article key={route.path_id} style={{borderTop:'1px solid var(--border)',padding:'10px 0'}}>
        <strong>{route.review_priority.replaceAll('_',' ')}</strong><p>{route.nodes.join(' → ')}</p>
        {route.reasons.map(reason => <div key={reason}>{reason}</div>)}
        {!!route.missing_context.length && <p>Missing: {route.missing_context.join(', ')}</p>}
        {route.citations.map((citation,index) => <button className="topic-chip" key={`${citation.chunk_id}-${index}`} onClick={() => onSelectChunk?.(citation)}>Inspect source {index+1}</button>)}
      </article>)}
      <ul>{assessment.validation_checklist.map(check => <li key={check}>{check}</li>)}</ul>
    </div>}
  </section>
}
