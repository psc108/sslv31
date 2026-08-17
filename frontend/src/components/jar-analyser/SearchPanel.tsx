import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Hit {
  category: string
  title: string
  detail: string
  extra: string
  report_id: string
  sub_report_id: string
  service_name: string
}

interface Props {
  /** If provided, search is scoped to this report only */
  reportId?: string
  /** Called when user clicks a hit — navigate to that sub-report on the given tab */
  onNavigate: (reportId: string, subReportId: string, tab: string) => void
}

const CATEGORY_META: Record<string, { label: string; tab: string; colour: string; icon: string }> = {
  endpoint:   { label: 'Endpoint',   tab: 'endpoints',    colour: 'bg-blue-100 text-blue-700',   icon: '⚡' },
  dependency: { label: 'Dependency', tab: 'dependencies', colour: 'bg-purple-100 text-purple-700', icon: '📦' },
  config:     { label: 'Config',     tab: 'config',       colour: 'bg-orange-100 text-orange-700', icon: '⚙' },
  schema:     { label: 'Schema',     tab: 'schemas',      colour: 'bg-green-100 text-green-700',  icon: '🗂' },
  event:      { label: 'Event',      tab: 'events',       colour: 'bg-pink-100 text-pink-700',    icon: '📡' },
  migration:  { label: 'Migration',  tab: 'migrations',   colour: 'bg-yellow-100 text-yellow-700', icon: '🗄' },
  string:     { label: 'String',     tab: 'strings',      colour: 'bg-teal-100 text-teal-700',    icon: '🔤' },
}

const ALL_CATEGORIES = Object.keys(CATEGORY_META)

