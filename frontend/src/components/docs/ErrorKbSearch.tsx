import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { DocLibrary, KbEntry, KbDiagnosisResult, BugFull, DecodedException, DecodeStackTraceResponse, StackFrame, KnownClassMatch, BugPrefillData, MlAnalysis } from './types'

const SEVERITY_COLOUR: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  high: 'bg-orange-100 text-orange-800 border-orange-200',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  low: 'bg-blue-100 text-blue-800 border-blue-200',
}
const SEVERITIES = ['critical', 'high', 'medium', 'low']

interface Props {
  onBack: () => void
  onOpenDoc: (docId: string, libraryId: string, libraryName: string, shelfId: string, shelfName: string, docName: string) => void
  // Set when arriving via a resolved bug's "Promote to KB" action — jumps
  // straight to the New Entry tab, prefilled from that bug, instead of the
  // default Search landing.
  fromBugId?: string
  // Diagnose's "🐛 Create Bug" action — cross-navigates to Bug Tracker's New
  // Bug form, prefilled with everything the diagnosis already worked out.
  onCreateBug: (prefill: BugPrefillData) => void
}

export default function ErrorKbSearch({ onBack, onOpenDoc, fromBugId, onCreateBug }: Props) {
  const { isOperator } = useAuth()
  const [tab, setTab] = useState<'search' | 'decode' | 'diagnose' | 'usage' | 'new'>(fromBugId ? 'new' : 'search')

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">← Docs</button>
        <h1 className="text-2xl font-bold text-gray-900">Error Knowledge Base</h1>
      </div>

      <div className="flex gap-1 border-b border-gray-200">
        {(['search', 'decode', 'diagnose', 'usage', ...(isOperator ? ['new'] as const : [])] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}>
            {t === 'search' ? '🔍 Search' : t === 'decode' ? '🧵 Decode' : t === 'diagnose' ? '🔬 Diagnose' : t === 'usage' ? '📊 Usage' : '+ New Entry'}
          </button>
        ))}
      </div>

      {tab === 'search' && <SearchTab onOpenDoc={onOpenDoc} />}
      {tab === 'decode' && <DecodeTab onOpenDoc={onOpenDoc} />}
      {tab === 'diagnose' && <DiagnoseTab onOpenDoc={onOpenDoc} onCreateBug={onCreateBug} />}
      {tab === 'usage' && <UsageTab onOpenDoc={onOpenDoc} />}
      {tab === 'new' && isOperator && <NewEntryTab fromBugId={fromBugId} onCreated={(docId, libId, libName, shelfId, shelfName, name) => onOpenDoc(docId, libId, libName, shelfId, shelfName, name)} />}
    </div>
  )
}

// ── Shared entry body ────────────────────────────────────────────────────────

