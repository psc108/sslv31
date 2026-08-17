import { useState, useEffect, useRef } from 'react'
import type React from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { SubReportSummary, DecompileRun } from './types'
import ExportControls from './ExportControls'
import SearchPanel from './SearchPanel'
import StorefrontGuideTab from './StorefrontGuideTab'
import TopologyTab from './TopologyTab'
import EnvVarsTab from './EnvVarsTab'
import NginxConfigTab from './NginxConfigTab'
import MessageBusTab from './MessageBusTab'
import DtoConflictsTab from './DtoConflictsTab'
import OutboundIntegrationsTab from './OutboundIntegrationsTab'

interface Props {
  reportId: string
  onSelectSub: (subId: string) => void
  onBack: () => void
  onCompare: () => void
  onRerun?: (uploadId: string) => void
  onNavigate: (reportId: string, subReportId: string, tab: string) => void
  onDiagnostics?: () => void
  onInfraDiagnostics?: (reportId: string) => void
  onBugTracker?: (mode: 'new' | 'list') => void
  onViewBug?: (bugId: string) => void
  onFirstSeenDocs?: () => void
}

function fmtBytes(b: number) {
  if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

// Matches BugTracker.tsx's own STATUS_COLOUR/SEVERITY_COLOUR badge palette
// (Related Bugs panel below) — kept local rather than shared/exported since
// this is the only other place badges like this appear outside Docs.
const STATUS_BADGE: Record<string, string> = {
  open: 'bg-red-50 text-red-700',
  investigating: 'bg-amber-50 text-amber-700',
  resolved: 'bg-green-50 text-green-700',
  closed: 'bg-gray-100 text-gray-500',
  'wont-fix': 'bg-gray-100 text-gray-500',
}
const SEVERITY_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-800',
  high: 'bg-orange-100 text-orange-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-blue-100 text-blue-800',
}

type TopTab = 'overview' | 'storefront' | 'topology' | 'envvars' | 'nginx' | 'messagebus' | 'dtoconflicts' | 'outbound'