export default function SearchPanel({ reportId, onNavigate }: Props) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [category, setCategory] = useState('')
  const [page, setPage] = useState(1)
  const inputRef = useRef<HTMLInputElement>(null)

  // Debounce
  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQ(q); setPage(1) }, 350)
    return () => clearTimeout(t)
  }, [q])

  const enabled = debouncedQ.length >= 2

  const { data, isFetching } = useQuery({
    queryKey: ['jar-search', debouncedQ, reportId, category, page],
    // Skips the structured-facts search entirely when the "String" pill is
    // selected — it has its own dedicated, FTS5-ranked endpoint below rather
    // than being one more ILIKE branch in this one, since string constants
    // are the highest-cardinality category by far (a service can have
    // hundreds of literals versus dozens of endpoints).
    queryFn: () => api.get('/jar-analyser/search', {
      params: {
        q: debouncedQ,
        report_id: reportId || undefined,
        category: category === 'string' ? undefined : (category || undefined),
        page,
        page_size: 40,
      },
    }).then(r => r.data),
    enabled: enabled && category !== 'string',
    placeholderData: (prev) => prev,
  })

  const includeStrings = !category || category === 'string'
  const { data: stringData, isFetching: isFetchingStrings } = useQuery({
    queryKey: ['jar-strings-search', debouncedQ, reportId, page],
    queryFn: () => api.get('/jar-analyser/strings/search', {
      params: { q: debouncedQ, report_id: reportId || undefined, page, page_size: 40 },
    }).then(r => r.data),
    enabled: enabled && includeStrings,
    placeholderData: (prev) => prev,
  })

  const structuredHits: Hit[] = category !== 'string' ? (data?.hits ?? []) : []
  const stringHits: Hit[] = includeStrings ? (stringData?.items ?? []).map((s: any) => ({
    category: 'string',
    title: s.value.length > 120 ? s.value.slice(0, 120) + '…' : s.value,
    detail: s.class_name,
    extra: s.service_name,
    report_id: s.report_id,
    sub_report_id: s.sub_report_id,
    service_name: s.service_name,
  })) : []
  const hits: Hit[] = [...structuredHits, ...stringHits]
  const isFetchingCombined = isFetching || isFetchingStrings
  // Two independently-paginated sources merged client-side — "loaded" once
  // whichever source(s) are actually enabled for the current category
  // filter have returned at least once; combinedTotal/combinedPages are an
  // approximation (each source's own page_size=40 aren't reconciled into
  // one true page count), same tolerance the pre-existing byService grouping
  // below already has for a merged result set.
  const loaded = (category !== 'string' ? data !== undefined : true) && (includeStrings ? stringData !== undefined : true)
  const combinedTotal = (category !== 'string' ? data?.total ?? 0 : 0) + (includeStrings ? stringData?.total ?? 0 : 0)
  const combinedPages = Math.max(data?.pages ?? 1, includeStrings ? stringData?.pages ?? 1 : 1)

  // Group hits by category for the count badges
  const countByCategory: Record<string, number> = {}
  for (const h of hits) {
    countByCategory[h.category] = (countByCategory[h.category] ?? 0) + 1
  }

  // Group hits by service for display
  const byService: Record<string, Hit[]> = {}
  for (const h of hits) {
    const key = `${h.report_id}::${h.service_name}`
    ;(byService[key] ??= []).push(h)
  }

  return (
    <div className="space-y-3">
      {/* Search input */}
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
        <input
          ref={inputRef}
          type="text"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder={reportId ? 'Search this report…' : 'Search all reports…'}
          className="w-full border border-gray-300 rounded-lg pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          autoFocus
        />
        {isFetchingCombined && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 animate-pulse">searching…</span>
        )}
      </div>

      {/* Category filter pills */}
      {enabled && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => { setCategory(''); setPage(1) }}
            className={`px-2.5 py-1 rounded-full text-xs border transition ${
              !category ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}
          >
            All {loaded ? `(${combinedTotal})` : ''}
          </button>
          {ALL_CATEGORIES.map(cat => {
            const meta = CATEGORY_META[cat]!
            const count = loaded
              ? hits.filter(h => h.category === cat).length
              : undefined
            if (count === 0 && category !== cat) return null
            return (
              <button
                key={cat}
                onClick={() => { setCategory(cat); setPage(1) }}
                className={`px-2.5 py-1 rounded-full text-xs border transition ${
                  category === cat ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}
              >
                {meta.icon} {meta.label}{count != null ? ` (${count})` : ''}
              </button>
            )
          })}
        </div>
      )}

      {/* Results */}
      {!enabled && (
        <p className="text-sm text-gray-400 text-center py-6">Type at least 2 characters to search</p>
      )}

      {enabled && !isFetchingCombined && loaded && hits.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-6">No results for <strong>{debouncedQ}</strong></p>
      )}

      {enabled && Object.entries(byService).map(([key, serviceHits]) => {
        const first = serviceHits[0]!
        return (
          <div key={key} className="border border-gray-200 rounded-lg overflow-hidden">
            {/* Service header */}
            <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center gap-2">
              <span className="text-xs font-semibold text-gray-700">{first.service_name}</span>
              {!reportId && (
                <span className="text-xs text-gray-400 font-mono">{first.report_id.slice(0, 8)}</span>
              )}
              <span className="ml-auto text-xs text-gray-400">{serviceHits.length} match{serviceHits.length !== 1 ? 'es' : ''}</span>
            </div>

            {/* Hits */}
            <div className="divide-y divide-gray-50">
              {serviceHits.map((h, i) => {
                const meta = CATEGORY_META[h.category] ?? CATEGORY_META['endpoint']!
                return (
                  <button
                    key={i}
                    onClick={() => onNavigate(h.report_id, h.sub_report_id, meta.tab)}
                    className="w-full flex items-start gap-3 px-4 py-2.5 hover:bg-blue-50 text-left transition"
                  >
                    <span className={`mt-0.5 px-1.5 py-0.5 rounded text-xs font-medium shrink-0 ${meta.colour}`}>
                      {meta.icon} {meta.label}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-mono text-gray-900 truncate">{h.title}</p>
                      {h.detail && (
                        <p className="text-xs text-gray-500 truncate mt-0.5">{h.detail}</p>
                      )}
                    </div>
                    {h.extra && (
                      <span className="text-xs text-gray-400 shrink-0">{h.extra}</span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}

      {/* Pagination */}
      {enabled && combinedPages > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
          <span>{combinedTotal} total results</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">← Prev</button>
            <span className="px-2 py-1">{page} / {combinedPages}</span>
            <button disabled={page >= combinedPages} onClick={() => setPage(p => p + 1)}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
