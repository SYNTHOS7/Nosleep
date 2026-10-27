import React, { useEffect, useRef, useState } from 'react'
import ConflictAlert from './ConflictAlert'
import { runInvestigation } from '../services/api'

/**
 * Chat and grounded query panel.
 * Displays questions, suggested queries, grounded answers, citations, limitations, and conflict alerts.
 */
export default function ChatPanel({ workspaceId, onRunQuery, isQuerying, queryResponse, onSelectChunk, onLoadDemo, isLoadingDemo, canWrite = true }) {
  const [queryText, setQueryText] = useState('')
  const [investigation, setInvestigation] = useState(null)
  const [isInvestigating, setIsInvestigating] = useState(false)
  const [investigationError, setInvestigationError] = useState('')
  const generation = useRef(0)
  useEffect(() => { generation.current++; setInvestigation(null); setInvestigationError(''); setIsInvestigating(false) }, [workspaceId])

  const investigate = async () => {
    const current = ++generation.current
    setIsInvestigating(true)
    setInvestigationError('')
    try { const result = await runInvestigation(workspaceId, queryText.trim()); if (current === generation.current) setInvestigation(result) }
    catch (error) { if (current === generation.current) setInvestigationError(error.message) }
    finally { if (current === generation.current) setIsInvestigating(false) }
  }

  const suggestedQueries = [
    'What is the blast radius of CVE-2024-4577?',
    'Trace the attack path from Legacy_PHP_Gateway',
    'Are there conflicting mitigation claims for CVE-2024-4577?',
    'What prompt injection appears in the malicious log?',
  ]

  const handleSubmit = e => {
    e.preventDefault()
    if (!queryText.trim() || isQuerying) return
    onRunQuery(queryText.trim())
  }

  const handleSelectSuggested = q => {
    setQueryText(q)
    onRunQuery(q)
  }

  return (
    <div className="glass-card" id="chat-panel">
      <div className="card-title">
        <span>Grounded Query & Reasoning</span>
      </div>

      {/* Suggested Queries */}
      <div style={{ marginBottom: '10px' }}>
        <button className="btn-primary" onClick={onLoadDemo} disabled={!canWrite || isLoadingDemo || isQuerying} style={{ marginBottom: '8px' }}>
          {isLoadingDemo ? 'Loading demo…' : 'Load synthetic cyber demo'}
        </button>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '6px' }}>
          Fictional enterprise scenario · source quotes preserved
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {suggestedQueries.map((sq, i) => (
            <button
              key={i}
              className="topic-chip"
              style={{ textAlign: 'left', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
              onClick={() => handleSelectSuggested(sq)}
              disabled={isQuerying || isLoadingDemo}
              id={`suggested-query-${i}`}
            >
              ↳ {sq}
            </button>
          ))}
        </div>
      </div>

      {/* Query Input */}
      <form onSubmit={handleSubmit} className="chat-input-box">
        <input
          type="text"
          className="chat-input"
          placeholder="Ask a question grounded in knowledge graph..."
          value={queryText}
          onChange={e => setQueryText(e.target.value)}
          id="query-input"
        />
        <button
          type="submit"
          className="btn-primary"
          disabled={isQuerying || !queryText.trim()}
          id="query-submit-btn"
        >
          {isQuerying ? 'Reasoning...' : 'Ask'}
        </button>
      </form>

      <button className="topic-chip" disabled={!queryText.trim() || isInvestigating || isQuerying}
        onClick={investigate} id="investigate-btn">
        {isInvestigating ? 'Gathering evidence…' : 'Investigate this CVE or entity'}
      </button>
      {investigationError && <p role="alert">{investigationError}</p>}
      {investigation && <section className="answer-box" aria-label="Investigation review">
        <strong>Investigation · {investigation.review.status === 'insufficient_evidence' ? 'More evidence needed' : 'Ready for your review'}</strong>
        <ol>
          <li>Gathered {investigation.evidence.source_chunks.length} cited passages.</li>
          <li>Checked {investigation.evidence.conflicts.length} opposing claim pairs.</li>
          <li>Found {investigation.paths.paths.length} potential routes.</li>
        </ol>
        <p>{investigation.review.finding}</p>
        <p style={{fontSize:'0.75rem',color:'var(--accent-amber)'}}>{investigation.review.limitations}</p>
        {investigation.evidence.source_chunks.map(source => <button className="topic-chip"
          key={`${source.chunk_id}-${source.start_char}`} onClick={() => onSelectChunk?.(source)}>
          Inspect {source.source_name} · page {source.page_number}
        </button>)}
      </section>}

      {/* Query Response View */}
      {queryResponse && (
        <div className="answer-box" id="answer-box">
          <div className="answer-header">
            <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>Synthesis & Grounded Evidence</span>
            <span className="badge-grounded">
              {queryResponse.source_chunks?.length ? 'Source-backed evidence' : 'Insufficient Evidence'}
            </span>
          </div>

          {/* Conflict Alert if contradiction detected */}
          {queryResponse.conflict_detected && (
            <ConflictAlert conflicts={queryResponse.conflicts} />
          )}

          {/* Answer text */}
          <div className="answer-text" id="answer-text">
            {queryResponse.answer}
          </div>

          {/* Limitations disclaimer if applicable */}
          {queryResponse.limitations && (
            <div style={{ fontSize: '0.75rem', color: 'var(--accent-amber)', marginTop: '8px' }}>
              ℹ Limitation: {queryResponse.limitations}
            </div>
          )}

          {/* Source Citations */}
          {queryResponse.source_chunks && queryResponse.source_chunks.length > 0 && (
            <div className="sources-list" id="sources-list">
              <div className="sources-label">Exact Source Evidence Provenance:</div>
              {queryResponse.source_chunks.map((src, idx) => (
                <div
                  key={idx}
                  className="source-item"
                  id={`source-item-${idx}`}
                  onClick={() => onSelectChunk && onSelectChunk(src)}
                  title="Click to inspect exact quote in Graph details"
                >
                  <span style={{ fontWeight: 500, color: 'var(--accent-blue)' }}>
                    📄 {src.source_name} (Page {src.page_number})
                  </span>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Rev {src.revision}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
