import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

type Tab = 'inventory' | 'weak-keys' | 'expiry' | 'revocations' | 'audit-export' | 'integrity'

export default function ReportsPage() {
  const [tab, setTab] = useState<Tab>('inventory')

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: 'inventory', label: 'Inventory', icon: '📦' },
    { id: 'weak-keys', label: 'Weak Keys', icon: '⚠️' },
    { id: 'expiry', label: 'Expiry Forecast', icon: '📅' },
    { id: 'revocations', label: 'Revocations', icon: '🚫' },
    { id: 'audit-export', label: 'Audit Export', icon: '📤' },
    { id: 'integrity', label: 'Integrity Check', icon: '🔗' },
  ]

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Compliance & Reports</h2>
        <p className="text-sm text-gray-500 mt-1">Certificate inventory, compliance checks, and audit exports</p>
      </div>

      <div className="flex gap-1 mb-6 border-b border-gray-200">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              tab === t.id ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'inventory' && <InventoryReport />}
      {tab === 'weak-keys' && <WeakKeysReport />}
      {tab === 'expiry' && <ExpiryForecast />}
      {tab === 'revocations' && <RevocationReport />}
      {tab === 'audit-export' && <AuditExport />}
      {tab === 'integrity' && <IntegrityCheck />}
    </div>
  )
}

function InventoryReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['reports', 'inventory'],
    queryFn: async () => (await api.get('/reports/inventory')).data,
  })

  if (isLoading) return <p className="text-gray-400">Loading...</p>
  if (!data) return null

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-4">
        {Object.entries(data.summary).map(([k, v]) => (
          <div key={k} className="bg-white rounded-lg border p-4 text-center">
            <p className="text-2xl font-bold text-gray-900">{v as number}</p>
            <p className="text-xs text-gray-500 capitalize">{k}</p>
          </div>
        ))}
      </div>

      {/* By algorithm */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg border p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">By Algorithm</h3>
          {Object.entries(data.by_algorithm).map(([k, v]) => (
            <div key={k} className="flex justify-between text-sm py-1">
              <span className="text-gray-600">{k}</span>
              <span className="font-medium">{v as number}</span>
            </div>
          ))}
        </div>
        <div className="bg-white rounded-lg border p-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">By Profile</h3>
          {Object.entries(data.by_profile).map(([k, v]) => (
            <div key={k} className="flex justify-between text-sm py-1">
              <span className="text-gray-600">{k}</span>
              <span className="font-medium">{v as number}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">CN</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Serial</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Profile</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Key</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Expires</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.certificates.map((c: any) => (
              <tr key={c.serial} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-gray-800">{c.cn}</td>
                <td className="px-4 py-2 font-mono text-xs text-gray-600">{c.serial.slice(0, 16)}...</td>
                <td className="px-4 py-2 text-gray-600">{c.profile}</td>
                <td className="px-4 py-2 text-gray-600">{c.key_algo} {c.key_size}</td>
                <td className="px-4 py-2">
                  <StatusBadge status={c.status} />
                </td>
                <td className="px-4 py-2 text-gray-600 text-xs">{c.expires_at?.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <ExportButton url="/reports/inventory" filename="inventory" />
    </div>
  )
}

function WeakKeysReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['reports', 'weak-keys'],
    queryFn: async () => (await api.get('/reports/weak-keys')).data,
  })

  if (isLoading) return <p className="text-gray-400">Loading...</p>
  if (!data) return null

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border p-4">
        <p className="text-sm text-gray-600">
          Found <span className="font-bold text-amber-700">{data.total_findings}</span> certificates/CAs with weak cryptographic parameters.
        </p>
      </div>

      {data.findings.length === 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
          ✓ No weak keys detected. All certificates meet minimum requirements.
        </div>
      )}

      {data.findings.map((f: any, i: number) => (
        <div key={i} className="bg-white rounded-lg border p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800 uppercase">{f.type}</span>
            <span className="font-medium text-gray-900">{f.cn}</span>
            <span className="text-xs text-gray-500 font-mono">{f.serial || f.id}</span>
          </div>
          <p className="text-sm text-gray-600 mb-1">{f.key_algo} {f.key_size} bits</p>
          <ul className="list-disc list-inside text-sm text-amber-700">
            {f.issues.map((issue: string, j: number) => <li key={j}>{issue}</li>)}
          </ul>
        </div>
      ))}
    </div>
  )
}

