import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '@/lib/api'

interface DashboardStats {
  environments: { total: number; active: number; pending: number; failed: number; degraded: number }
  certificates: { active: number; expiring_soon: number }
  products: number
  recent_jobs: { id: string; name: string; status: string; created_at: string | null; finished_at: string | null }[]
}

export default function BMDashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [counts, setCounts] = useState({ hosts: 0, templates: 0 })

  useEffect(() => {
    api.get('/build/dashboard-stats').then(r => setStats(r.data)).catch(() => {})
    Promise.all([
      api.get('/build/hosts').then(r => r.data.length).catch(() => 0),
      api.get('/build/templates').then(r => r.data.length).catch(() => 0),
    ]).then(([hosts, templates]) => setCounts({ hosts, templates }))
  }, [])

  const statusColor = (s: string) => {
    if (s === 'completed') return 'text-green-700 bg-green-50'
    if (s === 'failed') return 'text-red-700 bg-red-50'
    if (s === 'running') return 'text-blue-700 bg-blue-50'
    return 'text-gray-600 bg-gray-50'
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Build Manager</h1>

      {/* Top cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Link to="/inventory" className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Hosts</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{counts.hosts}</p>
            </div>
            <span className="text-3xl">🖥️</span>
          </div>
        </Link>
        <Link to="/bm-templates" className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Templates</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{counts.templates}</p>
            </div>
            <span className="text-3xl">📐</span>
          </div>
        </Link>
        <Link to="/environments" className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Environments</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{stats?.environments.total ?? 0}</p>
            </div>
            <span className="text-3xl">🌍</span>
          </div>
        </Link>
        <Link to="/bm-catalogue" className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Products</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{stats?.products ?? 0}</p>
            </div>
            <span className="text-3xl">📦</span>
          </div>
        </Link>
      </div>

      {/* Environment status + Cert warnings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Environment breakdown */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Environment Status</h2>
            <Link to="/bm-health" className="text-xs text-blue-600 hover:text-blue-800">Health →</Link>
          </div>
          {stats ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-green-500"></span>
                <span className="text-sm text-gray-600">Active</span>
                <span className="ml-auto font-semibold">{stats.environments.active}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-yellow-500"></span>
                <span className="text-sm text-gray-600">Pending</span>
                <span className="ml-auto font-semibold">{stats.environments.pending}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500"></span>
                <span className="text-sm text-gray-600">Failed</span>
                <span className="ml-auto font-semibold">{stats.environments.failed}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-orange-500"></span>
                <span className="text-sm text-gray-600">Degraded</span>
                <span className="ml-auto font-semibold">{stats.environments.degraded}</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Loading...</p>
          )}
        </div>

        {/* Certificate health */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Certificate Health</h2>
            <Link to="/bm-certs" className="text-xs text-blue-600 hover:text-blue-800">Manage →</Link>
          </div>
          {stats ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Active Certs</span>
                <span className="font-semibold text-green-700">{stats.certificates.active}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Expiring (&lt;30 days)</span>
                <span className={`font-semibold ${stats.certificates.expiring_soon > 0 ? 'text-amber-600' : 'text-green-700'}`}>
                  {stats.certificates.expiring_soon}
                </span>
              </div>
              {stats.certificates.expiring_soon > 0 && (
                <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
                  ⚠️ {stats.certificates.expiring_soon} certificate{stats.certificates.expiring_soon > 1 ? 's' : ''} expiring within 30 days. Consider rebuilding affected environments.
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">Loading...</p>
          )}
        </div>
      </div>

      {/* Recent jobs */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Recent Jobs</h2>
          <Link to="/jobs" className="text-xs text-blue-600 hover:text-blue-800">View all →</Link>
        </div>
        {stats?.recent_jobs.length ? (
          <div className="space-y-2">
            {stats.recent_jobs.map(job => (
              <Link key={job.id} to="/jobs" className="flex items-center justify-between py-2 px-3 rounded hover:bg-gray-50">
                <div className="flex items-center gap-3">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${statusColor(job.status)}`}>
                    {job.status}
                  </span>
                  <span className="text-sm text-gray-800 truncate max-w-xs">{job.name}</span>
                </div>
                <span className="text-xs text-gray-400">
                  {job.created_at ? new Date(job.created_at).toLocaleString() : ''}
                </span>
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No jobs yet</p>
        )}
      </div>
    </div>
  )
}
