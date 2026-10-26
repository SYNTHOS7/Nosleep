import React, { useState } from 'react'

/**
 * Ingested documents list component.
 * Displays all processed documents staying in the workspace, with search filter,
 * chunk counts, revision badges, inline revision editing, and deletion.
 */
export default function DocumentList({ documents, onSelectDocument, onEditDocument, onDeleteDocument, readOnly = false }) {
  const [filterQuery, setFilterQuery] = useState('')
  const [isExpanded, setIsExpanded] = useState(true)
  const [editingDocId, setEditingDocId] = useState(null)
  const [editContent, setEditContent] = useState('')
  const [isSavingEdit, setIsSavingEdit] = useState(false)

  const filteredDocs = (documents || []).filter((doc) =>
    (doc.source_name || doc.id).toLowerCase().includes(filterQuery.toLowerCase())
  )

  const handleStartEdit = (doc) => {
    if (readOnly) return
    setEditingDocId(doc.id)
    setEditContent(`Updated specification for ${doc.source_name}: System operating under revised high-availability protocol.`)
  }

  const handleSaveEdit = async (doc) => {
    if (readOnly) return
    if (!editContent.trim()) return
    setIsSavingEdit(true)
    try {
      await onEditDocument(doc.id, doc.revision, editContent, doc.source_name)
      setEditingDocId(null)
    } finally {
      setIsSavingEdit(false)
    }
  }

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
                maxHeight: '180px',
                overflowY: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
              }}
              id="documents-list-container"
            >
              {filteredDocs.slice(0, 100).map((doc) => (
                <div key={doc.id}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '6px 8px',
                      borderRadius: '6px',
                      background: editingDocId === doc.id ? 'rgba(56, 189, 248, 0.1)' : 'rgba(255, 255, 255, 0.03)',
                      border: editingDocId === doc.id ? '1px solid var(--accent-cyan)' : '1px solid rgba(255, 255, 255, 0.06)',
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
                          maxWidth: '140px',
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
                          color: '#38bdf8',
                          background: 'rgba(56, 189, 248, 0.12)',
                          padding: '1px 5px',
                          borderRadius: '4px',
                        }}
                        title="Document Revision"
                      >
                        rev {doc.revision}
                      </span>

                      {/* Edit without rebuild button */}
                      {onEditDocument && !readOnly && (
                        <button
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--text-secondary)',
                            cursor: 'pointer',
                            padding: '2px 4px',
                            fontSize: '0.75rem',
                          }}
                          title="Edit Document without Rebuild"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (editingDocId === doc.id) {
                              setEditingDocId(null)
                            } else {
                              handleStartEdit(doc)
                            }
                          }}
                        >
                          ✏
                        </button>
                      )}

                      {/* Delete button */}
                      {onDeleteDocument && !readOnly && (
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

                  {/* Inline edit drawer */}
                  {editingDocId === doc.id && (
                    <div
                      style={{
                        padding: '8px',
                        margin: '4px 0 6px 0',
                        background: 'rgba(15, 23, 42, 0.8)',
                        borderRadius: '6px',
                        border: '1px solid rgba(255, 255, 255, 0.1)',
                      }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <div style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', marginBottom: '4px' }}>
                        Edit prose (will produce rev {doc.revision + 1} without rebuild):
                      </div>
                      <textarea
                        className="chat-input"
                        style={{ width: '100%', height: '55px', fontSize: '0.75rem', resize: 'vertical' }}
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                      />
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '6px', marginTop: '6px' }}>
                        <button
                          className="btn-secondary"
                          style={{ fontSize: '0.7rem', padding: '4px 8px' }}
                          onClick={() => setEditingDocId(null)}
                        >
                          Cancel
                        </button>
                        <button
                          className="btn-primary"
                          style={{ fontSize: '0.7rem', padding: '4px 8px' }}
                          disabled={isSavingEdit || !editContent.trim()}
                          onClick={() => handleSaveEdit(doc)}
                        >
                          {isSavingEdit ? 'Updating...' : `Save as Rev ${doc.revision + 1}`}
                        </button>
                      </div>
                    </div>
                  )}
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
