import React, { useEffect, useState } from 'react'
import DocumentUploader from './components/DocumentUploader'
import TopicPicker from './components/TopicPicker'
import ChatPanel from './components/ChatPanel'
import GraphCanvas from './components/GraphCanvas'
import InspectorModal from './components/InspectorModal'
import {
  getWorkspaceGraph,
  getTopics,
  discoverTopics,
  runQuery,
  getChunkSource,
} from './services/api'

export default function App() {
  const [workspaceId, setWorkspaceId] = useState('ws-default')
  const [topics, setTopics] = useState([])
  const [selectedTopicIds, setSelectedTopicIds] = useState([])
  const [graphData, setGraphData] = useState({ nodes: [], edges: [], highlighted_path_ids: [] })
  const [queryResponse, setQueryResponse] = useState(null)
  const [selectedElement, setSelectedElement] = useState(null)
  const [isQuerying, setIsQuerying] = useState(false)
  const [isDiscovering, setIsDiscovering] = useState(false)

  // Refresh workspace data
  const refreshWorkspace = async () => {
    try {
      const [gData, topData] = await Promise.all([
        getWorkspaceGraph(workspaceId).catch(() => ({ nodes: [], edges: [], highlighted_path_ids: [] })),
        getTopics(workspaceId).catch(() => ({ topics: [] })),
      ])
      setGraphData(gData)
      setTopics(topData.topics || [])
    } catch (err) {
      console.error('Error refreshing workspace:', err)
    }
  }

  useEffect(() => {
    refreshWorkspace()
  }, [workspaceId])

  // Handle Query Execution
  const handleRunQuery = async queryText => {
    setIsQuerying(true)
    try {
      const resp = await runQuery(workspaceId, queryText, selectedTopicIds)
      setQueryResponse(resp)
      // Update graph view with returned graph path slice
      if (resp.graph_path && resp.graph_path.nodes && resp.graph_path.nodes.length > 0) {
        setGraphData(resp.graph_path)
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

  // Toggle Topic Filter
  const handleToggleTopic = topicId => {
    if (topicId === 'ALL') {
      setSelectedTopicIds([])
    } else {
      setSelectedTopicIds(prev =>
        prev.includes(topicId) ? prev.filter(id => id !== topicId) : [...prev, topicId]
      )
    }
  }

  // Click on a source chunk citation
  const handleSelectChunk = async sourceChunk => {
    const chunkNode = graphData.nodes.find(n => n.id === `chunk:${sourceChunk.chunk_id}`)
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
        },
      })
    }
  }

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-icon">❖</div>
          <span className="brand-title">Interactive Knowledge Base</span>
        </div>

        <div className="header-controls">
          <div className="workspace-badge" id="workspace-badge">
            <div className="status-dot"></div>
            <span>Workspace:</span>
            <input
              type="text"
              value={workspaceId}
              onChange={e => setWorkspaceId(e.target.value.trim() || 'ws-default')}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.85rem',
                width: '100px',
                outline: 'none',
              }}
              id="workspace-input"
            />
          </div>
        </div>
      </header>

      {/* Split-screen layout */}
      <div className="split-screen">
        {/* Left Panel */}
        <aside className="left-panel" id="left-panel">
          <div className="left-panel-content">
            <DocumentUploader
              workspaceId={workspaceId}
              onUploadComplete={refreshWorkspace}
            />

            <TopicPicker
              topics={topics}
              selectedTopicIds={selectedTopicIds}
              onToggleTopic={handleToggleTopic}
              onDiscoverTopics={handleDiscoverTopics}
              isDiscovering={isDiscovering}
            />

            <ChatPanel
              onRunQuery={handleRunQuery}
              isQuerying={isQuerying}
              queryResponse={queryResponse}
              onSelectChunk={handleSelectChunk}
            />
          </div>
        </aside>

        {/* Right Panel: Interactive Graph */}
        <main className="right-panel">
          <GraphCanvas
            graphData={graphData}
            onSelectElement={setSelectedElement}
            selectedElement={selectedElement}
          />

          {/* Node/Edge Inspector Drawer */}
          <InspectorModal
            element={selectedElement}
            onClose={() => setSelectedElement(null)}
          />
        </main>
      </div>
    </div>
  )
}
