import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface HealthCheck {
  id: string
  environment_id: string
  host_role: string
  service_type: string
  check_type: string
  status: string
  details: { output?: string; error?: string; exit_code?: number }
  last_checked: string | null
}

interface DriftItem {
  type: string
  role: string
  severity: string
  message: string
}

interface DriftReport {
  environment_id: string
  environment_name: string
  template_version: number
  checked_at: string
  drift_count: number
  items: DriftItem[]
}

interface Environment {
  id: string
  name: string
  status: string
}

export default function BMHealthPage() {
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [selectedEnv, setSelectedEnv] = useState<string>('')
  const [checks, setChecks] = useState<HealthCheck[]>([])
  const [drift, setDrift] = useState<DriftReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)
  const [tab, setTab] = useState<'health' | 'drift'>('health')

  useEffect(() => {
    api.get('/build/environments').then(r => {
      const active = r.data.filter((e: Environment) => ['active', 'degraded'].includes(e.status))
      setEnvironments(active)
      if (active.length > 0) setSelectedEnv(active[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedEnv) return
    setLoading(true)
    Promise.all([
      api.get(`/build/environments/${selectedEnv}/health`).then(r => r.data).catch(() => []),
      api.get(`/build/environments/${selectedEnv}/drift`).then(r => r.data).catch(() => null),
    ]).then(([h, d]) => {
      setChecks(h)
      setDrift(d)
      setLoading(false)
    })
  }, [selectedEnv])

  const handleRunChecks = async () => {
    if (!selectedEnv) return
    setChecking(true)
    try {
      const res = await api.post(`/build/environments/${selectedEnv}/health-check`)
      setChecks(res.data.results || [])
      // Refresh drift too
      const d = await api.get(`/build/environments/${selectedEnv}/drift`).then(r => r.data).catch(() => null)
      setDrift(d)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Health check failed')
    }
    setChecking(false)
  }

  const statusIcon = (s: string) => {
    if (s === 'healthy') return '🟢'
    if (s === 'degraded') return '🟡'
    if (s === 'down') return '🔴'
    return '⚪'
  }

  const severityColor = (s: string) => {
    if (s === 'critical') return 'bg-red-100 text-red-800'
    if (s === 'high') return 'bg-red-50 text-red-700'
    if (s === 'warning') return 'bg-amber-50 text-amber-700'
    return 'bg-blue-50 text-blue-700'
  }

  // Group checks by host_role
  const grouped: Record<string, HealthCheck[]> = {}
  for (const c of checks) {
    if (!grouped[c.host_role]) grouped[c.host_role] = []
    grouped[c.host_role].push(c)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Health & Observability</h1>
        <button
          onClick={handleRunChecks}
          disabled={checking || !selectedEnv}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {checking ? 'Checking...' : 'Run Health Checks'}
        </button>
      </div>

      {/* Environment selector */}
      <div className="flex items-center gap-3">
        <label className="text-sm font-medium text-gray-700">Environment:</label>
        <select
          value={selectedEnv}
          onChange={e => setSelectedEnv(e.target.value)}
          className="border border-gray-300 rounded px-3 py-1.5 text-sm"
        >
          {environments.length === 0 && <option value="">No active environments</option>}
          {environments.map(e => (
            <option key={e.id} value={e.id}>{e.name} ({e.status})</option>
          ))}
        </select>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        <button
          onClick={() => setTab('health')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === 'health' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
        >
          Service Health ({checks.length})
        </button>
        <button
          onClick={() => setTab('drift')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === 'drift' ? 'border-orange-600 text-orange-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
        >
          Drift Report {drift && drift.drift_count > 0 && `(${drift.drift_count})`}
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : !selectedEnv ? (
        <p className="text-sm text-gray-500">No active environments to monitor.</p>
      ) : tab === 'health' ? (
        /* Health tab */
        checks.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
            <p className="text-gray-500">No health check results yet.</p>
            <p className="text-sm text-gray-400 mt-1">Click "Run Health Checks" to check all services.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {Object.entries(grouped).map(([role, roleChecks]) => (
              <div key={role} className="bg-white rounded-lg border border-gray-200">
                <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
                  <span className="font-semibold text-gray-800">{role}</span>
                  <span className="text-xs text-gray-400">{roleChecks.length} service{roleChecks.length > 1 ? 's' : ''}</span>
                </div>
                <div className="divide-y divide-gray-50">
                  {roleChecks.map(c => (
                    <div key={c.id} className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span>{statusIcon(c.status)}</span>
                        <span className="text-sm font-medium text-gray-800">{c.service_type}</span>
                        <span className={`text-xs px-2 py-0.5 rounded ${c.status === 'healthy' ? 'bg-green-50 text-green-700' : c.status === 'down' ? 'bg-red-50 text-red-700' : 'bg-gray-50 text-gray-600'}`}>
                          {c.status}
                        </span>
                        {c.last_checked && (
                          <span className="text-xs text-gray-400 ml-auto">
                            {new Date(c.last_checked).toLocaleString()}
                          </span>
                        )}
                      </div>
                      {c.details.output && c.status !== 'healthy' && (
                        <pre className="mt-2 text-xs text-gray-600 bg-gray-50 rounded p-2 overflow-x-auto">
                          {c.details.output}
                          {c.details.error && `\n${c.details.error}`}
                        </pre>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        /* Drift tab */
        !drift ? (
          <p className="text-sm text-gray-400">No drift data available.</p>
        ) : drift.drift_count === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
            <span className="text-4xl">✅</span>
            <p className="text-gray-700 mt-2 font-medium">No drift detected</p>
            <p className="text-sm text-gray-400 mt-1">Environment matches template spec (v{drift.template_version})</p>
          </div>
        ) : (
          <div className="space-y-2">
            {drift.items.map((item, i) => (
              <div key={i} className={`rounded-lg border p-3 ${item.severity === 'critical' ? 'border-red-200 bg-red-50' : item.severity === 'warning' ? 'border-amber-200 bg-amber-50' : 'border-blue-200 bg-blue-50'}`}>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${severityColor(item.severity)}`}>
                    {item.severity}
                  </span>
                  <span className="text-sm font-medium text-gray-800">{item.role}</span>
                  <span className="text-xs text-gray-500">{item.type.replace('_', ' ')}</span>
                </div>
                <p className="text-sm text-gray-700 mt-1">{item.message}</p>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  )
}