export default function TopLevelReport({ reportId, onSelectSub, onBack, onCompare, onRerun, onNavigate, onDiagnostics, onInfraDiagnostics, onBugTracker, onViewBug, onFirstSeenDocs }: Props) {
  // Decompiling (and downloading decompiled source) is admin/operator only —
  // enforced on the backend too, this just avoids readonly/auditor users
  // hitting a 403 on click.
  const { isOperator } = useAuth()
  const [rerunning, setRerunning] = useState(false)
  const [rerunStatus, setRerunStatus] = useState<'idle' | 'pending' | 'analysing' | 'done' | 'failed'>('idle')
  const [showSearch, setShowSearch] = useState(false)
  const [topTab, setTopTab] = useState<TopTab>('overview')
  const [decompileTimeout, setDecompileTimeout] = useState(120)
  const [decompiling, setDecompiling] = useState(false)
  const [decompileRun, setDecompileRun] = useState<DecompileRun | null>(null)
  const decompilePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [rowDecompileStatus, setRowDecompileStatus] = useState<Record<string, 'running' | 'completed' | 'no_classes' | 'failed'>>({})
  const rowPollRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({})
  const queryClient = useQueryClient()

  useEffect(() => () => {
    if (decompilePollRef.current) clearInterval(decompilePollRef.current)
    Object.values(rowPollRefs.current).forEach(clearInterval)
  }, [])
  const { data: report } = useQuery({
    queryKey: ['report', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}`).then(r => r.data),
  })

  const { data: subs } = useQuery<SubReportSummary[]>({
    queryKey: ['sub-reports', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports`).then(r => r.data),
  })

  const { data: bugCount } = useQuery({
    queryKey: ['bug-count', reportId],
    queryFn: () => api.get('/bugs', { params: { report_id: reportId, page_size: 1 } }).then(r => r.data.total as number),
    enabled: !!onBugTracker,
  })

  const { data: firstSeenDocCount } = useQuery({
    queryKey: ['first-seen-doc-count', reportId],
    queryFn: () => api.get('/docs/search', { params: { first_seen_report_id: reportId, page_size: 1 } }).then(r => r.data.total as number),
    enabled: !!onFirstSeenDocs,
  })

  if (!report) return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>

  const jar = report.jar_file ?? {}
  const manifest = report.manifest ?? {}
  const summary = report.summary ?? {}

  const handleRerun = async () => {
    if (!report.upload_id || rerunning) return
    setRerunning(true)
    setRerunStatus('pending')
    try {
      await api.post(`/jar-analyser/uploads/${report.upload_id}/reanalyse`)
      setRerunStatus('analysing')
      const uploadId: string = report.upload_id
      const poll = setInterval(async () => {
        try {
          const r = await api.get(`/jar-analyser/uploads/${uploadId}/status`)
          const s = r.data
          if (s.status === 'completed' && s.report_id) {
            clearInterval(poll)
            setRerunning(false)
            setRerunStatus('done')
            await queryClient.invalidateQueries({ queryKey: ['jar-reports'] })
            onRerun?.(uploadId)
          } else if (s.status === 'failed') {
            clearInterval(poll)
            setRerunning(false)
            setRerunStatus('failed')
          }
        } catch {
          clearInterval(poll)
          setRerunning(false)
          setRerunStatus('failed')
        }
      }, 2000)
    } catch {
      setRerunning(false)
      setRerunStatus('failed')
    }
  }

  const handleDecompileAll = async () => {
    if (decompiling) return
    setDecompiling(true)
    try {
      const res = await api.post(`/jar-analyser/reports/${reportId}/decompile-all`, { timeout_seconds: decompileTimeout })
      const runId = res.data.run_id
      decompilePollRef.current = setInterval(async () => {
        try {
          const r = await api.get(`/jar-analyser/reports/${reportId}/decompile-runs/${runId}`)
          setDecompileRun(r.data)
          if (r.data.status === 'completed' || r.data.status === 'failed') {
            clearInterval(decompilePollRef.current!)
            setDecompiling(false)
          }
        } catch {
          clearInterval(decompilePollRef.current!)
          setDecompiling(false)
        }
      }, 2500)
    } catch {
      setDecompiling(false)
    }
  }

  const handleDownloadAllDecompiled = () => {
    api.get(`/jar-analyser/reports/${reportId}/decompile/export`, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'all-decompiled-source.zip'
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  const handleDecompileOne = async (subId: string) => {
    setRowDecompileStatus(s => ({ ...s, [subId]: 'running' }))
    try {
      const res = await api.post(`/jar-analyser/reports/${reportId}/sub-reports/${subId}/decompile`, { timeout_seconds: decompileTimeout })
      const runId = res.data.run_id
      rowPollRefs.current[subId] = setInterval(async () => {
        try {
          const r = await api.get(`/jar-analyser/reports/${reportId}/decompile-runs/${runId}`)
          if (r.data.status === 'completed' || r.data.status === 'failed') {
            clearInterval(rowPollRefs.current[subId])
            delete rowPollRefs.current[subId]
            // Per-jar result (not the job-level status) distinguishes "found
            // nothing to decompile" (no_classes — e.g. an nginx/frontend
            // installer with no .class files) from a real failure.
            const jarStatus = r.data.results?.[0]?.status ?? r.data.status
            setRowDecompileStatus(s => ({ ...s, [subId]: jarStatus === 'timed_out' ? 'failed' : jarStatus }))
          }
        } catch {
          clearInterval(rowPollRefs.current[subId])
          delete rowPollRefs.current[subId]
          setRowDecompileStatus(s => ({ ...s, [subId]: 'failed' }))
        }
      }, 2500)
    } catch {
      setRowDecompileStatus(s => ({ ...s, [subId]: 'failed' }))
    }
  }

  const handleDownloadOneDecompiled = (subId: string, filename: string) => {
    api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subId}/decompile/export`, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${filename.replace(/\.(jar|war)$/i, '')}-decompiled.zip`
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  const summaryCards = [
    { label: 'Services', value: summary.nested_jar_count ?? (subs?.length ?? 0), icon: '📦' },
    { label: 'Endpoints', value: summary.total_endpoint_count ?? 0, icon: '🔌' },
    { label: 'Dependencies', value: summary.total_dependency_count ?? 0, icon: '📚' },
    { label: 'Ports', value: (summary.ports_detected ?? []).length, icon: '🔢' },
    { label: 'Migrations', value: summary.total_migration_script_count ?? 0, icon: '🗄️' },
  ]

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-2">
            ← All Reports
          </button>
          <h1 className="text-2xl font-bold text-gray-900">{jar.original_filename}</h1>
          <div className="flex flex-wrap gap-3 mt-1 text-sm text-gray-500">
            {manifest.implementation_vendor && <span>{manifest.implementation_vendor}</span>}
            {manifest.implementation_version && <span>v{manifest.implementation_version}</span>}
            {summary.java_version_required && <span>Java {summary.java_version_required}</span>}
            {summary.spring_boot_version && <span>Spring Boot {summary.spring_boot_version}</span>}
            {report.analysis_duration_ms && <span>Analysis: {(report.analysis_duration_ms / 1000).toFixed(1)}s</span>}
          </div>
          {jar.sha256 && (
            <p className="text-xs text-gray-400 mt-1 font-mono">SHA256: {jar.sha256}</p>
          )}
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={() => setShowSearch(s => !s)}
            className={`px-3 py-1.5 border rounded text-sm flex items-center gap-1.5 transition ${
              showSearch ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
            }`}>
            🔍 Search
          </button>
          <button onClick={onCompare}
            className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50">
            ⚖ Compare versions
          </button>
          <button onClick={handleRerun} disabled={rerunning}
            className="px-3 py-1.5 border border-amber-300 rounded text-sm text-amber-700 hover:bg-amber-50 disabled:opacity-40 flex items-center gap-1.5">
            {rerunning && (
              <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
            )}
            {rerunStatus === 'pending' ? 'Starting…' : rerunStatus === 'analysing' ? 'Analysing…' : '↺ Re-run'}
          </button>
          <ExportControls reportId={reportId} />
          <label className="text-xs text-gray-500 flex items-center gap-1">
            <input
              type="number" min={1} max={900} value={decompileTimeout}
              onChange={e => setDecompileTimeout(Math.min(900, Math.max(1, Number(e.target.value) || 120)))}
              className="w-16 border border-gray-300 rounded px-1.5 py-1 text-xs"
              title="Per-jar decompile timeout (seconds)"
            />
            s
          </label>
          {isOperator && (
            <button onClick={handleDecompileAll} disabled={decompiling}
              className="px-3 py-1.5 border border-indigo-300 rounded text-sm text-indigo-700 hover:bg-indigo-50 disabled:opacity-40">
              {decompiling ? '⏳ Decompiling…' : '🧬 Decompile All Jars'}
            </button>
          )}
          {onDiagnostics && (
            <button
              onClick={onDiagnostics}
              className="px-3 py-1.5 border border-teal-300 rounded text-sm text-teal-700 hover:bg-teal-50">
              🩺 Diagnostics
            </button>
          )}
          {onInfraDiagnostics && (
            <button
              onClick={() => onInfraDiagnostics(reportId)}
              className="px-3 py-1.5 border border-orange-300 rounded text-sm text-orange-700 hover:bg-orange-50">
              🔧 Diagnose Infrastructure
            </button>
          )}
          {onBugTracker && (
            <>
              <button
                onClick={() => onBugTracker('new')}
                className="px-3 py-1.5 border border-rose-300 rounded text-sm text-rose-700 hover:bg-rose-50">
                🐛 Report Bug
              </button>
              {!!bugCount && (
                <button
                  onClick={() => onBugTracker('list')}
                  className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50">
                  🐛 {bugCount} bug{bugCount !== 1 ? 's' : ''}
                </button>
              )}
            </>
          )}
          {!!onFirstSeenDocs && !!firstSeenDocCount && (
            <button
              onClick={() => onFirstSeenDocs()}
              className="px-3 py-1.5 border border-indigo-300 rounded text-sm text-indigo-700 hover:bg-indigo-50">
              📄 {firstSeenDocCount} doc{firstSeenDocCount !== 1 ? 's' : ''} first seen here
            </button>
          )}
        </div>
      </div>

      {/* Top-level tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1">
          {(['overview', 'topology', 'outbound', 'messagebus', 'dtoconflicts', 'envvars', 'nginx', 'storefront'] as TopTab[]).map(t => (
            <button key={t} onClick={() => setTopTab(t)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                topTab === t
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t === 'storefront' ? '📖 Developer Guide'
                : t === 'topology' ? '🗺 Topology'
                : t === 'outbound' ? '🌐 Outbound'
                : t === 'messagebus' ? '🐰 Message Bus'
                : t === 'dtoconflicts' ? '⚠ DTO Conflicts'
                : t === 'envvars' ? '🔧 Env Vars'
                : t === 'nginx' ? '⚙️ Nginx Configs'
                : 'Overview'}
            </button>
          ))}
        </nav>
      </div>

      {topTab === 'storefront' && <StorefrontGuideTab reportId={reportId} />}
      {topTab === 'topology' && <TopologyTab reportId={reportId} />}
      {topTab === 'outbound' && <OutboundIntegrationsTab reportId={reportId} />}
      {topTab === 'messagebus' && <MessageBusTab reportId={reportId} />}
      {topTab === 'dtoconflicts' && <DtoConflictsTab reportId={reportId} />}
      {topTab === 'envvars' && <EnvVarsTab reportId={reportId} />}
      {topTab === 'nginx' && <NginxConfigTab reportId={reportId} />}

      {topTab === 'overview' && <>
      {/* Re-run status banner */}
      {rerunStatus === 'analysing' && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700 flex items-center gap-2">
          <svg className="animate-spin h-4 w-4 text-blue-600 shrink-0" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          Re-analysis in progress — this page will refresh automatically when complete.
        </div>
      )}
      {rerunStatus === 'failed' && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          ✗ Re-analysis failed. Check the file still exists on the server.
        </div>
      )}

      {/* Decompile-all progress/summary */}
      {decompileRun && (() => {
        const results = decompileRun.results ?? []
        const withClasses = results.filter(r => r.status === 'completed')
        const noClasses = results.filter(r => r.status === 'no_classes')
        const failedJars = results.filter(r => r.status === 'failed' || r.status === 'timed_out')
        return (
          <div className={`p-3 rounded-lg border text-sm ${
            decompileRun.status === 'failed' ? 'bg-red-50 border-red-200 text-red-700' :
            decompileRun.status === 'completed' ? 'bg-green-50 border-green-200 text-green-800' :
            'bg-blue-50 border-blue-200 text-blue-700'
          }`}>
            <div className="flex items-center gap-2">
              {(decompileRun.status === 'pending' || decompileRun.status === 'running') && (
                <svg className="animate-spin h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              )}
              <span className="font-medium">
                🧬 Decompile all jars — {decompileRun.jars_completed + decompileRun.jars_failed}/{decompileRun.jars_total} jars processed
                {failedJars.length > 0 && `, ${failedJars.length} failed`}
              </span>
              {decompileRun.status === 'completed' && withClasses.length > 0 && isOperator && (
                <button onClick={handleDownloadAllDecompiled}
                  className="ml-auto px-2.5 py-1 border border-green-300 bg-white rounded text-xs text-green-700 hover:bg-green-50">
                  ⬇ Download all decompiled source (zip)
                </button>
              )}
            </div>
            {failedJars.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {failedJars.map(r => (
                  <li key={r.sub_report_id} className="text-xs">
                    ✗ {r.filename} — {r.status}{r.error ? `: ${r.error}` : ''}
                  </li>
                ))}
              </ul>
            )}
            {noClasses.length > 0 && (
              <p className="mt-2 text-xs text-gray-500">
                ⓘ {noClasses.length} jar{noClasses.length !== 1 ? 's' : ''} had no Java classes to decompile
                (likely non-Java bundles — installer scripts, nginx/monitoring config, etc.): {noClasses.map(r => r.filename).join(', ')}
              </p>
            )}
          </div>
        )
      })()}

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {summaryCards.map(c => (
          <div key={c.label} className="bg-white border border-gray-200 rounded-lg p-4 text-center">
            <div className="text-2xl mb-1">{c.icon}</div>
            <div className="text-2xl font-bold text-gray-900">{c.value}</div>
            <div className="text-xs text-gray-500 mt-1">{c.label}</div>
          </div>
        ))}
      </div>

      {/* Scoped search */}
      {showSearch && (
        <div className="bg-white border border-blue-200 rounded-lg p-4">
          <SearchPanel
            reportId={reportId}
            onNavigate={(rId, subId, tab) => {
              setShowSearch(false)
              onNavigate(rId, subId, tab)
            }}
          />
        </div>
      )}

      {/* Feature flags */}
      <div className="flex flex-wrap gap-2">
        {summary.has_ssl_config && <span className="px-2 py-1 bg-blue-100 text-blue-700 rounded text-xs">🔐 SSL Config</span>}
        {summary.has_database_config && <span className="px-2 py-1 bg-purple-100 text-purple-700 rounded text-xs">🗄️ Database</span>}
        {summary.has_rabbitmq_config && <span className="px-2 py-1 bg-orange-100 text-orange-700 rounded text-xs">🐰 RabbitMQ</span>}
        {(summary.ports_detected ?? []).length > 0 && (
          <span className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs">
            Ports: {(summary.ports_detected as number[]).join(', ')}
          </span>
        )}
      </div>

      {/* Service index */}
      {subs && subs.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h2 className="text-sm font-semibold text-gray-700">Services ({subs.length})</h2>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Service</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Port</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Group</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-right font-medium text-gray-600">Size</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {subs.map((s: SubReportSummary) => (
                <tr key={s.sub_report_id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-900">
                    {s.service_name ?? s.filename}
                  </td>
                  <td className="px-4 py-2 text-gray-600 font-mono text-xs">
                    {s.declared_port ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{s.group_name ?? '—'}</td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{s.jar_type}</span>
                  </td>
                  <td className="px-4 py-2 text-right text-gray-400 text-xs">{fmtBytes(s.size_bytes)}</td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {!isOperator ? null : rowDecompileStatus[s.sub_report_id] === 'completed' ? (
                      <button onClick={() => handleDownloadOneDecompiled(s.sub_report_id, s.filename)}
                        title="Download decompiled source"
                        className="px-2 py-1 border border-green-300 bg-green-50 rounded text-xs text-green-700 hover:bg-green-100 mr-1">
                        ⬇
                      </button>
                    ) : rowDecompileStatus[s.sub_report_id] === 'no_classes' ? (
                      <span title="No Java classes found — likely a non-Java bundle (installer scripts, config, etc.), nothing to decompile"
                        className="inline-block px-2 py-1 border border-gray-200 bg-gray-50 rounded text-xs text-gray-400 mr-1 cursor-help">
                        ⓘ no code
                      </span>
                    ) : (
                      <button onClick={() => handleDecompileOne(s.sub_report_id)}
                        disabled={rowDecompileStatus[s.sub_report_id] === 'running'}
                        title={rowDecompileStatus[s.sub_report_id] === 'failed' ? 'Decompile failed — click to retry' : 'Decompile this jar'}
                        className={`px-2 py-1 border rounded text-xs mr-1 disabled:opacity-50 ${
                          rowDecompileStatus[s.sub_report_id] === 'failed'
                            ? 'border-red-300 bg-red-50 text-red-700 hover:bg-red-100'
                            : 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                        }`}>
                        {rowDecompileStatus[s.sub_report_id] === 'running' ? '⏳' : '🧬'}
                      </button>
                    )}
                    <button onClick={() => onSelectSub(s.sub_report_id)}
                      className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
                      View →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Errors — per-service persistence/extraction failures. The report can still
          be "completed" with partial results if at least one service succeeded. */}
      {report.errors?.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-red-800 mb-2">
            ✗ {report.errors.length} Service{report.errors.length !== 1 ? 's' : ''} Failed to Analyse or Persist
          </h3>
          <p className="text-xs text-red-600 mb-2">
            The rest of this report reflects only the services that succeeded — results below are partial.
          </p>
          <ul className="space-y-1">
            {report.errors.map((e: string, i: number) => (
              <li key={i} className="text-xs text-red-700 font-mono">{e}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Consistency Findings — static cross-checks between independently-extracted
          data (DTO fields vs DB columns, event payloads vs DTOs, service wiring).
          These are heuristic signals worth manually checking, not confirmed defects. */}
      {report.consistency_findings?.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-blue-800 mb-2">
            🔍 {report.consistency_findings.length} Consistency Finding{report.consistency_findings.length !== 1 ? 's' : ''}
          </h3>
          <p className="text-xs text-blue-600 mb-2">
            Static cross-checks between independently-extracted data (no live system was contacted) —
            worth manually checking, not confirmed defects.
          </p>
          <ul className="space-y-1.5 max-h-96 overflow-y-auto">
            {report.consistency_findings.slice(0, 50).map((f: any, i: number) => (
              <li key={i} className="text-xs text-blue-700 border-b border-blue-100 pb-1.5 last:border-0">
                <span className="font-mono text-blue-500">[{f.type}]</span>{' '}
                {f.note || JSON.stringify(f)}
              </li>
            ))}
          </ul>
          {report.consistency_findings.length > 50 && (
            <p className="text-xs text-blue-500 mt-2">
              +{report.consistency_findings.length - 50} more — export the full report for the complete list.
            </p>
          )}
        </div>
      )}

      {/* Infrastructure Requirements — static synthesis of what needs provisioning
          on the IAM/auth service, MySQL, and RabbitMQ, derived only from already-
          extracted evidence (roles/authorities, Flyway tables, connection config
          keys, event topology). Every requirement cites its evidence; each
          sub-section states explicitly what this tool cannot determine rather
          than guessing. */}
      {report.infra_requirements && (
        <div className="bg-teal-50 border border-teal-200 rounded-lg p-4 space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-teal-800 mb-1">🏗 Infrastructure Requirements</h3>
            <p className="text-xs text-teal-600">
              What this bundle needs provisioned on the IAM/auth service, MySQL, and RabbitMQ — derived
              only from static evidence already extracted elsewhere in this report. Each section states
              explicitly what this tool cannot determine, rather than guessing.
            </p>
          </div>

          <InfraRequirementsSubsection
            title="IAM / Auth Service"
            section={report.infra_requirements.iam}
            renderItem={(r: any, i: number) => (
              <li key={i} className="text-xs text-teal-800 border-b border-teal-100 pb-1 last:border-0">
                <span className="font-mono px-1 py-0.5 bg-teal-100 rounded mr-1">{r.kind}</span>
                <span className="font-semibold">{r.name}</span> — referenced by {r.reference_count} endpoint{r.reference_count !== 1 ? 's' : ''}
                {' '}across {r.services?.join(', ')}
              </li>
            )}
            extra={report.infra_requirements.iam?.connection && (
              <div className="text-xs text-teal-700 bg-white/60 rounded p-2 mb-2">
                {report.infra_requirements.iam.connection.auth_url ? (
                  <p>Auth URL: <span className="font-mono">{report.infra_requirements.iam.connection.auth_url}</span></p>
                ) : <p className="text-teal-500 italic">No auth-service connection URL found in config.</p>}
                {report.infra_requirements.iam.connection.project_name && (
                  <p>Project: <span className="font-mono">{report.infra_requirements.iam.connection.project_name}</span></p>
                )}
              </div>
            )}
          />

          <InfraRequirementsSubsection
            title="MySQL / Database"
            section={report.infra_requirements.database}
            renderItem={(r: any, i: number) => (
              <li key={i} className="text-xs text-teal-800 border-b border-teal-100 pb-1 last:border-0">
                <span className="font-semibold font-mono">{r.database_name}</span> — owned by {r.services?.join(', ')}
                {r.tables?.length > 0 && (
                  <span className="block text-teal-600 ml-2">tables: {r.tables.slice(0, 12).join(', ')}{r.tables.length > 12 ? ` +${r.tables.length - 12} more` : ''}</span>
                )}
              </li>
            )}
            extra={report.infra_requirements.database?.collisions?.length > 0 && (
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-2">
                {report.infra_requirements.database.collisions.map((c: any, i: number) => (
                  <p key={i}>⚠ {c.database_name}: {c.note} ({c.services.join(', ')})</p>
                ))}
              </div>
            )}
          />

          <InfraRequirementsSubsection
            title="RabbitMQ"
            section={report.infra_requirements.messaging}
            renderItem={(r: any, i: number) => (
              <li key={i} className="text-xs text-teal-800 border-b border-teal-100 pb-1 last:border-0">
                <span className="font-semibold">{r.service}</span> — {r.role}
                {r.virtual_host && <span className="font-mono ml-1">vhost={r.virtual_host}</span>}
                {r.address && <span className="font-mono ml-1">{r.address}</span>}
                {(r.exchanges?.length > 0 || r.queues?.length > 0) && (
                  <span className="block text-teal-600 ml-2">
                    {r.exchanges?.length > 0 && `exchanges: ${r.exchanges.join(', ')} `}
                    {r.queues?.length > 0 && `queues: ${r.queues.join(', ')}`}
                  </span>
                )}
              </li>
            )}
          />
        </div>
      )}

      {/* Actuator Exposure — a real, common production vulnerability class
          (unsecured /actuator/env or /actuator/heapdump leaking secrets),
          detected from management.endpoints.web.exposure.* config keys and
          cross-referenced with the Nginx proxy/port data already extracted.
          Custom Spring Security rules are not parsed — see known_gaps. */}
      {report.actuator_exposure?.services?.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 space-y-2">
          <h3 className="text-sm font-semibold text-red-800 mb-1">
            🔓 {report.actuator_exposure.services.length} Actuator Exposure Finding{report.actuator_exposure.services.length !== 1 ? 's' : ''}
          </h3>
          <p className="text-xs text-red-600 mb-2">
            Services where Spring Boot Actuator's config broadens exposure to sensitive management endpoints —
            worth manually checking, not a confirmed live vulnerability (no live system was contacted).
          </p>
          <ul className="space-y-1.5 max-h-96 overflow-y-auto">
            {report.actuator_exposure.services.map((s: any, i: number) => (
              <li key={i} className="text-xs border-b border-red-100 pb-1.5 last:border-0">
                <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-medium mr-1.5 ${
                  s.risk === 'high' ? 'bg-red-600 text-white' :
                  s.risk === 'medium' ? 'bg-amber-500 text-white' :
                  s.risk === 'low' ? 'bg-yellow-200 text-yellow-800' :
                  'bg-gray-200 text-gray-700'
                }`}>{s.risk}</span>
                <span className="font-semibold text-red-900">{s.service}</span>
                {s.note ? (
                  <span className="text-red-700"> — {s.note}</span>
                ) : (
                  <>
                    <span className="text-red-700"> exposes: </span>
                    <span className="font-mono text-red-800">{s.sensitive_endpoints_exposed?.join(', ')}</span>
                    {s.exposure_is_wildcard && <span className="text-red-500 italic"> (wildcard include=*)</span>}
                    <span className="block text-red-500 mt-0.5">
                      {s.same_port_as_app ? 'same port as main app' : `separate management port ${s.management_port}`}
                      {s.externally_proxied === true && ' · reachable via Nginx proxy'}
                      {s.externally_proxied === false && ' · not proxied'}
                    </span>
                  </>
                )}
              </li>
            ))}
          </ul>
          {report.actuator_exposure.known_gaps?.length > 0 && (
            <ul className="space-y-1 pt-1">
              {report.actuator_exposure.known_gaps.map((g: string, i: number) => (
                <li key={i} className="text-xs text-gray-500 italic">ⓘ {g}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Related Bugs — Improvements Plan Stage 12's automated cross-report
          bug pattern scan. Computed once, right after analysis, by scoring
          this report's own findings (consistency findings, actuator
          exposure, errors/warnings, purpose narratives) against the corpus
          of existing OPEN bugs using the same ranking as the Bug Tracker's
          duplicate-suggestion assist — surfaced here so a user doesn't have
          to go file a new bug to discover "this looks like a known issue." */}
      {report.related_bugs && report.related_bugs.length > 0 && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-purple-800 mb-1">
            🐛 {report.related_bugs.length} Related Bug{report.related_bugs.length !== 1 ? 's' : ''}
          </h3>
          <p className="text-xs text-purple-600 mb-2">
            Open bugs whose descriptions look related to what this analysis found — worth checking
            whether this upload is affected too, not a confirmed match.
          </p>
          <ul className="space-y-1.5">
            {report.related_bugs.map((b: { id: string; title: string; status: string; severity: string }) => (
              <li key={b.id} className="text-xs border-b border-purple-100 pb-1.5 last:border-0">
                <button
                  onClick={() => onViewBug?.(b.id)}
                  className="text-left text-purple-800 hover:text-purple-950 hover:underline font-medium disabled:no-underline disabled:cursor-default"
                  disabled={!onViewBug}
                >
                  {b.title}
                </button>
                <span className={`ml-2 inline-block px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_BADGE[b.status] ?? 'bg-gray-200 text-gray-700'}`}>
                  {b.status}
                </span>
                <span className={`ml-1 inline-block px-1.5 py-0.5 rounded text-xs font-medium ${SEVERITY_BADGE[b.severity] ?? 'bg-gray-200 text-gray-700'}`}>
                  {b.severity}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Warnings */}
      {report.warnings?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">⚠ Analysis Warnings</h3>
          <ul className="space-y-1">
            {report.warnings.map((w: string, i: number) => (
              <li key={i} className="text-xs text-amber-700">{w}</li>
            ))}
          </ul>
        </div>
      )}
      </> }
    </div>
  )
}

function InfraRequirementsSubsection({
  title, section, renderItem, extra,
}: {
  title: string
  section: { requirements: any[]; known_gaps: string[] } | undefined
  renderItem: (r: any, i: number) => React.ReactNode
  extra?: React.ReactNode
}) {
  if (!section) return null
  return (
    <div>
      <h4 className="text-xs font-semibold text-teal-900 uppercase tracking-wide mb-1">{title}</h4>
      {extra}
      {section.requirements.length > 0 ? (
        <ul className="space-y-1 max-h-48 overflow-y-auto mb-2">
          {section.requirements.map(renderItem)}
        </ul>
      ) : (
        <p className="text-xs text-teal-500 italic mb-2">No requirements derivable for this section.</p>
      )}
      {section.known_gaps?.length > 0 && (
        <ul className="space-y-1">
          {section.known_gaps.map((g, i) => (
            <li key={i} className="text-xs text-gray-500 italic">ⓘ {g}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
