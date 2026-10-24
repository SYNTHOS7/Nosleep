import React, { useEffect, useRef, useState, useCallback } from 'react'

/**
 * Interactive HTML5 Canvas Force-Directed Knowledge Graph component.
 * Features:
 * - Robust alpha-cooled force simulation (NO node drift or disappearing!)
 * - Boundary clamping & centering gravity so nodes stay permanently visible
 * - Pan, zoom, node drag & drop
 * - Distinct styling for Documents (Amber), Topics (Purple), Entities (Blue), Chunks (Slate), Values (Cyan)
 * - Conflict highlights (Red outline) and query path glow
 * - Auto-fit view and Reset View controls
 */
export default function GraphCanvas({ graphData, onSelectElement, selectedElement }) {
  const canvasRef = useRef(null)
  const containerRef = useRef(null)
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [elementStats, setElementStats] = useState({ nodes: 0, edges: 0 })

  // Simulation state maintained in refs for ultra-smooth 60fps rendering without React jitter
  const simNodesRef = useRef([])
  const simEdgesRef = useRef([])
  const alphaRef = useRef(1.0)
  const draggingNodeRef = useRef(null)
  const isPanningRef = useRef(false)
  const lastMousePosRef = useRef({ x: 0, y: 0 })
  const animFrameRef = useRef(null)

  // Initialize or update nodes and edges when graphData changes
  useEffect(() => {
    if (!graphData || !graphData.nodes) return

    const canvas = canvasRef.current
    const width = canvas ? canvas.clientWidth || 800 : 800
    const height = canvas ? canvas.clientHeight || 600 : 600
    const cx = width / 2
    const cy = height / 2

    const existingMap = new Map(simNodesRef.current.map(n => [n.id, n]))
    const totalNodes = graphData.nodes.length

    const updatedNodes = graphData.nodes.map((n, i) => {
      const existing = existingMap.get(n.id)
      if (existing) {
        return {
          ...n,
          x: existing.x,
          y: existing.y,
          vx: existing.vx * 0.5,
          vy: existing.vy * 0.5,
          radius: n.type === 'topic' ? 20 : n.type === 'document' ? 18 : n.type === 'entity' ? 15 : 13,
        }
      }

      // Spiral arrangement around center for new nodes
      const goldenAngle = 2.399963
      const angle = i * goldenAngle
      const minDim = Math.min(width, height)
      const r = Math.min(minDim * 0.38, 50 + Math.sqrt((i + 1) / Math.max(1, totalNodes)) * (minDim * 0.32))

      return {
        ...n,
        x: cx + Math.cos(angle) * r,
        y: cy + Math.sin(angle) * r,
        vx: (Math.random() - 0.5) * 2,
        vy: (Math.random() - 0.5) * 2,
        radius: n.type === 'topic' ? 20 : n.type === 'document' ? 18 : n.type === 'entity' ? 15 : 13,
      }
    })

    const nodeMap = new Map(updatedNodes.map(n => [n.id, n]))
    const updatedEdges = (graphData.edges || [])
      .map(e => ({
        ...e,
        sourceNode: nodeMap.get(e.source),
        targetNode: nodeMap.get(e.target),
      }))
      .filter(e => e.sourceNode && e.targetNode)

    simNodesRef.current = updatedNodes
    simEdgesRef.current = updatedEdges
    setElementStats({ nodes: updatedNodes.length, edges: updatedEdges.length })

    // Re-heat simulation smoothly to settle new nodes, then freeze
    alphaRef.current = 1.0
  }, [graphData])

  // Draw loop and physics step
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    const stepSimulation = () => {
      const width = canvas.clientWidth || 800
      const height = canvas.clientHeight || 600
      const cx = width / 2
      const cy = height / 2

      const simNodes = simNodesRef.current
      const simEdges = simEdgesRef.current
      const alpha = alphaRef.current

      // Only calculate physics while alpha is active
      if (alpha > 0.003 && simNodes.length > 0) {
        // 1. Centering gravity force (pulls all nodes gently to viewport center)
        const centerGravity = 0.025 * alpha
        for (let i = 0; i < simNodes.length; i++) {
          const n = simNodes[i]
          n.vx += (cx - n.x) * centerGravity
          n.vy += (cy - n.y) * centerGravity
        }

        // 2. Node-node bounded repulsion
        for (let i = 0; i < simNodes.length; i++) {
          for (let j = i + 1; j < simNodes.length; j++) {
            const ni = simNodes[i]
            const nj = simNodes[j]
            const dx = nj.x - ni.x
            const dy = nj.y - ni.y
            const dist = Math.hypot(dx, dy) || 1
            const idealDist = ni.radius + nj.radius + 45

            if (dist < idealDist * 2.5) {
              const force = Math.min(7.0, ((idealDist * 2.5 - dist) / (idealDist * 2.5)) * 4.0) * alpha
              const fx = (dx / dist) * force
              const fy = (dy / dist) * force
              ni.vx -= fx
              ni.vy -= fy
              nj.vx += fx
              nj.vy += fy
            }
          }
        }

        // 3. Edge spring attraction
        simEdges.forEach(e => {
          const s = e.sourceNode
          const t = e.targetNode
          if (!s || !t) return
          const dx = t.x - s.x
          const dy = t.y - s.y
          const dist = Math.hypot(dx, dy) || 1
          const targetDist = e.edge_type === 'provenance' ? 75 : e.edge_type === 'topic_membership' ? 95 : 110
          const force = (dist - targetDist) * 0.035 * alpha
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          s.vx += fx
          s.vy += fy
          t.vx -= fx
          t.vy -= fy
        })

        // 4. Velocity damping & position updates with strict canvas boundary clamps
        const friction = 0.82
        for (let i = 0; i < simNodes.length; i++) {
          const n = simNodes[i]
          n.vx *= friction
          n.vy *= friction

          const speed = Math.hypot(n.vx, n.vy)
          if (speed > 8) {
            n.vx = (n.vx / speed) * 8
            n.vy = (n.vy / speed) * 8
          }

          if (draggingNodeRef.current !== n) {
            n.x += n.vx
            n.y += n.vy

            // Hard boundary clamping: node CAN NEVER LEAVE CANVAS!
            const pad = n.radius + 35
            n.x = Math.max(pad, Math.min(width - pad, n.x))
            n.y = Math.max(pad, Math.min(height - pad, n.y))
          }
        }

        // Cool down physics simulation smoothly
        alphaRef.current *= 0.965
        if (alphaRef.current < 0.003) {
          alphaRef.current = 0 // Freeze completely so nodes stay locked in place
        }
      }

      // Draw frame
      renderScene(ctx, width, height, simNodes, simEdges)

      animFrameRef.current = requestAnimationFrame(stepSimulation)
    }

    animFrameRef.current = requestAnimationFrame(stepSimulation)
    return () => cancelAnimationFrame(animFrameRef.current)
  }, [transform, selectedElement, graphData])

  const renderScene = (ctx, width, height, simNodes, simEdges) => {
    const canvas = canvasRef.current
    if (!canvas) return

    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }

    ctx.clearRect(0, 0, width, height)
    ctx.save()

    // Pan and Zoom
    ctx.translate(transform.x, transform.y)
    ctx.scale(transform.k, transform.k)

    const highlightedIds = new Set(graphData?.highlighted_path_ids || [])

    // 1. Draw Edges
    simEdges.forEach(edge => {
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
        ctx.setLineDash([5, 5])
      } else if (edge.edge_type === 'provenance') {
        ctx.strokeStyle = isHighlighted ? '#2dd4bf' : '#0d9488'
        ctx.lineWidth = isHighlighted ? 2.5 : 1.5
        ctx.setLineDash([2, 4])
      } else {
        // Factual relationship
        ctx.strokeStyle = isHighlighted ? '#38bdf8' : isSelected ? '#f8fafc' : '#334155'
        ctx.lineWidth = isHighlighted ? 3 : isSelected ? 2.5 : 1.5
        ctx.setLineDash([])
      }

      ctx.stroke()
      ctx.setLineDash([])

      // Edge Predicate Label
      if (transform.k > 0.5) {
        const midX = (s.x + t.x) / 2
        const midY = (s.y + t.y) / 2
        ctx.fillStyle = isHighlighted ? '#f8fafc' : '#64748b'
        ctx.font = '10px Inter, sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(edge.predicate, midX, midY - 6)
      }
    })

    // 2. Draw Nodes
    simNodes.forEach(node => {
      const isHighlighted = highlightedIds.has(node.id)
      const isSelected = selectedElement && selectedElement.id === node.id
      const isConflict = node.conflict_status === 'conflicting'

      // Node Shadow / Glow when selected or highlighted
      if (isSelected || isHighlighted || isConflict) {
        ctx.save()
        ctx.shadowColor = isConflict ? '#ef4444' : isHighlighted ? '#38bdf8' : '#ffffff'
        ctx.shadowBlur = 12
        ctx.beginPath()
        ctx.arc(node.x, node.y, node.radius + 2, 0, 2 * Math.PI)
        ctx.fillStyle = isConflict ? '#ef4444' : isHighlighted ? '#38bdf8' : '#ffffff'
        ctx.fill()
        ctx.restore()
      }

      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius, 0, 2 * Math.PI)

      // Color coding by type
      if (node.type === 'document') {
        ctx.fillStyle = '#f59e0b' // Amber for Documents
      } else if (node.type === 'topic') {
        ctx.fillStyle = '#9333ea' // Purple for Topics
      } else if (node.type === 'chunk') {
        ctx.fillStyle = '#475569' // Slate for Chunks
      } else if (node.type === 'value') {
        ctx.fillStyle = '#06b6d4' // Cyan for Values
      } else {
        ctx.fillStyle = isHighlighted ? '#2563eb' : '#1e293b' // Blue for Entities
      }
      ctx.fill()

      // Border
      ctx.lineWidth = isSelected ? 3 : isHighlighted ? 2.5 : 1.5
      ctx.strokeStyle = isConflict ? '#ef4444' : isSelected ? '#ffffff' : isHighlighted ? '#60a5fa' : '#475569'
      ctx.stroke()

      // Center icon/symbol
      ctx.fillStyle = '#ffffff'
      ctx.font = '11px sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      const icon = node.type === 'document' ? '📄' : node.type === 'topic' ? '🏷️' : node.type === 'chunk' ? '§' : '●'
      ctx.fillText(icon, node.x, node.y)

      // Node Label
      ctx.fillStyle = isHighlighted || isSelected ? '#ffffff' : '#cbd5e1'
      ctx.font = isHighlighted || isSelected ? 'bold 11px Outfit, sans-serif' : '10px Inter, sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      const labelText = node.name || node.label || 'Node'
      const truncatedLabel = labelText.length > 22 ? `${labelText.slice(0, 20)}…` : labelText
      ctx.fillText(truncatedLabel, node.x, node.y + node.radius + 4)
    })

    ctx.restore()
  }

  // Mouse Handlers
  const handleMouseDown = e => {
    const rect = canvasRef.current.getBoundingClientRect()
    const mx = (e.clientX - rect.left - transform.x) / transform.k
    const my = (e.clientY - rect.top - transform.y) / transform.k

    // 1. Check if clicked a node
    for (const node of simNodesRef.current) {
      const dist = Math.hypot(node.x - mx, node.y - my)
      if (dist <= node.radius + 6) {
        draggingNodeRef.current = node
        alphaRef.current = 0.25 // Reactivate physics gently
        onSelectElement && onSelectElement({ ...node, elementType: 'node' })
        return
      }
    }

    // 2. Check if clicked an edge
    for (const edge of simEdgesRef.current) {
      if (!edge.sourceNode || !edge.targetNode) continue
      const dist = distToSegment({ x: mx, y: my }, edge.sourceNode, edge.targetNode)
      if (dist < 8) {
        onSelectElement && onSelectElement({ ...edge, elementType: 'edge' })
        return
      }
    }

    // 3. Otherwise, start panning canvas
    isPanningRef.current = true
    lastMousePosRef.current = { x: e.clientX, y: e.clientY }
  }

  const handleMouseMove = e => {
    if (draggingNodeRef.current) {
      const rect = canvasRef.current.getBoundingClientRect()
      draggingNodeRef.current.x = (e.clientX - rect.left - transform.x) / transform.k
      draggingNodeRef.current.y = (e.clientY - rect.top - transform.y) / transform.k
      draggingNodeRef.current.vx = 0
      draggingNodeRef.current.vy = 0
      alphaRef.current = 0.15
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
    const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89
    setTransform(prev => ({
      ...prev,
      k: Math.max(0.2, Math.min(4, prev.k * zoomFactor)),
    }))
  }

  const handleResetZoom = () => {
    setTransform({ x: 0, y: 0, k: 1 })
    alphaRef.current = 0.5
  }

  const handleFitView = () => {
    const nodes = simNodesRef.current
    if (!nodes.length || !canvasRef.current) return
    const width = canvasRef.current.clientWidth || 800
    const height = canvasRef.current.clientHeight || 600

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    nodes.forEach(n => {
      minX = Math.min(minX, n.x - n.radius)
      maxX = Math.max(maxX, n.x + n.radius)
      minY = Math.min(minY, n.y - n.radius)
      maxY = Math.max(maxY, n.y + n.radius)
    })

    const graphWidth = maxX - minX || 200
    const graphHeight = maxY - minY || 200
    const scale = Math.min(2.5, Math.max(0.3, Math.min((width * 0.85) / graphWidth, (height * 0.85) / graphHeight)))
    const midX = (minX + maxX) / 2
    const midY = (minY + maxY) / 2

    setTransform({
      k: scale,
      x: width / 2 - midX * scale,
      y: height / 2 - midY * scale,
    })
  }

  return (
    <div className="right-panel" id="graph-panel" ref={containerRef} style={{ position: 'relative' }}>
      <canvas
        id="graph-canvas"
        ref={canvasRef}
        className="graph-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
      />

      {/* Stats Badge */}
      <div
        style={{
          position: 'absolute',
          top: '16px',
          right: '16px',
          background: 'rgba(15, 23, 42, 0.75)',
          backdropFilter: 'blur(8px)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          borderRadius: '8px',
          padding: '6px 12px',
          fontSize: '0.75rem',
          color: 'var(--text-secondary)',
          display: 'flex',
          gap: '12px',
          pointerEvents: 'none',
        }}
      >
        <span><strong>{elementStats.nodes}</strong> nodes</span>
        <span><strong>{elementStats.edges}</strong> edges</span>
      </div>

      {/* Graph Toolbar */}
      <div className="graph-toolbar">
        <button
          className="toolbar-btn"
          id="zoom-in-btn"
          title="Zoom In"
          onClick={() => setTransform(t => ({ ...t, k: Math.min(4, t.k * 1.25) }))}
        >
          +
        </button>
        <button
          className="toolbar-btn"
          id="zoom-out-btn"
          title="Zoom Out"
          onClick={() => setTransform(t => ({ ...t, k: Math.max(0.2, t.k / 1.25) }))}
        >
          -
        </button>
        <button
          className="toolbar-btn"
          id="fit-view-btn"
          title="Fit to Screen"
          onClick={handleFitView}
        >
          ⛶
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
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#f59e0b' }}></div>
          <span>Document</span>
        </div>
        <div className="legend-item">
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#9333ea' }}></div>
          <span>Topic</span>
        </div>
        <div className="legend-item">
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#38bdf8' }}></div>
          <span>Entity</span>
        </div>
        <div className="legend-item">
          <div className="legend-line-factual"></div>
          <span>Factual Relation</span>
        </div>
        <div className="legend-item">
          <div className="legend-dot-conflict"></div>
          <span>Conflict</span>
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
