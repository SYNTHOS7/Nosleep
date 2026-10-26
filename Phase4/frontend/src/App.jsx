import React, { useEffect, useState } from 'react'
import DocumentUploader from './components/DocumentUploader'
import DocumentList from './components/DocumentList'
import TopicPicker from './components/TopicPicker'
import ChatPanel from './components/ChatPanel'
import GraphCanvas from './components/GraphCanvas'
import InspectorModal from './components/InspectorModal'
import DatabaseModal from './components/DatabaseModal'
import {
  getWorkspaceGraph,
  getTopics,
  discoverTopics,
  runQuery,
  getChunkSource,
  getWorkspaceDocuments,
  deleteDocument,
  editDocument,
  getDatabaseStatus,
  loadCyberDemo,
} from './services/api'

export default function App({ session = { demo: true, workspaces: {} }, onSignOut }) {
  const [workspaceId, setWorkspaceId] = useState(Object.keys(session.workspaces)[0] || 'ws-default')
  const canWrite = session.demo || session.platform_admin || ['editor', 'admin'].includes(session.workspaces[workspaceId])
  const [topics, setTopics] = useState([])
  const [documents, setDocuments] = useState([])
  const [selectedTopicIds, setSelectedTopicIds] = useState([])
  const [graphData, setGraphData] = useState({ nodes: [], edges: [], highlighted_path_ids: [] })
  const [queryResponse, setQueryResponse] = useState(null)
  const [selectedElement, setSelectedElement] = useState(null)
  const [focusElementId, setFocusElementId] = useState(null)
  const [isQuerying, setIsQuerying] = useState(false)
  const [isDiscovering, setIsDiscovering] = useState(false)
  const [dbStatus, setDbStatus] = useState(null)
  const [showDbModal, setShowDbModal] = useState(false)
  const [isLoadingDemo, setIsLoadingDemo] = useState(false)

  // Workbench state
  const [activeTab, setActiveTab] = useState('chat') // 'chat' | 'documents' | 'topics'
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Refresh all workspace data (graph, topics, documents, and database status)
  const refreshWorkspace = async () => {
    try {
      const [gData, topData, docsData, dStatus] = await Promise.all([
        getWorkspaceGraph(workspaceId).catch(() => ({ nodes: [], edges: [], highlighted_path_ids: [] })),
        getTopics(workspaceId).catch(() => ({ topics: [] })),
        getWorkspaceDocuments(workspaceId).catch(() => ({ documents: [] })),
        getDatabaseStatus().catch(() => null),
      ])
      setGraphData(gData)
      setTopics(topData.topics || [])
      setDocuments(docsData.documents || [])
      if (dStatus) setDbStatus(dStatus)
    } catch (err) {
      console.error('Error refreshing workspace:', err)
    }
  }

  useEffect(() => {
    refreshWorkspace()
  }, [workspaceId])

  // Handle Query Execution without wiping out non-query nodes
  const handleLoadDemo = async () => {
    setIsLoadingDemo(true)
    try {
      await loadCyberDemo(workspaceId)
      setSelectedTopicIds([])
      setQueryResponse(null)
      await refreshWorkspace()
    } catch (err) {
      alert(err.message)
    } finally {
      setIsLoadingDemo(false)
    }
  }

  const handleRunQuery = async (queryText) => {
    setIsQuerying(true)
    try {
      const resp = await runQuery(workspaceId, queryText, selectedTopicIds)
      setQueryResponse(resp)

      // Merge returned slice with full workspace graph so previous nodes stay permanently
      if (resp.graph_path && resp.graph_path.nodes && resp.graph_path.nodes.length > 0) {
        setGraphData((prev) => {
          const nodeMap = new Map(prev.nodes.map((n) => [n.id, n]))
          resp.graph_path.nodes.forEach((n) => {
            const existing = nodeMap.get(n.id)
            nodeMap.set(n.id, existing ? { ...existing, ...n } : n)
          })
          const edgeMap = new Map(prev.edges.map((e) => [e.id, e]))
          resp.graph_path.edges.forEach((e) => {
            const existing = edgeMap.get(e.id)
            edgeMap.set(e.id, existing ? { ...existing, ...e } : e)
          })
          return {
            nodes: Array.from(nodeMap.values()),
            edges: Array.from(edgeMap.values()),
            highlighted_path_ids: resp.graph_path.highlighted_path_ids || [],
          }
        })

        // Auto-focus on first seed chunk returned if available
        if (resp.source_chunks && resp.source_chunks.length > 0) {
          setFocusElementId(`chunk:${resp.source_chunks[0].chunk_id}`)
        }
      }
    } catch (err) {
      alert(`Query failed: ${err.message}`)
    } finally {
      setIsQuerying(false)
    }
  }

  // Handle Topic Discovery
  const handleDiscoverTopics = async () => {
    setIsDiscovering(true)
    try {
      const topList = await discoverTopics(workspaceId, 3)
      setTopics(topList.topics || [])
      await refreshWorkspace()
    } catch (err) {
      alert(`Topic discovery failed: ${err.message}`)
    } finally {
      setIsDiscovering(false)
    }
  }

  // Handle Document Deletion
  const handleDeleteDocument = async (docId) => {
    if (!confirm('Are you sure you want to delete this document from the workspace?')) return
    try {
      await deleteDocument(workspaceId, docId)
      await refreshWorkspace()
    } catch (err) {
      alert(`Delete failed: ${err.message}`)
    }
  }

  // Handle Document Edit without Rebuild
  const handleEditDocument = async (docId, currentRev, newText, filename) => {
    try {
      await editDocument(workspaceId, docId, currentRev, { rawText: newText, filename })
      await refreshWorkspace()
    } catch (err) {
      alert(`Edit failed: ${err.message}`)
      throw err
    }
  }

  // Toggle Topic Filter
  const handleToggleTopic = (topicId) => {
    if (topicId === 'ALL') {
      setSelectedTopicIds([])
    } else {
      setSelectedTopicIds((prev) =>
        prev.includes(topicId) ? prev.filter((id) => id !== topicId) : [...prev, topicId]
      )
    }
  }

  // Click on a source chunk citation -> focus on its card
  const handleSelectChunk = async (sourceChunk) => {
    const chunkNode = graphData.nodes.find((n) => n.id === `chunk:${sourceChunk.chunk_id}`)
    const targetId = `chunk:${sourceChunk.chunk_id}`
    setFocusElementId(targetId)

    if (chunkNode) {
      setSelectedElement({ ...chunkNode, elementType: 'node' })
    } else {
      setSelectedElement({
        elementType: 'node',
        label: 'Chunk',
        name: `Chunk (${sourceChunk.source_name})`,
        document_id: sourceChunk.document_id,
        exact_quote: sourceChunk.exact_quote,
        properties: {
          page: sourceChunk.page_number,
          revision: sourceChunk.revision,
          source_name: sourceChunk.source_name,
          text: sourceChunk.exact_quote,
        },
      })
    }
  }

  // Select document and focus in graph
  const handleSelectDocument = (doc) => {
    const docNodeId = `doc:${doc.id}`
    setFocusElementId(docNodeId)
    setSelectedElement({
      id: docNodeId,
      elementType: 'node',
      label: 'Document',
      name: doc.source_name,
      properties: {
        source_type: doc.source_type,
        revision: doc.revision,
        chunk_count: doc.chunk_count,
      },
    })
  }

  return (
    <div className="app-container">
      {/* Top Application Bar */}
      <header className="app-header">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="badge">{session.demo ? 'Local demo · no login' : session.email}</span>
          {!session.demo && <button className="btn-primary" onClick={onSignOut}>Sign out</button>}
        </div>
        <div className="header-brand">
          <div className="brand-icon">❖</div>
          <div className="brand-title-wrap">
            <span className="brand-title">AegisGraph AI</span>
            <span className="brand-subtitle">Cyber Threat Intelligence & Attack Paths</span>
          </div>
        </div>

        <div className="header-controls">
          {/* Active Topic Filters Indicator */}
          {selectedTopicIds.length > 0 && (
            <div
              className="active-filter-badge"
              onClick={() => setActiveTab('topics')}
              title="Click to adjust thematic scoping"
            >
              <span className="filter-dot"></span>
              <span>
                Filter: <strong>{selectedTopicIds.length}</strong> topic{selectedTopicIds.length > 1 ? 's' : ''}
              </span>
            </div>
          )}

          {/* Database Connection Pill */}
          <div
            className="workspace-badge"
            id="db-status-badge"
            onClick={() => setShowDbModal(true)}
            title="Click to view Database connection details and configure Neo4j Aura"
            style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <span
              style={{
                color:
                  dbStatus?.chromadb?.status === 'connected_persistent' ? '#10b981' : '#06b6d4',
              }}
            >
              ●
            </span>
            <span>
              DB: {dbStatus?.vector_backend === 'firebase' ? 'Firebase' : 'Local'} + {dbStatus?.neo4j?.status === 'connected' ? 'Neo4j Aura' : 'Embedded'}
            </span>
            <span style={{ fontSize: '0.75rem', opacity: 0.6 }}>⚙</span>
          </div>

          {/* Workspace ID Input */}
          <div className="workspace-badge" id="workspace-badge">
            <div className="status-dot"></div>
            <span>Workspace:</span>
            {(session.demo || session.platform_admin) ? <input
              type="text"
              value={workspaceId}
              onChange={(e) => setWorkspaceId(e.target.value.trim() || 'ws-default')}
              className="workspace-input"
              id="workspace-input"
            /> : <select aria-label="Workspace" className="workspace-input" value={workspaceId} onChange={event => setWorkspaceId(event.target.value)}>
              {Object.keys(session.workspaces).map(name => <option key={name} value={name}>{name} ({session.workspaces[name]})</option>)}
            </select>}
          </div>
        </div>
      </header>

      {/* Main Split-Screen Workspace */}
      <div className="split-screen">
        {/* Left Workbench Panel */}
        <aside
          className={`left-panel ${sidebarCollapsed ? 'collapsed' : ''}`}
          id="left-panel"
        >
          {/* Workbench Tab Switcher Navigation */}
          <div className="workbench-nav">
            <button
              className={`workbench-tab ${activeTab === 'chat' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('chat')
                if (sidebarCollapsed) setSidebarCollapsed(false)
              }}
              id="tab-chat-btn"
              title="Grounded Query & Reasoning"
            >
              <span className="tab-icon">💬</span>
              {!sidebarCollapsed && <span className="tab-title">Reasoner</span>}
              {queryResponse && <span className="tab-indicator green"></span>}
            </button>

            <button
              className={`workbench-tab ${activeTab === 'documents' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('documents')
                if (sidebarCollapsed) setSidebarCollapsed(false)
              }}
              id="tab-documents-btn"
              title="Corpus & Document Library"
            >
              <span className="tab-icon">📚</span>
              {!sidebarCollapsed && (
                <>
                  <span className="tab-title">Corpus</span>
                  <span className="tab-badge">{documents.length}</span>
                </>
              )}
            </button>

            <button
              className={`workbench-tab ${activeTab === 'topics' ? 'active' : ''}`}
              onClick={() => {
                setActiveTab('topics')
                if (sidebarCollapsed) setSidebarCollapsed(false)
              }}
              id="tab-topics-btn"
              title="Thematic Clusters"
            >
              <span className="tab-icon">🏷️</span>
              {!sidebarCollapsed && (
                <>
                  <span className="tab-title">Themes</span>
                  <span className="tab-badge">{topics.length}</span>
                </>
              )}
            </button>

            <button
              className="sidebar-collapse-btn"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              title={sidebarCollapsed ? 'Expand Workbench' : 'Collapse Workbench'}
              id="collapse-sidebar-btn"
            >
              {sidebarCollapsed ? '▶' : '◀'}
            </button>
          </div>

          {/* Active Tab Panel Content */}
          {!sidebarCollapsed && (
            <div className="left-panel-content">
              {activeTab === 'chat' && (
                <ChatPanel
                  onRunQuery={handleRunQuery}
                  isQuerying={isQuerying}
                  queryResponse={queryResponse}
                  onSelectChunk={handleSelectChunk}
                  onLoadDemo={handleLoadDemo}
                  isLoadingDemo={isLoadingDemo}
                  canWrite={canWrite}
                />
              )}

              {activeTab === 'documents' && (
                <>
                  {canWrite && <DocumentUploader
                    workspaceId={workspaceId}
                    onUploadComplete={refreshWorkspace}
                  />}
                  <DocumentList
                    documents={documents}
                    onSelectDocument={handleSelectDocument}
                    onEditDocument={handleEditDocument}
                    onDeleteDocument={handleDeleteDocument}
                    readOnly={!canWrite}
                  />
                </>
              )}

              {activeTab === 'topics' && (
                <TopicPicker
                  topics={topics}
                  selectedTopicIds={selectedTopicIds}
                  onToggleTopic={handleToggleTopic}
                  onDiscoverTopics={handleDiscoverTopics}
                  isDiscovering={isDiscovering || !canWrite}
                />
              )}
            </div>
          )}
        </aside>

        {/* Floating Sidebar Restore Button if collapsed */}
        {sidebarCollapsed && (
          <button
            className="floating-expand-btn"
            onClick={() => setSidebarCollapsed(false)}
            title="Expand Workbench"
          >
            ▶ Open Reasoner & Docs
          </button>
        )}

        {/* Right Panel: Interactive Dual-Mode Knowledge Canvas */}
        <main className="right-panel">
          <GraphCanvas
            graphData={graphData}
            onSelectElement={setSelectedElement}
            selectedElement={selectedElement}
            focusElementId={focusElementId}
            queryResponse={queryResponse}
          />

          {/* Granular Node & Edge Inspector Modal */}
          <InspectorModal
            element={selectedElement}
            onClose={() => setSelectedElement(null)}
          />

          {/* Database & Neo4j Settings Modal */}
          {showDbModal && (
            <DatabaseModal
              dbStatus={dbStatus}
              onClose={() => setShowDbModal(false)}
              onRefresh={refreshWorkspace}
              canConfigure={!session.demo && session.platform_admin}
            />
          )}
        </main>
      </div>
    </div>
  )
}
