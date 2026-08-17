import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import MarkdownPreview, { preprocessMarkdown } from './MarkdownPreview'
import AnnotationLayer from './AnnotationLayer'
import StructuredView from './StructuredView'
import VersionHistory from './VersionHistory'
import type { DocFull } from './types'

// Report/sub-report picker shape — same duplication convention as the
// backend's per-module helpers (see doc_first_seen_plan.md): redeclared
// here rather than imported from BugTracker.tsx, which owns its own copy.
interface ReportOption { report_id: string; filename: string; implementation_version?: string | null; uploaded_at?: string }
interface SubReportOption { sub_report_id: string; service_name: string | null; filename: string }

function reportOptionLabel(r: ReportOption): string {
  const parts = [r.filename]
  if (r.implementation_version) parts.push(`v${r.implementation_version}`)
  if (r.uploaded_at) parts.push(new Date(r.uploaded_at).toLocaleDateString())
  parts.push(`#${r.report_id.slice(0, 8)}`)
  return parts.join(' — ')
}

interface Props {
  docId: string
  libraryName: string
  shelfName: string
  onBackToShelf: () => void
  onNavigateToDoc: (name: string) => void
  onEdit: () => void
}

interface TocEntry { id: string; text: string; level: number }

function findScrollParent(el: Element | null): Element {
  let node = el?.parentElement ?? null
  while (node && node !== document.body) {
    const style = getComputedStyle(node)
    if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight) {
      return node
    }
    node = node.parentElement
  }
  return document.scrollingElement || document.documentElement
}

