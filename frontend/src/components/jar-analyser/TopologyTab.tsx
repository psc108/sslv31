import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface TopoNode { id: string; label: string; type: string; port: number | null }
interface TopoEdge { from: string; to: string; via: string; label: string }
interface TopoGraph { nodes: TopoNode[]; edges: TopoEdge[] }

const VIA_COLOUR: Record<string, string> = {
  event:   '#f59e0b',
  nginx:   '#6366f1',
  api_url: '#10b981',
}
const VIA_LABEL: Record<string, string> = {
  event:   'Event',
  nginx:   'Nginx proxy',
  api_url: 'API call',
}
const NODE_COLOUR: Record<string, string> = {
  load_balancer: '#fbbf24',
  frontend:      '#818cf8',
  infrastructure:'#9ca3af',
  service:       '#60a5fa',
}

// Canvas logical size — nodes spread across this space
const CW = 2400
const CH = 1800
const NODE_R = 28

// ── Force layout ──────────────────────────────────────────────────────────

function runForceLayout(
  nodes: TopoNode[],
  edges: TopoEdge[],
): Record<string, { x: number; y: number }> {
  const p: Record<string, { x: number; y: number }> = {}
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length
    p[n.id] = {
      x: CW / 2 + CW * 0.38 * Math.cos(angle),
      y: CH / 2 + CH * 0.38 * Math.sin(angle),
    }
  })

  const REPEL = 18000, ATTRACT = 0.03, DAMP = 0.82, STEPS = 200
  const vel: Record<string, { vx: number; vy: number }> = {}
  nodes.forEach(n => { vel[n.id] = { vx: 0, vy: 0 } })

  for (let s = 0; s < STEPS; s++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i].id, b = nodes[j].id
        const dx = p[a].x - p[b].x, dy = p[a].y - p[b].y
        const d2 = dx * dx + dy * dy + 1
        const f = REPEL / d2
        vel[a].vx += f * dx; vel[a].vy += f * dy
        vel[b].vx -= f * dx; vel[b].vy -= f * dy
      }
    }
    edges.forEach(e => {
      if (!p[e.from] || !p[e.to]) return
      const dx = p[e.to].x - p[e.from].x, dy = p[e.to].y - p[e.from].y
      vel[e.from].vx += ATTRACT * dx; vel[e.from].vy += ATTRACT * dy
      vel[e.to].vx -= ATTRACT * dx; vel[e.to].vy -= ATTRACT * dy
    })
    nodes.forEach(n => {
      vel[n.id].vx *= DAMP; vel[n.id].vy *= DAMP
      p[n.id].x = Math.max(NODE_R + 10, Math.min(CW - NODE_R - 10, p[n.id].x + vel[n.id].vx))
      p[n.id].y = Math.max(NODE_R + 20, Math.min(CH - NODE_R - 20, p[n.id].y + vel[n.id].vy))
    })
  }
  return p
}

// ── Deduplicate edges for display ─────────────────────────────────────────

interface DisplayEdge {
  from: string; to: string
  vias: string[]          // all via types on this pair
  labels: string[]        // all labels
  primaryVia: string
  count: number
}

function dedupeEdges(edges: TopoEdge[]): DisplayEdge[] {
  const map = new Map<string, DisplayEdge>()
  edges.forEach(e => {
    const key = `${e.from}→${e.to}`
    const existing = map.get(key)
    if (existing) {
      if (!existing.vias.includes(e.via)) existing.vias.push(e.via)
      if (e.label && !existing.labels.includes(e.label)) existing.labels.push(e.label)
      existing.count++
    } else {
      map.set(key, { from: e.from, to: e.to, vias: [e.via], labels: e.label ? [e.label] : [], primaryVia: e.via, count: 1 })
    }
  })
  return Array.from(map.values())
}

// ── SVG Diagram (interactive) ─────────────────────────────────────────────

interface DiagramProps {
  graph: TopoGraph
  height: number
}

