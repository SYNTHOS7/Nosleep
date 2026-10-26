import React, { useState } from 'react'

/**
 * Rich Paragraph & Passage Card Component for Knowledge Graph Canvas.
 * Features:
 * - Full narrative text with expandable full-text reader
 * - Provenance metadata: document name, page, revision badges
 * - Extracted entity relations preview
 * - Contradiction alerts
 * - Story Tour evidence step badges
 * - Copy quote and inspect actions
 */
export default function ParagraphCard({
  node,
  isHighlighted,
  isSelected,
  isFocused,
  searchMatch,
  tourStepNumber,
  connectedEdges = [],
  allNodesMap = new Map(),
  onSelect,
  onInspect,
}) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const props = node.properties || {}
  const text = props.text || node.name || 'No passage text available.'
  const sourceName = props.source_name || node.document_id || 'Document'
  const page = props.page || props.page_number || 1
  const revision = props.revision || 1
  const chunkIndex = props.chunk_index !== undefined ? props.chunk_index : ''
  const isConflict = node.conflict_status === 'conflicting'

  const handleCopyQuote = (e) => {
    e.stopPropagation()
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    })
  }

  // Find relationships extracted from or connected to this chunk
  const relatedRelations = connectedEdges.filter(
    (e) =>
      e.source === node.id ||
      e.target === node.id ||
      (e.provenance && e.provenance.chunk_id === node.id.replace('chunk:', ''))
  )

  const textPreview =
    !isExpanded && text.length > 200 ? `${text.slice(0, 195)}…` : text

  return (
    <div
      className={`paragraph-card ${isHighlighted ? 'highlighted' : ''} ${
        isSelected ? 'selected' : ''
      } ${isConflict ? 'conflict' : ''} ${isFocused ? 'focused-pulse' : ''} ${
        searchMatch ? 'search-match' : ''
      } ${tourStepNumber ? 'in-tour' : ''}`}
      onClick={(e) => {
        e.stopPropagation()
        onSelect && onSelect(node)
      }}
      id={`card-${node.id}`}
      title="Click to inspect this paragraph in detail"
    >
      {/* Tour Step Ribbon if Story Tour is Active */}
      {tourStepNumber && (
        <div className="tour-step-ribbon">
          <span className="tour-star">★</span>
          <span>REASONING STEP #{tourStepNumber}</span>
        </div>
      )}

      {/* Card Header */}
      <div className="paragraph-card-header">
        <div className="doc-pill" title={`Source: ${sourceName}`}>
          <span className="doc-icon">📄</span>
          <span className="doc-title">{sourceName}</span>
        </div>
        <div className="meta-pills">
          <span className="page-pill">P.{page}</span>
          <span className="rev-pill">R.{revision}</span>
          {isConflict && (
            <span className="conflict-badge" title="Contradictory claim detected in corpus">
              ⚔️ Conflict
            </span>
          )}
        </div>
      </div>

      {/* Paragraph Body Text */}
      <div
        className="paragraph-card-body"
        onMouseDown={(e) => e.stopPropagation()} // Allow text selection
      >
        <p className="paragraph-text">{textPreview}</p>
        {text.length > 200 && (
          <button
            className="expand-btn"
            onClick={(e) => {
              e.stopPropagation()
              setIsExpanded(!isExpanded)
            }}
          >
            {isExpanded ? 'Show less' : 'Read full paragraph'}
          </button>
        )}
      </div>

      {/* Extracted Entity Relations Preview */}
      {relatedRelations.length > 0 && (
        <div className="card-relations-box" onMouseDown={(e) => e.stopPropagation()}>
          <div className="relations-label">Extracted Assertions:</div>
          <div className="relations-chips">
            {relatedRelations.slice(0, 3).map((rel, idx) => {
              const srcNode = allNodesMap.get(rel.source)
              const tgtNode = allNodesMap.get(rel.target)
              const srcName = srcNode ? srcNode.name || srcNode.label : 'Source'
              const tgtName = tgtNode ? tgtNode.name || tgtNode.label : 'Target'

              return (
                <div key={idx} className="rel-chip" title={rel.predicate}>
                  <span className="rel-node">{srcName}</span>
                  <span className="rel-pred">──[{rel.predicate}]──►</span>
                  <span className="rel-node">{tgtName}</span>
                </div>
              )
            })}
            {relatedRelations.length > 3 && (
              <span className="rel-more">+{relatedRelations.length - 3} more</span>
            )}
          </div>
        </div>
      )}

      {/* Card Footer Tools */}
      <div className="paragraph-card-footer">
        <span className="chunk-label">
          {chunkIndex !== '' ? `Chunk #${chunkIndex}` : 'Passage'}
        </span>
        <div className="footer-actions">
          <button
            className="card-tool-btn"
            onClick={handleCopyQuote}
            title="Copy paragraph quote"
          >
            {copied ? '✓ Copied' : '📋 Copy'}
          </button>
          <button
            className="card-tool-btn primary"
            onClick={(e) => {
              e.stopPropagation()
              onInspect && onInspect(node)
            }}
            title="Open granular provenance inspector"
          >
            🔍 Details
          </button>
        </div>
      </div>
    </div>
  )
}
