import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { markdownToSchema, countCards, type DiagramCard, type TierColor, type CategoryRule } from './structuredParse'

interface Props {
  content: string
  onSwitchToDocument: () => void
  // Wiki-link click-through (e.g. a "See Also" bullet — `[[Doc Name]]` or
  // `[[Doc Name|Label]]`) — structuredParse.ts's stripMd() only strips
  // `[text](url)`-style markdown links, so `[[...]]` survives untouched
  // into card.services/detail.rows as plain text; renderWikiLinks() below
  // turns it back into a real clickable link, same behaviour as Document
  // view's MarkdownPreview.
  onNavigateToDoc?: (name: string) => void
}

const WIKILINK_RE = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g

function renderWikiLinks(text: string, onNavigateToDoc?: (name: string) => void): (string | JSX.Element)[] {
  if (!onNavigateToDoc || !text.includes('[[')) return [text]
  const parts: (string | JSX.Element)[] = []
  let lastIndex = 0
  let key = 0
  WIKILINK_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = WIKILINK_RE.exec(text)) !== null) {
    if (m.index > lastIndex) parts.push(text.slice(lastIndex, m.index))
    const name = m[1]!.trim()
    const label = (m[2] ?? m[1]!).trim()
    parts.push(
      <button
        key={key++}
        onClick={e => { e.stopPropagation(); onNavigateToDoc(name) }}
        className="text-blue-600 hover:underline font-medium">
        {label}
      </button>
    )
    lastIndex = m.index + m[0].length
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex))
  return parts
}

const COLOR_CLASSES: Record<TierColor, { border: string; label: string; badgeBg: string; badgeText: string; ring: string }> = {
  blue: { border: 'border-blue-400', label: 'text-blue-700', badgeBg: 'bg-blue-100', badgeText: 'text-blue-700', ring: 'ring-blue-400' },
  green: { border: 'border-green-400', label: 'text-green-700', badgeBg: 'bg-green-100', badgeText: 'text-green-700', ring: 'ring-green-400' },
  amber: { border: 'border-amber-400', label: 'text-amber-700', badgeBg: 'bg-amber-100', badgeText: 'text-amber-700', ring: 'ring-amber-400' },
  purple: { border: 'border-purple-400', label: 'text-purple-700', badgeBg: 'bg-purple-100', badgeText: 'text-purple-700', ring: 'ring-purple-400' },
  red: { border: 'border-red-400', label: 'text-red-700', badgeBg: 'bg-red-100', badgeText: 'text-red-700', ring: 'ring-red-400' },
  orange: { border: 'border-orange-400', label: 'text-orange-700', badgeBg: 'bg-orange-100', badgeText: 'text-orange-700', ring: 'ring-orange-400' },
  indigo: { border: 'border-indigo-400', label: 'text-indigo-700', badgeBg: 'bg-indigo-100', badgeText: 'text-indigo-700', ring: 'ring-indigo-400' },
}

