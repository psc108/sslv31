import { useState, useEffect, useRef, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import CodeViewer from '@/components/CodeViewer'
import { useAuth } from '@/lib/auth'
import type { DecompiledClassSummary, DecompiledClassSource, DecompileRun, DecompiledClassFacts } from './types'

interface Props {
  reportId: string
  subReportId: string
}

/** CFR prepends a "Could not load the following classes:" comment when a
 * decompiled class references types whose bytecode wasn't inside the one
 * jar CFR was given (framework/vendor dependencies nested in BOOT-INF/lib,
 * or shared internal libraries packaged separately) — not a decompile
 * failure, just an unresolvable cross-jar reference. Parsed here so the UI
 * can explain it inline rather than leave it as a mystery code comment. */
function parseUnresolvedClasses(source: string | null): string[] {
  if (!source) return []
  const marker = 'Could not load the following classes:'
  const idx = source.indexOf(marker)
  if (idx === -1) return []
  // Skip to the end of the marker's own line — slicing right after the
  // marker text picks up its empty line-remainder as a first "line", which
  // trips the empty-line break below before ever reaching a class name.
  const afterMarkerLine = source.indexOf('\n', idx + marker.length)
  if (afterMarkerLine === -1) return []
  const classes: string[] = []
  for (const line of source.slice(afterMarkerLine + 1).split('\n')) {
    const trimmed = line.replace(/^\s*\*\s?/, '').trim()
    if (!trimmed || trimmed.startsWith('*/')) break
    if (/^[\w.$]+$/.test(trimmed)) classes.push(trimmed)
    else break
  }
  return classes
}

const STATUS_COLOUR: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  timed_out: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-200 text-gray-600',
}

