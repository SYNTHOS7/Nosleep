import React, { useRef, useState } from 'react'
import { uploadDocument, pollOperation } from '../services/api'

/**
 * Workspace document uploader supporting drag-and-drop TXT/PDF, paste text,
 * and operation progress monitoring with live status.
 */
export default function DocumentUploader({ workspaceId, onUploadComplete }) {
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [rawText, setRawText] = useState('')
  const [docName, setDocName] = useState('')
  const [mode, setMode] = useState('file') // 'file' | 'text'
  const fileInputRef = useRef(null)

  const handleFileUpload = async file => {
    if (!file) return
    setIsUploading(true)
    setErrorMessage('')
    setUploadStatus(`Uploading ${file.name}...`)

    try {
      const receipt = await uploadDocument(workspaceId, { file })
      setUploadStatus(`Accepted (Op: ${receipt.operation_id}). Ingesting...`)

      // Poll until completed
      const op = await pollOperation(receipt.operation_id)
      setUploadStatus(`Completed in ${op.stage_timings?.total?.toFixed(2) || '0.2'}s!`)
      setTimeout(() => setUploadStatus(''), 3000)
      onUploadComplete && onUploadComplete()
    } catch (err) {
      setErrorMessage(err.message || 'Upload failed')
      setUploadStatus('')
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleRawTextSubmit = async e => {
    e.preventDefault()
    if (!rawText.trim()) return

    setIsUploading(true)
    setErrorMessage('')
    setUploadStatus('Ingesting document text...')

    try {
      const filename = docName.trim() ? (docName.endsWith('.txt') ? docName : `${docName}.txt`) : 'source_text.txt'
      const receipt = await uploadDocument(workspaceId, { rawText, filename })
      setUploadStatus(`Accepted. Processing operation...`)

      const op = await pollOperation(receipt.operation_id)
      setUploadStatus(`Successfully ingested!`)
      setRawText('')
      setDocName('')
      setTimeout(() => setUploadStatus(''), 3000)
      onUploadComplete && onUploadComplete()
    } catch (err) {
      setErrorMessage(err.message || 'Ingestion failed')
      setUploadStatus('')
    } finally {
      setIsUploading(false)
    }
  }

  return (
    <div className="glass-card" id="uploader-panel">
      <div className="card-title">
        <span>Workspace Ingestion</span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            className={`topic-chip ${mode === 'file' ? 'selected' : ''}`}
            onClick={() => setMode('file')}
            id="mode-file-btn"
          >
            File
          </button>
          <button
            className={`topic-chip ${mode === 'text' ? 'selected' : ''}`}
            onClick={() => setMode('text')}
            id="mode-text-btn"
          >
            Paste Text
          </button>
        </div>
      </div>

      {mode === 'file' ? (
        <div
          className={`dropzone ${isUploading ? 'active' : ''}`}
          id="dropzone"
          onClick={() => fileInputRef.current && fileInputRef.current.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            style={{ display: 'none' }}
            accept=".txt,.pdf"
            onChange={e => handleFileUpload(e.target.files[0])}
          />
          <div className="dropzone-icon">📄</div>
          <div className="dropzone-text">
            {isUploading ? uploadStatus : 'Click or drop PDF / TXT files here'}
          </div>
        </div>
      ) : (
        <form onSubmit={handleRawTextSubmit}>
          <input
            type="text"
            className="chat-input"
            style={{ marginBottom: '8px' }}
            placeholder="Document title (e.g. ServiceSpec.txt)"
            value={docName}
            onChange={e => setDocName(e.target.value)}
            id="doc-title-input"
          />
          <textarea
            className="chat-input"
            style={{ width: '100%', height: '80px', resize: 'vertical' }}
            placeholder="Paste document prose, policies, or specifications..."
            value={rawText}
            onChange={e => setRawText(e.target.value)}
            id="doc-text-area"
          />
          <button
            type="submit"
            className="btn-primary"
            style={{ width: '100%', marginTop: '8px' }}
            disabled={isUploading || !rawText.trim()}
            id="submit-text-btn"
          >
            {isUploading ? 'Ingesting...' : 'Ingest Document'}
          </button>
        </form>
      )}

      {isUploading && (
        <div className="progress-bar-container">
          <div className="progress-bar" style={{ width: '80%' }}></div>
        </div>
      )}

      {uploadStatus && !isUploading && (
        <div style={{ fontSize: '0.75rem', color: 'var(--accent-emerald)', marginTop: '8px' }}>
          ✓ {uploadStatus}
        </div>
      )}

      {errorMessage && (
        <div style={{ fontSize: '0.75rem', color: 'var(--accent-rose)', marginTop: '8px' }}>
          ✕ {errorMessage}
        </div>
      )}
    </div>
  )
}