function TopologyDiagram({ graph, height }: DiagramProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [pos, setPos] = useState<Record<string, { x: number; y: number }>>({})
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 })
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)

  // pan state
  const panning = useRef(false)
  const panStart = useRef({ mx: 0, my: 0, tx: 0, ty: 0 })

  // drag state
  const dragging = useRef<string | null>(null)
  const dragStart = useRef({ mx: 0, my: 0, nx: 0, ny: 0 })

  // Run layout once on mount / node change
  useEffect(() => {
    if (!graph.nodes.length) return
    const p = runForceLayout(graph.nodes, graph.edges)
    setPos(p)
    // Fit to view: centre the layout in the SVG
    setTransform({ x: 0, y: 0, scale: 1 })
  }, [graph.nodes.length, graph.edges.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const displayEdges = useMemo(() => dedupeEdges(graph.edges), [graph.edges])

  // ── Wheel zoom ────────────────────────────────────────────────────────
  const onWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault()
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12
    setTransform(t => {
      const newScale = Math.max(0.15, Math.min(4, t.scale * factor))
      // Zoom toward cursor
      const rect = svgRef.current!.getBoundingClientRect()
      const cx = e.clientX - rect.left
      const cy = e.clientY - rect.top
      return {
        scale: newScale,
        x: cx - (cx - t.x) * (newScale / t.scale),
        y: cy - (cy - t.y) * (newScale / t.scale),
      }
    })
  }, [])

  // ── Pan ───────────────────────────────────────────────────────────────
  const onSvgMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as SVGElement).closest('.topo-node')) return
    panning.current = true
    panStart.current = { mx: e.clientX, my: e.clientY, tx: transform.x, ty: transform.y }
  }, [transform])

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (dragging.current) {
      const dx = (e.clientX - dragStart.current.mx) / transform.scale
      const dy = (e.clientY - dragStart.current.my) / transform.scale
      setPos(p => ({
        ...p,
        [dragging.current!]: {
          x: Math.max(NODE_R + 10, Math.min(CW - NODE_R - 10, dragStart.current.nx + dx)),
          y: Math.max(NODE_R + 20, Math.min(CH - NODE_R - 20, dragStart.current.ny + dy)),
        },
      }))
      return
    }
    if (panning.current) {
      setTransform(t => ({
        ...t,
        x: panStart.current.tx + (e.clientX - panStart.current.mx),
        y: panStart.current.ty + (e.clientY - panStart.current.my),
      }))
    }
  }, [transform.scale])

  const onMouseUp = useCallback(() => {
    panning.current = false
    dragging.current = null
  }, [])

  const onNodeMouseDown = useCallback((e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation()
    dragging.current = nodeId
    dragStart.current = {
      mx: e.clientX, my: e.clientY,
      nx: pos[nodeId]?.x ?? 0, ny: pos[nodeId]?.y ?? 0,
    }
  }, [pos])

  const fitView = useCallback(() => {
    if (!Object.keys(pos).length || !svgRef.current) return
    const xs = Object.values(pos).map(p => p.x)
    const ys = Object.values(pos).map(p => p.y)
    const minX = Math.min(...xs) - NODE_R - 20
    const maxX = Math.max(...xs) + NODE_R + 80
    const minY = Math.min(...ys) - NODE_R - 20
    const maxY = Math.max(...ys) + NODE_R + 40
    const rect = svgRef.current.getBoundingClientRect()
    const scaleX = rect.width / (maxX - minX)
    const scaleY = rect.height / (maxY - minY)
    const scale = Math.min(scaleX, scaleY, 1.5)
    setTransform({
      scale,
      x: -minX * scale + (rect.width - (maxX - minX) * scale) / 2,
      y: -minY * scale + (rect.height - (maxY - minY) * scale) / 2,
    })
  }, [pos])

  // Auto-fit after layout
  useEffect(() => {
    if (Object.keys(pos).length) {
      // Small delay so SVG has rendered dimensions
      const t = setTimeout(fitView, 50)
      return () => clearTimeout(t)
    }
  }, [pos, fitView])

  if (!Object.keys(pos).length) {
    return <div className="flex items-center justify-center text-sm text-gray-400" style={{ height }}>Rendering…</div>
  }

  return (
    <div className="relative" style={{ height }}>
      {/* Toolbar */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button onClick={() => setTransform(t => ({ ...t, scale: Math.min(4, t.scale * 1.25) }))}
          className="w-7 h-7 bg-white border border-gray-300 rounded shadow-sm text-gray-600 hover:bg-gray-50 text-sm font-bold flex items-center justify-center">+</button>
        <button onClick={() => setTransform(t => ({ ...t, scale: Math.max(0.15, t.scale / 1.25) }))}
          className="w-7 h-7 bg-white border border-gray-300 rounded shadow-sm text-gray-600 hover:bg-gray-50 text-sm font-bold flex items-center justify-center">−</button>
        <button onClick={fitView}
          className="px-2 h-7 bg-white border border-gray-300 rounded shadow-sm text-gray-600 hover:bg-gray-50 text-xs">Fit</button>
      </div>

      <svg ref={svgRef} width="100%" height={height}
        style={{ cursor: panning.current ? 'grabbing' : 'grab', userSelect: 'none', background: '#f9fafb', borderRadius: 8 }}
        onWheel={onWheel}
        onMouseDown={onSvgMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}>

        <defs>
          {Object.entries(VIA_COLOUR).map(([via, col]) => (
            <marker key={via} id={`arr-${via}`} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill={col} />
            </marker>
          ))}
        </defs>

        <g transform={`translate(${transform.x},${transform.y}) scale(${transform.scale})`}>
          {/* Edges */}
          {displayEdges.map((e, i) => {
            const a = pos[e.from], b = pos[e.to]
            if (!a || !b) return null
            const col = VIA_COLOUR[e.primaryVia] ?? '#94a3b8'
            // Offset line endpoints to stop at node circumference
            const dx = b.x - a.x, dy = b.y - a.y
            const dist = Math.sqrt(dx * dx + dy * dy) || 1
            const ux = dx / dist, uy = dy / dist
            const x1 = a.x + ux * NODE_R, y1 = a.y + uy * NODE_R
            const x2 = b.x - ux * (NODE_R + 8), y2 = b.y - uy * (NODE_R + 8)
            const mx = (x1 + x2) / 2, my = (y1 + y2) / 2
            const strokeW = e.count > 1 ? 2.5 : 1.5
            return (
              <g key={i}
                onMouseEnter={ev => {
                  const rect = svgRef.current!.getBoundingClientRect()
                  const tip = e.labels.length
                    ? e.labels.slice(0, 6).join(', ') + (e.labels.length > 6 ? ` +${e.labels.length - 6}` : '')
                    : e.vias.map(v => VIA_LABEL[v] ?? v).join(', ')
                  setTooltip({ x: ev.clientX - rect.left, y: ev.clientY - rect.top, text: tip })
                }}
                onMouseLeave={() => setTooltip(null)}>
                <line x1={x1} y1={y1} x2={x2} y2={y2}
                  stroke={col} strokeWidth={strokeW} strokeOpacity={0.7}
                  markerEnd={`url(#arr-${e.primaryVia})`} />
                {e.count > 1 && (
                  <g>
                    <circle cx={mx} cy={my} r={9} fill={col} opacity={0.9} />
                    <text x={mx} y={my + 4} fontSize={9} fill="#fff" textAnchor="middle" fontWeight="bold">{e.count}</text>
                  </g>
                )}
              </g>
            )
          })}

          {/* Nodes */}
          {graph.nodes.map(n => {
            const p = pos[n.id]
            if (!p) return null
            const col = NODE_COLOUR[n.type] ?? '#60a5fa'
            const lbl = n.label
            const portLbl = n.port ? `:${n.port}` : ''
            return (
              <g key={n.id} className="topo-node"
                style={{ cursor: 'grab' }}
                onMouseDown={e => onNodeMouseDown(e, n.id)}
                onMouseEnter={ev => {
                  const rect = svgRef.current!.getBoundingClientRect()
                  setTooltip({
                    x: ev.clientX - rect.left,
                    y: ev.clientY - rect.top,
                    text: `${n.label}${portLbl} · ${n.type.replace('_', ' ')}`,
                  })
                }}
                onMouseLeave={() => setTooltip(null)}>
                <circle cx={p.x} cy={p.y} r={NODE_R} fill={col} stroke="#fff" strokeWidth={2.5}
                  filter="drop-shadow(0 1px 3px rgba(0,0,0,0.18))" />
                {/* Label backing */}
                <rect x={p.x - (lbl.length * 3.6 + 4)} y={p.y + NODE_R + 3}
                  width={lbl.length * 7.2 + 8} height={14}
                  rx={3} fill="rgba(255,255,255,0.85)" />
                <text x={p.x} y={p.y + NODE_R + 13} fontSize={11} textAnchor="middle"
                  fill="#1e293b" fontWeight={600}>{lbl}</text>
                {portLbl && (
                  <text x={p.x} y={p.y + NODE_R + 25} fontSize={9} textAnchor="middle"
                    fill="#64748b">{portLbl}</text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div className="pointer-events-none absolute z-20 px-2 py-1 bg-gray-900 text-white text-xs rounded shadow-lg max-w-xs"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}>
          {tooltip.text}
        </div>
      )}

      {/* Hint */}
      <div className="absolute bottom-2 left-2 text-xs text-gray-400 pointer-events-none">
        Scroll to zoom · drag to pan · drag nodes to reposition
      </div>
    </div>
  )
}

// ── Adjacency table ───────────────────────────────────────────────────────

function AdjacencyTable({ graph }: { graph: TopoGraph }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-4 py-2 text-left font-medium text-gray-600">Service</th>
            <th className="px-4 py-2 text-left font-medium text-gray-600">Type</th>
            <th className="px-4 py-2 text-left font-medium text-gray-600">Port</th>
            <th className="px-4 py-2 text-left font-medium text-gray-600">Depends on</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {graph.nodes.map(n => {
            const outgoing = graph.edges.filter(e => e.from === n.id)
            // Dedupe by target+via for display
            const byTarget = new Map<string, { via: string; labels: string[] }>()
            outgoing.forEach(e => {
              const ex = byTarget.get(e.to)
              if (ex) { if (e.label && !ex.labels.includes(e.label)) ex.labels.push(e.label) }
              else byTarget.set(e.to, { via: e.via, labels: e.label ? [e.label] : [] })
            })
            return (
              <tr key={n.id} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-medium text-gray-900">{n.label}</td>
                <td className="px-4 py-2">
                  <span className="px-2 py-0.5 rounded text-xs font-medium"
                    style={{ background: (NODE_COLOUR[n.type] ?? '#60a5fa') + '33', color: '#374151' }}>
                    {n.type.replace('_', ' ')}
                  </span>
                </td>
                <td className="px-4 py-2 font-mono text-xs text-gray-500">{n.port ?? '—'}</td>
                <td className="px-4 py-2">
                  <div className="flex flex-wrap gap-1">
                    {byTarget.size === 0 && <span className="text-gray-400 text-xs">—</span>}
                    {Array.from(byTarget.entries()).map(([target, info]) => (
                      <span key={target} className="px-2 py-0.5 rounded text-xs"
                        style={{ background: (VIA_COLOUR[info.via] ?? '#94a3b8') + '22', color: '#374151', border: `1px solid ${(VIA_COLOUR[info.via] ?? '#94a3b8')}55` }}
                        title={info.labels.join(', ')}>
                        {target}
                        <span className="ml-1 opacity-60">({VIA_LABEL[info.via] ?? info.via})</span>
                        {info.labels.length > 0 && <span className="ml-1 opacity-50">×{info.labels.length}</span>}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Pop-out modal ─────────────────────────────────────────────────────────

function PopOutModal({ graph, onClose }: { graph: TopoGraph; onClose: () => void }) {
  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-gray-900/80 backdrop-blur-sm">
      <div className="flex items-center justify-between px-4 py-2 bg-white border-b border-gray-200 shrink-0">
        <span className="text-sm font-semibold text-gray-700">Service Topology</span>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {Object.entries(VIA_LABEL).map(([via, lbl]) => (
            <span key={via} className="flex items-center gap-1">
              <span className="inline-block w-5 h-0.5 rounded" style={{ background: VIA_COLOUR[via] }} />
              {lbl}
            </span>
          ))}
          <button onClick={onClose}
            className="ml-4 px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded text-gray-700 font-medium">
            ✕ Close
          </button>
        </div>
      </div>
      <div className="flex-1 min-h-0 p-2">
        <TopologyDiagram graph={graph} height={window.innerHeight - 56} />
      </div>
    </div>
  )
}

// ── Main tab ──────────────────────────────────────────────────────────────

const MIN_H = 320
const MAX_H = 900
const DEFAULT_H = 520

export default function TopologyTab({ reportId }: { reportId: string }) {
  const [view, setView] = useState<'diagram' | 'table'>('diagram')
  const [diagramH, setDiagramH] = useState(DEFAULT_H)
  const [popOut, setPopOut] = useState(false)
  const resizing = useRef(false)
  const resizeStart = useRef({ y: 0, h: DEFAULT_H })

  const { data, isLoading, error } = useQuery<TopoGraph & { report_id: string }>({
    queryKey: ['topology', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/topology`).then(r => r.data),
  })

  // Resize drag handlers
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    resizing.current = true
    resizeStart.current = { y: e.clientY, h: diagramH }
    const onMove = (ev: MouseEvent) => {
      if (!resizing.current) return
      const newH = Math.max(MIN_H, Math.min(MAX_H, resizeStart.current.h + ev.clientY - resizeStart.current.y))
      setDiagramH(newH)
    }
    const onUp = () => { resizing.current = false; window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp) }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [diagramH])

  if (isLoading) return <div className="text-sm text-gray-400 py-8 text-center">Building topology…</div>
  if (error || !data) return <div className="text-sm text-red-500 py-4">Failed to load topology.</div>

  const { nodes, edges } = data
  const eventCount = edges.filter(e => e.via === 'event').length
  const nginxCount = edges.filter(e => e.via === 'nginx').length
  const apiCount  = edges.filter(e => e.via === 'api_url').length

  return (
    <>
      {popOut && <PopOutModal graph={data} onClose={() => setPopOut(false)} />}

      <div className="space-y-4">
        {/* Stats */}
        <div className="flex flex-wrap gap-3">
          <div className="px-3 py-2 bg-blue-50 border border-blue-200 rounded text-sm">
            <span className="font-semibold text-blue-800">{nodes.length}</span>
            <span className="text-blue-600 ml-1">services</span>
          </div>
          {[['event', eventCount], ['nginx', nginxCount], ['api_url', apiCount]].map(([via, cnt]) => (
            <div key={via as string} className="px-3 py-2 rounded text-sm"
              style={{ background: VIA_COLOUR[via as string] + '22', border: `1px solid ${VIA_COLOUR[via as string]}55` }}>
              <span className="font-semibold" style={{ color: VIA_COLOUR[via as string] }}>{cnt as number}</span>
              <span className="text-gray-600 ml-1">{VIA_LABEL[via as string]} edges</span>
            </div>
          ))}
        </div>

        {/* Controls row */}
        <div className="flex items-center justify-between">
          <div className="flex gap-4 text-xs text-gray-500">
            {Object.entries(VIA_LABEL).map(([via, lbl]) => (
              <span key={via} className="flex items-center gap-1.5">
                <span className="inline-block w-6 h-0.5 rounded" style={{ background: VIA_COLOUR[via] }} />
                {lbl}
              </span>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
              {(['diagram', 'table'] as const).map(v => (
                <button key={v} onClick={() => setView(v)}
                  className={`px-3 py-1.5 capitalize transition ${view === v ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-50'}`}>
                  {v}
                </button>
              ))}
            </div>
            {view === 'diagram' && (
              <button onClick={() => setPopOut(true)}
                className="px-3 py-1.5 border border-gray-200 rounded text-xs text-gray-600 hover:bg-gray-50 flex items-center gap-1"
                title="Open full-screen">
                ⛶ Pop out
              </button>
            )}
          </div>
        </div>

        {/* Diagram / table */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {view === 'diagram' ? (
            <>
              <TopologyDiagram graph={data} height={diagramH} />
              {/* Resize handle */}
              <div
                className="h-2 bg-gray-100 border-t border-gray-200 cursor-ns-resize flex items-center justify-center hover:bg-gray-200 transition-colors"
                onMouseDown={onResizeMouseDown}
                title="Drag to resize">
                <div className="w-8 h-0.5 bg-gray-400 rounded" />
              </div>
            </>
          ) : (
            <AdjacencyTable graph={data} />
          )}
        </div>
      </div>
    </>
  )
}
