import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { forceSimulation, forceManyBody, forceLink, forceCenter, forceCollide, type SimulationNodeDatum, type SimulationLinkDatum } from 'd3-force'
import api from '@/lib/api'
import type { DocMapData, DocMapEdgeType } from './types'

interface Props {
  // Improvements Plan Stage 14 — null means the "all libraries" map, which
  // has no persisted layout (see DocMapData.layout's own comment) and
  // fetches from a different, unscoped endpoint.
  libraryId: string | null
  libraryName: string
  onBack: () => void
  onOpenDoc: (docId: string, shelfId: string, shelfName: string, docName: string) => void
}

interface SimNode extends SimulationNodeDatum {
  id: string
  name: string
  shelf_id: string
  shelf_name: string
  word_count: number
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  type: DocMapEdgeType
}

// Matches DocApp's own doc-map-graph.js palette.
const EDGE_COLORS: Record<DocMapEdgeType, string> = {
  wiki: '#3b82f6',
  heading: '#a855f7',
  keyword: '#10b981',
}

const EDGE_LABELS: Record<DocMapEdgeType, string> = {
  wiki: 'Wiki-links',
  heading: 'Shared headings',
  keyword: 'Shared keywords',
}

export default function DocMap({ libraryId, libraryName, onBack, onOpenDoc }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const nodesRef = useRef<SimNode[]>([])
  const linksRef = useRef<SimLink[]>([])
  const transformRef = useRef({ x: 0, y: 0, k: 1 })
  const dragRef = useRef<{ node: SimNode; moved: boolean; startX: number; startY: number } | null>(null)
  const panRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)
  // Node ids with a manually-chosen position (loaded from a saved layout,
  // or dragged this session) — these stay pinned (fx/fy set) instead of
  // springing back into the simulation on drag release. Improvements Plan
  // Stage 14.
  const pinnedRef = useRef<Set<string>>(new Set())

  const [activeTypes, setActiveTypes] = useState<Set<DocMapEdgeType>>(new Set(['wiki', 'heading', 'keyword']))
  const [textFilter, setTextFilter] = useState('')
  const [layoutDirty, setLayoutDirty] = useState(false)
  // Mirrors pinnedRef.current.size for rendering purposes only — a plain
  // ref mutation doesn't trigger a re-render, so the "Reset Layout" button's
  // disabled state needs a real state value to stay in sync with it.
  const [pinnedCount, setPinnedCount] = useState(0)
  const [, forceRerender] = useState(0)
  const queryClient = useQueryClient()

  const mapUrl = libraryId ? `/docs/libraries/${libraryId}/map` : '/docs/map'
  const { data, isLoading } = useQuery<DocMapData>({
    queryKey: ['doc-map', libraryId],
    queryFn: () => api.get(mapUrl).then(r => r.data),
  })

  const saveLayoutMutation = useMutation({
    mutationFn: (positions: Record<string, { x: number; y: number }>) =>
      api.put(`/docs/libraries/${libraryId}/map/layout`, { positions }),
    onSuccess: () => { setLayoutDirty(false); queryClient.invalidateQueries({ queryKey: ['doc-map', libraryId] }) },
  })

  const collectPinnedPositions = (): Record<string, { x: number; y: number }> => {
    const positions: Record<string, { x: number; y: number }> = {}
    for (const id of pinnedRef.current) {
      const n = nodesRef.current.find(n => n.id === id)
      if (n && (n.fx ?? n.x) != null && (n.fy ?? n.y) != null) {
        positions[id] = { x: (n.fx ?? n.x) as number, y: (n.fy ?? n.y) as number }
      }
    }
    return positions
  }

  const saveLayout = () => saveLayoutMutation.mutate(collectPinnedPositions())

  const resetLayout = () => {
    for (const id of pinnedRef.current) {
      const n = nodesRef.current.find(n => n.id === id)
      if (n) { n.fx = null; n.fy = null }
    }
    pinnedRef.current.clear()
    setPinnedCount(0)
    simRef.current?.alphaTarget(0.3).restart()
    setTimeout(() => simRef.current?.alphaTarget(0), 300)
    saveLayoutMutation.mutate({})
  }

  const filteredLinks = useMemo(
    () => linksRef.current.filter(l => activeTypes.has(l.type)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeTypes, data]
  )

  const draw = () => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const w = container.clientWidth
    const h = container.clientHeight
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr
      canvas.height = h * dpr
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
    }

    ctx.save()
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const { x, y, k } = transformRef.current
    ctx.translate(x, y)
    ctx.scale(k, k)

    const needle = textFilter.trim().toLowerCase()
    const matches = (n: SimNode) => !needle || n.name.toLowerCase().includes(needle)

    // Edges
    linksRef.current.forEach(l => {
      if (!activeTypes.has(l.type)) return
      const source = l.source as SimNode
      const target = l.target as SimNode
      if (source.x == null || source.y == null || target.x == null || target.y == null) return
      const dim = needle && !(matches(source) && matches(target))
      ctx.strokeStyle = EDGE_COLORS[l.type]
      ctx.globalAlpha = dim ? 0.08 : 0.45
      ctx.lineWidth = 1.5 / k
      ctx.beginPath()
      ctx.moveTo(source.x, source.y)
      ctx.lineTo(target.x, target.y)
      ctx.stroke()
    })

    // Nodes
    ctx.globalAlpha = 1
    nodesRef.current.forEach(n => {
      if (n.x == null || n.y == null) return
      const dim = needle && !matches(n)
      const radius = Math.min(22, 6 + Math.sqrt(n.word_count) / 4)
      ctx.globalAlpha = dim ? 0.2 : 1
      ctx.fillStyle = '#2563eb'
      ctx.beginPath()
      ctx.arc(n.x, n.y, radius, 0, Math.PI * 2)
      ctx.fill()

      ctx.font = `${12 / k}px sans-serif`
      ctx.fillStyle = '#111827'
      ctx.fillText(n.name, n.x + radius + 4 / k, n.y + 4 / k)
    })
    ctx.globalAlpha = 1
    ctx.restore()
  }

  useEffect(() => { draw() })

  // Build/rebuild the simulation whenever fresh map data arrives.
  useEffect(() => {
    if (!data) return
    const container = containerRef.current
    const w = container?.clientWidth || 800
    const h = container?.clientHeight || 600

    const nodes: SimNode[] = data.nodes.map(n => ({ ...n }))
    const links: SimLink[] = data.edges.map(e => ({ source: e.source, target: e.target, type: e.type }))

    // Improvements Plan Stage 14 — restore any manually-saved layout by
    // pinning those nodes' starting position; the simulation still runs
    // for everything else, same as an ordinary fresh load.
    pinnedRef.current = new Set(Object.keys(data.layout ?? {}))
    setPinnedCount(pinnedRef.current.size)
    for (const n of nodes) {
      const saved = data.layout?.[n.id]
      if (saved) { n.x = saved.x; n.y = saved.y; n.fx = saved.x; n.fy = saved.y }
    }

    nodesRef.current = nodes
    linksRef.current = links

    simRef.current?.stop()
    const sim = forceSimulation(nodes)
      .force('charge', forceManyBody().strength(-180))
      .force('link', forceLink<SimNode, SimLink>(links).id(d => d.id).distance(90))
      .force('center', forceCenter(w / 2, h / 2))
      .force('collide', forceCollide(28))
      .on('tick', draw)
    simRef.current = sim

    return () => { sim.stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  // Resize observer keeps the canvas backing-store in sync with layout.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const ro = new ResizeObserver(() => draw())
    ro.observe(container)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const hitTest = (clientX: number, clientY: number): SimNode | null => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const { x, y, k } = transformRef.current
    const localX = (clientX - rect.left - x) / k
    const localY = (clientY - rect.top - y) / k
    for (let i = nodesRef.current.length - 1; i >= 0; i--) {
      const n = nodesRef.current[i]!
      if (n.x == null || n.y == null) continue
      const radius = Math.min(22, 6 + Math.sqrt(n.word_count) / 4)
      if ((n.x - localX) ** 2 + (n.y - localY) ** 2 <= radius ** 2) return n
    }
    return null
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    const hit = hitTest(e.clientX, e.clientY)
    if (hit) {
      hit.fx = hit.x
      hit.fy = hit.y
      dragRef.current = { node: hit, moved: false, startX: e.clientX, startY: e.clientY }
      simRef.current?.alphaTarget(0.3).restart()
    } else {
      panRef.current = { startX: e.clientX, startY: e.clientY, origX: transformRef.current.x, origY: transformRef.current.y }
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    if (dragRef.current) {
      const { node, startX, startY } = dragRef.current
      if (Math.abs(e.clientX - startX) > 2 || Math.abs(e.clientY - startY) > 2) dragRef.current.moved = true
      const rect = canvasRef.current!.getBoundingClientRect()
      const { x, y, k } = transformRef.current
      node.fx = (e.clientX - rect.left - x) / k
      node.fy = (e.clientY - rect.top - y) / k
      draw()
    } else if (panRef.current) {
      const { startX, startY, origX, origY } = panRef.current
      transformRef.current = { ...transformRef.current, x: origX + (e.clientX - startX), y: origY + (e.clientY - startY) }
      draw()
    }
  }

  const handleMouseUp = () => {
    if (dragRef.current) {
      const { node, moved } = dragRef.current
      if (moved && libraryId) {
        // A real drag pins the node in place and marks the layout dirty —
        // only per-library maps persist a layout (Improvements Plan
        // Stage 14); the all-libraries map has nowhere to save one, so
        // dragging there is a transient, un-persisted convenience only.
        pinnedRef.current.add(node.id)
        setPinnedCount(pinnedRef.current.size)
        setLayoutDirty(true)
      } else if (!moved && !pinnedRef.current.has(node.id)) {
        // A plain click (not a drag) releases the node back into the
        // simulation — unless it was already pinned (from a saved layout
        // or an earlier drag this session), in which case a click-to-open
        // shouldn't accidentally un-pin it.
        node.fx = null
        node.fy = null
      }
      simRef.current?.alphaTarget(0)
      if (!moved) onOpenDoc(node.id, node.shelf_id, node.shelf_name, node.name)
      dragRef.current = null
    }
    panRef.current = null
  }

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const { x, y, k } = transformRef.current
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1
    const newK = Math.min(4, Math.max(0.15, k * factor))
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    transformRef.current = {
      k: newK,
      x: cx - ((cx - x) / k) * newK,
      y: cy - ((cy - y) / k) * newK,
    }
    draw()
  }

  const fitToView = () => {
    const container = containerRef.current
    const nodes = nodesRef.current
    if (!container || nodes.length === 0) return
    const xs = nodes.map(n => n.x ?? 0)
    const ys = nodes.map(n => n.y ?? 0)
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const w = container.clientWidth, h = container.clientHeight
    const pad = 60
    const k = Math.min(4, Math.max(0.15, Math.min((w - pad) / Math.max(1, maxX - minX), (h - pad) / Math.max(1, maxY - minY))))
    transformRef.current = {
      k,
      x: w / 2 - ((minX + maxX) / 2) * k,
      y: h / 2 - ((minY + maxY) / 2) * k,
    }
    draw()
  }

  useEffect(() => {
    if (data && data.nodes.length > 0) {
      const t = setTimeout(fitToView, 400)
      return () => clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  const toggleType = (t: DocMapEdgeType) => {
    setActiveTypes(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
    forceRerender(n => n + 1)
  }

  const exportPng = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const link = document.createElement('a')
    link.download = `${libraryName.replace(/\s+/g, '_')}_map.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  }

  return (
    <div className="space-y-4">
      <div>
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700 mb-2">← {libraryName}</button>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Relationship Map</h1>
            <p className="text-sm text-gray-500 mt-0.5">{data?.nodes.length ?? 0} documents, {filteredLinks.length} connections shown</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text" value={textFilter} onChange={e => setTextFilter(e.target.value)}
              placeholder="Filter by name…"
              className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-48"
            />
            <button onClick={fitToView} className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm rounded-md hover:bg-gray-50">
              Fit to view
            </button>
            <button onClick={exportPng} className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm rounded-md hover:bg-gray-50">
              Export PNG
            </button>
            {libraryId && (
              <>
                <button onClick={saveLayout} disabled={!layoutDirty || saveLayoutMutation.isPending}
                  className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm rounded-md hover:bg-gray-50 disabled:opacity-40">
                  {saveLayoutMutation.isPending ? 'Saving…' : 'Save Layout'}
                </button>
                <button onClick={resetLayout} disabled={pinnedCount === 0 || saveLayoutMutation.isPending}
                  title="Clear all manually-positioned nodes and let them re-arrange automatically"
                  className="px-3 py-1.5 border border-gray-300 text-gray-700 text-sm rounded-md hover:bg-gray-50 disabled:opacity-40">
                  Reset Layout
                </button>
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4 mt-2">
          {(Object.keys(EDGE_LABELS) as DocMapEdgeType[]).map(t => (
            <label key={t} className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
              <input type="checkbox" checked={activeTypes.has(t)} onChange={() => toggleType(t)} />
              <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: EDGE_COLORS[t] }} />
              {EDGE_LABELS[t]}
            </label>
          ))}
        </div>
      </div>

      <div ref={containerRef} className="bg-white rounded-lg border border-gray-200 h-[600px] relative overflow-hidden">
        {isLoading && <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400">Loading...</div>}
        {!isLoading && data?.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-400">
            {libraryId ? 'No documents in this library yet.' : 'No documents yet.'}
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="cursor-grab active:cursor-grabbing"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onWheel={handleWheel}
        />
      </div>
    </div>
  )
}
