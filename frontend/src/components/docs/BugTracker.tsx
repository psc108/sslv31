import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import MarkdownPreview from './MarkdownPreview'
import type { BugSummary, BugFull, BugStatus, BugSeverity, BugFrequency, BugOccurrence as BugOccurrenceT, BugPrefillData } from './types'

const SEVERITY_COLOUR: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  high: 'bg-orange-100 text-orange-800 border-orange-200',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  low: 'bg-blue-100 text-blue-800 border-blue-200',
}
const STATUS_COLOUR: Record<string, string> = {
  open: 'bg-red-50 text-red-700',
  investigating: 'bg-amber-50 text-amber-700',
  resolved: 'bg-green-50 text-green-700',
  closed: 'bg-gray-100 text-gray-500',
  'wont-fix': 'bg-gray-100 text-gray-500',
}
const SEVERITIES: BugSeverity[] = ['critical', 'high', 'medium', 'low']
const STATUSES: BugStatus[] = ['open', 'investigating', 'resolved', 'closed', 'wont-fix']
const FREQUENCIES: BugFrequency[] = ['always', 'intermittent', 'one-off']

interface Props {
  onBack: () => void
  initialReportId?: string
  initialSubReportId?: string
  initialServiceName?: string
  // Distinct from initialReportId (which pre-fills a *new* bug's report
  // link): this pre-filters the *list* — used by the "N bugs" badge/link on
  // a report view, where the user wants to see what's already filed, not
  // file something new.
  filterReportId?: string
  // Same two roles as initialReportId/filterReportId, for the second origin
  // type (Improvements Plan Stage 20 — Build Manager's own "Report Bug"
  // entry point): pre-fill a *new* bug's job link, or pre-filter the list.
  initialBmJobId?: string
  filterBmJobId?: string
  // Deep-links straight into one specific bug's detail view — used by the
  // JAR Analyser report's "Related Bugs" panel (Improvements Plan Stage 12),
  // where the destination is a known bug id, not a filter to apply to the
  // list.
  initialBugId?: string
  // Same "pre-filter the list" role as filterReportId/filterBmJobId, for the
  // Dashboard's "auto-filed, awaiting triage" stat — jumps straight to the
  // list pre-filtered to open, auto-created bugs.
  filterAutoCreated?: boolean
  // A resolved bug's "Promote to KB" action — cross-navigates out of Bug
  // Tracker entirely, to the Error KB's New Entry tab, prefilled from that
  // bug. Optional: undefined when BugTracker is used somewhere that has no
  // Error KB to promote into.
  onPromoteToKb?: (bugId: string) => void
  // Error KB Diagnose's own "Create Bug" action — unlike initialReportId/
  // initialBmJobId (which just carry an id for NewBugForm to look up), a
  // diagnosis result has no id of its own to look up (it's a computed
  // response, not a persisted row), so the whole prefill payload travels as
  // plain data instead, straight from React state in the same page — Docs
  // and Bugs are both already siblings under DocsPage, so no cross-route
  // trip (and no re-fetch) is needed the way job/report cross-nav needs one.
  initialPrefill?: BugPrefillData
}

type View = { type: 'list' } | { type: 'detail'; bugId: string } | { type: 'new' } | { type: 'dashboard' }

