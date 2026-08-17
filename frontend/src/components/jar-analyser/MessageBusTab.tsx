import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Consumer {
  service: string
  handler: string | null
  payload_class: string | null
}

interface BusRow {
  publisher: string
  entity: string
  action: string
  event_key: string
  exchange: string | null
  routing_key: string | null
  operation: string | null
  payload_class: string | null
  payload_simple: string | null
  payload_sub_report_id: string | null
  consumers: Consumer[]
}

interface BusData {
  report_id: string
  total_events: number
  publishers: string[]
  consumers: string[]
  rows: BusRow[]
}

interface Props {
  reportId: string
}

export default function MessageBusTab({ reportId }: Props) {
  const [search, setSearch] = useState('')
  const [filterPublisher, setFilterPublisher] = useState('')
  const [filterConsumer, setFilterConsumer] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const { data, isLoading } = useQuery<BusData>({
    queryKey: ['message-bus', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/message-bus`).then(r => r.data),
  })

  if (isLoading) return <div className="text-sm text-gray-400 py-8 text-center">Loading message bus topology…</div>
  if (!data) return null

  const rows = data.rows.filter(r => {
    if (filterPublisher && r.publisher !== filterPublisher) return false
    if (filterConsumer && !r.consumers.some(c => c.service === filterConsumer)) return false
    if (search) {
      const q = search.toLowerCase()
      return r.event_key.toLowerCase().includes(q)
        || r.publisher.toLowerCase().includes(q)
        || r.consumers.some(c => c.service.toLowerCase().includes(q))
        || (r.payload_simple ?? '').toLowerCase().includes(q)
    }
    return true
  })

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="flex flex-wrap gap-3">
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-gray-900">{data.total_events}</div>
          <div className="text-xs text-gray-500 mt-0.5">Events</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-green-700">{data.publishers.length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Publishers</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg px-4 py-3 text-center min-w-[90px]">
          <div className="text-2xl font-bold text-blue-700">{data.consumers.length}</div>
          <div className="text-xs text-gray-500 mt-0.5">Consumers</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search events, services, payload…"
          className="border border-gray-300 rounded px-3 py-1.5 text-xs w-56"
        />
        <select
          value={filterPublisher} onChange={e => setFilterPublisher(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-xs"
        >
          <option value="">All publishers</option>
          {data.publishers.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select
          value={filterConsumer} onChange={e => setFilterConsumer(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1.5 text-xs"
        >
          <option value="">All consumers</option>
          {data.consumers.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        {(search || filterPublisher || filterConsumer) && (
          <button
            onClick={() => { setSearch(''); setFilterPublisher(''); setFilterConsumer('') }}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Clear
          </button>
        )}
        <span className="text-xs text-gray-400 ml-auto">{rows.length} event{rows.length !== 1 ? 's' : ''}</span>
      </div>

      {rows.length === 0 && (
        <p className="text-sm text-gray-400 py-6 text-center">
          {data.total_events === 0
            ? 'No event definitions found — re-analyse the JAR to extract event topology.'
            : 'No events match the current filters.'}
        </p>
      )}

      {/* Table */}
      {rows.length > 0 && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-600 w-36">Publisher</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Event</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600 w-32">Payload</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600">Consumers</th>
                <th className="px-4 py-2 text-left font-medium text-gray-600 w-24">Exchange</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map(row => {
                const key = `${row.publisher}/${row.event_key}`
                const isOpen = expanded === key
                return (
                  <>
                    <tr
                      key={key}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => setExpanded(isOpen ? null : key)}
                    >
                      <td className="px-4 py-2">
                        <span className="px-2 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded font-mono">
                          {row.publisher}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono font-medium text-gray-800">
                        <span className="text-gray-500">{row.entity}</span>
                        {row.action && <><span className="text-gray-400 mx-1">/</span><span className="text-gray-700">{row.action}</span></>}
                        {row.operation && (
                          <span className="ml-2 px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{row.operation}</span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        {row.payload_simple
                          ? <span className="font-mono text-purple-700">{row.payload_simple}</span>
                          : <span className="text-gray-300">—</span>}
                      </td>
                      <td className="px-4 py-2">
                        {row.consumers.length === 0
                          ? <span className="text-gray-300 italic">none detected</span>
                          : (
                            <div className="flex flex-wrap gap-1">
                              {row.consumers.map((c, i) => (
                                <span key={i} className="px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded font-mono">
                                  {c.service}
                                </span>
                              ))}
                            </div>
                          )}
                      </td>
                      <td className="px-4 py-2 font-mono text-gray-500 text-xs truncate max-w-[96px]" title={row.exchange ?? ''}>
                        {row.exchange ?? <span className="text-gray-300">—</span>}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr key={`${key}-detail`} className="bg-blue-50">
                        <td colSpan={5} className="px-6 py-3">
                          <RowDetail row={row} reportId={reportId} />
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RowDetail({ row, reportId }: { row: BusRow; reportId: string }) {
  return (
    <div className="space-y-3 text-xs">
      <div className="grid grid-cols-2 gap-x-8 gap-y-1">
        {row.exchange && <KV label="Exchange" value={row.exchange} />}
        {row.routing_key && <KV label="Routing key pattern" value={row.routing_key} />}
        {row.operation && <KV label="Entity operation" value={row.operation} />}
        {row.payload_class && <KV label="Payload class" value={row.payload_class} />}
      </div>

      {row.consumers.length > 0 && (
        <div>
          <p className="font-medium text-gray-700 mb-1">Consumers ({row.consumers.length})</p>
          <div className="space-y-1">
            {row.consumers.map((c, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded font-mono">{c.service}</span>
                {c.handler && <span className="text-gray-500">handler: <span className="font-mono">{c.handler}</span></span>}
                {c.payload_class && c.payload_class !== row.payload_class && (
                  <span className="text-gray-400 font-mono">{c.payload_class.split('.').pop()}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-gray-500 shrink-0 w-36">{label}:</span>
      <span className="font-mono text-gray-800 break-all">{value}</span>
    </div>
  )
}