function KbEntryBody({ entry }: { entry: KbEntry }) {
  return (
    <>
      {entry.causes.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Likely Causes</p>
          <ul className="space-y-1">
            {entry.causes.map((c, i) => (
              <li key={i} className="text-sm text-gray-700 flex gap-2"><span className="text-gray-400 shrink-0">•</span>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {entry.fix_steps.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Fix Steps</p>
          <ol className="space-y-1 list-decimal list-inside">
            {entry.fix_steps.map((s, i) => (
              <li key={i} className="text-sm text-gray-700">{s}</li>
            ))}
          </ol>
        </div>
      )}
    </>
  )
}

function EntryHeader({ entry, extra }: { entry: KbEntry; extra?: React.ReactNode }) {
  return (
    <div className="flex-1 min-w-0">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <span className={`px-2 py-0.5 text-xs font-medium rounded border ${SEVERITY_COLOUR[entry.severity] ?? 'bg-gray-100 text-gray-700 border-gray-200'}`}>
          {entry.severity}
        </span>
        <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-600">📚 {entry.library_name}</span>
        {extra}
      </div>
      <p className="font-medium text-gray-900 text-sm">{entry.title}</p>
      <p className="text-xs text-gray-500 mt-0.5">{entry.plain_english}</p>
    </div>
  )
}

// ── Search tab ───────────────────────────────────────────────────────────────

// Snippet text comes straight from document content, which is untrusted —
// escape it before turning the "**match**" markers (the FTS5 snippet()
// delimiters chosen server-side) into <mark> tags, so raw HTML sitting in
// a KB entry's own text can never get interpreted as markup here. Same
// approach as DocSearch.tsx's renderSnippet, duplicated per this
// codebase's per-file convention for small helpers.
function renderKbSnippet(snippet: string): string {
  const escaped = snippet
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
  return escaped.replace(/\*\*(.+?)\*\*/g, '<mark>$1</mark>')
}

function KbResultList({ results, expanded, setExpanded, onOpenDoc, renderExtra, countLabel }: {
  results: KbEntry[]
  expanded: string | null
  setExpanded: (id: string | null) => void
  onOpenDoc: Props['onOpenDoc']
  // Improvements Plan Stage 16 — lets the Usage tab attach a match-count
  // badge to each row without this shared list needing to know anything
  // about usage stats itself.
  renderExtra?: (entry: KbEntry) => React.ReactNode
  countLabel?: (n: number) => string
}) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-gray-500">{countLabel ? countLabel(results.length) : `${results.length} match${results.length !== 1 ? 'es' : ''} found`}</p>
      {results.map(entry => {
        const isOpen = expanded === entry.id
        return (
          <div key={entry.id} className="border border-gray-200 rounded-lg overflow-hidden bg-white">
            <button className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50"
              onClick={() => setExpanded(isOpen ? null : entry.id)}>
              <EntryHeader entry={entry} extra={renderExtra?.(entry)} />
              <span className="text-gray-400 text-sm mt-0.5">{isOpen ? '▲' : '▼'}</span>
            </button>
            {entry.snippet && (
              <p className="px-4 pb-2 text-xs text-gray-500 [&_mark]:bg-yellow-200 [&_mark]:text-gray-900 [&_mark]:rounded [&_mark]:px-0.5"
                dangerouslySetInnerHTML={{ __html: renderKbSnippet(entry.snippet) }} />
            )}
            {isOpen && (
              <div className="px-4 pb-4 border-t border-gray-100 space-y-3 pt-3">
                <KbEntryBody entry={entry} />
                <button
                  onClick={() => onOpenDoc(entry.doc_id, entry.library_id, entry.library_name, entry.shelf_id, entry.shelf_name, entry.title)}
                  className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700">
                  Open full entry →
                </button>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function SearchTab({ onOpenDoc }: { onOpenDoc: Props['onOpenDoc'] }) {
  const [mode, setMode] = useState<'pattern' | 'topic'>('pattern')
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)

  // Powers Browse by Topic's category pick-list — what's actually in the
  // KB, not a guessed keyword. Cheap (a handful of categories), so no
  // point gating the fetch behind the topic tab being active.
  const { data: categoriesData } = useQuery({
    queryKey: ['error-kb-categories'],
    queryFn: () => api.get('/docs/error-kb/categories').then(r => r.data),
  })
  const categories: { name: string; count: number }[] = categoriesData ?? []
  const toggleCategory = (name: string) => {
    setSelectedCategories(prev => prev.includes(name) ? prev.filter(c => c !== name) : [...prev, name])
  }

  const hasCategoryBrowse = mode === 'topic' && selectedCategories.length > 0
  const { data, isFetching } = useQuery({
    queryKey: ['error-kb-search', mode, query, selectedCategories],
    queryFn: () => {
      // Built by hand rather than passed via axios's `params` — axios
      // serialises an array value as `category[]=x`, but FastAPI's
      // `list[str] = Query(...)` only recognises the repeated-key form
      // (`category=x&category=y`), so an array under `params` silently
      // came through as an empty list server-side (confirmed live before
      // landing this fix).
      const usp = new URLSearchParams({ q: query, mode })
      selectedCategories.forEach(c => usp.append('category', c))
      return api.get(`/docs/error-kb/search?${usp.toString()}`).then(r => r.data)
    },
    enabled: query.length > 0 || hasCategoryBrowse,
  })

  const results: KbEntry[] = data?.results ?? []
  const doSearch = () => { const t = input.trim(); if (t) setQuery(t) }

  // Pattern search found nothing — fall back to a topic search on the same
  // text automatically, rather than leaving the user stuck at a dead end
  // just because their pasted text didn't literally match any regex.
  const fallbackEnabled = mode === 'pattern' && !isFetching && query.length > 0 && results.length === 0
  const { data: fallbackData, isFetching: fallbackFetching } = useQuery({
    queryKey: ['error-kb-search', 'topic', query, 'fallback'],
    queryFn: () => api.get('/docs/error-kb/search', { params: { q: query, mode: 'topic' } }).then(r => r.data),
    enabled: fallbackEnabled,
  })
  const fallbackResults: KbEntry[] = fallbackData?.results ?? []

  return (
    <div className="space-y-4">
      <div className="flex gap-1">
        {(['pattern', 'topic'] as const).map(m => (
          <button key={m} onClick={() => { setMode(m); setInput(''); setQuery(''); setSelectedCategories([]) }}
            className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide rounded-md border ${
              mode === m ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-500 border-gray-300 hover:bg-gray-50'
            }`}>
            {m === 'pattern' ? '📋 Paste Error Text' : '🔎 Browse by Topic'}
          </button>
        ))}
      </div>

      {mode === 'pattern' ? (
        <>
          <p className="text-sm text-gray-500">Paste a Java stack trace or error message to find matching causes and fix steps.</p>
          <div className="space-y-2">
            <textarea
              value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doSearch() }}
              placeholder="Paste error message or stack trace here…" rows={6}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex items-center gap-2">
              <button onClick={doSearch} disabled={!input.trim()}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
                Search KB
              </button>
              {input && <button onClick={() => { setInput(''); setQuery('') }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Clear</button>}
              <span className="text-xs text-gray-400 ml-1">Ctrl+Enter to search</span>
            </div>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-gray-500">Search KB entries by subject — no exact error message needed. Pick one or more topics below to browse them directly, with or without a keyword.</p>

          {categories.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {categories.map(c => {
                const isSelected = selectedCategories.includes(c.name)
                return (
                  <label key={c.name}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full border cursor-pointer select-none ${
                      isSelected ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                    }`}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleCategory(c.name)} className="sr-only" />
                    {c.name} <span className={isSelected ? 'text-blue-100' : 'text-gray-400'}>({c.count})</span>
                  </label>
                )
              })}
              {selectedCategories.length > 0 && (
                <button onClick={() => setSelectedCategories([])} className="px-2.5 py-1 text-xs text-gray-500 hover:text-gray-700 underline">
                  Clear topics
                </button>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            <input
              type="text" value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') doSearch() }}
              placeholder="e.g. keystone certificate, rabbitmq timeout…" autoFocus
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
            <button onClick={doSearch} disabled={!input.trim()}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
              Search KB
            </button>
          </div>
        </>
      )}

      {isFetching && <p className="text-sm text-gray-400">Searching…</p>}

      {!isFetching && (query || hasCategoryBrowse) && results.length === 0 && !fallbackFetching && fallbackResults.length === 0 && (
        <div className="p-6 bg-gray-50 border border-gray-200 rounded-lg text-center text-sm text-gray-500">
          No matching KB entries found.{mode === 'pattern' ? ' Try pasting more of the error message, or switch to "Browse by Topic."' : ' Try a different or broader term, or add a custom entry in New Entry.'}
        </div>
      )}

      {results.length > 0 && (
        <KbResultList results={results} expanded={expanded} setExpanded={setExpanded} onOpenDoc={onOpenDoc} />
      )}

      {results.length === 0 && fallbackFetching && (
        <p className="text-sm text-gray-400">No exact pattern match — checking by topic…</p>
      )}

      {results.length === 0 && !fallbackFetching && fallbackResults.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
            No exact pattern match, but these entries look related by topic:
          </p>
          <KbResultList results={fallbackResults} expanded={expanded} setExpanded={setExpanded} onOpenDoc={onOpenDoc} />
        </div>
      )}
    </div>
  )
}

// ── ML Analysis Panel ────────────────────────────────────────────────────────

const ML_SEVERITY_COLOUR: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  warning:  'bg-amber-100 text-amber-700',
  normal:   'bg-gray-100 text-gray-600',
}

function MlAnalysisPanel({ ml }: { ml: MlAnalysis }) {
  // Start expanded when degraded so the reason is immediately visible,
  // or when there are actual anomalies worth seeing straight away.
  const [open, setOpen] = useState(ml.degraded || ml.anomalous_windows > 0)

  const badge = ml.degraded
    ? <span className="px-2 py-0.5 text-xs font-semibold rounded bg-amber-100 text-amber-700 border border-amber-200">🧠 ML — partial</span>
    : ml.anomalous_windows > 0
      ? <span className="px-2 py-0.5 text-xs font-semibold rounded bg-purple-100 text-purple-700 border border-purple-200">🧠 ML — {ml.anomalous_windows} anomal{ml.anomalous_windows === 1 ? 'y' : 'ies'} detected</span>
      : <span className="px-2 py-0.5 text-xs font-semibold rounded bg-green-100 text-green-700 border border-green-200">🧠 ML — no anomalies</span>

  return (
    <div className="border-2 border-purple-300 rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left bg-purple-50 hover:bg-purple-100"
      >
        {badge}
        <span className="text-sm text-gray-700 flex-1">{ml.summary}</span>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-purple-100">
          <div className="flex flex-wrap gap-4 text-xs text-gray-500">
            <span>Windows analysed: <strong className="text-gray-700">{ml.windows_analysed}</strong></span>
            <span>Anomalous: <strong className="text-gray-700">{ml.anomalous_windows}</strong></span>
            <span>Correlated incidents: <strong className="text-gray-700">{ml.correlated_incidents.length}</strong></span>
          </div>

          {ml.degraded && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
              ⚠ {ml.degradation_reason || 'Partial analysis'}
            </p>
          )}

          {ml.top_anomalies.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1.5">Top Anomalous Windows</p>
              <div className="space-y-1.5">
                {ml.top_anomalies.map((a, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${ML_SEVERITY_COLOUR[a.severity] ?? 'bg-gray-100 text-gray-600'}`}>
                      {a.severity}
                    </span>
                    <span className="font-mono text-gray-500 shrink-0">score {a.score.toFixed(3)}</span>
                    {a.top_features.length > 0 && (
                      <span className="text-gray-600 truncate">{a.top_features.slice(0, 3).join(', ')}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {ml.correlated_incidents.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1.5">Correlated to Stack Trace</p>
              <div className="space-y-1.5">
                {ml.correlated_incidents.map((ci, i) => (
                  <div key={i} className="text-xs bg-white border border-purple-100 rounded px-2 py-1.5">
                    <span className="font-medium text-gray-800">{ci.exception_class ?? 'unknown'}</span>
                    <span className="ml-2 text-gray-500">confidence {(ci.confidence * 100).toFixed(0)}%</span>
                    {ci.matched_frames.length > 0 && (
                      <p className="font-mono text-gray-400 mt-0.5 truncate">{ci.matched_frames[0]}</p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Root cause export helpers ───────────────────────────────────────────────

function buildRootCauseMarkdown(exc: DecodedException): string {
  const lines: string[] = []
  lines.push(`# 🎯 Likely Root Cause`)
  lines.push(`\n**${exc.exception_class ?? 'Unknown exception'}**`)
  if (exc.message) lines.push(`\n> ${exc.message}`)
  const appFrames = exc.frames.filter(f => f.is_application_frame)
  const framesToShow = appFrames.length > 0 ? appFrames : exc.frames.slice(0, 5)
  if (framesToShow.length > 0) {
    lines.push(`\n## Stack Frames\n\`\`\``)
    framesToShow.forEach(f => {
      const loc = f.is_native ? 'Native Method'
        : f.file_name ? `${f.file_name}${f.line_number ? `:${f.line_number}` : ''}`
        : 'Unknown Source'
      lines.push(`at ${f.class_name}.${f.method_name}(${loc})`)
    })
    lines.push('```')
  }
  if (exc.kb_matches.length > 0) {
    lines.push(`\n## KB Matches`)
    exc.kb_matches.forEach(m => {
      lines.push(`\n### ${m.title} *(${m.severity})*`)
      if (m.plain_english) lines.push(m.plain_english)
      if (m.causes.length > 0) {
        lines.push('\n**Likely Causes**')
        m.causes.forEach(c => lines.push(`- ${c}`))
      }
      if (m.fix_steps.length > 0) {
        lines.push('\n**Fix Steps**')
        m.fix_steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`))
      }
    })
  }
  return lines.join('\n')
}

function openRootCauseTab(exc: DecodedException) {
  const md = buildRootCauseMarkdown(exc)
  const escaped = md
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/^# (.+)/gm, '<h1>$1</h1>')
    .replace(/^## (.+)/gm, '<h2>$1</h2>')
    .replace(/^### (.+)/gm, '<h3>$1</h3>')
    .replace(/^- (.+)/gm, '<li>$1</li>')
    .replace(/^(\d+)\. (.+)/gm, '<li>$1. $2</li>')
    .replace(/^&gt; (.+)/gm, '<blockquote>$1</blockquote>')
  const html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Root Cause — ${exc.exception_class ?? 'Unknown'}</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:860px;margin:40px auto;padding:0 24px;color:#1f2937;line-height:1.6}
  h1{color:#b91c1c;border-bottom:2px solid #fca5a5;padding-bottom:8px}
  h2{color:#374151;margin-top:2em}h3{color:#4b5563}
  code,pre{background:#f3f4f6;border-radius:4px;padding:2px 6px;font-size:.9em}
  pre{padding:12px;overflow-x:auto;white-space:pre-wrap}
  blockquote{border-left:4px solid #d1d5db;margin:0;padding:4px 16px;color:#6b7280}
  li{margin:.25em 0}.print-btn{position:fixed;top:16px;right:16px;padding:8px 16px;
  background:#2563eb;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:.875rem}
  @media print{.print-btn{display:none}}
</style></head><body>
<button class="print-btn" onclick="window.print()">🖨 Print / Save PDF</button>
${escaped}
</body></html>`
  const blob = new Blob([html], { type: 'text/html' })
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

function downloadMarkdown(exc: DecodedException) {
  const md = buildRootCauseMarkdown(exc)
  const blob = new Blob([md], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `root-cause-${(exc.exception_class ?? 'unknown').split('.').pop()}.md`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 5_000)
}

function RootCauseActions({ exc }: { exc: DecodedException }) {
  const [exportOpen, setExportOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!exportOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setExportOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [exportOpen])
  return (
    <div className="relative flex items-center gap-1 ml-auto">
      <button
        onClick={() => openRootCauseTab(exc)}
        title="Open root cause in a new tab for easier reading"
        className="px-2 py-0.5 text-xs rounded bg-white border border-red-200 text-red-700 hover:bg-red-50">
        ↗ Open in tab
      </button>
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setExportOpen(o => !o)}
          title="Export root cause"
          className="px-2 py-0.5 text-xs rounded bg-white border border-red-200 text-red-700 hover:bg-red-50">
          Export ▾
        </button>
        {exportOpen && (
          <div className="absolute right-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded shadow-lg text-xs min-w-[130px]">
            <button
              onClick={() => { openRootCauseTab(exc); setExportOpen(false) }}
              className="w-full text-left px-3 py-2 hover:bg-gray-50">
              🖨 PDF (print)
            </button>
            <button
              onClick={() => { downloadMarkdown(exc); setExportOpen(false) }}
              className="w-full text-left px-3 py-2 hover:bg-gray-50">
              📄 Markdown (.md)
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Decode tab ───────────────────────────────────────────────────────────────

const KIND_LABEL: Record<DecodedException['kind'], string> = {
  root: 'Exception', caused_by: 'Caused by', suppressed: 'Suppressed',
}

// Deep-links back into the JAR Analyser using the same `?report=&sub=&tab=`
// convention JarAnalyserPage.tsx already reads on mount for cross-navigation
// from Docs (bug/first-seen links) — landing on the Source tab only makes
// sense when this class has actually been decompiled (Section 36).
function FrameKnownInBadge({ match }: { match: KnownClassMatch }) {
  const navigate = useNavigate()
  const params = new URLSearchParams({ report: match.report_id, sub: match.sub_report_id })
  if (match.decompiled) params.set('tab', 'source')
  return (
    <button
      onClick={() => navigate(`/jar-analyser?${params.toString()}`)}
      title={match.decompiled ? 'This class has been decompiled — open its source' : 'Open this service in the JAR Analyser'}
      className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] rounded bg-blue-100 text-blue-700 hover:bg-blue-200 align-middle">
      📍 {match.service_name}{match.decompiled ? ' · source' : ''}
    </button>
  )
}

function FrameLine({ frame }: { frame: StackFrame }) {
  const loc = frame.is_native ? 'Native Method'
    : frame.file_name ? `${frame.file_name}${frame.line_number ? `:${frame.line_number}` : ''}`
    : 'Unknown Source'
  return (
    <li className={`whitespace-pre-wrap break-all ${frame.is_application_frame ? 'text-gray-700' : 'text-gray-400'}`}>
      at {frame.class_name}.{frame.method_name}({loc})
      {frame.known_in.map((m, i) => <FrameKnownInBadge key={i} match={m} />)}
    </li>
  )
}

function ExceptionFrames({ frames }: { frames: StackFrame[] }) {
  const [showAll, setShowAll] = useState(false)
  if (frames.length === 0) return null

  const appFrames = frames.filter(f => f.is_application_frame)
  const frameworkCount = frames.length - appFrames.length
  // Application frames first (the ones actually worth reading), framework/
  // JDK plumbing hidden by default — unless the whole block is framework
  // noise (e.g. the exception originates deep inside a library), in which
  // case falling back to the first few raw frames beats showing nothing.
  const visible = showAll ? frames : (appFrames.length > 0 ? appFrames : frames.slice(0, 3))

  return (
    <div className="mt-2 bg-gray-50 border border-gray-100 rounded px-3 py-2">
      <ol className="space-y-0.5 font-mono text-xs">
        {visible.map((f, i) => <FrameLine key={i} frame={f} />)}
      </ol>
      {!showAll && appFrames.length > 0 && frameworkCount > 0 && (
        <button onClick={() => setShowAll(true)} className="mt-1 text-xs text-blue-600 hover:underline">
          Show {frameworkCount} framework frame{frameworkCount !== 1 ? 's' : ''}
        </button>
      )}
      {!showAll && appFrames.length === 0 && frames.length > 3 && (
        <button onClick={() => setShowAll(true)} className="mt-1 text-xs text-blue-600 hover:underline">
          Show {frames.length - 3} more frame{frames.length - 3 !== 1 ? 's' : ''}
        </button>
      )}
      {showAll && (
        <button onClick={() => setShowAll(false)} className="mt-1 text-xs text-blue-600 hover:underline">
          Show fewer frames
        </button>
      )}
    </div>
  )
}

function DecodeTab({ onOpenDoc }: { onOpenDoc: Props['onOpenDoc'] }) {
  const [input, setInput] = useState('')
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data, isFetching, isError } = useQuery({
    queryKey: ['error-kb-decode', text],
    queryFn: () => api.post('/docs/error-kb/decode', { text }).then(r => r.data as DecodeStackTraceResponse),
    enabled: text.length > 0,
  })

  const doDecode = () => { const t = input.trim(); if (t) setText(t) }
  const exceptions: DecodedException[] = data?.exceptions ?? []

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Paste a full log excerpt or stack trace — including any "Caused by:"/"Suppressed:" chain — and each
        exception is matched against the Error KB independently, so a wrapped root cause isn't drowned out
        by the outer exception's own matches.
      </p>
      <div className="space-y-2">
        <textarea
          value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doDecode() }}
          placeholder="Paste a full log excerpt or stack trace here…" rows={10}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex items-center gap-2">
          <button onClick={doDecode} disabled={!input.trim()}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
            🧵 Decode
          </button>
          {input && <button onClick={() => { setInput(''); setText('') }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Clear</button>}
          <span className="text-xs text-gray-400 ml-1">Ctrl+Enter to decode</span>
          {data?.ml_analysis && (
            <span className={`ml-auto px-2 py-1 text-xs font-semibold rounded border ${
              data.ml_analysis.degraded ? 'bg-amber-50 text-amber-700 border-amber-300' :
              data.ml_analysis.anomalous_windows > 0 ? 'bg-purple-50 text-purple-700 border-purple-300' :
              'bg-green-50 text-green-700 border-green-300'
            }`}>
              🧠 ML active
            </span>
          )}
        </div>
      </div>

      {data?.ml_analysis && <MlAnalysisPanel ml={data.ml_analysis} />}

      {isFetching && <p className="text-sm text-gray-400">Decoding…</p>}

      {isError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">Failed to decode — check the pasted text and try again.</p>
      )}

      {!isFetching && !isError && text && exceptions.length === 0 && (
        <div className="p-6 bg-gray-50 border border-gray-200 rounded-lg text-center text-sm text-gray-500">
          No exception chain recognised in that text — this only parses Java "at ..." stack frames and
          "Caused by:"/"Suppressed:" headers, not arbitrary log lines.
        </div>
      )}

      {exceptions.length > 0 && (
        <div className="space-y-4">
          {exceptions.map((exc, i) => (
            <div key={i} className={`border rounded-lg p-3 ${exc.kind === 'root' ? 'bg-white' : 'bg-amber-50/40 ml-4'} ${
              exc.is_likely_root_cause ? 'border-red-300 ring-1 ring-red-100' : exc.kind === 'root' ? 'border-gray-300' : 'border-amber-200'
            }`}>
              <div className="flex items-center gap-2 mb-1 flex-wrap">
                <span className={`px-2 py-0.5 text-xs font-semibold rounded ${exc.kind === 'root' ? 'bg-gray-100 text-gray-700' : 'bg-amber-100 text-amber-800'}`}>
                  {KIND_LABEL[exc.kind]}
                </span>
                {exc.is_likely_root_cause && (
                  <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-100 text-red-700 border border-red-200"
                    title="Java wraps and rethrows exceptions as they propagate up the call stack — this is usually the deepest, most likely actual cause, not the outer exception that got logged.">
                    🎯 Likely root cause
                  </span>
                )}
                <span className="font-mono text-sm text-gray-900 whitespace-pre-wrap break-all">{exc.exception_class ?? '(unnamed — frames only)'}</span>
                {exc.is_likely_root_cause && <RootCauseActions exc={exc} />}
              </div>
              {exc.message && <p className="text-sm text-gray-600 whitespace-pre-wrap break-words">{exc.message}</p>}
              <ExceptionFrames frames={exc.frames} />

              {exc.kb_matches.length > 0 ? (
                <div className="mt-3">
                  <KbResultList results={exc.kb_matches} expanded={expanded} setExpanded={setExpanded} onOpenDoc={onOpenDoc} />
                </div>
              ) : (
                <p className="mt-2 text-xs text-gray-400">No KB entries matched this exception.</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Diagnose tab ─────────────────────────────────────────────────────────────

interface ReportOption {
  report_id: string
  filename: string
  label?: string | null
  implementation_title?: string | null
  implementation_version?: string | null
  uploaded_at?: string
}

// Filename + version + upload date + short id — implementation_title alone
// is often the same generic string ("installation-package") across many
// uploads of the same product, so it can't distinguish which report is
// which; even filename+version+date can collide when the same bundle was
// re-analysed (same upload, different analysis run), so the short report id
// is always appended as a guaranteed-unique tiebreaker.
function reportOptionLabel(r: ReportOption): string {
  const parts = [r.label || r.filename]
  if (r.implementation_version) parts.push(`v${r.implementation_version}`)
  if (r.uploaded_at) parts.push(new Date(r.uploaded_at).toLocaleDateString())
  parts.push(`#${r.report_id.slice(0, 8)}`)
  return parts.join(' — ')
}

// One line per context finding, covering the union of shapes the different
// context functions in error_diagnostician.py produce (config key/value,
// endpoint method/path, migration filename/version) — same fields SearchTab's
// own findings render already surfaces, just flattened to plain text for the
// bug form's "Relevant config" field instead of styled JSX.
function formatFinding(f: KbDiagnosisResult['context_findings'][number]): string {
  const parts = [f.service]
  if (f.config_key) parts.push(f.config_key)
  if (f.method && f.path) parts.push(`${f.method} ${f.path}`)
  if (f.filename) parts.push(`${f.filename}${f.version ? ` (v${f.version})` : ''}`)
  if (f.value) parts.push(`= ${f.value}`)
  if (f.is_placeholder) parts.push('(placeholder)')
  if (f.roles_required?.length) parts.push(`requires: ${f.roles_required.join(', ')}`)
  if (f.declared_port) parts.push(`port ${f.declared_port}`)
  return parts.join(' · ')
}

function buildBugPrefill(result: KbDiagnosisResult, reportId: string, pastedText: string): BugPrefillData {
  const entry = result.kb_entry
  const exc = result.matched_exception
  const title = exc?.exception_class ? `${exc.exception_class}: ${entry.title}` : entry.title
  const actual = exc?.exception_class
    ? `${exc.exception_class}${exc.message ? `: ${exc.message}` : ''}`
    : (entry.plain_english || pastedText.slice(0, 300))

  // Only carries a specific service forward when every finding agrees on
  // one — a KB entry whose findings span several services shouldn't silently
  // pick one at random, so it's left for the human to pick in that case.
  const subReportIds = new Set(result.context_findings.map(f => f.sub_report_id).filter(Boolean))
  const subReportId = subReportIds.size === 1 ? [...subReportIds][0] : undefined

  return {
    title, severity: (entry.severity as BugPrefillData['severity']) || 'medium',
    actual, logs: pastedText,
    envConfig: result.context_findings.map(formatFinding).join('\n'),
    tags: [entry.category].filter(Boolean),
    reportId, subReportId,
  }
}

function DiagnoseTab({ onOpenDoc, onCreateBug }: {
  onOpenDoc: Props['onOpenDoc']
  onCreateBug: Props['onCreateBug']
}) {
  const [reportId, setReportId] = useState('')
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data: reportsData } = useQuery({
    queryKey: ['jar-reports-picker'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 100 } }).then(r => r.data),
  })
  const reports: ReportOption[] = reportsData?.items ?? []

  const { data: diagData, isFetching } = useQuery({
    queryKey: ['error-diagnose', reportId, query],
    queryFn: () => api.post(`/jar-analyser/reports/${reportId}/diagnose`, { error_text: query }).then(r => r.data),
    enabled: query.length > 0 && !!reportId,
  })

  const results: KbDiagnosisResult[] = diagData?.results ?? []
  const doSearch = () => { const t = input.trim(); if (t && reportId) setQuery(t) }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">Cross-references KB matches against a specific report's own endpoints, config, and migrations.</p>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Report</label>
        <select value={reportId} onChange={e => { setReportId(e.target.value); setQuery('') }}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">Select a report…</option>
          {reports.map(r => (
            <option key={r.report_id} value={r.report_id}>{reportOptionLabel(r)}</option>
          ))}
        </select>
      </div>

      <div className="space-y-2">
        <textarea
          value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) doSearch() }}
          placeholder="Paste error message or stack trace here…" rows={6}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex items-center gap-2">
          <button onClick={doSearch} disabled={!input.trim() || !reportId}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
            🔬 Diagnose
          </button>
          {input && <button onClick={() => { setInput(''); setQuery('') }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700">Clear</button>}
          {diagData?.ml_analysis && (
            <span className={`ml-auto px-2 py-1 text-xs font-semibold rounded border ${
              diagData.ml_analysis.degraded ? 'bg-amber-50 text-amber-700 border-amber-300' :
              diagData.ml_analysis.anomalous_windows > 0 ? 'bg-purple-50 text-purple-700 border-purple-300' :
              'bg-green-50 text-green-700 border-green-300'
            }`}>
              🧠 ML active
            </span>
          )}
        </div>
      </div>

      {isFetching && <p className="text-sm text-gray-400">Diagnosing…</p>}

      {diagData?.ml_analysis && <MlAnalysisPanel ml={diagData.ml_analysis} />}

      {!isFetching && query && results.length === 0 && (
        <div className="p-6 bg-gray-50 border border-gray-200 rounded-lg text-center text-sm text-gray-500">
          No matching KB entries found for this error text.
        </div>
      )}

      {results.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-gray-500">{results.length} match{results.length !== 1 ? 'es' : ''} found</p>
          {results.map((result, idx) => {
            const entry = result.kb_entry
            const isOpen = expanded === (entry.id ?? String(idx))
            const hasContext = result.context_findings.length > 0 || result.suggested_actions.length > 0
            return (
              <div key={entry.id ?? idx} className="border border-blue-200 rounded-lg overflow-hidden bg-white">
                <button className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-blue-50"
                  onClick={() => setExpanded(isOpen ? null : (entry.id ?? String(idx)))}>
                  <EntryHeader entry={entry} extra={hasContext ? (
                    <span className="px-2 py-0.5 text-xs rounded bg-blue-100 text-blue-700 border border-blue-200">
                      🔬 {result.context_findings.length} context finding{result.context_findings.length !== 1 ? 's' : ''}
                    </span>
                  ) : undefined} />
                  <span className="text-gray-400 text-sm mt-0.5">{isOpen ? '▲' : '▼'}</span>
                </button>
                {isOpen && (
                  <div className="px-4 pb-4 border-t border-blue-100 space-y-4 pt-3">
                    <KbEntryBody entry={entry} />

                    {result.context_findings.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-2">📋 Report Context Findings</p>
                        <div className="space-y-2">
                          {result.context_findings.map((f, i) => (
                            <div key={i} className="bg-blue-50 border border-blue-100 rounded px-3 py-2 text-xs">
                              <span className="font-medium text-blue-800">{f.service}</span>
                              {f.config_key && <span className="text-blue-600"> · {f.config_key}</span>}
                              {f.path && <span className="text-blue-600"> · {f.method} {f.path}</span>}
                              {f.filename && <span className="text-blue-600"> · {f.filename} (v{f.version})</span>}
                              {f.value !== undefined && f.value !== '' && <span className="ml-1 font-mono text-gray-600">= {f.value}</span>}
                              {f.is_placeholder && <span className="ml-1 text-amber-600">(placeholder)</span>}
                              {f.has_default === false && <span className="ml-1 text-red-600 font-medium">⚠ no default</span>}
                              {f.roles_required && f.roles_required.length > 0 && <span className="ml-1 text-indigo-600">requires: {f.roles_required.join(', ')}</span>}
                              {f.declared_port && <span className="ml-1 text-gray-500">port {f.declared_port}</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {result.suggested_actions.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">✅ Suggested Actions</p>
                        <div className="space-y-2">
                          {result.suggested_actions.map((a, i) => (
                            <div key={i} className="bg-green-50 border border-green-100 rounded px-3 py-2">
                              <p className="text-sm font-medium text-green-800">{a.label}</p>
                              <p className="text-xs text-green-700 mt-0.5">{a.description}</p>
                              {a.cert_manager_tool && <CertManagerLink tool={a.cert_manager_tool} params={a.cert_manager_params} />}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="flex gap-2">
                      <button
                        onClick={() => onOpenDoc(entry.doc_id, entry.library_id, entry.library_name, entry.shelf_id, entry.shelf_name, entry.title)}
                        className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700">
                        Open full entry →
                      </button>
                      <button
                        onClick={() => onCreateBug(buildBugPrefill(result, reportId, query))}
                        title="Opens a new bug report, prefilled with this diagnosis's exception, severity, matched service, and config findings"
                        className="px-3 py-1.5 text-xs bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50">
                        🐛 Create Bug
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Usage tab (Improvements Plan Stage 16) ─────────────────────────────────────

function UsageTab({ onOpenDoc }: { onOpenDoc: Props['onOpenDoc'] }) {
  const [order, setOrder] = useState<'most' | 'least'>('most')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['error-kb-usage'],
    queryFn: () => api.get('/docs/error-kb/usage').then(r => r.data),
  })

  const entries: KbEntry[] = data?.entries ?? []
  // The endpoint already sorts most-matched-first — "least matched" is
  // just the reverse of that same list, not a second request.
  const sorted = order === 'most' ? entries : [...entries].reverse()

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        How many times each KB entry's pattern has actually matched real pasted or scanned error text —
        across both the Search tab's pattern mode and JAR Analyser's Diagnose. A high count means the
        entry is pulling its weight; a zero or low count (especially on an old entry) is a signal it
        might need a broader pattern, a rewrite, or removing.
      </p>

      <div className="flex gap-1">
        {(['most', 'least'] as const).map(o => (
          <button key={o} onClick={() => setOrder(o)}
            className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide rounded-md border ${
              order === o ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-500 border-gray-300 hover:bg-gray-50'
            }`}>
            {o === 'most' ? '🔥 Most Matched' : '🧊 Least Matched'}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}

      {!isLoading && entries.length === 0 && (
        <div className="p-6 bg-gray-50 border border-gray-200 rounded-lg text-center text-sm text-gray-500">
          No KB entries yet.
        </div>
      )}

      {sorted.length > 0 && (
        <KbResultList
          results={sorted} expanded={expanded} setExpanded={setExpanded} onOpenDoc={onOpenDoc}
          countLabel={n => `${n} KB entr${n !== 1 ? 'ies' : 'y'}`}
          renderExtra={entry => (
            <span className={`px-2 py-0.5 text-xs rounded ${
              (entry.match_count ?? 0) === 0 ? 'bg-gray-100 text-gray-500' : 'bg-blue-100 text-blue-700'
            }`}>
              {entry.match_count ?? 0} match{entry.match_count === 1 ? '' : 'es'}
              {entry.last_matched_at ? ` · last ${new Date(entry.last_matched_at).toLocaleDateString()}` : ''}
            </span>
          )}
        />
      )}
    </div>
  )
}

// ── Cert Manager deep-link button ─────────────────────────────────────────────

const CERT_MANAGER_TOOL_ROUTES: Record<string, string> = {
  keystore: '/tools?tool=keystore',
  p12: '/tools?tool=p12',
  remote: '/tools?tool=remote',
  decode: '/tools?tool=decode',
  verify: '/tools?tool=verify',
  javadebug: '/tools?tool=javadebug',
  conntest: '/tools?tool=conntest',
  csr: '/csr',
}

function CertManagerLink({ tool, params }: { tool: string; params: Record<string, unknown> }) {
  const base = CERT_MANAGER_TOOL_ROUTES[tool]
  if (!base) return null
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
  const href = qs ? `${base}&${qs}` : base
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="inline-flex items-center gap-1 mt-1.5 px-2 py-1 text-xs bg-white border border-green-300 text-green-700 rounded hover:bg-green-50">
      🔧 Fix with Cert Manager
    </a>
  )
}

// ── New entry tab ────────────────────────────────────────────────────────────

function renderKbDocContent(severity: string, pattern: string, plainEnglish: string, causes: string[], fixSteps: string[], seeAlso: string[]): string {
  const lines = [`**Severity:** ${severity}`, `**Pattern:** \`${pattern}\``, '']
  if (plainEnglish.trim()) lines.push(plainEnglish.trim(), '')
  if (causes.length) { lines.push('## Likely Causes', ''); lines.push(...causes.map(c => `- ${c}`)); lines.push('') }
  if (fixSteps.length) { lines.push('## Fix Steps', ''); lines.push(...fixSteps.map((s, i) => `${i + 1}. ${s}`)); lines.push('') }
  if (seeAlso.length) { lines.push('## See Also', ''); lines.push(...seeAlso.map(t => `- [[${t}]]`)); lines.push('') }
  return lines.join('\n').replace(/\n+$/, '') + '\n'
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function NewEntryTab({ onCreated, fromBugId }: {
  onCreated: (docId: string, libraryId: string, libraryName: string, shelfId: string, shelfName: string, title: string) => void
  fromBugId?: string
}) {
  const queryClient = useQueryClient()
  const { data: libraries } = useQuery<DocLibrary[]>({
    queryKey: ['doc-libraries'],
    queryFn: () => api.get('/docs/libraries').then(r => r.data),
  })

  const [libraryChoice, setLibraryChoice] = useState('__new__')
  const [newLibraryName, setNewLibraryName] = useState('')
  const [title, setTitle] = useState('')
  const [severity, setSeverity] = useState('medium')
  const [pattern, setPattern] = useState('')
  const [plainEnglish, setPlainEnglish] = useState('')
  const [causesText, setCausesText] = useState('')
  const [stepsText, setStepsText] = useState('')
  const [seeAlsoText, setSeeAlsoText] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // "Promote to KB" prefill — same "fetch once, prefill via useEffect + a
  // prefilled guard" pattern BugTracker.tsx's NewBugForm already uses for
  // its own job/environment prefill.
  const { data: sourceBug } = useQuery<BugFull>({
    queryKey: ['bug-for-kb-promote', fromBugId],
    queryFn: () => api.get(`/bugs/${fromBugId}`).then(r => r.data),
    enabled: !!fromBugId,
  })
  const [bugPrefilled, setBugPrefilled] = useState(false)
  useEffect(() => {
    if (!fromBugId || bugPrefilled || !sourceBug) return
    setTitle(sourceBug.title)
    setSeverity(sourceBug.severity)
    if (sourceBug.resolution) setPlainEnglish(sourceBug.resolution.trim())
    const failLine = sourceBug.description
      .split('\n')
      .map(l => l.trim())
      .find(l => l.includes('fatal:') || l.includes('FAILED!'))
    if (failLine) setPattern(escapeRegExp(failLine))
    if (sourceBug.bm_job_id && libraries?.some(l => l.name === 'Ansible')) {
      setLibraryChoice('Ansible')
    }
    setBugPrefilled(true)
  }, [fromBugId, sourceBug, bugPrefilled, libraries])

  const handleSave = async () => {
    setError('')
    const categoryName = libraryChoice === '__new__' ? newLibraryName.trim() : libraryChoice
    if (!title.trim() || !pattern.trim() || !categoryName) {
      setError('Category, Title, and Pattern are required.')
      return
    }
    setSaving(true)
    try {
      let libraryId = libraries?.find(l => l.name === categoryName)?.id
      let libraryName = categoryName
      if (!libraryId) {
        const res = await api.post('/docs/libraries', { name: categoryName })
        libraryId = res.data.id
        libraryName = res.data.name
      }
      const shelvesRes = await api.get(`/docs/libraries/${libraryId}/shelves`)
      let shelf = shelvesRes.data.find((s: { name: string }) => s.name === 'Errors')
      if (!shelf) {
        const res = await api.post('/docs/shelves', { library_id: libraryId, name: 'Errors' })
        shelf = res.data
      }

      const content = renderKbDocContent(
        severity, pattern.trim(), plainEnglish,
        causesText.split('\n').map(s => s.trim()).filter(Boolean),
        stepsText.split('\n').map(s => s.trim()).filter(Boolean),
        seeAlsoText.split(',').map(s => s.trim()).filter(Boolean),
      )
      const docRes = await api.post('/docs', { shelf_id: shelf.id, name: title.trim(), content })
      await queryClient.invalidateQueries({ queryKey: ['doc-libraries'] })
      onCreated(docRes.data.id, libraryId!, libraryName, shelf.id, shelf.name, docRes.data.name)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save entry')
    } finally {
      setSaving(false)
    }
  }

  const field = (label: string, node: React.ReactNode) => (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {node}
    </div>
  )

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}

      <div className="grid grid-cols-2 gap-4">
        {field('Category (library) *',
          <div className="flex gap-2">
            <select value={libraryChoice} onChange={e => setLibraryChoice(e.target.value)}
              className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm">
              <option value="__new__">+ New category…</option>
              {libraries?.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
            </select>
          </div>
        )}
        {field('Severity',
          <select value={severity} onChange={e => setSeverity(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
            {SEVERITIES.map(s => <option key={s}>{s}</option>)}
          </select>
        )}
      </div>

      {libraryChoice === '__new__' && field('New category name',
        <input value={newLibraryName} onChange={e => setNewLibraryName(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="e.g. Keystone" />
      )}

      {field('Title *',
        <input value={title} onChange={e => setTitle(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="Short descriptive title" />
      )}

      {field('Pattern (regex) *',
        <input value={pattern} onChange={e => setPattern(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
          placeholder="e.g. PKIX path building failed|unable to find valid certification" />
      )}

      {field('Plain English Description',
        <textarea value={plainEnglish} onChange={e => setPlainEnglish(e.target.value)}
          rows={2} className="w-full border border-gray-300 rounded px-3 py-2 text-sm resize-y"
          placeholder="One sentence explaining what this error means in plain language" />
      )}

      {field('Causes (one per line)',
        <textarea value={causesText} onChange={e => setCausesText(e.target.value)}
          rows={4} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono resize-y"
          placeholder="The server certificate is self-signed&#10;The CA is not in the JVM trust store" />
      )}

      {field('Fix Steps (one per line)',
        <textarea value={stepsText} onChange={e => setStepsText(e.target.value)}
          rows={4} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono resize-y"
          placeholder="Import the CA: keytool -importcert ...&#10;Restart the service" />
      )}

      {field('See Also (comma-separated entry titles)',
        <input value={seeAlsoText} onChange={e => setSeeAlsoText(e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          placeholder="SSL handshake failure, Empty or missing trust store" />
      )}

      <div className="flex gap-2 pt-2">
        <button onClick={handleSave} disabled={saving}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
          {saving ? 'Saving…' : 'Create Entry'}
        </button>
      </div>
    </div>
  )
}
