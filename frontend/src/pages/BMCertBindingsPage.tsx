import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '@/lib/api'

interface CertBinding {
  id: string
  environment_id: string
  environment_name: string | null
  cert_serial: string
  role: string
  cert_type: string
  host_id: string | null
  cert_path: string
  key_path: string
  ca_path: string
  expires_at: string | null
  auto_renew: boolean
  last_renewed_at: string | null
  renewal_count: number
  created_at: string | null
}

export default function BMCertBindingsPage() {
  const [bindings, setBindings] = useState<CertBinding[]>([])
  const [expiring, setExpiring] = useState<CertBinding[]>([])
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [tab, setTab] = useState<'all' | 'expiring'>('all')

  const load = () => {
    setLoading(true)
    Promise.all([
      api.get('/build/certs/bindings').then(r => r.data).catch(() => []),
      api.get('/build/certs/expiring?days=30').then(r => r.data).catch(() => []),
    ]).then(([all, exp]) => {
      setBindings(all)
      setExpiring(exp)
      setLoading(false)
    })
  }

  useEffect(() => { load() }, [])

  const handleRenew = async (id: string) => {
    setActionLoading(id)
    try {
      await api.post(`/build/certs/bindings/${id}/renew`)
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Renewal failed')
    }
    setActionLoading(null)
  }

  const handleRotate = async (id: string) => {
    if (!confirm('Rotate generates a new key pair. Continue?')) return
    setActionLoading(id)
    try {
      await api.post(`/build/certs/bindings/${id}/rotate`)
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Rotation failed')
    }
    setActionLoading(null)
  }

  const handleToggleAutoRenew = async (id: string, current: boolean) => {
    try {
      await api.patch(`/build/certs/bindings/${id}/auto-renew?enabled=${!current}`)
      load()
    } catch {}
  }

  const handleBulkRenew = async () => {
    setActionLoading('bulk')
    try {
      const res = await api.post('/build/certs/auto-renew-check?threshold_days=30')
      alert(`Renewed ${res.data.renewed_count} certificate(s)`)
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Bulk renewal failed')
    }
    setActionLoading(null)
  }

  const daysUntilExpiry = (expiresAt: string | null) => {
    if (!expiresAt) return null
    const diff = (new Date(expiresAt).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
    return Math.round(diff)
  }

  const expiryBadge = (expiresAt: string | null) => {
    const days = daysUntilExpiry(expiresAt)
    if (days === null) return <span className="text-xs text-gray-400">Unknown</span>
    if (days <= 0) return <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 font-medium">Expired</span>
    if (days <= 7) return <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 font-medium">{days}d</span>
    if (days <= 30) return <span className="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">{days}d</span>
    return <span className="text-xs px-2 py-0.5 rounded bg-green-100 text-green-700 font-medium">{days}d</span>
  }

  const displayed = tab === 'expiring' ? expiring : bindings

  // Group by environment
  const grouped: Record<string, CertBinding[]> = {}
  for (const b of displayed) {
    const key = b.environment_name || b.environment_id
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(b)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Certificate Bindings</h1>
        <button
          onClick={handleBulkRenew}
          disabled={actionLoading === 'bulk'}
          className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {actionLoading === 'bulk' ? 'Renewing...' : 'Auto-Renew Check'}
        </button>
      </div>

      {/* Expiring warning */}
      {expiring.length > 0 && (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center gap-2">
          <span className="text-amber-600">⚠️</span>
          <span className="text-sm text-amber-800">
            {expiring.length} certificate{expiring.length > 1 ? 's' : ''} expiring within 30 days
          </span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        <button
          onClick={() => setTab('all')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === 'all' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
        >
          All Bindings ({bindings.length})
        </button>
        <button
          onClick={() => setTab('expiring')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === 'expiring' ? 'border-amber-600 text-amber-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
        >
          Expiring Soon ({expiring.length})
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : Object.keys(grouped).length === 0 ? (
        <p className="text-sm text-gray-500">No certificate bindings found. Build an environment to create bindings.</p>
      ) : (
        <div className="space-y-4">
          {Object.entries(grouped).map(([envName, envBindings]) => (
            <div key={envName} className="bg-white rounded-lg border border-gray-200">
              <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
                <span className="text-lg">🌍</span>
                <span className="font-semibold text-gray-800">{envName}</span>
                <span className="text-xs text-gray-400 ml-2">{envBindings.length} cert{envBindings.length > 1 ? 's' : ''}</span>
              </div>
              <div className="divide-y divide-gray-50">
                {envBindings.map(b => (
                  <div key={b.id} className="px-4 py-3 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-800">{b.role}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${b.cert_type === 'server' ? 'bg-blue-50 text-blue-700' : 'bg-purple-50 text-purple-700'}`}>
                          {b.cert_type}
                        </span>
                        {expiryBadge(b.expires_at)}
                      </div>
                      <div className="flex items-center gap-3 mt-1">
                        <Link to={`/certificates/${b.cert_serial}`} className="text-xs text-blue-600 hover:underline font-mono">
                          {b.cert_serial.substring(0, 16)}...
                        </Link>
                        {b.renewal_count > 0 && (
                          <span className="text-xs text-gray-400">renewed {b.renewal_count}x</span>
                        )}
                        {b.last_renewed_at && (
                          <span className="text-xs text-gray-400">last: {new Date(b.last_renewed_at).toLocaleDateString()}</span>
                        )}
                      </div>
                    </div>

                    {/* Auto-renew toggle */}
                    <button
                      onClick={() => handleToggleAutoRenew(b.id, b.auto_renew)}
                      className={`text-xs px-2 py-1 rounded border ${b.auto_renew ? 'border-green-300 bg-green-50 text-green-700' : 'border-gray-200 bg-gray-50 text-gray-500'}`}
                      title={b.auto_renew ? 'Auto-renew enabled' : 'Auto-renew disabled'}
                    >
                      {b.auto_renew ? '🔄 Auto' : '⏸️ Manual'}
                    </button>

                    {/* Actions */}
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleRenew(b.id)}
                        disabled={actionLoading === b.id}
                        className="text-xs px-2 py-1 rounded border border-blue-200 text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                      >
                        Renew
                      </button>
                      <button
                        onClick={() => handleRotate(b.id)}
                        disabled={actionLoading === b.id}
                        className="text-xs px-2 py-1 rounded border border-orange-200 text-orange-700 hover:bg-orange-50 disabled:opacity-50"
                      >
                        Rotate
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
