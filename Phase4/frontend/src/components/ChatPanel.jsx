import React, { useState } from 'react'
import ConflictAlert from './ConflictAlert'

/**
 * Chat and grounded query panel.
 * Displays questions, suggested queries, grounded answers, citations, limitations, and conflict alerts.
 */
export default function ChatPanel({ onRunQuery, isQuerying, queryResponse, onSelectChunk, onLoadDemo, isLoadingDemo, canWrite = true }) {
  const [queryText, setQueryText] = useState('')

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