export default function DocReader({ docId, libraryName, shelfName, onBackToShelf, onNavigateToDoc, onEdit }: Props) {
  const { isOperator } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const containerRef = useRef<HTMLDivElement>(null)
  const [toc, setToc] = useState<TocEntry[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [viewMode, setViewMode] = useState<'document' | 'structured'>('structured')
  const [editingFirstSeen, setEditingFirstSeen] = useState(false)
  const [fsReportId, setFsReportId] = useState('')
  const [fsSubReportId, setFsSubReportId] = useState('')
  const [savingFirstSeen, setSavingFirstSeen] = useState(false)
  const [firstSeenError, setFirstSeenError] = useState('')
  const [unanchoredCount, setUnanchoredCount] = useState(0)
  const [unanchoredDismissedAt, setUnanchoredDismissedAt] = useState(0)
  const [showVersionHistory, setShowVersionHistory] = useState(false)
  const [exportingFormat, setExportingFormat] = useState<'pdf' | 'markdown' | null>(null)

  const { data: doc, isLoading } = useQuery<DocFull>({
    queryKey: ['doc', docId],
    queryFn: () => api.get(`/docs/${docId}`).then(r => r.data),
  })

  // "First seen on" — a single origin link (Stage 1's PATCH .../first-seen),
  // not the Bug Tracker's multi-report occurrence tracking.
  const { data: firstSeenReport } = useQuery({
    queryKey: ['jar-report-brief', doc?.first_seen_report_id],
    queryFn: () => api.get(`/jar-analyser/reports/${doc!.first_seen_report_id}`).then(r => r.data),
    enabled: !!doc?.first_seen_report_id,
  })

  const { data: reportsData } = useQuery({
    queryKey: ['jar-reports-picker'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 100 } }).then(r => r.data),
    enabled: isOperator && editingFirstSeen,
  })
  const reportOptions: ReportOption[] = reportsData?.items ?? []

  const { data: fsSubReportOptions } = useQuery<SubReportOption[]>({
    queryKey: ['jar-sub-reports-picker', fsReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${fsReportId}/sub-reports`).then(r => r.data),
    enabled: !!fsReportId,
  })

  const exportDoc = async (format: 'pdf' | 'markdown') => {
    setExportingFormat(format)
    try {
      const res = await api.get(`/docs/${docId}/export/${format}`, { responseType: 'blob' })
      const href = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = href
      const ext = format === 'pdf' ? 'pdf' : 'md'
      a.download = `${(doc?.name ?? 'document').replace(/[^A-Za-z0-9._-]+/g, '-')}.${ext}`
      a.click()
      URL.revokeObjectURL(href)
    } finally {
      setExportingFormat(null)
    }
  }

  const openFirstSeenEditor = () => {
    setFsReportId(doc?.first_seen_report_id ?? '')
    setFsSubReportId(doc?.first_seen_sub_report_id ?? '')
    setFirstSeenError('')
    setEditingFirstSeen(true)
  }

  const saveFirstSeen = async (reportId: string | null, subReportId: string | null) => {
    setSavingFirstSeen(true)
    setFirstSeenError('')
    try {
      await api.patch(`/docs/${docId}/first-seen`, { report_id: reportId, sub_report_id: subReportId })
      await queryClient.invalidateQueries({ queryKey: ['doc', docId] })
      setEditingFirstSeen(false)
    } catch (err: any) {
      setFirstSeenError(err.response?.data?.detail || 'Failed to update first-seen link')
    } finally {
      setSavingFirstSeen(false)
    }
  }

  const rendered = useMemo(() => (doc ? preprocessMarkdown(doc.content) : ''), [doc])

  const wordCount = useMemo(() => (doc ? doc.content.trim().split(/\s+/).filter(Boolean).length : 0), [doc])
  const readingMinutes = Math.max(1, Math.round(wordCount / 200))

  // Build the TOC from the rendered DOM (headings get ids from rehype-slug)
  // after each render, plus wire up collapsible-heading click handlers —
  // matches the source's own "pure DOM sibling-walk" approach rather than
  // tracking collapse state per-heading in React state.
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    const headings = Array.from(root.querySelectorAll('h1, h2, h3, h4, h5, h6')) as HTMLElement[]
    setToc(headings.map(h => ({
      id: h.id,
      text: h.textContent || '',
      level: Number(h.tagName[1]),
    })))

    const cleanups: (() => void)[] = []
    headings.forEach(h => {
      h.style.cursor = 'pointer'
      const onClick = () => {
        const level = Number(h.tagName[1])
        let collapsed = h.dataset.collapsed === 'true'
        let sib = h.nextElementSibling as HTMLElement | null
        while (sib) {
          const sibHeadingLevel = /^H[1-6]$/.test(sib.tagName) ? Number(sib.tagName[1]) : null
          if (sibHeadingLevel !== null && sibHeadingLevel <= level) break
          sib.style.display = collapsed ? '' : 'none'
          sib = sib.nextElementSibling as HTMLElement | null
        }
        h.dataset.collapsed = (!collapsed).toString()
        h.style.opacity = collapsed ? '1' : '0.6'
      }
      h.addEventListener('click', onClick)
      cleanups.push(() => h.removeEventListener('click', onClick))
    })

    const observer = new IntersectionObserver(
      entries => {
        const visible = entries.filter(e => e.isIntersecting)
        if (visible.length > 0) setActiveId(visible[0]!.target.id)
      },
      { rootMargin: '-10% 0px -70% 0px' }
    )
    headings.forEach(h => observer.observe(h))
    cleanups.push(() => observer.disconnect())

    return () => cleanups.forEach(fn => fn())
  }, [rendered])

  // Reading progress bar — tracked against whichever ancestor is actually
  // scrolling (Layout's <main> has overflow-auto, not the window).
  useEffect(() => {
    const root = containerRef.current
    if (!root) return
    const scrollParent = findScrollParent(root)
    const onScroll = () => {
      const scrollTop = scrollParent === document.documentElement ? window.scrollY : scrollParent.scrollTop
      const scrollHeight = (scrollParent === document.documentElement ? document.documentElement.scrollHeight : scrollParent.scrollHeight)
        - (scrollParent === document.documentElement ? window.innerHeight : scrollParent.clientHeight)
      setProgress(scrollHeight > 0 ? Math.min(100, Math.max(0, (scrollTop / scrollHeight) * 100)) : 0)
    }
    const target: Element | Window = scrollParent === document.documentElement ? window : scrollParent
    target.addEventListener('scroll', onScroll)
    onScroll()
    return () => target.removeEventListener('scroll', onScroll)
  }, [rendered])

  if (isLoading || !doc) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>
  }

  return (
    <div className="space-y-4">
      {/* Reading progress bar */}
      <div className="fixed top-0 left-64 right-0 h-1 bg-transparent z-10">
        <div className="h-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
      </div>

      {/* Breadcrumbs */}
      <div className="text-sm text-gray-500 flex items-center gap-1.5 flex-wrap">
        <button onClick={onBackToShelf} className="hover:text-blue-600">{libraryName}</button>
        <span>/</span>
        <button onClick={onBackToShelf} className="hover:text-blue-600">{shelfName}</button>
        <span>/</span>
        <span className="text-gray-900 font-medium">{doc.name}</span>
      </div>

      {/* First seen — a single origin link, not the Bug Tracker's
          multi-report occurrence tracking (see doc_first_seen_plan.md).
          A full banner card when set (this is worth noticing at a glance —
          same indigo language as the "N docs first seen here" badge on the
          report side), collapsed to a small link when unset so docs that
          never use this feature don't carry a permanent empty banner. */}
      {doc.first_seen_report_id ? (
        <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-3">
            <span className="text-2xl leading-none">📄</span>
            <div>
              <p className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">First Seen On</p>
              <button
                onClick={() => navigate(`/jar-analyser?report=${doc.first_seen_report_id}${doc.first_seen_sub_report_id ? `&sub=${doc.first_seen_sub_report_id}` : ''}`)}
                className="text-base font-semibold text-indigo-900 hover:underline">
                {firstSeenReport ? (firstSeenReport.implementation_title || firstSeenReport.filename) : `report #${doc.first_seen_report_id.slice(0, 8)}`}
              </button>
              {doc.first_seen_sub_report_id && <span className="text-xs text-indigo-600 ml-2">(specific service)</span>}
            </div>
          </div>
          {isOperator && (
            <div className="flex items-center gap-2 shrink-0">
              <button onClick={openFirstSeenEditor}
                className="px-3 py-1.5 text-xs bg-white border border-indigo-300 text-indigo-700 rounded-md hover:bg-indigo-100">
                Change
              </button>
              <button onClick={() => saveFirstSeen(null, null)} disabled={savingFirstSeen}
                className="px-3 py-1.5 text-xs bg-white border border-red-200 text-red-600 rounded-md hover:bg-red-50 disabled:opacity-40">
                Clear
              </button>
            </div>
          )}
        </div>
      ) : isOperator ? (
        <button
          onClick={openFirstSeenEditor}
          className="w-full flex items-center gap-3 bg-white border-2 border-dashed border-gray-300 rounded-lg px-4 py-3 text-left hover:border-indigo-300 hover:bg-indigo-50 transition">
          <span className="text-2xl leading-none">📄</span>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">First Seen On</p>
            <p className="text-sm font-medium text-gray-600">+ Set first seen report</p>
          </div>
        </button>
      ) : null}

      {editingFirstSeen && isOperator && (
        <div className="bg-white border border-gray-200 rounded-md p-3 space-y-2 text-sm">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Where was this first seen?</p>
          <div className="grid grid-cols-2 gap-2">
            <select
              value={fsReportId}
              onChange={e => { setFsReportId(e.target.value); setFsSubReportId('') }}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm">
              <option value="">Select report…</option>
              {reportOptions.map(r => <option key={r.report_id} value={r.report_id}>{reportOptionLabel(r)}</option>)}
            </select>
            <select
              value={fsSubReportId}
              onChange={e => setFsSubReportId(e.target.value)}
              disabled={!fsReportId}
              className="border border-gray-300 rounded px-2 py-1.5 text-sm disabled:opacity-50">
              <option value="">(whole report)</option>
              {fsSubReportOptions?.map(s => (
                <option key={s.sub_report_id} value={s.sub_report_id}>{s.service_name || s.filename}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button onClick={() => saveFirstSeen(fsReportId || null, fsSubReportId || null)} disabled={savingFirstSeen || !fsReportId}
              className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40">
              {savingFirstSeen ? 'Saving…' : 'Save'}
            </button>
            <button onClick={() => setEditingFirstSeen(false)} className="px-3 py-1.5 text-xs border border-gray-300 rounded-md hover:bg-gray-50">
              Cancel
            </button>
          </div>
          {firstSeenError && <p className="text-xs text-red-600">{firstSeenError}</p>}
        </div>
      )}

      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{doc.name}</h1>
        <div className="flex items-center gap-3">
          <div className="text-xs text-gray-400 flex items-center gap-3">
            <button onClick={() => setShowVersionHistory(true)} className="hover:text-blue-600 hover:underline" title="View version history">
              v{doc.version} 🕐
            </button>
            <span>{wordCount} words</span>
            <span>{readingMinutes} min read</span>
          </div>
          <div className="flex border border-gray-300 rounded-md overflow-hidden">
            <button onClick={() => setViewMode('document')}
              className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide ${viewMode === 'document' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              📄 Document
            </button>
            <button onClick={() => setViewMode('structured')}
              className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide border-l border-gray-300 ${viewMode === 'structured' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              🗂️ Structured
            </button>
          </div>
          <button onClick={() => exportDoc('markdown')} disabled={exportingFormat !== null}
            className="px-3 py-1.5 border border-gray-300 rounded-md text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40">
            {exportingFormat === 'markdown' ? 'Exporting…' : '⬇ MD'}
          </button>
          <button onClick={() => exportDoc('pdf')} disabled={exportingFormat !== null}
            className="px-3 py-1.5 border border-gray-300 rounded-md text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40">
            {exportingFormat === 'pdf' ? 'Exporting…' : '⬇ PDF'}
          </button>
          {isOperator && (
            <button onClick={onEdit}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
              ✏️ Edit
            </button>
          )}
        </div>
      </div>

      {viewMode === 'structured' ? (
        <StructuredView content={doc.content} onSwitchToDocument={() => setViewMode('document')} onNavigateToDoc={onNavigateToDoc} />
      ) : (
        <div className="flex gap-6 items-start">
          <div className="flex-1 min-w-0 space-y-3">
            {unanchoredCount > 0 && unanchoredCount !== unanchoredDismissedAt && (
              <div className="flex items-center gap-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
                <span>
                  {unanchoredCount} highlight{unanchoredCount !== 1 ? 's' : ''} from an earlier version of this document
                  couldn't be placed on this version — the highlighted text no longer appears as written.
                </span>
                <button onClick={() => setUnanchoredDismissedAt(unanchoredCount)} className="ml-auto text-amber-500 hover:text-amber-700 font-bold shrink-0">✕</button>
              </div>
            )}
            <div ref={containerRef} className="bg-white rounded-lg border border-gray-200 p-6">
              <MarkdownPreview content={doc.content} onNavigateToDoc={onNavigateToDoc} />
              <AnnotationLayer docId={docId} containerRef={containerRef} content={doc.content} onUnanchoredChange={setUnanchoredCount} />
            </div>
          </div>

          {/* TOC sidebar */}
          {toc.length > 0 && (
            <div className="w-56 shrink-0 sticky top-4 hidden lg:block">
              <div className="bg-white rounded-lg border border-gray-200 p-3">
                <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Contents</p>
                <nav className="space-y-1">
                  {toc.map(entry => (
                    <a
                      key={entry.id}
                      href={`#${entry.id}`}
                      style={{ paddingLeft: `${(entry.level - 1) * 10}px` }}
                      className={`block text-xs truncate hover:text-blue-600 ${
                        activeId === entry.id ? 'text-blue-600 font-medium' : 'text-gray-500'
                      }`}
                    >
                      {entry.text}
                    </a>
                  ))}
                </nav>
              </div>
            </div>
          )}
        </div>
      )}

      {showVersionHistory && <VersionHistory docId={docId} onClose={() => setShowVersionHistory(false)} />}
    </div>
  )
}
