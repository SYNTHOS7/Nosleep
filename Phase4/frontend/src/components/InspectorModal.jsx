import React from 'react'

/**
 * Inspector modal / drawer displaying granular node/edge details:
 * Source name, page, offset, exact quote, predicate, polarity, modality, revision, conflict status.
 */
export default function InspectorModal({ element, onClose }) {
  if (!element) return null

  const isNode = element.elementType === 'node'
  const isEdge = element.elementType === 'edge'

  return (
    <div className="inspector-modal" id="inspector-modal">
      <div className="inspector-header">
        <span className="inspector-title">
          {isNode ? `Node: ${element.name || element.label}` : `Edge: ${element.predicate}`}
        </span>
        <button className="close-btn" onClick={onClose} id="close-inspector-btn" title="Close">
          &times;
        </button>
      </div>

      <div className="inspector-body">
        {isNode && (
          <>
            <div className="prop-row">
              <div className="prop-label">Node Type</div>
              <div className="prop-value">{element.type || 'Entity'}</div>
            </div>
            <div className="prop-row">
              <div className="prop-label">Label</div>
              <div className="prop-value">{element.label}</div>
            </div>
            {element.conflict_status && (
              <div className="prop-row">
                <div className="prop-label" style={{ color: 'var(--accent-rose)' }}>Conflict Status</div>
                <div className="prop-value" style={{ color: 'var(--accent-rose)', fontWeight: 600 }}>
                  Contradictory Claim Detected
                </div>
              </div>
            )}
            {element.document_id && (
              <div className="prop-row">
                <div className="prop-label">Source Document ID</div>
                <div className="prop-value">{element.document_id}</div>
              </div>
            )}
            {element.properties && Object.keys(element.properties).length > 0 && (
              <div className="prop-row">
                <div className="prop-label">Properties</div>
                <pre style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {JSON.stringify(element.properties, null, 2)}
                </pre>
              </div>
            )}
          </>
        )}

        {isEdge && (
          <>
            <div className="prop-row">
              <div className="prop-label">Predicate / Relation</div>
              <div className="prop-value" style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>
                {element.predicate}
              </div>
            </div>
            <div className="prop-row">
              <div className="prop-label">Relationship Type</div>
              <div className="prop-value">{element.edge_type}</div>
            </div>
            <div className="prop-row">
              <div className="prop-label">Polarity</div>
              <div className="prop-value">{element.polarity || 'AFFIRMATIVE'}</div>
            </div>
            <div className="prop-row">
              <div className="prop-label">Modality</div>
              <div className="prop-value">{element.modality || 'CERTAIN'}</div>
            </div>
            {element.conflict_status && (
              <div className="prop-row">
                <div className="prop-label" style={{ color: 'var(--accent-rose)' }}>Conflict Status</div>
                <div className="prop-value" style={{ color: 'var(--accent-rose)', fontWeight: 600 }}>
                  Opposing assertions exist in corpus
                </div>
              </div>
            )}
            {element.provenance && (
              <>
                <div className="prop-row">
                  <div className="prop-label">Source Chunk</div>
                  <div className="prop-value">{element.provenance.chunk_id}</div>
                </div>
                <div className="prop-row">
                  <div className="prop-label">Extraction Method</div>
                  <div className="prop-value">{element.provenance.method || 'neo4j-graphrag-adapter'}</div>
                </div>
              </>
            )}
            {element.exact_quote && (
              <div className="prop-row">
                <div className="prop-label">Exact Source Quote</div>
                <div className="quote-highlight">"{element.exact_quote}"</div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
