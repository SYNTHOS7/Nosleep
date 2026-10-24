import React, { useState } from 'react'
import { configureDatabase } from '../services/api'

export default function DatabaseModal({ dbStatus, onClose, onRefresh }) {
  const [uri, setUri] = useState(dbStatus?.neo4j?.uri === 'none' ? '' : dbStatus?.neo4j?.uri || '')
  const [username, setUsername] = useState('neo4j')
  const [password, setPassword] = useState('')
  const [database, setDatabase] = useState('neo4j')
  const [isSaving, setIsSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState('')

  const handleConnectNeo4j = async (e) => {
    e.preventDefault()
    setIsSaving(true)
    setSaveMessage('')
    try {
      const res = await configureDatabase({ uri, username, password, database })
      setSaveMessage(res.neo4j?.status === 'connected' ? '✓ Neo4j Connected Successfully!' : `Info: ${res.neo4j?.error_or_info}`)
      onRefresh && onRefresh()
    } catch (err) {
      setSaveMessage(`Error: ${err.message}`)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} id="db-modal-backdrop">
      <div
        className="modal-container"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '580px', width: '90%' }}
        id="db-modal-container"
      >
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1.2rem' }}>🗄️</span>
            <h3>Database & Persistence Connections</h3>
          </div>
          <button className="modal-close-btn" onClick={onClose} id="db-modal-close-btn">
            ✕
          </button>
        </div>

        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* ChromaDB Card */}
          <div
            style={{
              padding: '12px 16px',
              borderRadius: '8px',
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.25)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ color: '#10b981', fontSize: '1rem' }}>●</span>
                <strong style={{ color: '#10b981' }}>Chroma Vector Database</strong>
              </div>
              <span className="badge" style={{ background: '#10b981', color: '#000', fontSize: '0.75rem', fontWeight: 600 }}>
                PERSISTENT DISK
              </span>
            </div>
            <p style={{ margin: '8px 0 4px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {dbStatus?.chromadb?.error_or_info || 'Chroma persistent engine active with HNSW cosine index.'}
            </p>
            <div style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
              Persist Dir: {dbStatus?.chromadb?.persist_directory || './data/chroma'} | Embedding Dim: 768
            </div>
          </div>

          {/* Graph Database Card */}
          <div
            style={{
              padding: '12px 16px',
              borderRadius: '8px',
              background: dbStatus?.neo4j?.status === 'connected' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(6, 182, 212, 0.08)',
              border: `1px solid ${dbStatus?.neo4j?.status === 'connected' ? 'rgba(16, 185, 129, 0.25)' : 'rgba(6, 182, 212, 0.25)'}`,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ color: dbStatus?.neo4j?.status === 'connected' ? '#10b981' : '#06b6d4', fontSize: '1rem' }}>●</span>
                <strong style={{ color: dbStatus?.neo4j?.status === 'connected' ? '#10b981' : '#06b6d4' }}>
                  Knowledge Graph Engine
                </strong>
              </div>
              <span
                className="badge"
                style={{
                  background: dbStatus?.neo4j?.status === 'connected' ? '#10b981' : '#06b6d4',
                  color: '#000',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                }}
              >
                {dbStatus?.neo4j?.status === 'connected' ? 'NEO4J AURADB' : 'EMBEDDED TRANSACTIONAL'}
              </span>
            </div>
            <p style={{ margin: '8px 0 4px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {dbStatus?.neo4j?.error_or_info || 'High-performance in-memory transactional graph repository active.'}
            </p>
            <div style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
              Mode: {dbStatus?.active_mode || 'embedded_transactional'} | Operations: {dbStatus?.operations_store?.directory || './data/operations'}
            </div>
          </div>

          {/* Optional Neo4j AuraDB credentials form */}
          <form
            onSubmit={handleConnectNeo4j}
            style={{
              padding: '14px',
              borderRadius: '8px',
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid var(--border-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <div style={{ fontSize: '0.88rem', fontWeight: 600 }}>Configure External Neo4j AuraDB (Optional)</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              If you have a live Neo4j AuraDB instance, enter credentials below to synchronize knowledge graph nodes directly to Neo4j.
            </div>

            <div>
              <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Neo4j URI</label>
              <input
                type="text"
                placeholder="neo4j+s://<instance-id>.databases.neo4j.io"
                value={uri}
                onChange={(e) => setUri(e.target.value)}
                style={{
                  width: '100%',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  background: 'rgba(0,0,0,0.3)',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                  fontSize: '0.82rem',
                  fontFamily: 'var(--font-mono)',
                  boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Username</label>
                <input
                  type="text"
                  placeholder="neo4j"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '6px 10px',
                    borderRadius: '6px',
                    background: 'rgba(0,0,0,0.3)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.82rem',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>Password</label>
                <input
                  type="password"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '6px 10px',
                    borderRadius: '6px',
                    background: 'rgba(0,0,0,0.3)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.82rem',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {saveMessage && (
              <div
                style={{
                  fontSize: '0.82rem',
                  color: saveMessage.startsWith('✓') ? '#10b981' : '#f59e0b',
                  padding: '6px 8px',
                  borderRadius: '4px',
                  background: 'rgba(0,0,0,0.2)',
                }}
              >
                {saveMessage}
              </div>
            )}

            <button
              type="submit"
              disabled={isSaving}
              className="topic-chip selected"
              style={{ padding: '8px 14px', alignSelf: 'flex-start', cursor: isSaving ? 'not-allowed' : 'pointer' }}
            >
              {isSaving ? 'Testing Connection...' : '🔌 Test & Connect Neo4j'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
