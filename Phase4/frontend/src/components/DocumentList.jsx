import React, { useState } from 'react'

/**
 * Ingested documents list component.
 * Displays all processed documents staying in the workspace, with search filter,
 * chunk counts, revision badges, and inspection triggers.
 */
export default function DocumentList({ documents, onSelectDocument, onDeleteDocument }) {
  const [filterQuery, setFilterQuery] = useState('')
  const [isExpanded, setIsExpanded] = useState(true)

  const filteredDocs = (documents || []).filter((doc) =>
    (doc.source_name || doc.id).toLowerCase().includes(filterQuery.toLowerCase())
  )

  return (
    <div className="glass-card" id="documents-panel">
      <div
        className="card-title"
        style={{ cursor: 'pointer' }}
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>Workspace Documents</span>
          <span
            style={{
              background: 'rgba(245, 158, 11, 0.15)',
              color: '#f59e0b',
              padding: '2px 8px',
              borderRadius: '12px',
              fontSize: '0.72rem',
              fontWeight: 600,
            }}
          >
            {documents?.length || 0}
          </span>
        </div>
        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          {isExpanded ? '▼' : '►'}
        </span>
      </div>

      {isExpanded && (
        <div style={{ marginTop: '8px' }}>
          {/* Search filter for 500+ documents */}
          {(documents?.length || 0) > 4 && (
            <input
              type="text"
              className="chat-input"
              style={{ width: '100%', marginBottom: '8px', fontSize: '0.75rem', padding: '6px 10px' }}
              placeholder={`Search ${documents.length} documents...`}
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              id="doc-filter-input"
            />
          )}

          {filteredDocs.length === 0 ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center', padding: '12px 0' }}>
              {documents?.length === 0
                ? 'No documents ingested yet. Upload files above.'
                : 'No documents match your search.'}
            </div>
          ) : (
            <div
              style={{
                maxHeight: '160px',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
              }}
              id="documents-list-container"
            >
              {filteredDocs.slice(0, 100).map((doc) => (
                <div
                  key={doc.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '6px 8px',
                    borderRadius: '6px',
                    background: 'rgba(255, 255, 255, 0.03)',
                    border: '1px solid rgba(255, 255, 255, 0.06)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                  onClick={() =>
                    onSelectDocument &&
                    onSelectDocument({
                      id: `doc:${doc.id}`,
                      label: 'Document',
                      name: doc.source_name,
                      type: 'document',
                      properties: {
                        revision: doc.revision,
                        source_type: doc.source_type,
                        chunk_count: doc.chunk_count,
                      },
                      elementType: 'node',
                    })
                  }
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', overflow: 'hidden' }}>
                    <span style={{ color: '#f59e0b' }}>📄</span>
                    <span
                      style={{
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        maxWidth: '160px',
                        color: 'var(--text-primary)',
                      }}
                      title={doc.source_name}
                    >
                      {doc.source_name}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span
                      style={{
                        fontSize: '0.68rem',
                        color: 'var(--text-muted)',
                        background: 'rgba(255, 255, 255, 0.05)',
                        padding: '1px 5px',
                        borderRadius: '4px',
                      }}
                    >
                      rev {doc.revision}
                    </span>
                    {onDeleteDocument && (
                      <button
                        style={{
                          background: 'none',
                          border: 'none',
                          color: 'var(--text-muted)',
                          cursor: 'pointer',
                          padding: '2px 4px',
                          fontSize: '0.75rem',
                        }}
                        title="Delete Document"
                        onClick={(e) => {
                          e.stopPropagation()
                          onDeleteDocument(doc.id)
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {filteredDocs.length > 100 && (
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textAlign: 'center', padding: '4px' }}>
                  Showing first 100 of {filteredDocs.length} documents
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
