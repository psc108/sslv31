import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

export interface OutboundIntegration {
  id: string
  kind: 'feign_client' | 'config_value'
  class_name: string
  target: string
  config_key: string | null
  raw_value: string | null
  resolved_value: string | null
  service_name?: string
}

export interface OutboundCallSite {
  id: string
  engine: string
  class_name: string
  method_name: string | null
  call_type: 'jaxrs_client' | 'resttemplate' | 'webclient'
  call_snippet: string
  response_type: string | null
  caught_exceptions: string[]
  thrown_exceptions: string[]
  status_checks: string[]
  service_name?: string
}

const KIND_META: Record<string, { icon: string; label: string; colour: string }> = {
  feign_client: { icon: '🔌', label: 'Feign Client', colour: 'bg-indigo-100 text-indigo-700' },
  config_value: { icon: '🔧', label: 'Config URL', colour: 'bg-teal-100 text-teal-700' },
}

const CALL_TYPE_LABEL: Record<string, string> = {
  jaxrs_client: 'JAX-RS Client',
  resttemplate: 'RestTemplate',
  webclient: 'WebClient',
}

function IntegrationRow({ item, showService }: { item: OutboundIntegration; showService?: boolean }) {
  const meta = KIND_META[item.kind] ?? KIND_META.config_value!
  return (
    <div className="px-4 py-2.5 border-b border-gray-50 last:border-b-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`px-1.5 py-0.5 rounded text-xs font-medium shrink-0 ${meta.colour}`}>
          {meta.icon} {meta.label}
        </span>
        <span className="text-sm font-semibold text-gray-800">{item.target}</span>
        {showService && item.service_name && (
          <span className="text-xs text-gray-400 ml-auto">{item.service_name}</span>
        )}
      </div>
      <p className="text-xs font-mono text-gray-400 truncate mt-0.5">{item.class_name}</p>
      {item.config_key && (
        <p className="text-xs text-gray-500 mt-0.5">
          <span className="font-mono">{item.config_key}</span>
          {item.resolved_value ? (
            <> → <span className="font-mono text-gray-700">{item.resolved_value}</span></>
          ) : (
            <span className="italic text-gray-400"> (not resolved in this bundle's own config — may be supplied externally)</span>
          )}
        </p>
      )}
      {!item.config_key && item.raw_value && (
        <p className="text-xs text-gray-500 mt-0.5 font-mono">{item.raw_value}</p>
      )}
    </div>
  )
}

function CallSiteRow({ item, showService }: { item: OutboundCallSite; showService?: boolean }) {
  return (
    <div className="px-4 py-2.5 border-b border-gray-50 last:border-b-0">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="px-1.5 py-0.5 rounded text-xs font-medium shrink-0 bg-sky-100 text-sky-700">
          📥 {CALL_TYPE_LABEL[item.call_type] ?? item.call_type}
        </span>
        <span className="text-sm font-semibold text-gray-800">
          {item.method_name ?? '(method not determined)'}
        </span>
        <span className="text-xs text-gray-400 font-mono">· {item.engine}</span>
        {showService && item.service_name && (
          <span className="text-xs text-gray-400 ml-auto">{item.service_name}</span>
        )}
      </div>
      <p className="text-xs font-mono text-gray-400 truncate mt-0.5">{item.class_name}</p>
      {item.response_type && (
        <p className="text-xs text-gray-600 mt-1">
          Expects back: <span className="font-mono text-gray-800">{item.response_type}</span>
        </p>
      )}
      {(item.status_checks.length > 0 || item.thrown_exceptions.length > 0 || item.caught_exceptions.length > 0) && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {item.status_checks.map((s, i) => (
            <span key={`s${i}`} className="text-xs px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded font-mono">status {s}</span>
          ))}
          {item.thrown_exceptions.map((e, i) => (
            <span key={`t${i}`} className="text-xs px-1.5 py-0.5 bg-red-50 text-red-700 rounded font-mono">throws {e}</span>
          ))}
          {item.caught_exceptions.map((e, i) => (
            <span key={`c${i}`} className="text-xs px-1.5 py-0.5 bg-orange-50 text-orange-700 rounded font-mono">catches {e}</span>
          ))}
        </div>
      )}
    </div>
  )
}

const CALL_SITE_CAVEAT = "Response type and error handling found by scanning already-decompiled source text for known call patterns (JAX-RS Client, RestTemplate, WebClient) — best-effort, not a real parser. Only appears for classes that have actually been decompiled (Section 36); nothing shows here until you run Decompile on this jar."

