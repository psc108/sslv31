import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { MlAnalysis } from './types'
const ML_SEVERITY_COLOUR: Record<string, string> = {
  critical: 'bg-red-100 text-red-700',
  warning:  'bg-amber-100 text-amber-700',
  normal:   'bg-gray-100 text-gray-600',
}

function MlAnalysisPanel({ ml }: { ml: MlAnalysis }) {
  const [open, setOpen] = useState(ml.degraded || ml.anomalous_windows > 0)
  const badge = ml.degraded
    ? <span className="px-2 py-0.5 text-xs font-semibold rounded bg-amber-100 text-amber-700 border border-amber-200">🧠 ML — partial</span>
    : ml.anomalous_windows > 0
      ? <span className="px-2 py-0.5 text-xs font-semibold rounded bg-purple-100 text-purple-700 border border-purple-200">🧠 ML — {ml.anomalous_windows} anomal{ml.anomalous_windows === 1 ? 'y' : 'ies'} detected</span>
      : <span className="px-2 py-0.5 text-xs font-semibold rounded bg-green-100 text-green-700 border border-green-200">🧠 ML — no anomalies</span>
  return (
    <div className="border-2 border-purple-300 rounded-lg bg-white overflow-hidden">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-3 px-4 py-3 text-left bg-purple-50 hover:bg-purple-100">
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
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">⚠ {ml.degradation_reason || 'Partial analysis'}</p>
          )}
          {ml.top_anomalies.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1.5">Top Anomalous Windows</p>
              <div className="space-y-1.5">
                {ml.top_anomalies.map((a, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <span className={`shrink-0 px-1.5 py-0.5 rounded font-medium ${ML_SEVERITY_COLOUR[a.severity] ?? 'bg-gray-100 text-gray-600'}`}>{a.severity}</span>
                    <span className="font-mono text-gray-500 shrink-0">score {a.score.toFixed(3)}</span>
                    {a.top_features.length > 0 && <span className="text-gray-600 truncate">{a.top_features.slice(0, 3).join(', ')}</span>}
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
                    {ci.matched_frames.length > 0 && <p className="font-mono text-gray-400 mt-0.5 truncate">{ci.matched_frames[0]}</p>}
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

interface Props {
  reportId: string
  onBack: () => void
  onManualCollection?: () => void
}

function fmtBytes(b: number) {
  if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleString()
}

const STATUS_COLOUR: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  analysing: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
}

export default function DiagnosticsRunPage({ reportId, onBack, onManualCollection }: Props) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [pollingRunId, setPollingRunId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const { data: runs = [], isLoading } = useQuery<any[]>({
    queryKey: ['diag-runs', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/diagnostics`).then(r => r.data),
  })

  const { data: runDetail } = useQuery<any>({
    queryKey: ['diag-run', reportId, selectedRunId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/diagnostics/${selectedRunId}`).then(r => r.data),
    enabled: !!selectedRunId,
  })

  // Poll until the selected/latest run completes
  useEffect(() => {
    if (!pollingRunId) return
    pollRef.current = setInterval(async () => {
      try {
        const r = await api.get(`/jar-analyser/reports/${reportId}/diagnostics/${pollingRunId}`)
        if (r.data.status === 'completed' || r.data.status === 'failed') {
          clearInterval(pollRef.current!)
          setPollingRunId(null)
          await queryClient.invalidateQueries({ queryKey: ['diag-runs', reportId] })
          await queryClient.invalidateQueries({ queryKey: ['diag-run', reportId, pollingRunId] })
        }
      } catch {
        clearInterval(pollRef.current!)
        setPollingRunId(null)
      }
    }, 2500)
    return () => clearInterval(pollRef.current!)
  }, [pollingRunId, reportId, queryClient])

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post(`/jar-analyser/reports/${reportId}/diagnostics`, fd)
    },
    onSuccess: (res) => {
      const runId = res.data.run_id
      setSelectedRunId(runId)
      setPollingRunId(runId)
      setUploadFile(null)
      queryClient.invalidateQueries({ queryKey: ['diag-runs', reportId] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (runId: string) => api.delete(`/jar-analyser/reports/${reportId}/diagnostics/${runId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diag-runs', reportId] })
      if (selectedRunId) setSelectedRunId(null)
    },
  })

  const handleDownloadScript = () => {
    api.get(`/jar-analyser/reports/${reportId}/diagnostic-script`, { responseType: 'blob' }).then(res => {
      const cd = res.headers['content-disposition'] || ''
      const match = cd.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : 'diag-collect.sh'
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  const detail = runDetail ?? runs.find(r => r.run_id === selectedRunId)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-1">← Back to Report</button>
          <h2 className="text-xl font-bold text-gray-900">🩺 Diagnostic Runs</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            <button onClick={handleDownloadScript} className="text-blue-600 hover:underline">Download the collection script</button>, run it on the target server, then upload the resulting tar.gz for analysis.
          </p>
        </div>
        <div className="flex gap-2">
          {onManualCollection && (
            <button
              onClick={onManualCollection}
              className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 flex items-center gap-2"
            >
              📋 Can't upload a bundle?
            </button>
          )}
          <button
            onClick={handleDownloadScript}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 flex items-center gap-2"
          >
            ⬇ Download Collection Script
          </button>
        </div>
      </div>

      {/* Prerequisites */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-700">📦 Script Prerequisites</h3>
            <p className="text-xs text-gray-500 mt-0.5">Install these packages on the target server before running the collection script.</p>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-gray-100">
          {([
            {
              os: 'RHEL / CentOS 8+', icon: '🎩', cmd: 'dnf install',
              packages: [
                { pkg: 'openssl',           reason: 'PEM/CRT cert inspection' },
                { pkg: 'java-17-openjdk',   reason: 'keytool (JKS/P12) + java -version' },
                { pkg: 'nmap-ncat',         reason: 'nc — port connectivity checks' },
                { pkg: 'curl',              reason: 'RabbitMQ management API' },
                { pkg: 'iproute',           reason: 'ss — listening port list' },
              ],
            },
            {
              os: 'Ubuntu / Debian', icon: '🐧', cmd: 'apt-get install',
              packages: [
                { pkg: 'openssl',           reason: 'PEM/CRT cert inspection' },
                { pkg: 'default-jdk',       reason: 'keytool (JKS/P12) + java -version' },
                { pkg: 'netcat-openbsd',    reason: 'nc — port connectivity checks' },
                { pkg: 'curl',              reason: 'RabbitMQ management API' },
                { pkg: 'iproute2',          reason: 'ss — listening port list' },
              ],
            },
            {
              os: 'Amazon Linux 2023', icon: '☁️', cmd: 'dnf install',
              packages: [
                { pkg: 'openssl',                    reason: 'PEM/CRT cert inspection' },
                { pkg: 'java-17-amazon-corretto',    reason: 'keytool (JKS/P12) + java -version' },
                { pkg: 'nmap-ncat',                  reason: 'nc — port connectivity checks' },
                { pkg: 'curl',                       reason: 'RabbitMQ management API' },
                { pkg: 'iproute',                    reason: 'ss — listening port list' },
              ],
            },
            {
              os: 'Alpine Linux', icon: '🏔️', cmd: 'apk add',
              packages: [
                { pkg: 'openssl',           reason: 'PEM/CRT cert inspection' },
                { pkg: 'openjdk17',         reason: 'keytool (JKS/P12) + java -version' },
                { pkg: 'netcat-openbsd',    reason: 'nc — port connectivity checks' },
                { pkg: 'curl',              reason: 'RabbitMQ management API' },
                { pkg: 'iproute2',          reason: 'ss — listening port list' },
              ],
            },
          ] as { os: string; icon: string; cmd: string; packages: { pkg: string; reason: string }[] }[]).map(({ os, icon, cmd, packages }) => (
            <div key={os} className="p-4">
              <p className="text-sm font-semibold text-gray-800">{icon} {os}</p>
              <p className="text-xs font-mono text-indigo-400 mb-3">{cmd}</p>
              <ul className="space-y-2">
                {packages.map(({ pkg, reason }) => (
                  <li key={pkg} className="flex flex-col gap-0.5">
                    <span className="font-mono text-xs text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded w-fit">{pkg}</span>
                    <span className="text-xs text-gray-500">{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="px-4 py-2.5 border-t border-gray-100 bg-gray-50 text-xs text-gray-500">
          <span className="font-mono">tar</span> and <span className="font-mono">gzip</span> are required for packaging and are pre-installed on all listed distros.
          {' '}If <span className="font-mono">nc</span> is unavailable the script falls back to bash TCP redirection.
          {' '}<span className="font-mono">journalctl</span> requires systemd — journal collection is skipped gracefully on non-systemd hosts.
        </div>
      </div>

      {/* Upload panel */}
      <div className="bg-white border border-gray-200 rounded-lg p-5">
        <h3 className="font-semibold text-gray-900 mb-3">Upload Diagnostic Bundle</h3>
        <div className="flex items-center gap-4">
          <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
            {uploadFile ? uploadFile.name : 'Choose .tar.gz bundle…'}
            <input type="file" className="hidden" accept=".tar.gz,.gz"
              onChange={e => setUploadFile(e.target.files?.[0] || null)} />
          </label>
          {uploadFile && (
            <span className="text-xs text-gray-500">{fmtBytes(uploadFile.size)}</span>
          )}
          <button
            onClick={() => uploadFile && uploadMutation.mutate(uploadFile)}
            disabled={!uploadFile || uploadMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {uploadMutation.isPending ? 'Uploading…' : 'Upload & Analyse'}
          </button>
        </div>
        {uploadMutation.isError && (
          <p className="text-red-600 text-sm mt-2">
            {(uploadMutation.error as any)?.response?.data?.detail || 'Upload failed'}
          </p>
        )}
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Run list */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="text-sm font-semibold text-gray-700">Runs ({runs.length})</h3>
          </div>
          {isLoading && <p className="text-sm text-gray-400 p-4">Loading…</p>}
          {!isLoading && runs.length === 0 && (
            <p className="text-sm text-gray-400 p-4">No runs yet.</p>
          )}
          <ul className="divide-y divide-gray-100">
            {runs.map(r => (
              <li key={r.run_id}
                onClick={() => setSelectedRunId(r.run_id)}
                className={`px-4 py-3 cursor-pointer hover:bg-gray-50 ${selectedRunId === r.run_id ? 'bg-blue-50' : ''}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-mono text-gray-500 truncate">
                    {r.bundle_filename === '[manual-questionnaire]'
                      ? <span className="text-purple-600">📋 Manual collection</span>
                      : r.bundle_filename}
                  </span>
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium shrink-0 ${STATUS_COLOUR[r.status] ?? 'bg-gray-100 text-gray-600'}`}>
                    {r.status}
                  </span>
                </div>
                <div className="text-xs text-gray-400 mt-0.5">{fmtDate(r.uploaded_at)}</div>
                {r.hostname && <div className="text-xs text-gray-500 mt-0.5">🖥 {r.hostname}</div>}
              </li>
            ))}
          </ul>
        </div>

        {/* Run detail */}
        <div className="col-span-2 space-y-4">
          {!selectedRunId && (
            <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-sm text-gray-400">
              Select a run to view results
            </div>
          )}

          {selectedRunId && detail && (
            <>
              {/* Status / meta */}
              <div className="bg-white border border-gray-200 rounded-lg p-5">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLOUR[detail.status] ?? 'bg-gray-100 text-gray-600'}`}>
                        {detail.status}
                      </span>
                      {detail.status === 'analysing' && (
                        <svg className="animate-spin h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                      )}
                    </div>
                    <p className="text-sm text-gray-700 font-medium">{detail.bundle_filename}</p>
                    <div className="flex flex-wrap gap-4 text-xs text-gray-500">
                      {detail.hostname && <span>🖥 {detail.hostname}</span>}
                      {detail.os_id && <span>🐧 {detail.os_id}</span>}
                      {detail.platform_version && <span>📦 v{detail.platform_version}</span>}
                      <span>📁 {fmtBytes(detail.bundle_size_bytes)}</span>
                      <span>🕐 {fmtDate(detail.uploaded_at)}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => deleteMutation.mutate(detail.run_id)}
                    disabled={deleteMutation.isPending}
                    className="text-xs text-red-500 hover:text-red-700 disabled:opacity-40"
                  >
                    Delete
                  </button>
                </div>
                {detail.error && (
                  <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                    ✗ {detail.error}
                  </div>
                )}
              </div>

              {detail.status === 'completed' && detail.summary && (
                <>
                  {/* Limited collection warning */}
                  {detail.summary.limited_collection && (
                    <div className="p-4 bg-amber-50 border border-amber-300 rounded-lg">
                      <p className="text-sm font-semibold text-amber-800">⚠ Limited collection — some tools were missing on the target server</p>
                      <p className="text-sm text-amber-700 mt-1">
                        The following tools were not available: {' '}
                        {(detail.summary.missing_tools as string[]).map(t => (
                          <span key={t} className="font-mono text-xs bg-amber-100 px-1.5 py-0.5 rounded mr-1">{t}</span>
                        ))}
                      </p>
                      <p className="text-xs text-amber-600 mt-1.5">
                        Certificate inspection, JVM cacerts, journal logs, and/or port checks may be incomplete or absent.
                        Install the missing packages (see the prerequisites panel above) and re-run the collection script for a full report.
                      </p>
                    </div>
                  )}
                  {/* Summary cards */}
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { label: 'Cert Issues', value: detail.summary.cert_issues ?? 0, icon: '🔐', colour: detail.summary.cert_issues > 0 ? 'text-red-600' : 'text-green-600' },
                      { label: 'Port Checks', value: detail.summary.port_checks ?? 0, icon: '🔌', colour: 'text-gray-900' },
                      { label: 'Log Findings', value: detail.summary.log_findings ?? 0, icon: '📋', colour: detail.summary.log_findings > 0 ? 'text-amber-600' : 'text-green-600' },
                      { label: 'Config Issues', value: detail.summary.config_issues ?? 0, icon: '⚙️', colour: detail.summary.config_issues > 0 ? 'text-amber-600' : 'text-green-600' },
                    ].map(c => (
                      <div key={c.label} className="bg-white border border-gray-200 rounded-lg p-4 text-center">
                        <div className="text-xl mb-1">{c.icon}</div>
                        <div className={`text-2xl font-bold ${c.colour}`}>{c.value}</div>
                        <div className="text-xs text-gray-500 mt-1">{c.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* OS info */}
                  {detail.os_info && (
                    <details className="bg-white border border-gray-200 rounded-lg">
                      <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-gray-700 hover:bg-gray-50">
                        🖥 OS / Environment Info
                      </summary>
                      <pre className="px-4 pb-4 text-xs font-mono text-gray-600 whitespace-pre-wrap overflow-x-auto">{detail.os_info}</pre>
                    </details>
                  )}

                  {/* Cert results */}
                  {detail.cert_results?.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h3 className="text-sm font-semibold text-gray-700">🔐 Certificate Analysis ({detail.cert_results.length})</h3>
                      </div>
                      <div className="divide-y divide-gray-100">
                        {detail.cert_results.map((c: any, i: number) => (
                          <div key={i} className="px-4 py-3">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-medium text-gray-900">{c.path}</p>
                                {c.subject && <p className="text-xs text-gray-500 mt-0.5">Subject: {c.subject}</p>}
                                {c.expiry && (
                                  <p className={`text-xs mt-0.5 ${c.expired ? 'text-red-600 font-medium' : c.days_remaining < 30 ? 'text-amber-600' : 'text-green-600'}`}>
                                    Expires: {c.expiry} {c.expired ? '(EXPIRED)' : c.days_remaining != null ? `(${c.days_remaining}d)` : ''}
                                  </p>
                                )}
                              </div>
                              {c.error && <span className="text-xs text-red-500 shrink-0">{c.error}</span>}
                            </div>
                            {c.issues?.length > 0 && (
                              <ul className="mt-2 space-y-1">
                                {c.issues.map((iss: string, j: number) => (
                                  <li key={j} className="text-xs text-amber-700 flex gap-1.5">⚠ {iss}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Port results */}
                  {detail.port_results?.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h3 className="text-sm font-semibold text-gray-700">🔌 Port Checks ({detail.port_results.length})</h3>
                      </div>
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 border-b border-gray-100">
                          <tr>
                            <th className="px-4 py-2 text-left font-medium text-gray-600">Service</th>
                            <th className="px-4 py-2 text-left font-medium text-gray-600">Port</th>
                            <th className="px-4 py-2 text-left font-medium text-gray-600">Status</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {detail.port_results.map((p: any, i: number) => (
                            <tr key={i}>
                              <td className="px-4 py-2 text-gray-700">{p.service ?? '—'}</td>
                              <td className="px-4 py-2 font-mono text-xs text-gray-600">{p.port}</td>
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

                  {/* RabbitMQ summary */}
                  {detail.rmq_summary && Object.keys(detail.rmq_summary).length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg p-4">
                      <h3 className="text-sm font-semibold text-gray-700 mb-2">🐰 RabbitMQ</h3>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        {Object.entries(detail.rmq_summary).map(([k, v]) => (
                          <div key={k}><span className="text-gray-500">{k}:</span> <span className="text-gray-800">{String(v)}</span></div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* ML Analysis */}
                  {(() => {
                    const lf = detail.log_findings
                    const ml = Array.isArray(lf) ? null : lf?.ml
                    const findings = Array.isArray(lf) ? lf : (lf?.rule_based ?? [])
                    return (
                      <>
                        {ml && (
                          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                              <h3 className="text-sm font-semibold text-gray-700">🧠 ML Analysis</h3>
                            </div>
                            <div className="p-4">
                              <MlAnalysisPanel ml={ml} />
                            </div>
                          </div>
                        )}
                        {findings.length > 0 && (
                          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                              <h3 className="text-sm font-semibold text-gray-700">📋 Log Findings ({findings.length})</h3>
                            </div>
                            <div className="divide-y divide-gray-100 max-h-72 overflow-y-auto">
                              {findings.map((f: any, i: number) => (
                                <div key={i} className="px-4 py-3">
                                  <div className="flex items-start gap-2">
                                    <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${
                                      f.severity === 'critical' ? 'bg-red-100 text-red-700' :
                                      f.severity === 'high' ? 'bg-orange-100 text-orange-700' :
                                      'bg-amber-100 text-amber-700'
                                    }`}>{f.severity ?? 'warn'}</span>
                                    <div>
                                      <p className="text-sm font-medium text-gray-900">{f.title ?? f.kb_id}</p>
                                      {f.service && <p className="text-xs text-gray-500">{f.service}</p>}
                                      {f.line && <p className="text-xs font-mono text-gray-400 mt-0.5 truncate max-w-lg">{f.line}</p>}
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )
                  })()}

                  {/* Config issues */}
                  {detail.config_issues?.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h3 className="text-sm font-semibold text-gray-700">⚙️ Config Issues ({detail.config_issues.length})</h3>
                      </div>
                      <div className="divide-y divide-gray-100">
                        {detail.config_issues.map((c: any, i: number) => (
                          <div key={i} className="px-4 py-3 text-sm">
                            <p className="font-medium text-gray-900">{c.service ?? '—'} — {c.file ?? ''}</p>
                            <p className="text-gray-600 mt-0.5">{c.issue}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* All findings */}
                  {detail.findings?.length > 0 && (
                    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
                      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
                        <h3 className="text-sm font-semibold text-gray-700">📌 All Findings ({detail.findings.length})</h3>
                      </div>
                      <div className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
                        {detail.findings.map((f: any, i: number) => (
                          <div key={i} className={`px-4 py-3 flex items-start gap-3 ${
                            f.severity === 'critical' ? 'bg-red-50' :
                            f.severity === 'high' ? 'bg-orange-50' :
                            f.severity === 'medium' ? 'bg-amber-50' : ''
                          }`}>
                            <span className={`shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${
                              f.severity === 'critical' ? 'bg-red-100 text-red-700' :
                              f.severity === 'high' ? 'bg-orange-100 text-orange-700' :
                              f.severity === 'medium' ? 'bg-amber-100 text-amber-700' :
                              'bg-gray-100 text-gray-600'
                            }`}>{f.severity ?? 'info'}</span>
                            <div>
                              <p className="text-sm font-medium text-gray-900">{f.title}</p>
                              {f.detail && <p className="text-xs text-gray-600 mt-0.5">{f.detail}</p>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
