import React, { useMemo, useState } from 'react'

export default function RepositoryArchitecture({ review, onSelectFinding }) {
  const map = review.architecture
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState('')
  const ranked = useMemo(() => {
    if (!map) return []
    const degree = new Map()
    for (const edge of map.edges) {
      degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
      degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
    }
    return [...map.nodes].sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0) || a.id.localeCompare(b.id))
  }, [map])
  if (!map) return <p>This older review has no architecture map. Rescan its source to generate one.</p>
  const filtered = ranked.filter(node => node.id.toLowerCase().includes(search.toLowerCase()))
  const focus = filtered.find(node => node.id === selected) || filtered[0]
  const incoming = focus ? map.edges.filter(edge => edge.target === focus.id) : []
  const outgoing = focus ? map.edges.filter(edge => edge.source === focus.id) : []
  const distinct = (edges, key) => [...new Map(edges.map(edge => [edge[key], edge])).values()].slice(0, 6)
  const left = distinct(incoming, 'source'), right = distinct(outgoing, 'target')
  const height = Math.max(260, Math.max(left.length, right.length) * 85 + 40)
  const mid = height / 2
  const node = (path, x, y, key) => {
    const data = map.nodes.find(n => n.id === path)
    return <g key={key}>
      <title>{path} · {data?.finding_count || 0} finding candidates</title>
      <rect x={x} y={y - 28} width="230" height="56" rx="7" fill={data?.finding_count ? '#493321' : '#1d3448'} stroke={data?.finding_count ? '#e4b96b' : '#83b5d4'} />
      <text x={x + 10} y={y - 3} fill="#f2f6fb" fontSize="12">{path.split('/').pop().slice(0, 30)}</text>
      <text x={x + 10} y={y + 16} fill="#c1d1e1" fontSize="11">{data?.role} · {data?.finding_count || 0} findings</text>
    </g>
  }
  return <section className="repo-architecture" aria-label="Repository architecture map">
    <h3>How the source fits together</h3>
    <p>{map.nodes.length} source files · {map.edges.length} resolved import declarations · {map.routes.length} route declaration candidates.</p>
    <p>{map.explanation}</p>
    <label>Find a source file<input value={search} onChange={e => { setSearch(e.target.value); setSelected('') }} placeholder="Search file or folder" /></label>
    <label>Explore a component<select value={focus?.id || ''} onChange={e => setSelected(e.target.value)}>
      {!filtered.length && <option value="">No matching files</option>}
      {filtered.map(n => <option key={n.id} value={n.id}>{n.id} · {n.finding_count} findings</option>)}
    </select></label>
    {focus && <>
      <p><strong>Selected:</strong> {focus.id} · {focus.language} · {focus.line_count} lines. Role “{focus.role}” is inferred from its path or extension.</p>
      <div className="repo-map-scroll"><svg viewBox={`0 0 920 ${height}`} role="img" aria-label={`Import diagram for ${focus.id}`}>
        <defs><marker id="repo-import-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#91b8cf" /></marker></defs>
        <text x="20" y="17" fill="#c1d1e1" fontSize="12">FILES THAT IMPORT THIS FILE</text>
        <text x="345" y="17" fill="#c1d1e1" fontSize="12">SELECTED FILE</text>
        <text x="670" y="17" fill="#c1d1e1" fontSize="12">FILES IT IMPORTS</text>
        {left.map((e, i) => <path key={`in-${i}`} d={`M250,${60 + i * 85} C300,${60 + i * 85} 300,${mid} 345,${mid}`} fill="none" stroke="#91b8cf" markerEnd="url(#repo-import-arrow)" />)}
        {right.map((e, i) => <path key={`out-${i}`} d={`M575,${mid} C620,${mid} 620,${60 + i * 85} 670,${60 + i * 85}`} fill="none" stroke="#91b8cf" markerEnd="url(#repo-import-arrow)" />)}
        {left.map((e, i) => node(e.source, 20, 60 + i * 85, `in-${i}`))}
        {node(focus.id, 345, mid, 'focus')}
        {right.map((e, i) => node(e.target, 670, 60 + i * 85, `out-${i}`))}
      </svg></div>
      <p>One-hop view: up to six distinct files per side. Amber marks a file with finding candidates. Import arrows are not attack paths.</p>
      {incoming.length + outgoing.length === 0 && <p>No resolved internal imports for this file. It may still use external libraries or dynamic connections.</p>}
      <details><summary>Inspect import evidence ({incoming.length + outgoing.length})</summary>
        <ul>{[...incoming, ...outgoing].slice(0, 100).map((edge, i) => <li key={i}>{edge.source} → {edge.target} · declared at {edge.evidence.file}:{edge.evidence.line}</li>)}</ul>
        {incoming.length + outgoing.length > 100 && <p>First 100 shown; the full set is in the JSON export.</p>}
      </details>
      <details><summary>Potential entry points in this file</summary>
      {map.routes.filter(route => route.file === focus.id).length === 0 ? <p>No supported route decorator detected. This does not rule out other entry points.</p> :
        <ul>{map.routes.filter(route => route.file === focus.id).slice(0, 100).map(route => <li key={route.id}>{route.method} declaration · {route.function} · {route.file}:{route.line}. Exposure and access controls are unverified.</li>)}</ul>}</details>
      <h4>Security review for this component</h4>
      {review.findings.filter(f => f.file === focus.id).length ? <ul>{review.findings.filter(f => f.file === focus.id).map(f => <li key={f.id}><a href={`#finding-${f.id}`} onClick={onSelectFinding}>{f.title} · line {f.line}</a></li>)}</ul> : <p>No matching findings within the current rules. This component has not been proven secure.</p>}
    </>}
    <details><summary>What this map cannot establish</summary><p>{map.coverage}</p><p>{map.unresolved_import_count} external or unresolved import declarations; {map.parse_failures.length} Python files could not be mapped.</p><ul>{map.unknowns.map(text => <li key={text}>{text}</li>)}</ul></details>
  </section>
}