/** One service's own outbound integrations + (if decompiled) call-site
 * response-shape/error-handling signals — a sub-report tab. */
export function OutboundIntegrationsSubTab({ reportId, subReportId }: { reportId: string; subReportId: string }) {
  const { data, isLoading } = useQuery<OutboundIntegration[]>({
    queryKey: ['jar-outbound', reportId, subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/outbound-integrations`).then(r => r.data),
  })
  const { data: callSites, isLoading: callSitesLoading } = useQuery<OutboundCallSite[]>({
    queryKey: ['jar-outbound-call-sites', reportId, subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/outbound-call-sites`).then(r => r.data),
  })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Statically-discovered signals that this jar calls out to a system outside this bundle —
        Feign client declarations and @Value-injected config keys that look like a URL/host/endpoint.
        This is a heuristic, not proof a field is ever used to build an outbound call (that would need
        actually reading method bodies, which this tool never does automatically — see Section 37 of
        the Help guide).
      </p>
      {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
      {!isLoading && (data?.length ?? 0) === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">No outbound integration signals found for this jar.</p>
      )}
      {!!data?.length && (
        <div className="border border-gray-200 rounded-lg overflow-hidden">
          {data.map(item => <IntegrationRow key={item.id} item={item} />)}
        </div>
      )}

      {!!callSites?.length && (
        <>
          <p className="text-xs text-gray-500 pt-2">📥 Response Handling — {CALL_SITE_CAVEAT}</p>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            {callSites.map(item => <CallSiteRow key={item.id} item={item} />)}
          </div>
        </>
      )}
      {!callSitesLoading && !callSites?.length && (
        <p className="text-xs text-gray-400 italic pt-1">
          No response-handling signals yet — decompile this jar (🧬 Source tab) to see what it expects back and how it handles errors.
        </p>
      )}
    </div>
  )
}

/** Every service's outbound integrations + call-site signals across one
 * report — grouped by service, so "which of our services talk to which
 * external systems, and what do they expect back" is answerable in one
 * place for a jar-of-jars bundle. */
export default function OutboundIntegrationsTab({ reportId }: { reportId: string }) {
  const { data, isLoading } = useQuery<OutboundIntegration[]>({
    queryKey: ['jar-outbound-report', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/outbound-integrations`).then(r => r.data),
  })
  const { data: callSites } = useQuery<OutboundCallSite[]>({
    queryKey: ['jar-outbound-call-sites-report', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/outbound-call-sites`).then(r => r.data),
  })

  const byService: Record<string, OutboundIntegration[]> = {}
  for (const item of data ?? []) {
    const key = item.service_name || 'unknown'
    ;(byService[key] ??= []).push(item)
  }
  const callSitesByService: Record<string, OutboundCallSite[]> = {}
  for (const item of callSites ?? []) {
    const key = item.service_name || 'unknown'
    ;(callSitesByService[key] ??= []).push(item)
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Statically-discovered outbound integration signals across every service in this upload —
        Feign client declarations and @Value-injected URL/host/endpoint config keys. A heuristic, not
        proof of an actual runtime call — see each service's own Outbound tab, or Section 37 of the
        Help guide, for the full caveats.
      </p>
      {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}
      {!isLoading && (data?.length ?? 0) === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">No outbound integration signals found across this bundle.</p>
      )}
      {Object.entries(byService).map(([service, items]) => (
        <div key={service} className="border border-gray-200 rounded-lg overflow-hidden">
          <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center gap-2">
            <span className="text-xs font-semibold text-gray-700">{service}</span>
            <span className="ml-auto text-xs text-gray-400">{items.length} signal{items.length !== 1 ? 's' : ''}</span>
          </div>
          <div>
            {items.map(item => <IntegrationRow key={item.id} item={item} />)}
          </div>
        </div>
      ))}

      {!!callSites?.length && (
        <>
          <p className="text-xs text-gray-500 pt-2">📥 Response Handling — {CALL_SITE_CAVEAT}</p>
          {Object.entries(callSitesByService).map(([service, items]) => (
            <div key={service} className="border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-50 border-b border-gray-200 px-4 py-2 flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-700">{service}</span>
                <span className="ml-auto text-xs text-gray-400">{items.length} signal{items.length !== 1 ? 's' : ''}</span>
              </div>
              <div>
                {items.map(item => <CallSiteRow key={item.id} item={item} />)}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
