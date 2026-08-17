import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { EventFile, DtoSchema, PublishedEvent, ConsumedEvent } from './types'
import SchemaViewer from './SchemaViewer'

interface Props {
  events: EventFile[]
  reportId: string
  subReportId: string
}

function PayloadSchema({ reportId, subReportId, payloadClass }: {
  reportId: string; subReportId: string; payloadClass: string
}) {
  const [open, setOpen] = useState(false)
  const { data: schema, isLoading } = useQuery<DtoSchema>({
    queryKey: ['schema', subReportId, payloadClass],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schemas/${encodeURIComponent(payloadClass)}`
    ).then(r => r.data),
    enabled: open,
    retry: false,
  })

  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
      >
        <span>{open ? '▼' : '▶'}</span>
        <span className="font-mono">{payloadClass.split('.').pop()}</span>
        <span className="text-gray-400">payload schema</span>
      </button>
      {open && (
        <div className="mt-2 ml-2">
          {isLoading && <p className="text-xs text-gray-400">Loading schema...</p>}
          {schema && <SchemaViewer schema={schema} inline />}
          {!isLoading && !schema && (
            <p className="text-xs text-gray-400 italic">Schema not available — re-analyse JAR to extract.</p>
          )}
        </div>
      )}
    </div>
  )
}

function RulesBadges({ rules }: { rules?: ConsumedEvent['rules'] | PublishedEvent['rules'] }) {
  if (!rules?.length) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {rules.map((r, i) => (
        <span key={i} className="text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded font-mono">
          {r.type} {r.attribute}{r.targetValue != null ? ` = ${r.targetValue}` : ''}
        </span>
      ))}
    </div>
  )
}

function ParamList({ params }: { params?: ConsumedEvent['parameters'] | PublishedEvent['parameters'] }) {
  if (!params?.length) return null
  return (
    <div className="mt-1 text-xs text-gray-500">
      Params: {params.map(p => p.name).join(', ')}
    </div>
  )
}

function PublishedCard({ p, reportId, subReportId }: {
  p: PublishedEvent; reportId: string; subReportId: string
}) {
  const consumers = p.consumers ?? []
  const consumerTypes = p.consumer_types ?? []
  const rules = p.rules ?? []
  const parameters = p.parameters ?? []
  const actions = p.actions ?? []
  return (
    <div className="px-3 py-2">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-0.5 text-xs flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono font-medium text-gray-800">{p.entity}</span>
            <span className="text-gray-400">/</span>
            <span className="font-mono text-gray-600">{actions.join(', ')}</span>
            {p.operation && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{p.operation}</span>
            )}
          </div>
          {consumers.length > 0 && (
            <div className="text-gray-500">
              Consumers: {consumers.map((c, i) => (
                <span key={i} className="font-mono">{c}{i < consumers.length - 1 ? ', ' : ''}</span>
              ))}
            </div>
          )}
          {consumerTypes.length > 0 && (
            <div className="text-gray-400">
              Handlers: {consumerTypes.filter(Boolean).join(', ')}
            </div>
          )}
          <RulesBadges rules={rules} />
          <ParamList params={parameters} />
        </div>
        {p.payload_class && (
          <span className="text-xs px-2 py-0.5 bg-green-50 text-green-700 border border-green-200 rounded font-mono shrink-0">
            {p.payload_class.split('.').pop()}
          </span>
        )}
      </div>
      {p.payload_class && (
        <PayloadSchema reportId={reportId} subReportId={subReportId} payloadClass={p.payload_class} />
      )}
    </div>
  )
}

function ConsumedCard({ c, reportId, subReportId }: {
  c: ConsumedEvent; reportId: string; subReportId: string
}) {
  const rules = c.rules ?? []
  const parameters = c.parameters ?? []
  return (
    <div className="px-3 py-2">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-0.5 text-xs flex-1">
          <div className="flex items-center gap-2">
            {c.source_service && (
              <span className="px-1.5 py-0.5 bg-blue-50 text-blue-600 border border-blue-200 rounded font-mono">
                {c.source_service}
              </span>
            )}
            <span className="font-mono font-medium text-gray-800">{c.entity}</span>
            <span className="text-gray-400">/</span>
            <span className="font-mono text-gray-600">{c.action}</span>
            {c.operation && (
              <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{c.operation}</span>
            )}
          </div>
          {c.handler && (
            <div className="text-gray-500">Handler: <span className="font-mono">{c.handler}</span></div>
          )}
          <RulesBadges rules={rules} />
          <ParamList params={parameters} />
        </div>
        {c.payload_class && (
          <span className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-200 rounded font-mono shrink-0">
            {c.payload_class.split('.').pop()}
          </span>
        )}
      </div>
      {c.payload_class && (
        <PayloadSchema reportId={reportId} subReportId={subReportId} payloadClass={c.payload_class} />
      )}
    </div>
  )
}

export default function EventViewer({ events, reportId, subReportId }: Props) {
  // Collect all consumed events across all files into a single flat list
  const allConsumed = events.flatMap(ev => ev.consumed)

  if (!events.length) return <p className="text-sm text-gray-400 py-4">No event definition files found.</p>

  return (
    <div className="space-y-6">
      {/* Published events — grouped by file */}
      {events.some(ev => ev.published.length > 0) && (
        <div>
          <p className="text-xs font-semibold text-green-700 mb-2">📤 Published Events</p>
          <div className="space-y-3">
            {events.filter(ev => ev.published.length > 0).map(ev => (
              <div key={ev.id} className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-200 flex items-center gap-2">
                  <span className="font-mono text-sm font-medium text-gray-800">{ev.filename}</span>
                  <span className="text-xs text-gray-400">{ev.path_in_jar}</span>
                </div>
                <div className="divide-y divide-gray-100">
                  {ev.published.map((p, i) => (
                    <PublishedCard key={i} p={p} reportId={reportId} subReportId={subReportId} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Consumed events — flat list grouped by source service */}
      {allConsumed.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-blue-700 mb-2">📥 Consumed Events</p>
          <div className="border border-gray-200 rounded-lg overflow-hidden divide-y divide-gray-100">
            {allConsumed.map((c, i) => (
              <ConsumedCard key={i} c={c} reportId={reportId} subReportId={subReportId} />
            ))}
          </div>
        </div>
      )}

      {events.every(ev => ev.published.length === 0) && allConsumed.length === 0 && (
        <p className="text-sm text-gray-400 py-4">No published or consumed events detected.</p>
      )}
    </div>
  )
}