function ExpiryForecast() {
  const { data, isLoading } = useQuery({
    queryKey: ['reports', 'expiry-forecast'],
    queryFn: async () => (await api.get('/reports/expiry-forecast')).data,
  })

  if (isLoading) return <p className="text-gray-400">Loading...</p>
  if (!data) return null

  const bucketLabels: Record<string, string> = {
    '30_days': 'Expiring within 30 days',
    '60_days': 'Expiring within 31–60 days',
    '90_days': 'Expiring within 61–90 days',
  }

  const bucketColors: Record<string, string> = {
    '30_days': 'border-red-200 bg-red-50',
    '60_days': 'border-amber-200 bg-amber-50',
    '90_days': 'border-blue-200 bg-blue-50',
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        {Object.entries(data.summary).map(([k, v]) => (
          <div key={k} className={`rounded-lg border p-4 text-center ${bucketColors[k] || ''}`}>
            <p className="text-2xl font-bold">{v as number}</p>
            <p className="text-xs text-gray-600">{bucketLabels[k]}</p>
          </div>
        ))}
      </div>

      {/* Details */}
      {Object.entries(data.buckets).map(([bucket, certs]) => (
        <div key={bucket}>
          {(certs as any[]).length > 0 && (
            <div className="bg-white rounded-lg border overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b">
                <h3 className="text-sm font-medium text-gray-700">{bucketLabels[bucket]}</h3>
              </div>
              <table className="w-full text-sm">
                <thead className="border-b">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-600">CN</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-600">Serial</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-600">Expires</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-600">Days Left</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-600">Auto-Renew</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {(certs as any[]).map((c: any) => (
                    <tr key={c.serial} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-800">{c.cn}</td>
                      <td className="px-4 py-2 font-mono text-xs text-gray-600">{c.serial.slice(0, 16)}...</td>
                      <td className="px-4 py-2 text-gray-600 text-xs">{c.expires_at?.slice(0, 10)}</td>
                      <td className="px-4 py-2 font-medium text-gray-900">{c.days_remaining}</td>
                      <td className="px-4 py-2">{c.auto_renew ? '✓' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}

      {Object.values(data.summary).every(v => v === 0) && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
          ✓ No certificates expiring within 90 days.
        </div>
      )}
    </div>
  )
}

function RevocationReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['reports', 'revocations'],
    queryFn: async () => (await api.get('/reports/revocations')).data,
  })

  if (isLoading) return <p className="text-gray-400">Loading...</p>
  if (!data) return null

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border p-4 text-center">
          <p className="text-2xl font-bold">{data.total}</p>
          <p className="text-xs text-gray-500">Total</p>
        </div>
        <div className="bg-red-50 rounded-lg border border-red-200 p-4 text-center">
          <p className="text-2xl font-bold text-red-700">{data.revoked}</p>
          <p className="text-xs text-gray-500">Revoked</p>
        </div>
        <div className="bg-amber-50 rounded-lg border border-amber-200 p-4 text-center">
          <p className="text-2xl font-bold text-amber-700">{data.held}</p>
          <p className="text-xs text-gray-500">On Hold</p>
        </div>
      </div>

      {data.certificates.length > 0 && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">CN</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Serial</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Status</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Date</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Profile</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.certificates.map((c: any) => (
                <tr key={c.serial} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-800">{c.cn}</td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-600">{c.serial.slice(0, 16)}...</td>
                  <td className="px-4 py-2"><StatusBadge status={c.status} /></td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{(c.revoked_at || c.held_at)?.slice(0, 10)}</td>
                  <td className="px-4 py-2 text-gray-600">{c.profile}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.total === 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm text-green-800">
          ✓ No revoked or held certificates.
        </div>
      )}
    </div>
  )
}

