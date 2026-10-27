/**
 * API client service connecting React frontend to FastAPI Person 4 backend.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')

let tokenProvider = null
export function setTokenProvider(provider) { tokenProvider = provider }

export async function apiFetch(url, options = {}) {
  const send = async forceRefresh => {
    const headers = new Headers(options.headers || {})
    const token = tokenProvider ? await tokenProvider(forceRefresh) : null
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return fetch(url, { ...options, headers })
  }
  let response = await send(false)
  if (response.status === 401 && tokenProvider) response = await send(true)
  return response
}

export async function getAuthConfig() {
  const response = await fetch(`${BASE_URL}/v1/auth/config`)
  if (!response.ok) throw new Error('Could not reach the authentication service.')
  return response.json()
}

export async function getCurrentUser() {
  const response = await apiFetch(`${BASE_URL}/v1/auth/me`)
  if (!response.ok) throw new Error('Your session or workspace access could not be verified.')
  return response.json()
}


export async function loadCyberDemo(workspaceId) {
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${encodeURIComponent(workspaceId)}/demo/cyber`, { method: 'POST' })
  if (!res.ok) throw new Error('Could not load the cyber demo. Check backend storage configuration.')
  return res.json()
}

export async function getHealth() {
  const res = await apiFetch(`${BASE_URL}/health`)
  if (!res.ok) throw new Error('Health check failed')
  return res.json()
}

export async function uploadDocument(workspaceId, { file, rawText, filename }) {
  const formData = new FormData()
  if (file) {
    formData.append('file', file)
  }
  if (rawText) {
    formData.append('raw_text', rawText)
  }
  if (filename) {
    formData.append('filename', filename)
  }

  const isKev = file && (file.name === 'known_exploited_vulnerabilities.json' || file.name.endsWith('.kev.json'))
  const route = isKev ? 'imports/cisa-kev' : 'documents'
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${encodeURIComponent(workspaceId)}/${route}`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Upload failed' }))
    throw new Error(err.message || 'Upload failed')
  }
  return res.json() // MutationReceipt
}

export async function uploadDocumentsBatch(workspaceId, files) {
  const formData = new FormData()
  for (const f of files) {
    formData.append('files', f)
  }

  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents/batch`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Batch upload failed' }))
    throw new Error(err.message || 'Batch upload failed')
  }
  return res.json() // BatchMutationReceipt
}

export async function getBatchStatus(workspaceId, operationIds = null) {
  const queryParam = operationIds && operationIds.length > 0 ? `?operation_ids=${encodeURIComponent(operationIds.join(','))}` : ''
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${workspaceId}/operations/batch-status${queryParam}`)
  if (!res.ok) throw new Error('Failed to get batch status')
  return res.json()
}

export async function pollBatchStatus(workspaceId, operationIds, onProgress = null, intervalMs = 200, maxAttempts = 300) {
  for (let i = 0; i < maxAttempts; i++) {
    const st = await getBatchStatus(workspaceId, operationIds)
    if (onProgress) onProgress(st)
    if (st.is_finished) return st
    await new Promise(r => setTimeout(r, intervalMs))
  }
  throw new Error('Batch operation polling timed out')
}

export async function getWorkspaceDocuments(workspaceId) {
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${encodeURIComponent(workspaceId)}/documents`)
  if (!res.ok) throw new Error('Failed to load workspace documents')
  return res.json()
}

export async function editDocument(workspaceId, docId, expectedRevisionId, { file, rawText, filename }) {
  const formData = new FormData()
  formData.append('expected_revision_id', expectedRevisionId)
  if (file) formData.append('file', file)
  if (rawText) formData.append('raw_text', rawText)
  if (filename) formData.append('filename', filename)

  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents/${docId}`, {
    method: 'PUT',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Edit failed' }))
    throw new Error(err.message || `Edit failed (${res.status})`)
  }
  return res.json()
}

export async function deleteDocument(workspaceId, docId) {
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents/${docId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Delete failed' }))
    throw new Error(err.message || 'Delete failed')
  }
  return res.json()
}

export async function getOperation(operationId) {
  const res = await apiFetch(`${BASE_URL}/v1/operations/${operationId}`)
  if (!res.ok) throw new Error('Failed to fetch operation')
  return res.json()
}

export async function getDatabaseStatus() {
  const res = await apiFetch(`${BASE_URL}/v1/database/status`)
  if (!res.ok) throw new Error('Failed to fetch database status')
  return res.json()
}

export async function configureDatabase(config) {
  const res = await apiFetch(`${BASE_URL}/v1/database/configure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  if (!res.ok) throw new Error('Failed to configure database')
  return res.json()
}

export async function pollOperation(operationId, intervalMs = 150, maxAttempts = 150) {
  for (let i = 0; i < maxAttempts; i++) {
    const op = await getOperation(operationId)
    const st = (op.status || '').toUpperCase()
    if (st === 'COMPLETED' || st === 'STAGED') return op
    if (st === 'FAILED') throw new Error(op.error_message || 'Operation failed')
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  throw new Error('Operation polling timed out')
}

export async function runQuery(workspaceId, query, topicIds = null) {
  const payload = {
    workspace_id: workspaceId,
    query: query,
    top_k: 5,
  }
  if (topicIds && topicIds.length > 0) {
    payload.topic_ids = topicIds
  }

  const res = await apiFetch(`${BASE_URL}/v1/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Query failed' }))
    throw new Error(err.message || 'Query failed')
  }
  return res.json() // QueryResponse
}

export async function getTopics(workspaceId) {
  const res = await apiFetch(`${BASE_URL}/v1/topics?workspace_id=${encodeURIComponent(workspaceId)}`)
  if (!res.ok) throw new Error('Failed to load topics')
  return res.json()
}

export async function discoverTopics(workspaceId, k = 3) {
  const res = await apiFetch(`${BASE_URL}/v1/topics/discover?workspace_id=${encodeURIComponent(workspaceId)}&k=${k}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Failed to discover topics')
  return res.json()
}

export async function getChunkSource(chunkId) {
  const res = await apiFetch(`${BASE_URL}/v1/chunks/${chunkId}/source`)
  if (!res.ok) throw new Error('Failed to load chunk source')
  return res.json()
}

export async function getWorkspaceGraph(workspaceId) {
  const res = await apiFetch(`${BASE_URL}/v1/workspaces/${encodeURIComponent(workspaceId)}/graph`)
  if (!res.ok) throw new Error('Failed to load workspace graph')
  return res.json()
}