export default function BugTracker({ onBack, initialReportId, initialSubReportId, initialServiceName, filterReportId, initialBmJobId, filterBmJobId, initialBugId, filterAutoCreated, onPromoteToKb, initialPrefill }: Props) {
  const { isOperator } = useAuth()
  // Dashboard is the landing view — the list (and everything else) sits
  // underneath it, one click away, rather than being the first thing shown.
  // The cross-navigation entry points still skip straight past it: filing a
  // bug from a report or job (initialReportId/initialBmJobId) or a Diagnose
  // result (initialPrefill), a "N bugs" badge's pre-filtered list
  // (filterReportId/filterBmJobId/filterAutoCreated), and a direct link to
  // one bug (initialBugId) are all explicit requests for a specific view,
  // not a generic "open Bugs" landing.
  const [view, setView] = useState<View>(
    initialBugId ? { type: 'detail', bugId: initialBugId }
      : initialReportId || initialBmJobId || initialPrefill ? { type: 'new' }
      : filterReportId || filterBmJobId || filterAutoCreated ? { type: 'list' } : { type: 'dashboard' }
  )
  // Distinct from the initialReportId/filterReportId props (set once, from
  // outside this component) — this lets Dashboard's "open this report's
  // bugs" action re-filter the list from inside the tracker.
  const [listFilterReportId, setListFilterReportId] = useState(filterReportId)
  const [listFilterAutoCreated, setListFilterAutoCreated] = useState(filterAutoCreated)

  // Dashboard and List are both "home" views for the tracker — the back
  // button leaves to Docs from either of them, not just List.
  const isHome = view.type === 'dashboard' || view.type === 'list'

  // In-app activity badge (Improvements Plan Stage 5) — "N bugs you're
  // involved in changed since you last looked." Polled rather than pushed
  // since there's no websocket/SSE channel in this app; cleared by visiting
  // the Dashboard, which POSTs a checkpoint (see Dashboard below).
  const { data: activity } = useQuery({
    queryKey: ['bugs-activity-count'],
    queryFn: () => api.get('/bugs/my-activity-count').then(r => r.data as { count: number }),
    refetchInterval: 60000,
  })

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex items-center gap-3">
        <button
          onClick={() => (isHome ? onBack() : setView({ type: 'dashboard' }))}
          className="text-sm text-gray-500 hover:text-gray-700">
          ← {isHome ? 'Docs' : 'Bugs'}
        </button>
        <h1 className="text-2xl font-bold text-gray-900">🐛 Bugs</h1>
        {!!activity?.count && (
          <span
            title={`${activity.count} update${activity.count === 1 ? '' : 's'} on bugs you're involved in since you last checked`}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-100 text-red-700 text-xs font-semibold">
            🔔 {activity.count}
          </span>
        )}
        {isHome ? (
          <div className="ml-auto flex border border-gray-300 rounded-md overflow-hidden">
            <button
              onClick={() => setView({ type: 'dashboard' })}
              className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide ${view.type === 'dashboard' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              📊 Dashboard
            </button>
            <button
              onClick={() => setView({ type: 'list' })}
              className={`px-3 py-1.5 text-xs font-semibold uppercase tracking-wide border-l border-gray-300 ${view.type === 'list' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
              📋 List
            </button>
          </div>
        ) : null}
        {isHome && isOperator && (
          <button
            onClick={() => setView({ type: 'new' })}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
            + New Bug
          </button>
        )}
        {!isHome && (
          <button
            onClick={() => setView({ type: 'dashboard' })}
            className="ml-auto text-xs text-gray-500 hover:text-gray-700 border border-gray-300 rounded-md px-3 py-1.5">
            📊 Dashboard
          </button>
        )}
      </div>

      {view.type === 'list' && (
        <ListView
          initialReportId={listFilterReportId}
          initialBmJobId={filterBmJobId}
          initialAutoCreated={listFilterAutoCreated}
          onOpen={id => setView({ type: 'detail', bugId: id })}
          onNew={() => setView({ type: 'new' })}
        />
      )}
      {view.type === 'new' && (
        <NewBugForm
          initialReportId={initialReportId}
          initialSubReportId={initialSubReportId}
          initialServiceName={initialServiceName}
          initialBmJobId={initialBmJobId}
          prefill={initialPrefill}
          onCreated={id => setView({ type: 'detail', bugId: id })}
          onCancel={() => setView({ type: 'list' })}
        />
      )}
      {view.type === 'detail' && (
        <BugDetail
          key={view.bugId}
          bugId={view.bugId}
          onDeleted={() => setView({ type: 'list' })}
          onPromoteToKb={onPromoteToKb}
          onOpenBug={id => setView({ type: 'detail', bugId: id })}
        />
      )}
      {view.type === 'dashboard' && (
        <Dashboard
          onOpenReport={reportId => { setListFilterReportId(reportId); setView({ type: 'list' }) }}
          onOpenAutoFiled={() => { setListFilterAutoCreated(true); setView({ type: 'list' }) }}
        />
      )}
    </div>
  )
}

// ── List view ────────────────────────────────────────────────────────────────

function ListView({ initialReportId, initialBmJobId, initialAutoCreated, onOpen, onNew }: { initialReportId?: string; initialBmJobId?: string; initialAutoCreated?: boolean; onOpen: (id: string) => void; onNew: () => void }) {
  const { isOperator, user } = useAuth()
  const queryClient = useQueryClient()
  // The auto-filed triage queue is specifically about still-open bugs
  // nobody has acted on yet (Dashboard's own auto_filed_open_count
  // definition) — defaulting status to 'open' here matches that so the
  // stat card's count and the list that opens from it actually agree.
  const [status, setStatus] = useState(initialAutoCreated ? 'open' : '')
  const [severity, setSeverity] = useState('')
  const [tag, setTag] = useState('')
  const [reportFilter, setReportFilter] = useState(initialReportId ?? '')
  const [bmJobFilter, setBmJobFilter] = useState(initialBmJobId ?? '')
  const [assigneeFilter, setAssigneeFilter] = useState('')
  const [autoCreatedFilter, setAutoCreatedFilter] = useState(!!initialAutoCreated)
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkStatus, setBulkStatus] = useState<BugStatus>('open')
  const [bulkTag, setBulkTag] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [bulkError, setBulkError] = useState('')

  const { data: listData, isLoading: listLoading } = useQuery({
    queryKey: ['bugs-list', status, severity, tag, reportFilter, bmJobFilter, assigneeFilter, autoCreatedFilter],
    queryFn: () => api.get('/bugs', { params: {
      status: status || undefined, severity: severity || undefined, tag: tag || undefined,
      report_id: reportFilter || undefined, bm_job_id: bmJobFilter || undefined,
      assignee_id: assigneeFilter || undefined, auto_created: autoCreatedFilter || undefined, page_size: 100,
    } }).then(r => r.data),
    enabled: !query,
  })

  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ['bugs-search', query],
    queryFn: () => api.get('/bugs/search', { params: { q: query, page_size: 100 } }).then(r => r.data),
    enabled: !!query,
  })

  const data = query ? searchData : listData
  const isLoading = query ? searchLoading : listLoading
  const bugs: BugSummary[] = data?.items ?? []

  const doSearch = () => setQuery(searchInput.trim())

  const exportBugs = async () => {
    const res = await api.get('/bugs/export', {
      params: {
        status: status || undefined, severity: severity || undefined,
        tag: tag || undefined, report_id: reportFilter || undefined,
        assignee_id: assigneeFilter || undefined,
      },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([res.data], { type: 'text/markdown' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'bugs-export.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  const toggleSelected = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const refreshAfterBulk = async () => {
    setSelected(new Set())
    await queryClient.invalidateQueries({ queryKey: ['bugs-list'] })
    await queryClient.invalidateQueries({ queryKey: ['bugs-search'] })
  }

  const applyBulkStatus = async () => {
    setBulkBusy(true)
    setBulkError('')
    try {
      await api.post('/bugs/bulk/status', { bug_ids: Array.from(selected), status: bulkStatus })
      await refreshAfterBulk()
    } catch (err: any) {
      setBulkError(err.response?.data?.detail || 'Failed to update status')
    } finally {
      setBulkBusy(false)
    }
  }

  const applyBulkTag = async (action: 'add' | 'remove') => {
    if (!bulkTag.trim()) return
    setBulkBusy(true)
    setBulkError('')
    try {
      await api.post('/bugs/bulk/tag', { bug_ids: Array.from(selected), tag: bulkTag.trim(), action })
      setBulkTag('')
      await refreshAfterBulk()
    } catch (err: any) {
      setBulkError(err.response?.data?.detail || 'Failed to update tags')
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {reportFilter && (
        <div className="flex items-center gap-2 text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-1.5 w-fit">
          <span>Filtered to report #{reportFilter.slice(0, 8)}</span>
          <button onClick={() => setReportFilter('')} className="text-blue-500 hover:text-blue-700 font-bold">✕</button>
        </div>
      )}
      {bmJobFilter && (
        <div className="flex items-center gap-2 text-xs text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-1.5 w-fit">
          <span>🏗️ Filtered to Build Manager job #{bmJobFilter.slice(0, 8)}</span>
          <button onClick={() => setBmJobFilter('')} className="text-blue-500 hover:text-blue-700 font-bold">✕</button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text" value={searchInput} onChange={e => setSearchInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') doSearch() }}
          placeholder="Search bugs…"
          className="border border-gray-300 rounded-md px-3 py-1.5 text-sm w-56"
        />
        {query && (
          <button onClick={() => { setSearchInput(''); setQuery('') }} className="text-xs text-gray-500 hover:text-gray-700">Clear search</button>
        )}
        <select value={status} onChange={e => setStatus(e.target.value)} className="border border-gray-300 rounded-md px-2 py-1.5 text-sm">
          <option value="">All statuses</option>
          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={severity} onChange={e => setSeverity(e.target.value)} className="border border-gray-300 rounded-md px-2 py-1.5 text-sm">
          <option value="">All severities</option>
          {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <input
          type="text" value={tag} onChange={e => setTag(e.target.value)}
          placeholder="Filter by tag"
          className="border border-gray-300 rounded-md px-2 py-1.5 text-sm w-32"
        />
        {user && (
          <button
            onClick={() => setAssigneeFilter(f => (f === user.user_id ? '' : user.user_id))}
            className={`text-xs rounded-md px-3 py-1.5 border ${
              assigneeFilter === user.user_id ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 text-gray-500 hover:bg-gray-50'
            }`}>
            🙋 My Bugs
          </button>
        )}
        <button
          onClick={() => setAutoCreatedFilter(f => !f)}
          className={`text-xs rounded-md px-3 py-1.5 border ${
            autoCreatedFilter ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 text-gray-500 hover:bg-gray-50'
          }`}>
          🤖 Auto-filed only
        </button>
        <button
          onClick={exportBugs}
          className={`text-xs text-gray-500 hover:text-gray-700 border border-gray-300 rounded-md px-3 py-1.5 ${isOperator ? '' : 'ml-auto'}`}>
          ⬇ Export
        </button>
        {isOperator && (
          <button onClick={onNew} className="ml-auto px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
            + New Bug
          </button>
        )}
      </div>

      {isOperator && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 p-3 bg-blue-50 border border-blue-200 rounded-md text-sm">
          <span className="font-medium text-blue-800">{selected.size} selected</span>
          {bulkError && <span className="text-xs text-red-600">{bulkError}</span>}
          <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value as BugStatus)}
            className="border border-gray-300 rounded-md px-2 py-1.5 text-sm">
            {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button onClick={applyBulkStatus} disabled={bulkBusy}
            className="px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50">
            Set status
          </button>
          <input type="text" value={bulkTag} onChange={e => setBulkTag(e.target.value)} placeholder="tag"
            className="border border-gray-300 rounded-md px-2 py-1.5 text-sm w-24" />
          <button onClick={() => applyBulkTag('add')} disabled={bulkBusy || !bulkTag.trim()}
            className="px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50">
            + Add tag
          </button>
          <button onClick={() => applyBulkTag('remove')} disabled={bulkBusy || !bulkTag.trim()}
            className="px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50">
            − Remove tag
          </button>
          <button onClick={() => setSelected(new Set())} className="ml-auto text-xs text-gray-500 hover:text-gray-700">
            Clear selection
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
        {isLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
        {!isLoading && bugs.length === 0 && (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No bugs found.</div>
        )}
        {bugs.map(bug => (
          <div key={bug.id}
            className="px-4 py-3 flex items-center gap-3 hover:bg-gray-50 cursor-pointer"
            onClick={() => onOpen(bug.id)}>
            {isOperator && (
              <input type="checkbox" checked={selected.has(bug.id)}
                onClick={e => e.stopPropagation()}
                onChange={() => toggleSelected(bug.id)}
                className="shrink-0" />
            )}
            <span className={`px-1.5 py-0.5 text-xs font-bold rounded border ${SEVERITY_COLOUR[bug.severity]}`}>
              {bug.severity.charAt(0).toUpperCase()}
            </span>
            <span className="flex-1 min-w-0 font-medium text-gray-900 truncate">{bug.title}</span>
            {bug.auto_created && (
              <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium" title="Automatically filed by the Ansible-failure scanner">
                🤖 Auto-filed
              </span>
            )}
            {bug.tags.map(t => (
              <span key={t} className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{t}</span>
            ))}
            <span className={`px-2 py-0.5 text-xs rounded ${STATUS_COLOUR[bug.status]}`}>{bug.status}</span>
            <span className="text-xs text-gray-400 w-20 text-right">{new Date(bug.updated_at).toLocaleDateString()}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── New Bug form ─────────────────────────────────────────────────────────────

interface ReportOption { report_id: string; filename: string; implementation_version?: string | null; uploaded_at?: string }
interface SubReportOption { sub_report_id: string; service_name: string | null; filename: string }
interface AssignableUser { id: string; username: string }

function reportOptionLabel(r: ReportOption): string {
  const parts = [r.filename]
  if (r.implementation_version) parts.push(`v${r.implementation_version}`)
  if (r.uploaded_at) parts.push(new Date(r.uploaded_at).toLocaleDateString())
  parts.push(`#${r.report_id.slice(0, 8)}`)
  return parts.join(' — ')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface DescriptionFields {
  scope: string; envOs: string; envVersion: string; envRuntime: string; envDeploy: string; envConfig: string
  tls: string; network: string; steps: string; expected: string; actual: string; repro: string
  logs: string; diffs: string; workarounds: string; tfDiff: string; ansible: string; chainLogs: string
}

function buildDescription(f: DescriptionFields): string {
  const lines: string[] = []
  const section = (heading: string, body: string, fenced = false) => {
    if (!body.trim()) return
    lines.push(`## ${heading}`, '', fenced ? `\`\`\`\n${body.trim()}\n\`\`\`` : body.trim(), '')
  }
  section('Scope', f.scope)
  const env = [
    f.envOs && `- **OS / distro:** ${f.envOs}`,
    f.envVersion && `- **App version:** ${f.envVersion}`,
    f.envRuntime && `- **Runtime versions:** ${f.envRuntime}`,
    f.envDeploy && `- **Deployment context:** ${f.envDeploy}`,
    f.envConfig && `- **Relevant config:** ${f.envConfig}`,
    f.tls && `- **TLS / cert details:** ${f.tls}`,
    f.network && `- **Network path:** ${f.network}`,
  ].filter(Boolean).join('\n')
  if (env) lines.push('## Environment', '', env, '')
  section('Steps to Reproduce', f.steps)
  section('Expected Behaviour', f.expected)
  section('Actual Behaviour', f.actual)
  section('Minimal Reproducible Example', f.repro)
  section('Logs / Stack Traces', f.logs, true)
  section('Recent Changes', f.diffs)
  section('Workarounds Tried', f.workarounds)
  section('Terraform / OpenTofu Diff', f.tfDiff, true)
  section('Ansible Output', f.ansible, true)
  section('Service Chain Logs', f.chainLogs, true)
  return lines.join('\n').replace(/\n+$/, '')
}

// ansible-playbook's own exit codes, for a "what does this number mean" hint
// next to it in a job-origin bug's prefilled description. Codes 2/3/4 are
// flagged "varies by version" deliberately, not guessed as one fixed
// meaning: ansible-playbook's own man page documents 4 as "Parser error",
// but a real, version-spanning report (ansible/ansible#19720, seen on
// 2.15, 2.16, 2.18) shows a plain unreachable host producing exit code 4
// too - exactly the case this hint exists to help with, so the hedge is
// real, not decorative.
const EXIT_CODE_HINTS: Record<number, string> = {
  1: 'fatal error or exception during the run',
  2: 'one or more hosts failed a task, or the run was aborted - meaning varies by Ansible version',
  3: 'one or more hosts were unreachable (older Ansible) - meaning varies by Ansible version',
  4: 'in current Ansible, most often hosts unreachable (SSH/login issue), though older docs call it a parser error - meaning varies by Ansible version',
  5: 'bad or incomplete command-line options passed to ansible-playbook',
  6: 'command-line arguments were not UTF-8 encoded',
  8: 'an internal task-queue break-play condition',
  99: 'the run was interrupted (Ctrl+C)',
  143: 'the process was killed (SIGKILL)',
  250: 'an unexpected exception - often a module bug or a Jinja templating error',
  255: 'an unknown/internal error',
}

// One row in the duplicate-suggestion panel — "Link instead" used to be the
// only option, committing to a merge on nothing but a title/status/severity
// summary with no way to actually check whether the suggested bug is the
// same issue. Preview fetches the full bug inline (lazy — only once opened,
// so browsing several suggestions doesn't fire N requests up front); Open
// uses a real new-tab link rather than in-app navigation specifically so the
// in-progress New Bug form (never saved until "Create Bug" is clicked) isn't
// torn down by a route change — this component's own tab keeps its state
// exactly as it was when the user comes back to it.
function SimilarBugRow({ bug, onLink, disabled }: { bug: BugSummary; onLink: () => void; disabled: boolean }) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const { data: full, isFetching } = useQuery<BugFull>({
    queryKey: ['bug-similar-preview', bug.id],
    queryFn: () => api.get(`/bugs/${bug.id}`).then(r => r.data),
    enabled: previewOpen,
  })

  return (
    <div className="bg-white border border-amber-100 rounded px-2 py-1.5 text-xs">
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 font-bold rounded border ${SEVERITY_COLOUR[bug.severity]}`}>{bug.severity.charAt(0).toUpperCase()}</span>
        <span className={`px-1.5 py-0.5 rounded ${STATUS_COLOUR[bug.status]}`}>{bug.status}</span>
        <span className="flex-1 min-w-0 truncate text-gray-800">{bug.title}</span>
        <button type="button" onClick={() => setPreviewOpen(o => !o)}
          className="px-2 py-1 bg-white border border-amber-300 text-amber-700 rounded hover:bg-amber-100 shrink-0">
          {previewOpen ? 'Hide' : '👁 Preview'}
        </button>
        <a href={`/docs?bugs=1&action=view&bugId=${bug.id}`} target="_blank" rel="noopener noreferrer"
          title="Opens in a new tab — this form's progress is kept exactly as it is"
          className="px-2 py-1 bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-50 shrink-0">
          Open ↗
        </a>
        <button type="button" onClick={onLink} disabled={disabled}
          className="px-2 py-1 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-40 shrink-0">
          Link instead
        </button>
      </div>
      {previewOpen && (
        <div className="mt-2 pt-2 border-t border-amber-100 space-y-1.5">
          {isFetching && <p className="text-gray-400">Loading…</p>}
          {full && (
            <>
              {full.resolution && (
                <p><span className="font-semibold text-green-700">Resolution: </span><span className="text-gray-700">{full.resolution}</span></p>
              )}
              <p className="text-gray-600 whitespace-pre-wrap line-clamp-6">{full.description}</p>
              {full.tags.length > 0 && <p className="text-gray-500">Tags: {full.tags.join(', ')}</p>}
            </>
          )}
        </div>
      )}
    </div>
  )
}

function NewBugForm({ initialReportId, initialSubReportId, initialServiceName, initialBmJobId, prefill, onCreated, onCancel }: {
  initialReportId?: string
  initialSubReportId?: string
  initialServiceName?: string
  initialBmJobId?: string
  prefill?: BugPrefillData
  onCreated: (id: string) => void
  onCancel: () => void
}) {
  // prefill arrives as plain data already in hand (see BugTracker's own
  // initialPrefill docstring) rather than an id to look up, so — unlike the
  // bmJobId/environment prefill below, which needs useEffect + a "prefilled"
  // guard because it's fetched asynchronously — it can just seed these
  // lazy useState initialisers directly.
  const [title, setTitle] = useState(prefill?.title ?? (initialServiceName ? `${initialServiceName}: ` : ''))
  const [severity, setSeverity] = useState<BugSeverity>(prefill?.severity ?? 'medium')
  const [frequency, setFrequency] = useState('')
  const [scope, setScope] = useState('')
  const [envOs, setEnvOs] = useState('')
  const [envVersion, setEnvVersion] = useState('')
  const [envRuntime, setEnvRuntime] = useState('')
  const [envDeploy, setEnvDeploy] = useState('')
  const [envConfig, setEnvConfig] = useState(prefill?.envConfig ?? '')
  const [tls, setTls] = useState('')
  const [network, setNetwork] = useState('')
  const [steps, setSteps] = useState('')
  const [expected, setExpected] = useState('')
  const [actual, setActual] = useState(prefill?.actual ?? '')
  const [repro, setRepro] = useState('')
  const [logs, setLogs] = useState(prefill?.logs ?? '')
  const [diffs, setDiffs] = useState('')
  const [workarounds, setWorkarounds] = useState('')
  const [tfDiff, setTfDiff] = useState('')
  const [ansible, setAnsible] = useState('')
  const [chainLogs, setChainLogs] = useState('')
  const [reportId, setReportId] = useState(prefill?.reportId ?? initialReportId ?? '')
  const [subReportId, setSubReportId] = useState(prefill?.subReportId ?? initialSubReportId ?? '')
  // No manual job picker yet (Improvements Plan Stage 20 is cross-navigation-
  // only) — a job-origin bug is always pre-filled from Build Manager's own
  // "Report Bug" button, never chosen by hand here, so this doesn't need a
  // setter.
  const bmJobId = initialBmJobId ?? ''
  const [jobPrefilled, setJobPrefilled] = useState(false)
  const [envPrefilled, setEnvPrefilled] = useState(false)
  const [assigneeId, setAssigneeId] = useState('')
  const [tagsText, setTagsText] = useState(prefill?.tags?.join(', ') ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const { data: reportsData } = useQuery({
    queryKey: ['jar-reports-picker'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 100 } }).then(r => r.data),
  })
  const reports: ReportOption[] = reportsData?.items ?? []

  const { data: assignableUsers } = useQuery<AssignableUser[]>({
    queryKey: ['bugs-assignable-users'],
    queryFn: () => api.get('/bugs/assignable-users').then(r => r.data),
  })

  const { data: subReports } = useQuery<SubReportOption[]>({
    queryKey: ['jar-sub-reports-picker', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports`).then(r => r.data),
    enabled: !!reportId,
  })

  // Pre-fill title/actual-behaviour/Ansible-output from the failed job
  // itself when opened via Build Manager's "Report Bug" button — previously
  // only bmJobId carried over, leaving a human to retype everything the
  // system already knew (playbook, failed hosts, exit code, the actual
  // fatal/FAILED! lines from the run) — the exact same signal the Stage 22
  // auto-filer already builds server-side, just surfaced here for a human
  // to review/edit instead of skipped entirely for a manual report.
  const { data: jobDetail } = useQuery({
    queryKey: ['bm-job-detail-for-bug', bmJobId],
    queryFn: () => api.get(`/build/jobs/${bmJobId}`).then(r => r.data),
    enabled: !!bmJobId,
  })
  const { data: jobOutput } = useQuery({
    queryKey: ['bm-job-output-for-bug', bmJobId],
    queryFn: () => api.get(`/build/jobs/${bmJobId}/output`).then(r => r.data),
    enabled: !!bmJobId,
  })
  // Error KB guidance for this job's own failure text — real curated
  // causes/fix steps for a known Ansible failure type, not just the
  // coarse exit-code hint above. Same engine JAR Analyser's Diagnose
  // action and the Docs Search tab's pattern mode already use.
  const { data: kbDiagnosis } = useQuery({
    queryKey: ['bm-job-diagnose-for-bug', bmJobId],
    queryFn: () => api.get(`/build/jobs/${bmJobId}/diagnose`).then(r => r.data),
    enabled: !!bmJobId,
  })
  const kbMatches: { id: string; title: string; severity: string; causes: string[]; fix_steps: string[] }[] = kbDiagnosis?.results ?? []
  useEffect(() => {
    if (!bmJobId || jobPrefilled || !jobDetail || !jobOutput) return
    const failMarkers = ['fatal:', 'FAILED!']
    const failLines: string[] = (jobOutput.lines ?? [])
      .map((l: { line: string }) => l.line)
      .filter((line: string) => failMarkers.some(m => line.includes(m)))
    const hosts: string[] = jobDetail.failed_hosts ?? []
    const exitHint = jobDetail.exit_code != null ? EXIT_CODE_HINTS[jobDetail.exit_code] : undefined
    setTitle(`Job failure: ${jobDetail.playbook || jobDetail.name}${hosts.length ? ` (${hosts.join(', ')})` : ''}`)
    setActual(
      `Build Manager job "${jobDetail.name}" finished failed.\n` +
      `Playbook: ${jobDetail.playbook || '(none)'}\n` +
      `Failed hosts: ${hosts.length ? hosts.join(', ') : '(none reported)'}\n` +
      `Exit code: ${jobDetail.exit_code ?? '(none)'}` +
      (exitHint ? ` (commonly: ${exitHint})` : '')
    )
    if (failLines.length) setAnsible(failLines.slice(0, 50).join('\n'))
    setJobPrefilled(true)
  }, [bmJobId, jobDetail, jobOutput, jobPrefilled])

  // Also pull in the job's environment/template — OS, product/service
  // versions, network IP allocations, and issued certs — so a report from
  // a doomed build carries the full build context, not just the failure
  // signal. Prefers the job's own build_snapshot (captured at submit_job()
  // time — see environment_service.build_environment_snapshot — so it
  // survives the environment later being destroyed, which is routine for
  // test/build workflows and previously meant this section silently stayed
  // blank for most failed jobs by the time anyone got around to filing a
  // bug). Falls back to a live environment/template-version join for jobs
  // submitted before that snapshot existed. A job isn't always tied to an
  // environment at all (e.g. a plan-only or TLS-verify job), so this
  // quietly does nothing when there's neither.
  const buildSnapshot = jobDetail?.build_snapshot as {
    environment_name?: string; template_name?: string; template_version?: number; status?: string
    base_os?: string; base_os_version?: string
    hosts?: { role: string; products?: { product: string; version: string }[] }[]
    ip_allocations?: Record<string, string>
    certs?: { role: string; cert_type: string }[]
  } | null | undefined
  const environmentId: string | undefined = (!buildSnapshot && jobDetail?.environment_id) ? jobDetail.environment_id : undefined
  const { data: envDetail } = useQuery({
    queryKey: ['bm-env-detail-for-bug', environmentId],
    queryFn: () => api.get(`/build/environments/${environmentId}`).then(r => r.data),
    enabled: !!environmentId,
  })
  const { data: templateVersionDetail } = useQuery({
    queryKey: ['bm-template-version-for-bug', envDetail?.template_id, envDetail?.template_version],
    queryFn: () => api.get(`/build/templates/${envDetail.template_id}/versions/${envDetail.template_version}`).then(r => r.data),
    enabled: !!envDetail?.template_id && envDetail?.template_version != null,
  })
  useEffect(() => {
    if (!bmJobId || envPrefilled || !jobDetail) return

    let envName: string | undefined, templateName: string | undefined, templateVersion: number | undefined, status: string | undefined
    let baseOs: string | undefined, baseOsVersion: string | undefined
    let hosts: { role: string; products?: { product: string; version: string }[] }[] = []
    let ipAllocations: Record<string, string> = {}
    let certs: { role: string; cert_type: string }[] = []

    if (buildSnapshot) {
      envName = buildSnapshot.environment_name
      templateName = buildSnapshot.template_name
      templateVersion = buildSnapshot.template_version
      status = buildSnapshot.status
      baseOs = buildSnapshot.base_os
      baseOsVersion = buildSnapshot.base_os_version
      hosts = buildSnapshot.hosts ?? []
      ipAllocations = buildSnapshot.ip_allocations ?? {}
      certs = buildSnapshot.certs ?? []
    } else if (jobDetail.environment_id) {
      if (!envDetail) return
      if (envDetail.template_id && envDetail.template_version != null && !templateVersionDetail) return
      const spec = templateVersionDetail?.spec
      envName = envDetail.name
      templateName = envDetail.template_name
      templateVersion = envDetail.template_version
      status = envDetail.status
      baseOs = spec?.base_os
      baseOsVersion = spec?.base_os_version
      hosts = spec?.hosts ?? []
      ipAllocations = envDetail.ip_allocations ?? {}
      certs = envDetail.certs ?? []
    } else {
      setEnvPrefilled(true)
      return
    }

    if (baseOs) setEnvOs(`${baseOs}${baseOsVersion ? ` ${baseOsVersion}` : ''}`)
    const products: string[] = []
    const roleBreakdown: string[] = []
    for (const host of hosts) {
      const hostProducts: string[] = (host.products ?? []).map(p => `${p.product}@${p.version}`)
      products.push(...hostProducts)
      if (hostProducts.length) roleBreakdown.push(`${host.role}: ${hostProducts.join(', ')}`)
    }
    const uniqueProducts = Array.from(new Set(products))
    if (uniqueProducts.length) {
      const joined = uniqueProducts.join(', ')
      setEnvVersion(joined.length > 400 ? `${joined.slice(0, 400)}...` : joined)
    }
    const ipEntries = Object.entries(ipAllocations)
    if (ipEntries.length) setNetwork(ipEntries.map(([role, ip]) => `${role}=${ip}`).join(', '))
    if (certs.length) setTls(`${certs.length} cert(s) issued: ${certs.map(c => `${c.role} (${c.cert_type})`).join(', ')}`)
    setEnvConfig([
      `Environment: ${envName ?? '?'} (template: ${templateName ?? '?'} v${templateVersion ?? '?'}, status: ${status ?? '?'})` +
        (buildSnapshot ? ' [from build snapshot - environment may since have been destroyed]' : ''),
      ...roleBreakdown,
    ].join('\n'))
    setEnvPrefilled(true)
  }, [bmJobId, jobDetail, buildSnapshot, envDetail, templateVersionDetail, envPrefilled])

  // Duplicate-suggestion assist — debounced, word-overlap search (no AI) over
  // existing bugs while the user types, so a near-duplicate can be linked as
  // another occurrence instead of filed as a brand new bug.
  const [similarQuery, setSimilarQuery] = useState('')
  useEffect(() => {
    const text = [title, steps, actual].filter(Boolean).join(' ').trim()
    if (text.length < 8) { setSimilarQuery(''); return }
    const t = setTimeout(() => setSimilarQuery(text), 600)
    return () => clearTimeout(t)
  }, [title, steps, actual])

  const { data: similarData } = useQuery({
    queryKey: ['bugs-similar', similarQuery],
    queryFn: () => api.get('/bugs/similar', { params: { title, text: similarQuery, limit: 5 } }).then(r => r.data),
    enabled: !!similarQuery,
  })
  const similarBugs: BugSummary[] = similarData?.results ?? []

  const linkAsOccurrence = async (targetBugId: string) => {
    if (!reportId && !bmJobId) { setError('Select a linked report above before linking to an existing bug.'); return }
    setError('')
    setSaving(true)
    try {
      await api.post(`/bugs/${targetBugId}/occurrences`, reportId
        ? { report_id: reportId, sub_report_id: subReportId || null }
        : { bm_job_id: bmJobId })
      onCreated(targetBugId)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to link occurrence')
    } finally {
      setSaving(false)
    }
  }

  const handleSave = async () => {
    setError('')
    if (!title.trim()) { setError('Title is required.'); return }
    if (!steps.trim() && !actual.trim()) { setError('Steps to Reproduce or Actual Behaviour is required.'); return }
    setSaving(true)
    try {
      const description = buildDescription({
        scope, envOs, envVersion, envRuntime, envDeploy, envConfig, tls, network,
        steps, expected, actual, repro, logs, diffs, workarounds, tfDiff, ansible, chainLogs,
      })
      const tags = tagsText.split(',').map(t => t.trim()).filter(Boolean)
      const res = await api.post('/bugs', {
        title: title.trim(), description, severity,
        frequency: frequency || null,
        tags, report_id: reportId || null, sub_report_id: subReportId || null,
        bm_job_id: bmJobId || null, assignee_id: assigneeId || null,
      })
      onCreated(res.data.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save bug')
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
  const inputCls = 'w-full border border-gray-300 rounded px-3 py-2 text-sm'
  const groupLabel = (text: string) => <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide pt-3 first:pt-0">{text}</div>

  return (
    <div className="space-y-4">
      {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}

      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
        {field('Title *', <input value={title} onChange={e => setTitle(e.target.value)} className={inputCls} placeholder="Login fails with 500 error on invalid session token" />)}

        {similarBugs.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-md p-3 space-y-1.5">
            <p className="text-xs font-semibold text-amber-800">This looks similar to existing bugs — link this report as another occurrence instead of filing a new one?</p>
            {similarBugs.map(b => (
              <SimilarBugRow key={b.id} bug={b} onLink={() => linkAsOccurrence(b.id)} disabled={saving} />
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          {field('Severity', (
            <select value={severity} onChange={e => setSeverity(e.target.value as BugSeverity)} className={inputCls}>
              {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          ))}
          {field('Frequency', (
            <select value={frequency} onChange={e => setFrequency(e.target.value)} className={inputCls}>
              <option value="">(not specified)</option>
              {FREQUENCIES.map(f => <option key={f} value={f}>{f}</option>)}
            </select>
          ))}
        </div>
        {field('Scope of reproduction', <input value={scope} onChange={e => setScope(e.target.value)} className={inputCls} placeholder="All environments / staging only / single host" />)}

        {groupLabel('Environment')}
        <div className="grid grid-cols-2 gap-3">
          {field('OS / distro + version', <input value={envOs} onChange={e => setEnvOs(e.target.value)} className={inputCls} placeholder="AL2023, Ubuntu 22.04, Windows 11" />)}
          {field('App version / commit', <input value={envVersion} onChange={e => setEnvVersion(e.target.value)} className={inputCls} placeholder="v1.2.3 or abc1234" />)}
          {field('Runtime versions', <input value={envRuntime} onChange={e => setEnvRuntime(e.target.value)} className={inputCls} placeholder="Java 21, Node 20, Python 3.12" />)}
          {field('Deployment context', (
            <select value={envDeploy} onChange={e => setEnvDeploy(e.target.value)} className={inputCls}>
              <option value="">Select…</option>
              <option value="local">Local</option>
              <option value="staging">Staging</option>
              <option value="production">Production</option>
              <option value="container">Container (Docker)</option>
              <option value="vm">VM</option>
            </select>
          ))}
        </div>
        {field('Relevant config', <textarea value={envConfig} onChange={e => setEnvConfig(e.target.value)} rows={2} className={inputCls} placeholder="Feature flags, env vars, security groups, proxy settings" />)}
        <div className="grid grid-cols-2 gap-3">
          {field('TLS / cert details', <input value={tls} onChange={e => setTls(e.target.value)} className={inputCls} placeholder="Issuer, SAN, expiry if PKI-adjacent" />)}
          {field('Network path', <input value={network} onChange={e => setNetwork(e.target.value)} className={inputCls} placeholder="Security groups, VPC/subnet, proxy env vars" />)}
        </div>

        {groupLabel('Reproduction')}
        {field('Steps to reproduce', <textarea value={steps} onChange={e => setSteps(e.target.value)} rows={5} className={inputCls} placeholder={'1. Run terraform apply\n2. SSH to instance\n3. curl localhost:8080/api/health\n4. Observe 502'} />)}
        {field('Expected behaviour', <textarea value={expected} onChange={e => setExpected(e.target.value)} rows={2} className={inputCls} placeholder='200 OK with {"status":"healthy"}' />)}
        {field('Actual behaviour', <textarea value={actual} onChange={e => setActual(e.target.value)} rows={2} className={inputCls} placeholder="502 Bad Gateway — exact error text, not a summary" />)}
        {field('Minimal reproducible example', <textarea value={repro} onChange={e => setRepro(e.target.value)} rows={3} className={inputCls} placeholder="Smallest input/config that triggers the issue" />)}

        {groupLabel('Diagnostics')}
        {field('Logs / stack traces', <textarea value={logs} onChange={e => setLogs(e.target.value)} rows={5} className={`${inputCls} font-mono`} placeholder="Full trace with timestamps — not truncated" />)}
        {field('Diffs / recent changes', <textarea value={diffs} onChange={e => setDiffs(e.target.value)} rows={3} className={inputCls} placeholder="Deploy, config change, dependency bump that preceded this" />)}
        {field('Workarounds tried', <textarea value={workarounds} onChange={e => setWorkarounds(e.target.value)} rows={2} className={inputCls} placeholder="What you already ruled out" />)}

        {groupLabel('Infrastructure context')}
        {field('Terraform / OpenTofu diff', <textarea value={tfDiff} onChange={e => setTfDiff(e.target.value)} rows={3} className={`${inputCls} font-mono`} placeholder="Plan output if infra-related" />)}
        {field('Ansible output', <textarea value={ansible} onChange={e => setAnsible(e.target.value)} rows={3} className={`${inputCls} font-mono`} placeholder="Playbook run output/tags if config drift suspected" />)}

        {kbMatches.length > 0 && (
          <div className="bg-blue-50 border border-blue-200 rounded-md p-3 space-y-2">
            <p className="text-xs font-semibold text-blue-800">📖 Error KB matches for this job's failure — worth checking, not a confirmed diagnosis:</p>
            {kbMatches.map(m => (
              <div key={m.id} className="bg-white border border-blue-100 rounded px-2.5 py-2 text-xs space-y-1">
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 font-bold rounded border ${SEVERITY_COLOUR[m.severity] ?? 'bg-gray-100 text-gray-600 border-gray-200'}`}>{m.severity.charAt(0).toUpperCase()}</span>
                  <span className="font-medium text-gray-800">{m.title}</span>
                </div>
                {m.causes.length > 0 && (
                  <p className="text-gray-600"><span className="font-medium">Likely cause:</span> {m.causes[0]}</p>
                )}
                {m.fix_steps.length > 0 && (
                  <p className="text-gray-600"><span className="font-medium">First fix step:</span> {m.fix_steps[0]}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {field('Service chain logs', <textarea value={chainLogs} onChange={e => setChainLogs(e.target.value)} rows={3} className={`${inputCls} font-mono`} placeholder="App → RabbitMQ → consumer — logs from all hops" />)}

        {groupLabel('Metadata')}
        {bmJobId ? (
          <div className="text-sm text-gray-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-2">
            🏗️ Filed against Build Manager job <code className="text-xs">#{bmJobId.slice(0, 8)}</code>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {field('Linked report', (
              <select value={reportId} onChange={e => { setReportId(e.target.value); setSubReportId('') }} className={inputCls}>
                <option value="">(none)</option>
                {reports.map(r => <option key={r.report_id} value={r.report_id}>{reportOptionLabel(r)}</option>)}
              </select>
            ))}
            {field('Linked service (sub-report)', (
              <select value={subReportId} onChange={e => setSubReportId(e.target.value)} disabled={!reportId} className={inputCls}>
                <option value="">(whole report)</option>
                {subReports?.map(s => <option key={s.sub_report_id} value={s.sub_report_id}>{s.service_name || s.filename}</option>)}
              </select>
            ))}
          </div>
        )}
        {field('Assignee', (
          <select value={assigneeId} onChange={e => setAssigneeId(e.target.value)} className={inputCls}>
            <option value="">(unassigned)</option>
            {assignableUsers?.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
          </select>
        ))}
        {field('Tags (comma-separated)', <input value={tagsText} onChange={e => setTagsText(e.target.value)} className={inputCls} placeholder="infra, rabbitmq, tls" />)}
      </div>

      <div className="flex gap-2">
        <button onClick={handleSave} disabled={saving} className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
          {saving ? 'Saving…' : 'Submit Bug'}
        </button>
        <button onClick={onCancel} className="px-4 py-2 border border-gray-300 text-sm rounded-md hover:bg-gray-50">Cancel</button>
      </div>
    </div>
  )
}

// ── Bug detail ───────────────────────────────────────────────────────────────

function BugDetail({ bugId, onDeleted, onPromoteToKb, onOpenBug }: { bugId: string; onDeleted: () => void; onPromoteToKb?: (bugId: string) => void; onOpenBug: (bugId: string) => void }) {
  const { isOperator, isAdmin } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [resolutionDraft, setResolutionDraft] = useState<string | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [addingOccurrence, setAddingOccurrence] = useState(false)
  const [occReportId, setOccReportId] = useState('')
  const [occSubReportId, setOccSubReportId] = useState('')
  const [occNote, setOccNote] = useState('')
  const [savingToDocs, setSavingToDocs] = useState(false)
  const [saveDocsError, setSaveDocsError] = useState('')
  const [savedDoc, setSavedDoc] = useState<{ doc_id: string; doc_name: string; shelf_id: string; version: number } | null>(null)
  const [uploadingAttachment, setUploadingAttachment] = useState(false)
  const [attachmentError, setAttachmentError] = useState('')
  // Editing the core fields (title/description/severity/frequency) picked
  // at filing time — everything else in this view (status, assignee,
  // resolution, tags via bulk actions) already has its own inline edit
  // affordance; these four never did, even though PATCH /bugs/{id} already
  // supported them. Same "toggle a form, draft locally, PATCH on save"
  // shape as the resolution textarea just below.
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editSeverity, setEditSeverity] = useState<BugSeverity>('medium')
  const [editFrequency, setEditFrequency] = useState<BugFrequency | ''>('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [editError, setEditError] = useState('')
  // Mark-as-duplicate — search-and-pick the canonical bug, distinct from
  // the "Also seen on another report" occurrence flow below (that links an
  // additional origin to *this* bug; this links *this whole bug* to
  // another one entirely).
  const [pickingDuplicate, setPickingDuplicate] = useState(false)
  const [duplicateSearch, setDuplicateSearch] = useState('')
  const [markingDuplicate, setMarkingDuplicate] = useState(false)
  const [duplicateError, setDuplicateError] = useState('')

  const { data: bug, isLoading } = useQuery<BugFull>({
    queryKey: ['bug', bugId],
    queryFn: () => api.get(`/bugs/${bugId}`).then(r => r.data),
  })

  const { data: report } = useQuery({
    queryKey: ['jar-report-brief', bug?.report_id],
    queryFn: () => api.get(`/jar-analyser/reports/${bug!.report_id}`).then(r => r.data),
    enabled: !!bug?.report_id,
  })

  // Report/sub-report pickers for "Also seen on another report" — same
  // fetch pattern NewBugForm uses, but only loaded once the operator opens
  // the add-occurrence form (no point fetching this on every detail view).
  const { data: reportsData } = useQuery({
    queryKey: ['jar-reports-picker'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 100 } }).then(r => r.data),
    enabled: isOperator && addingOccurrence,
  })
  const reportOptions: ReportOption[] = reportsData?.items ?? []

  const { data: occSubReportOptions } = useQuery<SubReportOption[]>({
    queryKey: ['jar-sub-reports-picker', occReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${occReportId}/sub-reports`).then(r => r.data),
    enabled: !!occReportId,
  })

  const { data: assignableUsers } = useQuery<AssignableUser[]>({
    queryKey: ['bugs-assignable-users'],
    queryFn: () => api.get('/bugs/assignable-users').then(r => r.data),
    enabled: isOperator,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['bug', bugId] })

  const changeStatus = async (status: string) => {
    await api.patch(`/bugs/${bugId}/status`, { status })
    await invalidate()
  }

  const changeAssignee = async (assigneeId: string) => {
    await api.patch(`/bugs/${bugId}`, { assignee_id: assigneeId || null })
    await invalidate()
  }

  const startEditing = () => {
    if (!bug) return
    setEditTitle(bug.title)
    setEditDescription(bug.description)
    setEditSeverity(bug.severity)
    setEditFrequency(bug.frequency ?? '')
    setEditError('')
    setEditing(true)
  }

  const saveEdit = async () => {
    if (!editTitle.trim()) {
      setEditError('Title is required.')
      return
    }
    setSavingEdit(true)
    setEditError('')
    try {
      await api.patch(`/bugs/${bugId}`, {
        title: editTitle.trim(), description: editDescription,
        severity: editSeverity, frequency: editFrequency || null,
      })
      setEditing(false)
      await invalidate()
    } catch (err: any) {
      setEditError(err.response?.data?.detail || 'Failed to save changes')
    } finally {
      setSavingEdit(false)
    }
  }

  const { data: duplicateSearchData } = useQuery({
    queryKey: ['bugs-duplicate-search', duplicateSearch],
    queryFn: () => api.get('/bugs/search', { params: { q: duplicateSearch, page_size: 10 } }).then(r => r.data),
    enabled: pickingDuplicate && duplicateSearch.trim().length > 1,
  })
  const duplicateCandidates: BugSummary[] = (duplicateSearchData?.items ?? []).filter((b: BugSummary) => b.id !== bugId)

  const markDuplicate = async (targetId: string) => {
    setMarkingDuplicate(true)
    setDuplicateError('')
    try {
      await api.post(`/bugs/${bugId}/mark-duplicate`, { target_bug_id: targetId })
      setPickingDuplicate(false)
      setDuplicateSearch('')
      await invalidate()
    } catch (err: any) {
      setDuplicateError(err.response?.data?.detail || 'Failed to mark as duplicate')
    } finally {
      setMarkingDuplicate(false)
    }
  }

  const unmarkDuplicate = async () => {
    await api.post(`/bugs/${bugId}/unmark-duplicate`)
    await invalidate()
  }

  const saveResolution = async () => {
    if (resolutionDraft === null) return
    await api.patch(`/bugs/${bugId}`, { resolution: resolutionDraft })
    await api.patch(`/bugs/${bugId}/status`, { status: 'resolved', note: 'Resolution documented' })
    setResolutionDraft(null)
    await invalidate()
  }

  const addComment = async () => {
    if (!commentDraft.trim()) return
    await api.post(`/bugs/${bugId}/comments`, { text: commentDraft.trim() })
    setCommentDraft('')
    await invalidate()
  }

  const deleteBug = async () => {
    if (!confirm(`Delete bug "${bug?.title}"? It'll move to Rubbish and can be restored by an admin within 30 days.`)) return
    await api.delete(`/bugs/${bugId}`)
    onDeleted()
  }

  const addOccurrence = async () => {
    if (!occReportId) return
    await api.post(`/bugs/${bugId}/occurrences`, {
      report_id: occReportId,
      sub_report_id: occSubReportId || null,
      note: occNote.trim() || null,
    })
    setAddingOccurrence(false)
    setOccReportId('')
    setOccSubReportId('')
    setOccNote('')
    await invalidate()
  }

  const removeOccurrence = async (occurrenceId: string) => {
    if (!confirm('Unlink this occurrence?')) return
    await api.delete(`/bugs/${bugId}/occurrences/${occurrenceId}`)
    await invalidate()
  }

  const uploadAttachment = async (file: File) => {
    setUploadingAttachment(true)
    setAttachmentError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      await api.post(`/bugs/${bugId}/attachments`, fd)
      await invalidate()
    } catch (err: any) {
      setAttachmentError(err.response?.data?.detail || 'Failed to upload attachment')
    } finally {
      setUploadingAttachment(false)
    }
  }

  const removeAttachment = async (attachmentId: string) => {
    if (!confirm('Delete this attachment? This cannot be undone.')) return
    await api.delete(`/bugs/${bugId}/attachments/${attachmentId}`)
    await invalidate()
  }

  const downloadAttachment = async (attachmentId: string, filename: string) => {
    const res = await api.get(`/bugs/${bugId}/attachments/${attachmentId}/download`, { responseType: 'blob' })
    const href = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    URL.revokeObjectURL(href)
  }

  const saveToDocs = async () => {
    setSavingToDocs(true)
    setSaveDocsError('')
    try {
      const res = await api.post(`/bugs/${bugId}/save-to-docs`)
      setSavedDoc(res.data)
    } catch (err: any) {
      setSaveDocsError(err.response?.data?.detail || 'Failed to save to Docs')
    } finally {
      setSavingToDocs(false)
    }
  }

  if (isLoading || !bug) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>
  }

  return (
    <div className="space-y-4">
      <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className={`px-2 py-0.5 text-xs font-medium rounded border ${SEVERITY_COLOUR[bug.severity]}`}>{bug.severity}</span>
              {bug.frequency && <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{bug.frequency}</span>}
              {bug.auto_created && (
                <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-medium" title="Automatically filed by the Ansible-failure scanner — Improvements Plan Stage 22">
                  🤖 Auto-filed
                </span>
              )}
              {bug.tags.map(t => <span key={t} className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{t}</span>)}
              {isOperator && !editing && (
                <button onClick={startEditing} className="text-[10px] text-blue-600 hover:underline ml-auto">✏️ Edit</button>
              )}
            </div>
            {editing ? (
              <div className="space-y-2 mb-2">
                <input
                  value={editTitle} onChange={e => setEditTitle(e.target.value)}
                  className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm font-semibold"
                  placeholder="Title"
                />
                <div className="flex gap-2">
                  <select value={editSeverity} onChange={e => setEditSeverity(e.target.value as BugSeverity)}
                    className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                    {SEVERITIES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <select value={editFrequency} onChange={e => setEditFrequency(e.target.value as BugFrequency | '')}
                    className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                    <option value="">No frequency set</option>
                    {FREQUENCIES.map(f => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
              </div>
            ) : (
              <h2 className="text-lg font-semibold text-gray-900">{bug.title}</h2>
            )}
            {report && (
              <p className="text-xs text-gray-400 mt-0.5">
                Filed against:{' '}
                <button
                  onClick={() => navigate(`/jar-analyser?report=${bug.report_id}${bug.sub_report_id ? `&sub=${bug.sub_report_id}` : ''}`)}
                  className="text-blue-600 hover:underline">
                  {report.implementation_title || report.filename}
                </button>
                {bug.sub_report_id ? ' (specific service)' : ''}
              </p>
            )}
            <p className="text-xs text-gray-400 mt-0.5 flex items-center gap-1.5">
              <span>Assignee:</span>
              {isOperator ? (
                <select
                  value={bug.assignee_id ?? ''}
                  onChange={e => changeAssignee(e.target.value)}
                  className="text-xs border border-gray-200 rounded px-1.5 py-0.5">
                  <option value="">Unassigned</option>
                  {assignableUsers?.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                </select>
              ) : (
                <span className="text-gray-600">{bug.assignee_username || 'Unassigned'}</span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={bug.status}
              onChange={e => isOperator && changeStatus(e.target.value)}
              disabled={!isOperator}
              className={`px-2 py-1.5 text-xs rounded-md border ${STATUS_COLOUR[bug.status]} disabled:opacity-70`}
            >
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            {isOperator && !bug.duplicate_of_bug_id && (
              <button onClick={() => setPickingDuplicate(v => !v)}
                className="px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-50 rounded border border-gray-300">
                🔗 Mark as duplicate
              </button>
            )}
            {isAdmin && (
              <button onClick={deleteBug} className="px-2 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded border border-red-200">Delete</button>
            )}
          </div>
        </div>

        {bug.duplicate_of_bug_id && (
          <div className="flex items-center gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
            <span>🔗 Marked as a duplicate of "{bug.duplicate_of_title ?? bug.duplicate_of_bug_id.slice(0, 8)}"</span>
            <button onClick={() => onOpenBug(bug.duplicate_of_bug_id!)}
              className="text-amber-900 font-medium hover:underline">
              View →
            </button>
            {isAdmin && (
              <button onClick={unmarkDuplicate} className="text-amber-700 hover:underline ml-auto shrink-0">Unmark</button>
            )}
          </div>
        )}

        {pickingDuplicate && (
          <div className="border border-gray-200 rounded-md p-3 space-y-2 bg-gray-50">
            {duplicateError && <p className="text-xs text-red-600">{duplicateError}</p>}
            <input
              value={duplicateSearch} onChange={e => setDuplicateSearch(e.target.value)}
              placeholder="Search for the bug this is a duplicate of…"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm"
              autoFocus
            />
            {duplicateSearch.trim().length > 1 && (
              <div className="space-y-1 max-h-56 overflow-y-auto">
                {duplicateCandidates.map(c => (
                  <button key={c.id} onClick={() => markDuplicate(c.id)} disabled={markingDuplicate}
                    className="w-full text-left text-sm px-2 py-1.5 rounded border border-gray-200 bg-white hover:border-blue-300 hover:bg-blue-50 disabled:opacity-40 flex items-center gap-2">
                    <span className={`px-1.5 py-0.5 text-[10px] rounded border shrink-0 ${SEVERITY_COLOUR[c.severity]}`}>{c.severity}</span>
                    <span className="truncate">{c.title}</span>
                  </button>
                ))}
                {duplicateCandidates.length === 0 && (
                  <p className="text-xs text-gray-400 px-1">No matching bugs found.</p>
                )}
              </div>
            )}
            <button onClick={() => { setPickingDuplicate(false); setDuplicateSearch(''); setDuplicateError('') }}
              className="text-xs text-gray-500 hover:text-gray-700">
              Cancel
            </button>
          </div>
        )}

        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Description</p>
          {editing ? (
            <>
              {editError && <p className="text-xs text-red-600 mb-1">{editError}</p>}
              <textarea
                value={editDescription} onChange={e => setEditDescription(e.target.value)}
                rows={6} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
              />
              <div className="flex gap-2 mt-1.5">
                <button onClick={saveEdit} disabled={savingEdit}
                  className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40">
                  {savingEdit ? 'Saving…' : 'Save Changes'}
                </button>
                <button onClick={() => setEditing(false)} className="px-3 py-1.5 text-xs border border-gray-300 rounded-md hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <div className="border border-gray-100 rounded p-3 bg-gray-50">
              <MarkdownPreview content={bug.description || '*No description provided.*'} onNavigateToDoc={() => {}} />
            </div>
          )}
        </div>

        <div>
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Resolution</p>
          {bug.resolution && resolutionDraft === null && (
            <div className="border border-green-100 bg-green-50 rounded p-3 mb-2">
              <MarkdownPreview content={bug.resolution} onNavigateToDoc={() => {}} />
            </div>
          )}
          {isOperator && (
            <>
              <textarea
                value={resolutionDraft ?? bug.resolution ?? ''}
                onChange={e => setResolutionDraft(e.target.value)}
                rows={3} placeholder="Describe how this was resolved…"
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              />
              <button onClick={saveResolution} disabled={resolutionDraft === null}
                className="mt-1 px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40">
                Save Resolution
              </button>
            </>
          )}
        </div>

        {isOperator && bug.resolution && (
          <div className="pt-3 border-t border-gray-100 flex flex-wrap items-center gap-2">
            {savedDoc ? (
              <div className="flex items-center gap-2 text-xs text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">
                <span>✓ Saved to Docs as "{savedDoc.doc_name}" (v{savedDoc.version})</span>
                <button
                  onClick={() => navigate(`/docs?openDoc=1&docId=${savedDoc.doc_id}&shelfId=${savedDoc.shelf_id}&docName=${encodeURIComponent(savedDoc.doc_name)}`)}
                  className="text-green-800 font-medium hover:underline ml-auto shrink-0">
                  View in Docs →
                </button>
              </div>
            ) : (
              <button onClick={saveToDocs} disabled={savingToDocs}
                className="text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded-md px-3 py-1.5 disabled:opacity-40">
                {savingToDocs ? 'Saving…' : '📄 Save to Docs'}
              </button>
            )}
            {onPromoteToKb && (
              <button
                onClick={() => onPromoteToKb(bugId)}
                title="Prefill a new Error Knowledge Base entry from this bug's title, severity and resolution"
                className="text-xs text-blue-700 hover:text-blue-900 border border-blue-200 bg-blue-50 rounded-md px-3 py-1.5">
                📖 Promote to KB
              </button>
            )}
            {saveDocsError && <p className="text-xs text-red-600 mt-1 w-full">{saveDocsError}</p>}
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Attachments ({bug.attachments.length})</p>
        <div className="space-y-1.5 mb-3">
          {bug.attachments.map(a => (
            <div key={a.id} className="flex items-center gap-2 text-sm border-b border-gray-100 pb-1.5">
              <button onClick={() => downloadAttachment(a.id, a.filename)} className="text-blue-600 hover:underline text-left truncate">
                📎 {a.filename}
              </button>
              <span className="text-xs text-gray-400 shrink-0">{formatFileSize(a.size_bytes)}</span>
              {a.uploaded_by && <span className="text-xs text-gray-400 shrink-0">by {a.uploaded_by}</span>}
              {isAdmin && (
                <button onClick={() => removeAttachment(a.id)} className="text-xs text-red-500 hover:underline ml-auto shrink-0">Delete</button>
              )}
            </div>
          ))}
          {bug.attachments.length === 0 && <p className="text-sm text-gray-400">No attachments yet.</p>}
        </div>
        {isOperator && (
          <div>
            <input
              type="file"
              disabled={uploadingAttachment}
              onChange={e => { const f = e.target.files?.[0]; if (f) void uploadAttachment(f); e.target.value = '' }}
              className="text-xs text-gray-600 file:mr-2 file:px-3 file:py-1.5 file:rounded-md file:border-0 file:bg-blue-600 file:text-white file:text-xs hover:file:bg-blue-700 disabled:opacity-40"
            />
            {uploadingAttachment && <p className="text-xs text-gray-400 mt-1">Uploading…</p>}
            {attachmentError && <p className="text-xs text-red-600 mt-1">{attachmentError}</p>}
            <p className="text-xs text-gray-400 mt-1">Max 25 MB per file.</p>
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Comments ({bug.comments.length})</p>
        <div className="space-y-2 mb-3">
          {bug.comments.map(c => (
            <div key={c.id} className="text-sm border-b border-gray-100 pb-2">
              <div className="flex items-center gap-2 text-xs text-gray-400 mb-0.5">
                <span className="font-medium text-gray-600">{c.author}</span>
                <span>{new Date(c.created_at).toLocaleString()}</span>
              </div>
              <div className="text-gray-800">
                <MarkdownPreview content={c.text} onNavigateToDoc={() => {}} />
              </div>
            </div>
          ))}
          {bug.comments.length === 0 && <p className="text-sm text-gray-400">No comments yet.</p>}
        </div>
        {isOperator && (
          <div className="flex gap-2">
            <textarea value={commentDraft} onChange={e => setCommentDraft(e.target.value)} rows={2}
              placeholder="Add a comment…" className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm" />
            <button onClick={addComment} className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 self-end">Comment</button>
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">
            Seen in {(bug.report_id || bug.bm_job_id ? 1 : 0) + bug.occurrences.length} place{(bug.report_id || bug.bm_job_id ? 1 : 0) + bug.occurrences.length === 1 ? '' : 's'}
          </p>
          {isOperator && (
            <button onClick={() => setAddingOccurrence(v => !v)} className="text-xs text-blue-600 hover:underline">
              {addingOccurrence ? 'Cancel' : '+ Also seen on another report'}
            </button>
          )}
        </div>

        <div className="space-y-1.5 mb-2">
          {bug.report_id && report && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded shrink-0">primary</span>
              <button
                onClick={() => navigate(`/jar-analyser?report=${bug.report_id}${bug.sub_report_id ? `&sub=${bug.sub_report_id}` : ''}`)}
                className="text-blue-600 hover:underline text-left">
                {report.implementation_title || report.filename}
              </button>
            </div>
          )}
          {bug.bm_job_id && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded shrink-0">primary</span>
              <button onClick={() => navigate(`/jobs?id=${bug.bm_job_id}`)} className="text-blue-600 hover:underline text-left">
                🏗️ Build Manager job #{bug.bm_job_id.slice(0, 8)}
              </button>
            </div>
          )}
          {bug.occurrences.map(o => (
            <OccurrenceRow key={o.id} occurrence={o} isAdmin={isAdmin} onRemove={() => removeOccurrence(o.id)} />
          ))}
          {!bug.report_id && !bug.bm_job_id && bug.occurrences.length === 0 && (
            <p className="text-sm text-gray-400">Not linked to any report or job yet.</p>
          )}
        </div>

        {addingOccurrence && isOperator && (
          <div className="border-t border-gray-100 pt-3 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <select
                value={occReportId}
                onChange={e => { setOccReportId(e.target.value); setOccSubReportId('') }}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                <option value="">Select report…</option>
                {reportOptions.map(r => <option key={r.report_id} value={r.report_id}>{reportOptionLabel(r)}</option>)}
              </select>
              <select
                value={occSubReportId}
                onChange={e => setOccSubReportId(e.target.value)}
                disabled={!occReportId}
                className="border border-gray-300 rounded px-2 py-1.5 text-sm disabled:opacity-50">
                <option value="">(whole report)</option>
                {occSubReportOptions?.map(s => (
                  <option key={s.sub_report_id} value={s.sub_report_id}>{s.service_name || s.filename}</option>
                ))}
              </select>
            </div>
            <input
              value={occNote}
              onChange={e => setOccNote(e.target.value)}
              placeholder="Note (optional) — e.g. 'same NPE, different version'"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
            />
            <button onClick={addOccurrence} disabled={!occReportId}
              className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40">
              Link Report
            </button>
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">Timeline</p>
        <div className="space-y-1.5">
          {bug.history.map(h => (
            <div key={h.id} className="text-xs text-gray-500 flex items-center gap-2">
              <span className="text-gray-400 w-32 shrink-0">{new Date(h.created_at).toLocaleString()}</span>
              <span>{h.action}{h.to_status ? ` → ${h.to_status}` : ''}</span>
              {h.actor && <span className="text-gray-400">({h.actor})</span>}
              {h.note && <span className="text-gray-400">— {h.note}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// One row per BugOccurrence — a per-row query for the report's display name
// is unavoidable since occurrences only carry report_id, and hooks can't be
// called inside BugDetail's .map() directly.
function OccurrenceRow({ occurrence, isAdmin, onRemove }: { occurrence: BugOccurrenceT; isAdmin: boolean; onRemove: () => void }) {
  const navigate = useNavigate()
  // report_id/bm_job_id are mutually exclusive (Improvements Plan Stage 19)
  // — the query below is a no-op (enabled: false) for a job-origin occurrence.
  const { data: report } = useQuery({
    queryKey: ['jar-report-brief', occurrence.report_id],
    queryFn: () => api.get(`/jar-analyser/reports/${occurrence.report_id}`).then(r => r.data),
    enabled: !!occurrence.report_id,
  })

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded shrink-0">occurrence</span>
      {occurrence.report_id ? (
        <button
          onClick={() => navigate(`/jar-analyser?report=${occurrence.report_id}${occurrence.sub_report_id ? `&sub=${occurrence.sub_report_id}` : ''}`)}
          className="text-blue-600 hover:underline text-left">
          {report ? (report.implementation_title || report.filename) : `report #${occurrence.report_id.slice(0, 8)}`}
        </button>
      ) : (
        <button onClick={() => navigate(`/jobs?id=${occurrence.bm_job_id}`)} className="text-blue-600 hover:underline text-left">
          🏗️ Build Manager job #{occurrence.bm_job_id?.slice(0, 8)}
        </button>
      )}
      {occurrence.note && <span className="text-xs text-gray-400 truncate">— {occurrence.note}</span>}
      {isAdmin && (
        <button onClick={onRemove} className="text-xs text-red-500 hover:underline ml-auto shrink-0">Unlink</button>
      )}
    </div>
  )
}

// ── Dashboard ────────────────────────────────────────────────────────────────
// Stage 5 — the direct evolution of DocApp's "counts + severity breakdown +
// avg resolution time + top affected documents" widget, with "top reports/
// services" replacing "top documents" per this plan's cross-report focus.

interface DashboardData {
  total: number
  by_status: Record<string, number>
  open_by_severity: Record<string, number>
  avg_resolution_hours: number | null
  top_reports: { report_id: string; bug_count: number }[]
  auto_filed_open_count: number
}

function Dashboard({ onOpenReport, onOpenAutoFiled }: { onOpenReport: (reportId: string) => void; onOpenAutoFiled: () => void }) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ['bugs-dashboard'],
    queryFn: () => api.get('/bugs/dashboard').then(r => r.data),
  })

  // Visiting the Dashboard is treated as "caught up" — marks the checkpoint
  // and clears the header's activity badge. Fire-and-forget: a failure here
  // just leaves the badge count stale, not worth surfacing to the user.
  useEffect(() => {
    api.post('/bugs/my-activity-checkpoint').then(() => {
      queryClient.invalidateQueries({ queryKey: ['bugs-activity-count'] })
    }).catch(() => {})
  }, [queryClient])

  // Open + investigating count scoped to the logged-in user's own
  // assignments — two small count-only calls rather than a dashboard
  // backend change, same "page_size=1, read total" pattern used for the
  // report/sub-report bug-count badges elsewhere in this file.
  const { data: myOpenCount } = useQuery({
    queryKey: ['bugs-my-open-count', user?.user_id],
    queryFn: async () => {
      const [open, investigating] = await Promise.all([
        api.get('/bugs', { params: { assignee_id: user!.user_id, status: 'open', page_size: 1 } }),
        api.get('/bugs', { params: { assignee_id: user!.user_id, status: 'investigating', page_size: 1 } }),
      ])
      return (open.data.total as number) + (investigating.data.total as number)
    },
    enabled: !!user,
  })

  if (isLoading || !data) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>
  }

  const openCount = (data.by_status.open ?? 0) + (data.by_status.investigating ?? 0)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Total bugs" value={data.total} />
        <StatCard label="Open" value={openCount} />
        <StatCard label="My Open Bugs" value={myOpenCount ?? 0} />
        <StatCard label="Resolved" value={data.by_status.resolved ?? 0} />
        <StatCard label="Avg. time to resolve" value={data.avg_resolution_hours == null ? '—' : formatHours(data.avg_resolution_hours)} />
        <StatCard
          label="🤖 Auto-filed, awaiting triage" value={data.auto_filed_open_count}
          onClick={data.auto_filed_open_count > 0 ? onOpenAutoFiled : undefined}
        />
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">Status breakdown</p>
        <div className="space-y-1.5">
          {STATUSES.map(s => (
            <div key={s} className="flex items-center gap-2 text-sm">
              <span className={`px-2 py-0.5 text-xs rounded w-28 text-center shrink-0 ${STATUS_COLOUR[s]}`}>{s}</span>
              <div className="flex-1 bg-gray-100 rounded h-2 overflow-hidden">
                <div className="bg-blue-500 h-2" style={{ width: data.total ? `${((data.by_status[s] ?? 0) / data.total) * 100}%` : '0%' }} />
              </div>
              <span className="text-xs text-gray-500 w-8 text-right shrink-0">{data.by_status[s] ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">Open bugs by severity</p>
        <div className="flex gap-3">
          {SEVERITIES.map(s => (
            <div key={s} className={`flex-1 text-center rounded border px-3 py-2 ${SEVERITY_COLOUR[s]}`}>
              <div className="text-lg font-bold">{data.open_by_severity[s] ?? 0}</div>
              <div className="text-xs capitalize">{s}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">Top affected reports</p>
        {data.top_reports.length === 0 && <p className="text-sm text-gray-400">No reports have known bugs yet.</p>}
        <div className="space-y-1">
          {data.top_reports.map(r => (
            <TopReportRow key={r.report_id} reportId={r.report_id} bugCount={r.bug_count} onOpen={() => onOpenReport(r.report_id)} />
          ))}
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, onClick }: { label: string; value: string | number; onClick?: () => void }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      onClick={onClick}
      className={`bg-white border border-gray-200 rounded-lg p-4 text-left ${onClick ? 'hover:border-blue-300 hover:bg-blue-50 cursor-pointer' : ''}`}>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </Tag>
  )
}

function formatHours(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`
  if (hours < 48) return `${hours.toFixed(1)}h`
  return `${(hours / 24).toFixed(1)}d`
}

function TopReportRow({ reportId, bugCount, onOpen }: { reportId: string; bugCount: number; onOpen: () => void }) {
  const { data: report } = useQuery({
    queryKey: ['jar-report-brief', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}`).then(r => r.data),
  })
  return (
    <button onClick={onOpen} className="w-full flex items-center gap-2 text-sm text-left hover:bg-gray-50 rounded px-2 py-1.5 -mx-2">
      <span className="flex-1 min-w-0 truncate text-blue-600">
        {report ? (report.implementation_title || report.filename) : `report #${reportId?.slice(0, 8) ?? '?'}`}
      </span>
      <span className="text-xs text-gray-500 shrink-0">{bugCount} bug{bugCount === 1 ? '' : 's'}</span>
    </button>
  )
}
