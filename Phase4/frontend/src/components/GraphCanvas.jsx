import React, { useEffect, useRef, useState } from 'react'

/**
 * Interactive HTML5 Canvas Force-Directed Knowledge Graph component.
 * Supports zoom, pan, node dragging, click inspection, and visual distinctions:
 * - Factual edges (Solid Blue)
 * - Topic membership edges (Dashed Purple)
 * - Provenance edges (Dotted Teal)
 * - Highlighted answer paths (Bright Glow)
 * - Conflict pairs (Red / Amber highlight)
 */
export default function GraphCanvas({ graphData, onSelectElement, selectedElement }) {
  const canvasRef = useRef(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [nodes, setNodes] = useState([])
  const [edges, setEdges] = useState([])
  const draggingNodeRef = useRef(null)
  const isPanningRef = useRef(false)
  const lastMousePosRef = useRef({ x: 0, y: 0 })

  // Initialize or update nodes and edges with physics simulation positions
  useEffect(() => {
    if (!graphData || !graphData.nodes) return

    const width = canvasRef.current ? canvasRef.current.clientWidth : 800
    const height = canvasRef.current ? canvasRef.current.clientHeight : 600

    const currentNodesMap = new Map(nodes.map(n => [n.id, n]))

    const newNodes = graphData.nodes.map((n, i) => {
      const existing = currentNodesMap.get(n.id)
      const angle = (i / graphData.nodes.length) * 2 * Math.PI
      const radius = 150 + Math.random() * 100
      return {
        ...n,
        x: existing ? existing.x : width / 2 + Math.cos(angle) * radius,
        y: existing ? existing.y : height / 2 + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        radius: n.type === 'topic' ? 18 : n.type === 'document' ? 16 : 14,
      }
    })

    const nodeMap = new Map(newNodes.map(n => [n.id, n]))
    const newEdges = (graphData.edges || [])
      .map(e => ({
        ...e,
        sourceNode: nodeMap.get(e.source),
        targetNode: nodeMap.get(e.target),
      }))
      .filter(e => e.sourceNode && e.targetNode)

    setNodes(newNodes)
    setEdges(newEdges)
  }, [graphData])

  // Physics animation loop
  useEffect(() => {
    let animId
    const step = () => {
      // Repulsion between nodes
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x - nodes[i].x
          const dy = nodes[j].y - nodes[i].y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          if (dist < 220) {
            const force = (220 - dist) / dist * 0.08
            nodes[i].x -= dx * force
            nodes[i].y -= dy * force
            nodes[j].x += dx * force
            nodes[j].y += dy * force
          }
        }
      }

      // Spring attraction along edges
      edges.forEach(e => {
        if (!e.sourceNode || !e.targetNode) return
        const dx = e.targetNode.x - e.sourceNode.x
        const dy = e.targetNode.y - e.sourceNode.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const targetDist = 120
        const force = (dist - targetDist) * 0.02
        e.sourceNode.x += dx * force
        e.sourceNode.y += dy * force
        e.targetNode.x -= dx * force
        e.targetNode.y -= dy * force
      })

      draw()
      animId = requestAnimationFrame(step)
    }

    animId = requestAnimationFrame(step)
    return () => cancelAnimationFrame(animId)
  }, [nodes, edges, transform, graphData, selectedElement])

  const draw = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const width = canvas.clientWidth
    const height = canvas.clientHeight

    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }

    ctx.clearRect(0, 0, width, height)
    ctx.save()

    // Apply zoom & pan transform
    ctx.translate(transform.x, transform.y)
    ctx.scale(transform.k, transform.k)

    const highlightedIds = new Set(graphData?.highlighted_path_ids || [])

    // 1. Draw Edges
    edges.forEach(edge => {
      const s = edge.sourceNode
      const t = edge.targetNode
      if (!s || !t) return

      const isHighlighted = highlightedIds.has(edge.id)
      const isSelected = selectedElement && selectedElement.id === edge.id

      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)

      if (edge.edge_type === 'topic_membership') {
        ctx.strokeStyle = isHighlighted ? '#c084fc' : '#a855f7'
        ctx.lineWidth = isHighlighted ? 3 : 1.5
        ctx.setLineDash([5, 5]) // Dashed for topic membership
      } else if (edge.edge_type === 'provenance') {
        ctx.strokeStyle = isHighlighted ? '#2dd4bf' : '#14b8a6'
        ctx.lineWidth = isHighlighted ? 2.5 : 1.5
        ctx.setLineDash([2, 4]) // Dotted for provenance
      } else {
        // Factual relationship
        ctx.strokeStyle = isHighlighted ? '#38bdf8' : '#334155'
        ctx.lineWidth = isHighlighted ? 3 : isSelected ? 2.5 : 1.5
        ctx.setLineDash([]) // Solid
      }

      ctx.stroke()
      ctx.setLineDash([])

      // Draw Predicate Label
      const midX = (s.x + t.x) / 2
      const midY = (s.y + t.y) / 2
      ctx.fillStyle = isHighlighted ? '#f8fafc' : '#64748b'
      ctx.font = '10px Inter, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(edge.predicate, midX, midY - 6)
    })

    // 2. Draw Nodes
    nodes.forEach(node => {
      const isHighlighted = highlightedIds.has(node.id)
      const isSelected = selectedElement && selectedElement.id === node.id
      const isConflict = node.conflict_status === 'conflicting'

      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius, 0, 2 * Math.PI)

      // Node Fill based on type
      if (node.type === 'topic') {
        ctx.fillStyle = '#7c3aed' // Violet
      } else if (node.type === 'document') {
        ctx.fillStyle = '#f59e0b' // Amber
      } else if (node.type === 'chunk') {
        ctx.fillStyle = '#475569' // Slate
      } else if (node.type === 'value') {
        ctx.fillStyle = '#06b6d4' // Cyan
      } else {
        // Entity
        ctx.fillStyle = isHighlighted ? '#3b82f6' : '#1e293b'
      }
      ctx.fill()

      // Node Border / Glow
      if (isConflict) {
        ctx.strokeStyle = '#ef4444' // Red for conflict
        ctx.lineWidth = 3
      } else if (isSelected) {
        ctx.strokeStyle = '#f8fafc'
        ctx.lineWidth = 3
      } else if (isHighlighted) {
        ctx.strokeStyle = '#60a5fa'
        ctx.lineWidth = 2.5
      } else {
        ctx.strokeStyle = '#64748b'
        ctx.lineWidth = 1.5
      }
      ctx.stroke()

      // Node Label
      ctx.fillStyle = isHighlighted ? '#ffffff' : '#cbd5e1'
      ctx.font = isHighlighted ? 'bold 12px Outfit, sans-serif' : '11px Inter, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillText(node.name || node.label, node.x, node.y + node.radius + 4)
    })

    ctx.restore()
  }

  // Mouse event handlers for pan & zoom & click
  const handleMouseDown = e => {
    const rect = canvasRef.current.getBoundingClientRect()
    const mx = (e.clientX - rect.left - transform.x) / transform.k
    const my = (e.clientY - rect.top - transform.y) / transform.k

    // Check if clicked a node
    for (const node of nodes) {
      const dist = Math.hypot(node.x - mx, node.y - my)
      if (dist <= node.radius + 4) {
        draggingNodeRef.current = node
        onSelectElement && onSelectElement({ ...node, elementType: 'node' })
        return
      }
    }

    // Check if clicked an edge
    for (const edge of edges) {
      if (!edge.sourceNode || !edge.targetNode) continue
      const dist = distToSegment({ x: mx, y: my }, edge.sourceNode, edge.targetNode)
      if (dist < 6) {
        onSelectElement && onSelectElement({ ...edge, elementType: 'edge' })
        return
      }
    }

    // Panning canvas
    isPanningRef.current = true
    lastMousePosRef.current = { x: e.clientX, y: e.clientY }
  }

  const handleMouseMove = e => {
    if (draggingNodeRef.current) {
      const rect = canvasRef.current.getBoundingClientRect()
      draggingNodeRef.current.x = (e.clientX - rect.left - transform.x) / transform.k
      draggingNodeRef.current.y = (e.clientY - rect.top - transform.y) / transform.k
      return
    }

    if (isPanningRef.current) {
      const dx = e.clientX - lastMousePosRef.current.x
      const dy = e.clientY - lastMousePosRef.current.y
      lastMousePosRef.current = { x: e.clientX, y: e.clientY }
      setTransform(prev => ({ ...prev, x: prev.x + dx, y: prev.y + dy }))
    }
  }

  const handleMouseUp = () => {
    draggingNodeRef.current = null
    isPanningRef.current = false
  }

  const handleWheel = e => {
    e.preventDefault()
    const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9
    setTransform(prev => ({
      ...prev,
      k: Math.max(0.2, Math.min(3, prev.k * zoomFactor)),
    }))
  }

  const handleResetZoom = () => {
    setTransform({ x: 0, y: 0, k: 1 })
  }

  return (
    <div className="right-panel" id="graph-panel">
      <canvas
        id="graph-canvas"
        ref={canvasRef}
        className="graph-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
      />

      {/* Graph Toolbar */}
      <div className="graph-toolbar">
        <button
          className="toolbar-btn"
          id="zoom-in-btn"
          title="Zoom In"
          onClick={() => setTransform(t => ({ ...t, k: Math.min(3, t.k * 1.2) }))}
        >
          +
        </button>
        <button
          className="toolbar-btn"
          id="zoom-out-btn"
          title="Zoom Out"
          onClick={() => setTransform(t => ({ ...t, k: Math.max(0.2, t.k / 1.2) }))}
        >
          -
        </button>
        <button
          className="toolbar-btn"
          id="reset-zoom-btn"
          title="Reset View"
          onClick={handleResetZoom}
        >
          ⟲
        </button>
      </div>

      {/* Legend */}
      <div className="graph-legend">
        <div className="legend-item">
          <div className="legend-line-factual"></div>
          <span>Factual Relation (Solid)</span>
        </div>
        <div className="legend-item">
          <div className="legend-line-topic"></div>
          <span>Topic Scope (Dashed)</span>
        </div>
        <div className="legend-item">
          <div className="legend-line-provenance"></div>
          <span>Provenance (Dotted)</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot-conflict"></div>
          <span>Contradiction / Conflict</span>
        </div>
      </div>
    </div>
  )
}

function distToSegment(p, v, w) {
  const l2 = (v.x - w.x) ** 2 + (v.y - w.y) ** 2
  if (l2 === 0) return Math.hypot(p.x - v.x, p.y - v.y)
  let t = ((p.x - v.x) * (w.x - v.x) + (p.y - v.y) * (w.y - v.y)) / l2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(p.x - (v.x + t * (w.x - v.x)), p.y - (v.y + t * (w.y - v.y)))
}