export default function StructuredView({ content, onSwitchToDocument, onNavigateToDoc }: Props) {
  // Improvements Plan Stage 13 — the heading->category badge mapping is now
  // admin-editable (Settings -> Structured View Categories) rather than a
  // fixed hardcoded list. Long staleTime since this changes rarely, and
  // markdownToSchema() already falls back to sane built-in defaults if this
  // hasn't loaded yet or the fetch fails.
  const { data: categoryRules } = useQuery<CategoryRule[]>({
    queryKey: ['category-rules'],
    queryFn: () => api.get('/category-rules').then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const schema = useMemo(() => markdownToSchema(content, categoryRules), [content, categoryRules])
  const cardCount = useMemo(() => countCards(schema), [schema])

  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [activeFlow, setActiveFlow] = useState<string | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null)
  const [kbIndex, setKbIndex] = useState(-1)
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  const allCardIds = useMemo(() => {
    const ids: string[] = []
    schema.layout.forEach(node => {
      if (node.type === 'tier') node.children.forEach(cn => cn.items.forEach(c => ids.push(c.id)))
    })
    return ids
  }, [schema])

  // Keyboard nav over cards — arrows move focus, Enter opens detail, Escape closes it.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return
      if (e.key === 'Escape') { setDetailId(null); return }
      if (!allCardIds.length) return
      if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
        e.preventDefault()
        setKbIndex(i => Math.min(i + 1, allCardIds.length - 1))
      } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
        e.preventDefault()
        setKbIndex(i => Math.max(i - 1, 0))
      } else if (e.key === 'Home') {
        e.preventDefault(); setKbIndex(0)
      } else if (e.key === 'End') {
        e.preventDefault(); setKbIndex(allCardIds.length - 1)
      } else if (e.key === 'Enter' && kbIndex >= 0) {
        e.preventDefault()
        const id = allCardIds[kbIndex]
        if (id) setDetailId(id)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [allCardIds, kbIndex])

  useEffect(() => {
    const id = allCardIds[kbIndex]
    if (id) cardRefs.current.get(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [kbIndex, allCardIds])

  if (cardCount <= 1) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-10 text-center">
        <p className="text-sm text-gray-500 mb-4">
          This document doesn't have enough heading structure for the Structured view.<br />
          It needs multiple H2 sections (optionally with H3 subsections) to generate a useful card diagram.
        </p>
        <button onClick={onSwitchToDocument}
          className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
          Switch to Document View
        </button>
      </div>
    )
  }

  const flow = activeFlow ? schema.flows[activeFlow] : null
  const needle = searchTerm.trim().toLowerCase()
  const detail = detailId ? schema.data[detailId] : null

  const cardState = (card: DiagramCard): 'active' | 'dim' | 'search-hit' | 'search-dim' | 'normal' => {
    if (needle) {
      const text = (card.title + ' ' + card.body + ' ' + card.badge.text).toLowerCase()
      return text.includes(needle) ? 'search-hit' : 'search-dim'
    }
    if (flow) return flow.active.includes(card.id) ? 'active' : 'dim'
    return 'normal'
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 relative">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-bold text-gray-900">{schema.title}</h2>
      </div>

      {Object.keys(schema.flows).length > 0 && (
        <div className="px-4 py-2 border-b border-gray-100 flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-400 mr-1">Highlight section:</span>
          {Object.entries(schema.flows).map(([key, f]) => (
            <button key={key}
              onClick={() => setActiveFlow(prev => prev === key ? null : key)}
              className={`px-2.5 py-1 text-xs rounded-md border ${activeFlow === key ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 text-gray-600 hover:bg-gray-50'}`}>
              {f.label}
            </button>
          ))}
          {activeFlow && (
            <button onClick={() => setActiveFlow(null)} className="px-2.5 py-1 text-xs rounded-md border border-gray-300 text-gray-600 hover:bg-gray-50">
              Clear
            </button>
          )}
          <input
            type="text" value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            onKeyDown={e => { if (e.key === 'Escape') setSearchTerm('') }}
            placeholder="Filter cards…"
            className="ml-auto border border-gray-300 rounded-md px-2.5 py-1 text-xs w-44"
          />
        </div>
      )}

      <div className="p-4 space-y-3">
        {schema.layout.map((node, i) => {
          if (node.type === 'connector') {
            return <div key={i} className="flex justify-center text-gray-300 text-lg">↓</div>
          }
          const isCollapsed = collapsed.has(node.label + i)
          const colors = COLOR_CLASSES[node.color]
          return (
            <div key={i} className={`border-l-4 ${colors.border} bg-gray-50 rounded-r-md`}>
              <div
                className="px-3 py-2 flex items-center gap-1.5 cursor-pointer select-none"
                onClick={() => setCollapsed(prev => {
                  const next = new Set(prev)
                  if (next.has(node.label + i)) next.delete(node.label + i)
                  else next.add(node.label + i)
                  return next
                })}
              >
                <span className={`text-xs transition-transform ${isCollapsed ? '-rotate-90' : ''}`}>▾</span>
                <span className={`font-semibold text-sm ${colors.label}`}>{node.label}</span>
              </div>
              {!isCollapsed && (
                <div className="px-3 pb-3 flex flex-wrap gap-3">
                  {node.children.flatMap(cn => cn.items).map(card => {
                    const state = cardState(card)
                    const badgeColors = COLOR_CLASSES[card.badge.color]
                    return (
                      <div
                        key={card.id}
                        ref={el => { if (el) cardRefs.current.set(card.id, el); else cardRefs.current.delete(card.id) }}
                        onMouseEnter={e => setHover({ id: card.id, x: e.clientX, y: e.clientY })}
                        onMouseMove={e => setHover(h => h && h.id === card.id ? { id: card.id, x: e.clientX, y: e.clientY } : h)}
                        onMouseLeave={() => setHover(h => h?.id === card.id ? null : h)}
                        onClick={() => setDetailId(card.id)}
                        className={[
                          'bg-white border rounded-md p-3 cursor-pointer transition-all',
                          card.wide ? 'flex-1 min-w-[220px]' : 'w-64',
                          state === 'active' ? `ring-2 ${badgeColors.ring} border-transparent` : 'border-gray-200',
                          state === 'dim' ? 'opacity-25' : '',
                          state === 'search-hit' ? 'border-amber-400 ring-1 ring-amber-300' : '',
                          state === 'search-dim' ? 'opacity-15 pointer-events-none' : '',
                          allCardIds[kbIndex] === card.id ? 'outline outline-2 outline-blue-500' : '',
                        ].join(' ')}
                      >
                        <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded mb-1.5 ${badgeColors.badgeBg} ${badgeColors.badgeText}`}>
                          {card.badge.text}
                        </span>
                        <div className="font-medium text-sm text-gray-900">{card.title}</div>
                        {card.body && (
                          <div className="text-xs text-gray-500 mt-1 whitespace-pre-wrap break-words">{renderWikiLinks(card.body, onNavigateToDoc)}</div>
                        )}
                        {card.pills && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {card.pills.map((p, pi) => (
                              <span key={pi} className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">{p}</span>
                            ))}
                          </div>
                        )}
                        {card.services && (
                          <ul className="mt-2 space-y-0.5">
                            {card.services.map((s, si) => (
                              <li key={si} className="text-xs text-gray-600 truncate">{renderWikiLinks(s, onNavigateToDoc)}</li>
                            ))}
                          </ul>
                        )}
                        {card.ports && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {card.ports.map((p, pi) => (
                              <span key={pi} className="text-[10px] bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded font-mono">{p.text}</span>
                            ))}
                          </div>
                        )}
                        {card.footnote && (
                          <div className="text-[10px] text-amber-600 mt-2">{card.footnote}</div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Hover tooltip */}
      {hover && schema.data[hover.id] && !detailId && (
        <div
          className="fixed z-50 bg-gray-900 text-white text-xs rounded-md shadow-lg p-3 w-64 pointer-events-none"
          style={{ left: Math.min(hover.x + 16, window.innerWidth - 270), top: Math.min(hover.y + 8, window.innerHeight - 140) }}
        >
          <div className="font-semibold mb-1">{schema.data[hover.id]!.title}</div>
          {schema.data[hover.id]!.rows.slice(0, 4).map(([k, v], i) => (
            <div key={i} className="flex gap-1.5 text-gray-300">
              {k && <span className="text-gray-400 shrink-0">{k}:</span>}
              <span className="truncate">{v}</span>
            </div>
          ))}
          {schema.data[hover.id]!.rows.length > 4 && <div className="text-gray-500 mt-1">Click for full details…</div>}
        </div>
      )}

      {/* Detail panel */}
      {detail && (
        <div className="fixed inset-y-0 right-0 w-96 bg-white border-l border-gray-200 shadow-xl z-50 overflow-y-auto">
          <div className="sticky top-0 bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
            <div>
              <div className="text-xs text-gray-400">{detail.sub}</div>
              <h3 className="font-bold text-gray-900">{detail.title}</h3>
            </div>
            <button onClick={() => setDetailId(null)} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
          </div>
          <div className="p-4 space-y-4">
            {detail.rows.length > 0 && (
              <div className="space-y-1.5">
                {detail.rows.map(([k, v], i) => (
                  <div key={i} className="text-sm">
                    {k && <span className="text-gray-500 font-medium">{k}: </span>}
                    <span className="text-gray-800">{renderWikiLinks(v, onNavigateToDoc)}</span>
                  </div>
                ))}
              </div>
            )}
            {detail.table && (
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr>{detail.table.headers.map((h, i) => <th key={i} className="text-left border-b border-gray-200 py-1 pr-2 text-gray-500">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {detail.table.rows.map((row, ri) => (
                    <tr key={ri}>{row.map((cell, ci) => <td key={ci} className="border-b border-gray-100 py-1 pr-2 text-gray-700">{cell}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            )}
            {detail.cmds && (
              <pre className="bg-gray-900 text-gray-100 text-xs p-3 rounded-md overflow-x-auto whitespace-pre-wrap">{detail.cmds}</pre>
            )}
            {detail.note && (
              <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2">⚠ {renderWikiLinks(detail.note, onNavigateToDoc)}</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
