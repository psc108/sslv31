import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  onSelectService: (service: string, reportId?: string) => void
  onViewRun: (runId: string, service: string) => void
  onBack: () => void
  reportId?: string
}

function fmtDate(s: string | null) {
  if (!s) return '—'
  return new Date(s).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
}

const SERVICE_ICON: Record<string, string> = { mysql: '🗄', rabbitmq: '📨', keystone: '🔑' }

export default function InfraDiagnosticsLandingPage({ onSelectService, onViewRun, onBack, reportId }: Props) {
  const { data: services = [], isLoading: loadingServices } = useQuery<any[]>({
    queryKey: ['infra-services'],
    queryFn: () => api.get('/infra-diagnostics/services').then(r => r.data),
  })

  const { data: runsData } = useQuery<any>({
    queryKey: ['infra-runs-recent'],
    queryFn: () => api.get('/infra-diagnostics/runs', { params: { page_size: 5 } }).then(r => r.data),
  })

  const recentRuns: any[] = runsData?.items ?? []

  const severityColour = (n: number, sev: string) => {
    if (n === 0) return 'text-gray-400'
    return sev === 'critical' ? 'text-red-600 font-semibold' : sev === 'high' ? 'text-orange-600 font-semibold' : 'text-amber-600'
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-1">← Back to JAR Analyser</button>
          <h2 className="text-xl font-bold text-gray-900">🔧 Infrastructure Diagnostics</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Collect diagnostic evidence from infrastructure components to investigate service failures.
          </p>
        </div>
      </div>

      {reportId && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
          ℹ Using JAR report context — parameter prompts will be pre-filled from the report's configuration.
        </div>
      )}

      {/* Service cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {loadingServices && <p className="text-sm text-gray-400 col-span-3">Loading services…</p>}
        {services.map((svc: any) => (
          <div key={svc.id} className="bg-white border border-gray-200 rounded-lg p-5 flex flex-col gap-3">
            <div>
              <div className="text-2xl mb-1">{SERVICE_ICON[svc.id] ?? '🔧'}</div>
              <h3 className="text-base font-semibold text-gray-900">{svc.display_name}</h3>
              <p className="text-xs text-gray-500 mt-1">{svc.description}</p>
            </div>
            <div className="text-xs text-gray-400">{svc.question_count} questions · {svc.section_count} sections</div>
            <button
              onClick={() => onSelectService(svc.id, reportId)}
              className="mt-auto px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700"
            >
              Start →
            </button>
          </div>
        ))}
      </div>

      {/* Recent runs */}
      {recentRuns.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
            <h3 className="text-sm font-semibold text-gray-700">Recent Runs</h3>
          </div>
          <ul className="divide-y divide-gray-100">
            {recentRuns.map((r: any) => {
              const s = r.summary ?? {}
              return (
                <li key={r.run_id} className="px-4 py-3 flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-lg shrink-0">{SERVICE_ICON[r.service] ?? '🔧'}</span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">{r.label || r.service}</p>
                      <p className="text-xs text-gray-400">{fmtDate(r.created_at)}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <div className="flex gap-2 text-xs">
                      {s.critical > 0 && <span className={severityColour(s.critical, 'critical')}>🔴 {s.critical}</span>}
                      {s.high > 0 && <span className={severityColour(s.high, 'high')}>🟠 {s.high}</span>}
                      {s.total_findings === 0 && <span className="text-green-600">✓ No findings</span>}
                    </div>
                    <button
                      onClick={() => onViewRun(r.run_id, r.service)}
                      className="px-3 py-1 border border-gray-300 rounded text-xs text-gray-600 hover:bg-gray-50"
                    >
                      View
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}
