import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatDate } from '@/lib/utils'
import type { AuditEvent, PaginatedResponse } from '@/lib/types'

const severityBadge = (severity: string) => {
  if (severity === 'WARNING') return <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">WARNING</span>
  return <span className="px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800">INFO</span>
}

export default function AuditLogViewer() {
  const [page, setPage] = useState(1)
  const [tab, setTab] = useState<'all' | 'downloads'>('all')
  const [eventTypeFilter, setEventTypeFilter] = useState('')
  const [subjectFilter, setSubjectFilter] = useState('')

  const downloadEventTypes = [
    'CERT_DOWNLOAD', 'KEY_DOWNLOAD', 'P12_DOWNLOAD', 'JKS_DOWNLOAD',
    'TRUSTSTORE_DOWNLOAD', 'CSR_DOWNLOAD', 'BACKUP_DOWNLOAD', 'CRL_DOWNLOAD',
  ]

  const { data, isLoading } = useQuery<PaginatedResponse<AuditEvent>>({
    queryKey: ['audit', page, tab, eventTypeFilter, subjectFilter],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: '50' })
      if (tab === 'downloads') {
        // Filter to download events only — use first type as filter (API supports single type)
        if (!eventTypeFilter) params.set('event_type', 'KEY_DOWNLOAD')
      }
      if (eventTypeFilter) params.set('event_type', eventTypeFilter)
      if (subjectFilter) params.set('subject_id', subjectFilter)
      return (await api.get(`/audit?${params}`)).data
    },
  })

  const events = data?.items || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / 50)

  const exportCSV = () => {
    const headers = ['Timestamp', 'Event Type', 'Severity', 'Subject', 'Source IP', 'Description']
    const rows = events.map(e => [
      e.timestamp, e.event_type, e.severity, e.subject_id || '', e.source_ip || '', e.description || ''
    ])
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Audit Log</h2>
          <p className="text-sm text-gray-500 mt-1">All system events and download activity</p>
        </div>
        <button onClick={exportCSV}
          className="px-4 py-2 border border-gray-300 text-sm font-medium rounded-md hover:bg-gray-50">
          Export CSV
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        <button onClick={() => { setTab('all'); setPage(1) }}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === 'all' ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}>
          All Events
        </button>
        <button onClick={() => { setTab('downloads'); setPage(1) }}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === 'downloads' ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}>
          Download Events
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select value={eventTypeFilter} onChange={e => { setEventTypeFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">All Event Types</option>
          <option value="CA_CREATED">CA Created</option>
          <option value="CERT_ISSUED">Cert Issued</option>
          <option value="CERT_REVOKED">Cert Revoked</option>
          <option value="KEY_DOWNLOAD">Key Download</option>
          <option value="P12_DOWNLOAD">P12 Download</option>
          <option value="CERT_DOWNLOAD">Cert Download</option>
          <option value="TRUSTSTORE_CREATED">TrustStore Created</option>
          <option value="BACKUP_DOWNLOAD">Backup Download</option>
        </select>
        <input type="text" value={subjectFilter}
          onChange={e => { setSubjectFilter(e.target.value); setPage(1) }}
          placeholder="Filter by serial / ID..."
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm" />
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Timestamp</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Event</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Severity</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Subject</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Source IP</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Description</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {!isLoading && events.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No events found</td></tr>
            )}
            {events.map(event => (
              <tr key={event.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                  {new Date(event.timestamp).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'medium' })}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-800">{event.event_type}</td>
                <td className="px-4 py-3">{severityBadge(event.severity)}</td>
                <td className="px-4 py-3 text-gray-600 font-mono text-xs">{event.subject_id || '—'}</td>
                <td className="px-4 py-3 text-gray-600 text-xs">{event.source_ip || '—'}</td>
                <td className="px-4 py-3 text-gray-600 text-xs truncate max-w-[200px]">{event.description || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-500">Page {page} of {totalPages}</p>
          <div className="flex gap-2">
            <button onClick={() => setPage(p => p - 1)} disabled={page <= 1}
              className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-30">← Prev</button>
            <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages}
              className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-30">Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
