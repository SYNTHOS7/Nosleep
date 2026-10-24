/**
 * API client service connecting React frontend to FastAPI Person 4 backend.
 */

const BASE_URL = ''

export async function getHealth() {
  const res = await fetch(`${BASE_URL}/health`)
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

  const res = await fetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Upload failed' }))
    throw new Error(err.message || 'Upload failed')
  }
  return res.json() // MutationReceipt
}

export async function editDocument(workspaceId, docId, expectedRevisionId, { file, rawText, filename }) {
  const formData = new FormData()
  formData.append('expected_revision_id', expectedRevisionId)
  if (file) formData.append('file', file)
  if (rawText) formData.append('raw_text', rawText)
  if (filename) formData.append('filename', filename)

  const res = await fetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents/${docId}`, {
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
  const res = await fetch(`${BASE_URL}/v1/workspaces/${workspaceId}/documents/${docId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: 'Delete failed' }))
    throw new Error(err.message || 'Delete failed')
  }
  return res.json()
}

export async function getOperation(operationId) {
  const res = await fetch(`${BASE_URL}/v1/operations/${operationId}`)
  if (!res.ok) throw new Error('Failed to fetch operation')
  return res.json()
}

export async function pollOperation(operationId, intervalMs = 150, maxAttempts = 100) {
  for (let i = 0; i < maxAttempts; i++) {
    const op = await getOperation(operationId)
    if (op.status === 'COMPLETED') return op
    if (op.status === 'FAILED') throw new Error(op.error_message || 'Operation failed')
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

  const res = await fetch(`${BASE_URL}/v1/query`, {
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
  const res = await fetch(`${BASE_URL}/v1/topics?workspace_id=${encodeURIComponent(workspaceId)}`)
  if (!res.ok) throw new Error('Failed to load topics')
  return res.json()
}

export async function discoverTopics(workspaceId, k = 3) {
  const res = await fetch(`${BASE_URL}/v1/topics/discover?workspace_id=${encodeURIComponent(workspaceId)}&k=${k}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('Failed to discover topics')
  return res.json()
}

export async function getChunkSource(chunkId) {
  const res = await fetch(`${BASE_URL}/v1/chunks/${chunkId}/source`)
  if (!res.ok) throw new Error('Failed to load chunk source')
  return res.json()
}

export async function getWorkspaceGraph(workspaceId) {
  const res = await fetch(`${BASE_URL}/v1/workspaces/${encodeURIComponent(workspaceId)}/graph`)
  if (!res.ok) throw new Error('Failed to load workspace graph')
  return res.json()
}