export default function DecompileTab({ reportId, subReportId }: Props) {
  // Decompiled source (and triggering a decompile) is admin/operator only —
  // the backend enforces this too, this just avoids readonly/auditor users
  // hitting a 403 on click. The class list and structural facts stay open
  // to all 4 roles, unaffected.
  const { isOperator } = useAuth()
  const [timeoutSeconds, setTimeoutSeconds] = useState(120)
  const [pollingRunId, setPollingRunId] = useState<string | null>(null)
  const [selectedClass, setSelectedClass] = useState<string | null>(null)
  const [selectedEngine, setSelectedEngine] = useState<'cfr' | 'vineflower'>('cfr')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const queryClient = useQueryClient()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: runs = [] } = useQuery<DecompileRun[]>({
    queryKey: ['decompile-runs', reportId, subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompile-runs`).then(r => r.data),
  })
  const latestRun = runs[0]

  const { data: classData, isLoading: classesLoading } = useQuery<{ items: DecompiledClassSummary[]; total: number }>({
    queryKey: ['decompiled-classes', reportId, subReportId, search],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompiled-classes`, {
      params: { page_size: 1000, search: search || undefined },
    }).then(r => r.data),
  })
  const classes = classData?.items ?? []

  const { data: source, isLoading: sourceLoading } = useQuery<DecompiledClassSource>({
    queryKey: ['decompiled-class-source', reportId, subReportId, selectedClass, selectedEngine],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompiled-classes/${encodeURIComponent(selectedClass!)}`,
      { params: { engine: selectedEngine } }
    ).then(r => r.data),
    enabled: !!selectedClass && isOperator,
  })

  // Cross-references this class against facts already extracted elsewhere
  // in the report (endpoints, scheduled jobs, DTO schema, error handlers) —
  // no new analysis, just surfacing existing data inline with the source.
  const { data: facts } = useQuery<DecompiledClassFacts>({
    queryKey: ['decompiled-class-facts', reportId, subReportId, selectedClass],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompiled-classes/${encodeURIComponent(selectedClass!)}/facts`
    ).then(r => r.data),
    enabled: !!selectedClass,
  })

  useEffect(() => {
    if (!pollingRunId) return
    pollRef.current = setInterval(async () => {
      try {
        const r = await api.get(`/jar-analyser/reports/${reportId}/decompile-runs/${pollingRunId}`)
        if (r.data.status === 'completed' || r.data.status === 'failed') {
          clearInterval(pollRef.current!)
          setPollingRunId(null)
          await queryClient.invalidateQueries({ queryKey: ['decompile-runs', reportId, subReportId] })
          await queryClient.invalidateQueries({ queryKey: ['decompiled-classes', reportId, subReportId] })
        }
      } catch {
        clearInterval(pollRef.current!)
        setPollingRunId(null)
      }
    }, 2500)
    return () => clearInterval(pollRef.current!)
  }, [pollingRunId, reportId, subReportId, queryClient])

  const decompileMutation = useMutation({
    mutationFn: () => api.post(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompile`, { timeout_seconds: timeoutSeconds }),
    onSuccess: (res) => {
      setPollingRunId(res.data.run_id)
      queryClient.invalidateQueries({ queryKey: ['decompile-runs', reportId, subReportId] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => api.post(`/jar-analyser/reports/${reportId}/decompile-runs/${latestRun!.run_id}/cancel`),
    onSuccess: () => {
      if (pollRef.current) clearInterval(pollRef.current)
      setPollingRunId(null)
      queryClient.invalidateQueries({ queryKey: ['decompile-runs', reportId, subReportId] })
    },
  })

  const handleDownload = () => {
    api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/decompile/export`, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'decompiled-source.zip'
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  const grouped = useMemo(() => {
    const map: Record<string, DecompiledClassSummary[]> = {}
    for (const c of classes) {
      const pkg = c.package_name || '(default package)'
      if (!map[pkg]) map[pkg] = []
      map[pkg].push(c)
    }
    return Object.entries(map).sort((a, b) => a[0].localeCompare(b[0]))
  }, [classes])

  const isRunning = pollingRunId != null || latestRun?.status === 'pending' || latestRun?.status === 'running'
  const hasClasses = classes.length > 0

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3 flex-wrap">
        <label className="text-xs text-gray-600 flex items-center gap-1.5">
          Timeout
          <input
            type="number" min={1} max={900} value={timeoutSeconds}
            onChange={e => setTimeoutSeconds(Math.min(900, Math.max(1, Number(e.target.value) || 120)))}
            className="w-20 border border-gray-300 rounded px-2 py-1 text-xs"
          />
          seconds
        </label>
        {isOperator ? (
          <button
            onClick={() => decompileMutation.mutate()}
            disabled={isRunning}
            className="px-3 py-1.5 border border-indigo-300 bg-indigo-50 rounded text-sm text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
          >
            {isRunning ? '⏳ Decompiling…' : latestRun ? '🧬 Re-decompile this jar' : '🧬 Decompile this jar'}
          </button>
        ) : (
          <span className="text-xs text-gray-400" title="Decompiling requires the admin or operator role">
            🔒 Decompile (admin/operator only)
          </span>
        )}
        {isRunning && isOperator && latestRun && (
          <button
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
            className="px-2.5 py-1.5 border border-red-300 bg-red-50 rounded text-xs text-red-700 hover:bg-red-100 disabled:opacity-50"
          >
            {cancelMutation.isPending ? '…' : '✕ Cancel'}
          </button>
        )}
        {hasClasses && isOperator && (
          <button
            onClick={handleDownload}
            className="px-3 py-1.5 border border-green-300 bg-green-50 rounded text-sm text-green-700 hover:bg-green-100"
          >
            ⬇ Download source (zip)
          </button>
        )}
        {latestRun && (
          <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOUR[isRunning ? 'running' : latestRun.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {isRunning ? 'running' : latestRun.status}
          </span>
        )}
      </div>

      {latestRun?.status === 'failed' && !isRunning && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          ✗ {latestRun.error ?? latestRun.results?.[0]?.error ?? 'Decompile failed'}
        </div>
      )}

      {!classesLoading && !hasClasses && !isRunning && latestRun?.status === 'completed' && (
        <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-sm text-gray-500">
          ⓘ No Java classes found in this jar — likely a non-Java bundle (installer scripts, nginx/monitoring
          config, etc.), so there's nothing to decompile here.
        </div>
      )}

      {!classesLoading && !hasClasses && !isRunning && !latestRun && (
        <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-sm text-gray-400">
          No decompiled source yet — click "Decompile this jar" above. This reconstructs real, readable
          Java from every class in the jar via CFR — not just the structural facts (annotations, endpoints,
          schemas) shown elsewhere in this report.
        </div>
      )}

      {hasClasses && (
        <div className="grid grid-cols-3 gap-4">
          {/* Package/class tree */}
          <div className="col-span-1 bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-3 py-2 border-b border-gray-200 bg-gray-50">
              <input
                type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search classes…"
                className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
              />
            </div>
            <div className="max-h-[65vh] overflow-y-auto">
              {grouped.map(([pkg, items]) => (
                <div key={pkg}>
                  <button
                    onClick={() => setExpanded(e => ({ ...e, [pkg]: !e[pkg] }))}
                    className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-gray-50 text-xs text-left"
                  >
                    <span className="font-mono text-gray-600 truncate">{pkg}</span>
                    <span className="flex items-center gap-1 shrink-0 text-gray-400">
                      {items.length}
                      <span>{expanded[pkg] ? '▲' : '▼'}</span>
                    </span>
                  </button>
                  {expanded[pkg] && (
                    <div className="pb-1">
                      {items.map(c => (
                        <button
                          key={c.class_name}
                          onClick={() => setSelectedClass(c.class_name)}
                          className={`w-full text-left px-5 py-1 text-xs font-mono truncate ${
                            selectedClass === c.class_name ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-50'
                          }`}
                        >
                          {c.simple_name}.java
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Source viewer */}
          <div className="col-span-2 bg-white border border-gray-200 rounded-lg overflow-hidden" style={{ minHeight: '65vh' }}>
            {!selectedClass && (
              <div className="flex items-center justify-center h-full text-sm text-gray-400 py-16">
                Select a class on the left to view its decompiled source
              </div>
            )}
            {selectedClass && !isOperator && (
              <div className="flex items-center justify-center h-full text-sm text-gray-400 py-16 text-center px-8">
                🔒 Viewing decompiled source requires the admin or operator role.
              </div>
            )}
            {selectedClass && isOperator && sourceLoading && (
              <div className="flex items-center justify-center h-full text-sm text-gray-400 py-16">Loading…</div>
            )}
            {selectedClass && isOperator && source && (() => {
              const unresolved = parseUnresolvedClasses(source.source)
              const factCount = facts
                ? facts.endpoints.length + facts.scheduled_jobs.length + (facts.dto_schema ? 1 : 0) + facts.error_handlers.length
                : 0
              const bannerCount = (unresolved.length > 0 ? 1 : 0) + (factCount > 0 ? 1 : 0)
              const codeHeight = bannerCount === 2 ? '50vh' : bannerCount === 1 ? '56vh' : '63vh'
              return (
                <div className="h-full flex flex-col">
                  <div className="px-3 py-2 border-b border-gray-200 bg-gray-50 text-xs font-mono text-gray-600 flex items-center justify-between gap-2">
                    <span className="truncate">{source.class_name}.java</span>
                    <div className="flex items-center gap-1 shrink-0 font-sans">
                      {(['cfr', 'vineflower'] as const).map(eng => {
                        const available = source.available_engines.includes(eng)
                        const active = source.engine === eng
                        return (
                          <button
                            key={eng}
                            onClick={() => available && setSelectedEngine(eng)}
                            disabled={!available}
                            title={available ? undefined : `${eng === 'cfr' ? 'CFR' : 'Vineflower'} didn't produce output for this class`}
                            className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                              active
                                ? 'bg-indigo-100 border-indigo-300 text-indigo-700'
                                : available
                                  ? 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                                  : 'bg-gray-50 border-gray-200 text-gray-300 cursor-not-allowed'
                            }`}
                          >
                            {eng === 'cfr' ? 'CFR' : 'Vineflower'}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {facts && factCount > 0 && (
                    <details className="px-3 py-2 bg-blue-50 border-b border-blue-200 text-xs text-blue-800">
                      <summary className="cursor-pointer font-medium">
                        📎 Also referenced elsewhere in this report: {[
                          facts.endpoints.length > 0 && `${facts.endpoints.length} endpoint${facts.endpoints.length !== 1 ? 's' : ''}`,
                          facts.scheduled_jobs.length > 0 && `${facts.scheduled_jobs.length} scheduled job${facts.scheduled_jobs.length !== 1 ? 's' : ''}`,
                          facts.dto_schema && 'a DTO schema',
                          facts.error_handlers.length > 0 && `${facts.error_handlers.length} error handler${facts.error_handlers.length !== 1 ? 's' : ''}`,
                        ].filter(Boolean).join(', ')}
                      </summary>
                      <p className="mt-1.5 text-blue-700">
                        Facts already extracted elsewhere in this report via static bytecode analysis — not new,
                        not AI-generated, just surfaced here for context. See the corresponding tab for full detail.
                      </p>
                      {facts.endpoints.length > 0 && (
                        <ul className="mt-1.5 font-mono space-y-0.5">
                          {facts.endpoints.map(e => (
                            <li key={e.id}><span className="font-semibold">{e.http_method}</span> {e.full_path}</li>
                          ))}
                        </ul>
                      )}
                      {facts.scheduled_jobs.length > 0 && (
                        <ul className="mt-1.5 font-mono space-y-0.5">
                          {facts.scheduled_jobs.map(j => (
                            <li key={j.id}>{j.method_name} — {j.display}</li>
                          ))}
                        </ul>
                      )}
                      {facts.dto_schema && (
                        <p className="mt-1.5 font-mono">
                          {facts.dto_schema.simple_name} — {facts.dto_schema.is_enum
                            ? 'enum'
                            : `${facts.dto_schema.fields.length} field${facts.dto_schema.fields.length !== 1 ? 's' : ''}`}
                        </p>
                      )}
                      {facts.error_handlers.length > 0 && (
                        <ul className="mt-1.5 font-mono space-y-0.5">
                          {facts.error_handlers.map(e => (
                            <li key={e.id}>{e.http_status ?? '?'} — {e.exception_class ?? 'unknown exception'}</li>
                          ))}
                        </ul>
                      )}
                    </details>
                  )}
                  {unresolved.length > 0 && (
                    <details className="px-3 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800">
                      <summary className="cursor-pointer font-medium">
                        ⓘ {unresolved.length} referenced type{unresolved.length !== 1 ? 's' : ''} couldn't be fully resolved — not a decompile failure
                      </summary>
                      <p className="mt-1.5 text-amber-700">
                        This class references types whose bytecode isn't inside this jar — usually a framework/vendor
                        dependency bundled separately (e.g. Spring's own classes live in their own nested jar) or a
                        shared internal library packaged elsewhere. The code below is still accurate; these specific
                        references are rendered by best-effort inference rather than confirmed against their real signature.
                      </p>
                      <ul className="mt-1.5 font-mono space-y-0.5">
                        {unresolved.map(c => <li key={c}>{c}</li>)}
                      </ul>
                    </details>
                  )}
                  <div style={{ height: codeHeight }}>
                    <CodeViewer content={source.source ?? ''} format="java" readOnly />
                  </div>
                </div>
              )
            })()}
          </div>
        </div>
      )}
    </div>
  )
}
