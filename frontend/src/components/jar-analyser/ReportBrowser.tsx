import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { ReportListItem } from './types'
import SearchPanel from './SearchPanel'

interface Props {
  onSelect: (reportId: string) => void
  onUpload: () => void
  onCompare: (a: string, b: string) => void
  onNavigate: (reportId: string, subReportId: string, tab: string) => void
  onInfraDiagnostics?: () => void
}

export default function ReportBrowser({ onSelect, onUpload, onCompare, onNavigate, onInfraDiagnostics }: Props) {
  const [q, setQ] = useState('')
  const [jarType, setJarType] = useState('')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string[]>([])
  const [deleting, setDeleting] = useState<string | null>(null)
  const [showSearch, setShowSearch] = useState(false)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['jar-reports', q, jarType, page],
    queryFn: () =>
      api.get('/jar-analyser/reports', { params: { q: q || undefined, jar_type: jarType || undefined, page, page_size: 20 } })
        .then(r => r.data),
  })

  const toggleSelect = (id: string) => {
    setSelected(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : prev.length < 2 ? [...prev, id] : [prev[1]!, id]
    )
  }

  const handleDelete = async (reportId: string, filename: string) => {
    if (!confirm(`Delete report for "${filename}"? This cannot be undone.`)) return
    setDeleting(reportId)
    try {
      await api.delete(`/jar-analyser/reports/${reportId}`)
      setSelected(prev => prev.filter(x => x !== reportId))
      await queryClient.invalidateQueries({ queryKey: ['jar-reports'] })
    } finally {
      setDeleting(null)
    }
  }

  const fmtDate = (iso: string | null) => {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
  }

  const jarTypeLabel = (t: string) => {
    const map: Record<string, string> = {
      jar_of_jars: 'JAR-of-JARs', spring_boot_fat: 'Spring Boot Fat',
      spring_boot_war: 'Spring Boot WAR', library: 'Library', executable_jar: 'Executable',
    }
    return map[t] ?? t
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">JAR Analyser</h1>
        <div className="flex gap-2">
          <button onClick={() => setShowSearch(true)}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1.5">
            🔍 Search Reports
          </button>
          {onInfraDiagnostics && (
            <button onClick={onInfraDiagnostics}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1.5">
              🔧 Infrastructure Diagnostics
            </button>
          )}
          <button onClick={onUpload}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
            + Upload New JAR
          </button>
        </div>
      </div>

      <div className="flex gap-3">
        <input
          type="text" value={q} onChange={e => { setQ(e.target.value); setPage(1) }}
          placeholder="Search by filename, title, version..."
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
        />
        <select value={jarType} onChange={e => { setJarType(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">All Types</option>
          <option value="jar_of_jars">JAR-of-JARs</option>
          <option value="spring_boot_fat">Spring Boot Fat</option>
          <option value="library">Library</option>
        </select>
      </div>

      {selected.length === 2 && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-center justify-between">
          <span className="text-sm text-blue-800">2 reports selected for comparison</span>
          <button onClick={() => onCompare(selected[0]!, selected[1]!)}
            className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
            Compare Selected →
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="w-8 px-3 py-3"></th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Filename / Version</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Type</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">Services</th>
              <th className="px-4 py-3 text-right font-medium text-gray-600">Endpoints</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Uploaded</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Analysed</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {!isLoading && !data?.items?.length && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No reports yet. Upload a JAR to get started.</td></tr>
            )}
            {data?.items?.map((r: ReportListItem) => (
              <tr key={r.report_id}
                className="hover:bg-gray-50 cursor-pointer"
                onClick={() => onSelect(r.report_id)}>
                <td className="px-3 py-3" onClick={e => { e.stopPropagation(); toggleSelect(r.report_id) }}>
                  <input type="checkbox" checked={selected.includes(r.report_id)} readOnly
                    className="rounded border-gray-300" />
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900 truncate max-w-xs">{r.filename}</div>
                  <div className="flex gap-2 mt-0.5">
                    {r.implementation_version && (
                      <span className="text-xs text-blue-600 font-mono">v{r.implementation_version}</span>
                    )}
                    <span className="text-xs text-gray-400 font-mono">{r.report_id.slice(0, 8)}</span>
                    {r.label && <span className="text-xs text-gray-400">{r.label}</span>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs">
                    {jarTypeLabel(r.jar_type)}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-gray-600">{r.service_count}</td>
                <td className="px-4 py-3 text-right text-gray-600">{r.endpoint_count}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">{fmtDate(r.uploaded_at)}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">{fmtDate(r.analysis_completed_at)}</td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                  <button
                    onClick={() => handleDelete(r.report_id, r.filename)}
                    disabled={deleting === r.report_id}
                    className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded border border-red-200 disabled:opacity-40"
                  >
                    {deleting === r.report_id ? '…' : 'Delete'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>{data.total} reports</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">← Prev</button>
            <span className="px-3 py-1">{page} / {data.pages}</span>
            <button disabled={page >= data.pages} onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next →</button>
          </div>
        </div>
      )}

      {/* Global search modal */}
      {showSearch && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-16 px-4"
          onClick={() => setShowSearch(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[75vh] flex flex-col"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 pt-4 pb-2 border-b border-gray-200">
              <h2 className="text-sm font-semibold text-gray-700">Search All Reports</h2>
              <button onClick={() => setShowSearch(false)} className="text-gray-400 hover:text-gray-600 text-lg">×</button>
            </div>
            <div className="overflow-y-auto p-4">
              <SearchPanel
                onNavigate={(reportId, subReportId, tab) => {
                  setShowSearch(false)
                  onNavigate(reportId, subReportId, tab)
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
