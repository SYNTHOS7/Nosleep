import React from 'react'

/**
 * Renders conflict alerts presenting both conflicting statements side-by-side with source attribution.
 */
export default function ConflictAlert({ conflicts }) {
  if (!conflicts || conflicts.length === 0) return null

  return (
    <div className="conflict-alert" id="conflict-alert">
      <div className="conflict-alert-title">
        <span>⚠</span>
        <span>Contradictory Knowledge Detected</span>
      </div>
      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
        The ingested documents contain conflicting assertions. Both perspectives and their exact provenance are preserved:
      </p>

      {conflicts.map((c, i) => (
        <div key={i} className="conflict-pair-container">
          <div className="conflict-side">
            <div style={{ fontWeight: 600, color: 'var(--accent-amber)', marginBottom: '4px' }}>
              Perspective A ({c.source_a?.source_name || 'Source 1'}):
            </div>
            <div style={{ color: 'var(--text-primary)' }}>{c.statement_a}</div>
            {c.source_a?.quote && (
              <div style={{ fontStyle: 'italic', color: 'var(--text-muted)', marginTop: '4px' }}>
                "{c.source_a.quote}"
              </div>
            )}
          </div>

          <div className="conflict-side">
            <div style={{ fontWeight: 600, color: 'var(--accent-amber)', marginBottom: '4px' }}>
              Perspective B ({c.source_b?.source_name || 'Source 2'}):
            </div>
            <div style={{ color: 'var(--text-primary)' }}>{c.statement_b}</div>
            {c.source_b?.quote && (
              <div style={{ fontStyle: 'italic', color: 'var(--text-muted)', marginTop: '4px' }}>
                "{c.source_b.quote}"
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
