import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  runId: string
  service: string
  onBack: () => void
}

const SEV_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-gray-100 text-gray-600',
}

const SEV_ROW: Record<string, string> = {
  critical: 'bg-red-50',
  high: 'bg-orange-50',
  medium: 'bg-amber-50',
  low: '',
}

const SERVICE_ICON: Record<string, string> = { mysql: '🗄', rabbitmq: '📨', keystone: '🔑' }

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

export default function InfraRunPage({ runId, service, onBack }: Props) {
  const [expandedFindings, setExpandedFindings] = useState<Set<number>>(new Set())
  const [showResponses, setShowResponses] = useState(false)

  const { data: run, isLoading } = useQuery<any>({
    queryKey: ['infra-run', runId],
    queryFn: () => api.get(`/infra-diagnostics/runs/${runId}`).then(r => r.data),
  })

  const handleDownloadMarkdown = () => {
    api.get(`/infra-diagnostics/runs/${runId}/markdown`, { responseType: 'blob' }).then(res => {
      const cd = res.headers['content-disposition'] || ''
      const match = cd.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : `infra-diag-${service}-${runId.slice(0, 8)}.md`
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
    })
  }

  const toggleFinding = (i: number) => {
    setExpandedFindings(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  if (isLoading || !run) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading run…</div>
  }

  const s = run.summary ?? {}
  const findings: any[] = run.findings ?? []
  const portResults: any[] = run.port_results ?? []
  const certResults: any[] = run.cert_results ?? []
  const responses: Record<string, string> = run.responses ?? {}

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-1">← Back to Infrastructure Diagnostics</button>
          <h2 className="text-xl font-bold text-gray-900">
            {SERVICE_ICON[service] ?? '🔧'} {run.label || `${service} diagnostic run`}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">{fmtDate(run.created_at)} · run {runId.slice(0, 8)}</p>
        </div>
        <button
          onClick={handleDownloadMarkdown}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 shrink-0"
        >
          ⬇ Export Markdown
        </button>
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Critical', value: s.critical ?? 0, cls: s.critical > 0 ? 'text-red-600' : 'text-gray-400' },
          { label: 'High', value: s.high ?? 0, cls: s.high > 0 ? 'text-orange-600' : 'text-gray-400' },
          { label: 'Medium', value: s.medium ?? 0, cls: s.medium > 0 ? 'text-amber-600' : 'text-gray-400' },
          { label: 'Low', value: s.low ?? 0, cls: 'text-gray-500' },
        ].map(c => (
          <div key={c.label} className="bg-white border border-gray-200 rounded-lg p-4 text-center">
            <div className={`text-2xl font-bold ${c.cls}`}>{c.value}</div>
            <div className="text-xs text-gray-500 mt-1">{c.label}</div>
          </div>
        ))}
      </div>

      {s.missing_required_count > 0 && (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
          ⚠ {s.missing_required_count} required item(s) were not submitted — some checks may be incomplete.
        </div>
      )}

      {/* Findings */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-700">
            📌 Findings ({findings.length})
            {findings.length === 0 && <span className="ml-2 text-green-600 font-normal">— no issues found</span>}
          </h3>
        </div>
        {findings.length === 0 ? (
          <p className="px-4 py-6 text-sm text-gray-400 text-center">✓ No findings for this run.</p>
        ) : (
          <div className="divide-y divide-gray-100">
            {findings.map((f: any, i: number) => {
              const expanded = expandedFindings.has(i)
              const hasCauses = f.causes?.length > 0
              const hasSteps = f.fix_steps?.length > 0
              const expandable = hasCauses || hasSteps || f.trigger_line
              return (
                <div key={i} className={`px-4 py-3 ${SEV_ROW[f.severity] ?? ''}`}>
                  <div
                    className={`flex items-start gap-3 ${expandable ? 'cursor-pointer' : ''}`}
                    onClick={() => expandable && toggleFinding(i)}
                  >
                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${SEV_BADGE[f.severity] ?? 'bg-gray-100 text-gray-600'}`}>
                      {f.severity}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900">{f.message}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        {f.category} · <span className="font-mono">{f.item_id}</span>
                        {f.source === 'cross_reference' && (
                          <span className="ml-2 px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs">cross-reference</span>
                        )}
                      </p>
                    </div>
                    {expandable && (
                      <span className="text-gray-400 text-xs shrink-0">{expanded ? '▲' : '▼'}</span>
                    )}
                  </div>

                  {expanded && (
                    <div className="mt-3 ml-16 space-y-2">
                      {f.trigger_line && (
                        <p className="text-xs font-mono text-gray-500 bg-gray-100 px-2 py-1 rounded truncate">
                          {f.trigger_line}
                        </p>
                      )}
                      {hasCauses && (
                        <div>
                          <p className="text-xs font-semibold text-gray-600 mb-1">Causes</p>
                          <ul className="space-y-0.5">
                            {f.causes.map((c: string, j: number) => (
                              <li key={j} className="text-xs text-gray-600 flex gap-1.5">⚠ {c}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {hasSteps && (
                        <div>
                          <p className="text-xs font-semibold text-gray-600 mb-1">Fix steps</p>
                          <ol className="space-y-0.5 list-decimal list-inside">
                            {f.fix_steps.map((step: string, j: number) => (
                              <li key={j} className="text-xs text-gray-600">{step}</li>
                            ))}
                          </ol>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Port results */}
      {portResults.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="text-sm font-semibold text-gray-700">🔌 Port Checks ({portResults.length})</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Item</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Port</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {portResults.map((p: any, i: number) => (
                <tr key={i}>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">{p.item_id}</td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-700">{p.port}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${p.open ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {p.open ? 'open' : 'closed'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Cert results */}
      {certResults.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="text-sm font-semibold text-gray-700">🔐 Certificate Analysis ({certResults.length})</h3>
          </div>
          <div className="divide-y divide-gray-100">
            {certResults.map((c: any, i: number) => (
              <div key={i} className="px-4 py-3">
                <p className="text-sm font-medium text-gray-900 font-mono">{c.item_id}</p>
                {c.subject && <p className="text-xs text-gray-500 mt-0.5">Subject: {c.subject}</p>}
                {c.expiry && (
                  <p className={`text-xs mt-0.5 ${c.expired ? 'text-red-600 font-medium' : (c.days_remaining ?? 999) < 30 ? 'text-amber-600' : 'text-green-600'}`}>
                    Expires: {c.expiry}
                    {c.expired ? ' (EXPIRED)' : c.days_remaining != null ? ` (${c.days_remaining}d)` : ''}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Submitted responses accordion */}
      {Object.keys(responses).length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setShowResponses(v => !v)}
            className="w-full px-4 py-3 flex items-center justify-between text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            <span>📋 Submitted Responses ({Object.keys(responses).length})</span>
            <span className="text-gray-400">{showResponses ? '▲' : '▼'}</span>
          </button>
          {showResponses && (
            <div className="divide-y divide-gray-100 border-t border-gray-200">
              {Object.entries(responses).map(([itemId, output]) => (
                <div key={itemId} className="px-4 py-3">
                  <p className="text-xs font-mono text-gray-500 mb-1">{itemId}</p>
                  {output?.trim() ? (
                    <pre className="text-xs font-mono text-gray-700 bg-gray-50 rounded px-3 py-2 overflow-x-auto whitespace-pre-wrap max-h-40">
                      {output.trim()}
                    </pre>
                  ) : (
                    <p className="text-xs text-gray-400 italic">no output submitted</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* AI summary slot — reserved for future AI agent integration */}
      <div data-slot="ai-summary" className="hidden" />
    </div>
  )
}