function AuditExport() {
  const [format, setFormat] = useState('json')
  const [loading, setLoading] = useState(false)

  const handleExport = async () => {
    setLoading(true)
    try {
      const resp = await api.get(`/reports/audit-export?format=${format}`, { responseType: 'blob' })
      const ext = format === 'json' ? 'json' : format === 'csv' ? 'csv' : 'cef'
      const blob = new Blob([resp.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-export-${new Date().toISOString().slice(0, 10)}.${ext}`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border p-6">
        <h3 className="text-sm font-medium text-gray-700 mb-4">Export Audit Log</h3>
        <p className="text-sm text-gray-500 mb-4">
          Download the full audit trail in your preferred format. CEF (Common Event Format) is compatible with most SIEM platforms.
        </p>

        <div className="flex items-end gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Format</label>
            <select value={format} onChange={e => setFormat(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
              <option value="cef">CEF (SIEM)</option>
            </select>
          </div>
          <button onClick={handleExport} disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
            {loading ? 'Exporting...' : 'Download Export'}
          </button>
        </div>
      </div>

      <div className="bg-gray-50 rounded-lg border p-4 text-sm text-gray-600">
        <p className="font-medium mb-2">Format details:</p>
        <ul className="list-disc list-inside space-y-1">
          <li><strong>JSON</strong> — Structured data with hash chain for integrity verification</li>
          <li><strong>CSV</strong> — Spreadsheet-compatible, suitable for manual review</li>
          <li><strong>CEF</strong> — Common Event Format for Splunk, QRadar, ArcSight, and other SIEM tools</li>
        </ul>
      </div>
    </div>
  )
}

function IntegrityCheck() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['reports', 'integrity'],
    queryFn: async () => (await api.get('/reports/audit-integrity')).data,
    enabled: false,
  })

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border p-6">
        <h3 className="text-sm font-medium text-gray-700 mb-2">Audit Log Integrity Verification</h3>
        <p className="text-sm text-gray-500 mb-4">
          Verify the tamper-evident hash chain. Each audit event includes a SHA-256 hash of the previous event,
          creating a chain that detects any modification or deletion.
        </p>
        <button onClick={() => refetch()} disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {isLoading ? 'Verifying...' : 'Run Integrity Check'}
        </button>
      </div>

      {data && (
        <div className={`rounded-lg border p-4 ${data.intact ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg">{data.intact ? '✓' : '✗'}</span>
            <span className={`font-medium ${data.intact ? 'text-green-800' : 'text-red-800'}`}>
              {data.intact ? 'Hash chain intact' : 'Hash chain broken!'}
            </span>
          </div>
          <div className="text-sm text-gray-600 space-y-1">
            <p>Total events: {data.total_events}</p>
            <p>Verified: {data.verified}</p>
            {data.broken_at_id && <p className="text-red-700">Chain broken at event ID: {data.broken_at_id}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    valid: 'bg-green-100 text-green-800',
    revoked: 'bg-red-100 text-red-800',
    expired: 'bg-gray-100 text-gray-800',
    held: 'bg-amber-100 text-amber-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  )
}

function ExportButton({ url, filename }: { url: string; filename: string }) {
  const handleExport = async () => {
    const resp = await api.get(url)
    const blob = new Blob([JSON.stringify(resp.data, null, 2)], { type: 'application/json' })
    const u = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = u
    a.download = `${filename}-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(u)
  }

  return (
    <button onClick={handleExport}
      className="px-4 py-2 border border-gray-300 text-sm font-medium rounded-md hover:bg-gray-50">
      Export JSON
    </button>
  )
}
