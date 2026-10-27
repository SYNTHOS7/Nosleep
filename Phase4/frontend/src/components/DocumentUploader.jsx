import React, { useRef, useState } from 'react'
import { uploadDocument, uploadDocumentsBatch, pollOperation, pollBatchStatus, getWorkspaceGraph } from '../services/api'

/**
 * High-throughput workspace document uploader supporting:
 * - Multi-file upload (500+ documents at once)
 * - 1-Click 500+ documents benchmark with live timing & graph size reporting
 * - ZIP archive bundle extraction
 * - Folder upload
 * - Drag-and-drop
 * - Paste text
 * - Real-time progress bar with completed/total counter
 */
export default function DocumentUploader({ workspaceId, onUploadComplete }) {
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStatus, setUploadStatus] = useState('')
  const [progressPercent, setProgressPercent] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [rawText, setRawText] = useState('')
  const [docName, setDocName] = useState('')
  const [mode, setMode] = useState('file') // 'file' | 'text'
  const [isDragging, setIsDragging] = useState(false)
  const [ingestionReport, setIngestionReport] = useState(null)

  const fileInputRef = useRef(null)
  const folderInputRef = useRef(null)

  const handleFilesUpload = async (fileList) => {
    if (!fileList || fileList.length === 0) return
    const files = Array.from(fileList)

    setIsUploading(true)
    setErrorMessage('')
    setProgressPercent(5)
    const startTime = performance.now()

    try {
      if (files.length === 1 && !files[0].name.endsWith('.zip')) {
        // Single file upload
        const file = files[0]
        setUploadStatus(`Uploading ${file.name}...`)
        const receipt = await uploadDocument(workspaceId, { file })
        setProgressPercent(40)
        setUploadStatus(`Accepted (${receipt.operation_id.slice(0, 14)}…). Ingesting...`)

        const op = await pollOperation(receipt.operation_id)
        setProgressPercent(100)
        const elapsedSec = ((performance.now() - startTime) / 1000).toFixed(2)
        const g = await getWorkspaceGraph(workspaceId).catch(() => ({ nodes: [], edges: [] }))
        setIngestionReport({
          timeSeconds: elapsedSec,
          nodes: g.nodes?.length || 0,
          edges: g.edges?.length || 0,
          count: 1,
        })
        setUploadStatus(`✓ Ingested in ${elapsedSec}s | Graph: ${g.nodes?.length || 0} nodes, ${g.edges?.length || 0} edges`)
      } else {
        // Bulk upload (2 to 500+ files or zip archive)
        const total = files.length
        setUploadStatus(`Queuing ${total} document${total > 1 ? 's' : ''} for bulk ingestion...`)
        setProgressPercent(10)

        const receipt = await uploadDocumentsBatch(workspaceId, files)
        setUploadStatus(`Accepted ${receipt.total_documents} documents. Processing in parallel...`)

        // Poll batch status with live counter
        await pollBatchStatus(
          workspaceId,
          receipt.operation_ids,
          (st) => {
            setProgressPercent(st.percent_complete)
            setUploadStatus(`Ingesting: ${st.completed} / ${st.total} files completed (${st.percent_complete}%)`)
          },
          150,
          600
        )

        setProgressPercent(100)
        const elapsedSec = ((performance.now() - startTime) / 1000).toFixed(2)
        const g = await getWorkspaceGraph(workspaceId).catch(() => ({ nodes: [], edges: [] }))
        const report = {
          timeSeconds: elapsedSec,
          nodes: g.nodes?.length || 0,
          edges: g.edges?.length || 0,
          count: receipt.total_documents,
        }
        setIngestionReport(report)
        setUploadStatus(`✓ Ingestion Time: ${elapsedSec}s | Graph Size: ${g.nodes?.length || 0} nodes, ${g.edges?.length || 0} edges`)
      }

      onUploadComplete && onUploadComplete()
    } catch (err) {
      setErrorMessage(err.message || 'Upload failed')
      setUploadStatus('')
      setProgressPercent(0)
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
      if (folderInputRef.current) folderInputRef.current.value = ''
    }
  }

  // 1-Click 500+ Documents Benchmark generator
  const handleIngest500Benchmark = async () => {
    setIsUploading(true)
    setErrorMessage('')
    setUploadStatus('Generating 500 structured enterprise documents...')
    setProgressPercent(5)

    const benchmarkFiles = []
    const domains = ['Telemetry', 'Security', 'Database', 'Streaming', 'Auth', 'Networking', 'Storage', 'Compute', 'Logging', 'Gateway']
    for (let i = 1; i <= 500; i++) {
      const domain = domains[i % domains.length]
      const content = `Component Service_${i} manages ${domain} subsystem. Protocol version ${i % 8 + 1} deployed in region Zone_${i % 5}. Throughput metric is active with status OK.`
      const blob = new Blob([content], { type: 'text/plain' })
      const file = new File([blob], `Doc_${domain}_${i}.txt`, { type: 'text/plain' })
      benchmarkFiles.push(file)
    }

    await handleFilesUpload(benchmarkFiles)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }

  const handleDragLeave = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFilesUpload(e.dataTransfer.files)
    }
  }

  const handleRawTextSubmit = async (e) => {
    e.preventDefault()
    if (!rawText.trim()) return

    setIsUploading(true)
    setErrorMessage('')
    setUploadStatus('Ingesting document text...')
    setProgressPercent(30)
    const startTime = performance.now()

    try {
      const filename = docName.trim() ? (docName.endsWith('.txt') ? docName : `${docName}.txt`) : 'source_text.txt'
      const receipt = await uploadDocument(workspaceId, { rawText, filename })
      setProgressPercent(60)
      setUploadStatus(`Accepted. Processing operation...`)

      await pollOperation(receipt.operation_id)
      setProgressPercent(100)
      const elapsedSec = ((performance.now() - startTime) / 1000).toFixed(2)
      const g = await getWorkspaceGraph(workspaceId).catch(() => ({ nodes: [], edges: [] }))
      setIngestionReport({
        timeSeconds: elapsedSec,
        nodes: g.nodes?.length || 0,
        edges: g.edges?.length || 0,
        count: 1,
      })
      setUploadStatus(`✓ Ingestion Time: ${elapsedSec}s | Graph Size: ${g.nodes?.length || 0} nodes, ${g.edges?.length || 0} edges`)
      setRawText('')
      setDocName('')
      onUploadComplete && onUploadComplete()
    } catch (err) {
      setErrorMessage(err.message || 'Ingestion failed')
      setUploadStatus('')
      setProgressPercent(0)
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
            Files / Bulk
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
        <div>
          <div
            className={`dropzone ${isDragging ? 'dragging' : ''} ${isUploading ? 'active' : ''}`}
            id="dropzone"
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current && fileInputRef.current.click()}
            style={{
              cursor: isUploading ? 'not-allowed' : 'pointer',
              borderColor: isDragging ? 'var(--accent-cyan)' : undefined,
              backgroundColor: isDragging ? 'rgba(6, 182, 212, 0.1)' : undefined,
            }}
          >
            {/* Multiple files input */}
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              multiple
              accept=".txt,.pdf,.md,.csv,.json,.zip"
              onChange={(e) => handleFilesUpload(e.target.files)}
              disabled={isUploading}
            />
            {/* Folder upload input */}
            <input
              type="file"
              ref={folderInputRef}
              style={{ display: 'none' }}
              webkitdirectory=""
              directory=""
              multiple
              onChange={(e) => handleFilesUpload(e.target.files)}
              disabled={isUploading}
            />

            <div className="dropzone-icon">{isUploading ? '⚡' : '📂'}</div>
            <div className="dropzone-text">
              {isUploading ? (
                uploadStatus
              ) : (
                <>
                  <div><strong>Click or drop 1 to 500+ files here</strong></div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Supports TXT, PDF, MD, CSV, JSON, or .ZIP bundles
                    <div>For CISA KEV import, upload one known_exploited_vulnerabilities.json or *.kev.json file.</div>
                  </div>
                </>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '8px' }}>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                className="btn-secondary"
                style={{ flex: 1, fontSize: '0.75rem', padding: '6px' }}
                onClick={() => fileInputRef.current && fileInputRef.current.click()}
                disabled={isUploading}
                id="choose-files-btn"
              >
                Select 500+ Files
              </button>
              <button
                className="btn-secondary"
                style={{ flex: 1, fontSize: '0.75rem', padding: '6px' }}
                onClick={() => folderInputRef.current && folderInputRef.current.click()}
                disabled={isUploading}
                id="choose-folder-btn"
              >
                Upload Folder
              </button>
            </div>

            {/* 1-Click 500+ Benchmark Button */}
            <button
              className="btn-primary"
              style={{
                width: '100%',
                fontSize: '0.78rem',
                padding: '7px',
                background: 'linear-gradient(135deg, #0284c7 0%, #7c3aed 100%)',
                fontWeight: 600,
              }}
              onClick={handleIngest500Benchmark}
              disabled={isUploading}
              id="benchmark-500-btn"
              title="Generates and ingests 500 documents concurrently, reporting ingestion time and graph size."
            >
              ⚡ Benchmark: Ingest 500+ Documents
            </button>
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
            onChange={(e) => setDocName(e.target.value)}
            id="doc-title-input"
          />
          <textarea
            className="chat-input"
            style={{ width: '100%', height: '80px', resize: 'vertical' }}
            placeholder="Paste document prose, policies, or specifications..."
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
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

      {/* Progress Bar for Bulk / Single Ingestion */}
      {isUploading && (
        <div style={{ marginTop: '10px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
            <span>Bulk Ingestion Concurrency</span>
            <span>{Math.round(progressPercent)}%</span>
          </div>
          <div className="progress-bar-container">
            <div
              className="progress-bar"
              style={{ width: `${Math.max(5, Math.min(100, progressPercent))}%`, transition: 'width 0.2s ease-out' }}
            ></div>
          </div>
        </div>
      )}

      {/* Prominent Ingestion & Graph Size Benchmark Report */}
      {ingestionReport && (
        <div
          style={{
            marginTop: '10px',
            padding: '8px 10px',
            borderRadius: '6px',
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            fontSize: '0.75rem',
          }}
          id="ingestion-report-card"
        >
          <div style={{ fontWeight: 600, color: 'var(--accent-emerald)', marginBottom: '3px', display: 'flex', justifyContent: 'space-between' }}>
            <span>✓ Benchmark Verified ({ingestionReport.count} Documents)</span>
            <span>{(ingestionReport.count / Math.max(0.1, Number(ingestionReport.timeSeconds))).toFixed(0)} docs/s</span>
          </div>
          <div style={{ color: 'var(--text-primary)', display: 'flex', gap: '12px' }}>
            <span><strong>Ingestion Time:</strong> {ingestionReport.timeSeconds}s</span>
            <span><strong>Graph Size:</strong> {ingestionReport.nodes} nodes, {ingestionReport.edges} edges</span>
          </div>
        </div>
      )}

      {uploadStatus && !ingestionReport && !isUploading && (
        <div style={{ fontSize: '0.75rem', color: 'var(--accent-emerald)', marginTop: '8px' }}>
          {uploadStatus}
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
