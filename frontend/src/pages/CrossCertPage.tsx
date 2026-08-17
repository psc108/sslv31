import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface CrossCert {
  id: string
  issuing_ca_id: string
  issuing_ca_cn: string | null
  external_ca_cn: string
  serial: string
  status: string
  direction: string
  path_length: number
  name_constraints_json: string | null
  expires_at: string
  created_at: string
  revoked_at: string | null
}

interface CA {
  id: string
  cn: string
  is_root: boolean
  has_key: boolean
}

export default function CrossCertPage() {
  const [crossCerts, setCrossCerts] = useState<CrossCert[]>([])
  const [cas, setCas] = useState<CA[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [msg, setMsg] = useState('')
  const [form, setForm] = useState({
    ca_id: '',
    external_pem: '',
    validity_days: 730,
    path_length: 0,
    direction: 'outbound',
    permitted: '',
    excluded: '',
  })

  useEffect(() => { loadData() }, [])

  async function loadData() {
    setLoading(true)
    try {
      const [ccRes, caRes] = await Promise.all([
        api.get('/cross-certs'),
        api.get('/ca'),
      ])
      setCrossCerts(ccRes.data)
      setCas(caRes.data.filter((c: CA) => c.has_key))
    } catch { /* ignore */ }
    setLoading(false)
  }

  async function crossSign() {
    if (!form.ca_id || !form.external_pem.trim()) {
      setMsg('Select a CA and paste the external CA certificate')
      return
    }
    const nameConstraints = (form.permitted || form.excluded) ? {
      ...(form.permitted ? { permitted: form.permitted.split(',').map(s => s.trim()).filter(Boolean) } : {}),
      ...(form.excluded ? { excluded: form.excluded.split(',').map(s => s.trim()).filter(Boolean) } : {}),
    } : null

    try {
      const res = await api.post(`/cross-certs/${form.ca_id}/cross-sign`, {
        external_ca_pem: form.external_pem,
        validity_days: form.validity_days,
        path_length: form.path_length,
        direction: form.direction,
        name_constraints: nameConstraints,
      })
      setMsg(`Cross-certificate issued: ${res.data.issuing_ca_cn} → ${res.data.external_ca_cn}`)
      setShowForm(false)
      setForm({ ca_id: '', external_pem: '', validity_days: 730, path_length: 0, direction: 'outbound', permitted: '', excluded: '' })
      loadData()
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Cross-sign failed')
    }
  }

  async function revoke(id: string, cn: string) {
    if (!confirm(`Revoke trust bridge to "${cn}"? This terminates the trust relationship.`)) return
    try {
      await api.post(`/cross-certs/${id}/revoke`)
      setMsg(`Trust bridge to ${cn} revoked`)
      loadData()
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Revoke failed')
    }
  }

  async function exportCert(id: string) {
    try {
      const res = await api.get(`/cross-certs/${id}/export`)
      const blob = new Blob([res.data.chain_pem], { type: 'application/x-pem-file' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `cross-cert-${id.slice(0, 8)}.pem`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Export failed')
    }
  }

  const active = crossCerts.filter(c => c.status === 'active')
  const revoked = crossCerts.filter(c => c.status === 'revoked')

  if (loading) return <div className="p-6">Loading...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">🔗 Cross-Certification</h1>
        <button onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">
          {showForm ? 'Cancel' : '+ Cross-Sign CA'}
        </button>
      </div>

      {msg && (
        <div className="bg-blue-50 border border-blue-200 text-blue-800 px-4 py-2 rounded text-sm">
          {msg}
          <button onClick={() => setMsg('')} className="ml-2 text-blue-600">✕</button>
        </div>
      )}

      {/* Cross-sign form */}
      {showForm && (
        <div className="bg-white rounded-lg border p-6 space-y-4">
          <h2 className="text-lg font-semibold">Create Trust Bridge</h2>
          <p className="text-sm text-gray-500">
            Cross-sign an external CA so that clients trusting your CA can validate certificates from the external CA.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Signing CA (local)</span>
              <select value={form.ca_id} onChange={e => setForm({ ...form, ca_id: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border">
                <option value="">Select CA...</option>
                {cas.map(ca => (
                  <option key={ca.id} value={ca.id}>{ca.cn} {ca.is_root ? '(Root)' : '(Intermediate)'}</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Direction</span>
              <select value={form.direction} onChange={e => setForm({ ...form, direction: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border">
                <option value="outbound">Outbound (we trust them)</option>
                <option value="inbound">Inbound (they trust us)</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Validity (days)</span>
              <input type="number" value={form.validity_days}
                onChange={e => setForm({ ...form, validity_days: parseInt(e.target.value) || 730 })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Path Length</span>
              <input type="number" value={form.path_length} min={0} max={2}
                onChange={e => setForm({ ...form, path_length: parseInt(e.target.value) || 0 })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Permitted domains (comma-separated)</span>
              <input type="text" value={form.permitted}
                onChange={e => setForm({ ...form, permitted: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border"
                placeholder=".partner.com, .vendor.internal" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Excluded domains (comma-separated)</span>
              <input type="text" value={form.excluded}
                onChange={e => setForm({ ...form, excluded: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border"
                placeholder=".internal, .corp" />
            </label>
          </div>

          <label className="block">
            <span className="text-sm font-medium text-gray-700">External CA Certificate (PEM)</span>
            <textarea value={form.external_pem}
              onChange={e => setForm({ ...form, external_pem: e.target.value })}
              rows={8}
              className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border font-mono"
              placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----" />
          </label>

          <button onClick={crossSign}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">
            Issue Cross-Certificate
          </button>
        </div>
      )}

      {/* Active trust bridges */}
      <div className="bg-white rounded-lg border p-4">
        <h2 className="text-lg font-semibold mb-3">Active Trust Bridges ({active.length})</h2>
        {active.length === 0 ? (
          <p className="text-gray-500 text-sm">No active cross-certifications.</p>
        ) : (
          <div className="space-y-2">
            {active.map(cc => (
              <div key={cc.id} className="flex items-center justify-between p-3 bg-gray-50 rounded">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{cc.direction === 'outbound' ? '➡️' : '⬅️'}</span>
                  <div>
                    <div className="font-medium text-sm">
                      {cc.issuing_ca_cn || 'Local CA'} → {cc.external_ca_cn}
                    </div>
                    <div className="text-xs text-gray-500">
                      Serial: {cc.serial.slice(0, 16)}… | Expires: {new Date(cc.expires_at).toLocaleDateString()}
                      {cc.name_constraints_json && ' | Name constrained'}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded ${cc.direction === 'outbound' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'}`}>
                    {cc.direction}
                  </span>
                  <button onClick={() => exportCert(cc.id)}
                    className="text-xs text-blue-600 hover:underline">Export</button>
                  <button onClick={() => revoke(cc.id, cc.external_ca_cn)}
                    className="text-xs text-red-600 hover:underline">Revoke</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Revoked bridges */}
      {revoked.length > 0 && (
        <div className="bg-white rounded-lg border p-4">
          <h2 className="text-lg font-semibold mb-3 text-gray-500">Revoked Trust Bridges ({revoked.length})</h2>
          <div className="space-y-2">
            {revoked.map(cc => (
              <div key={cc.id} className="flex items-center justify-between p-3 bg-red-50 rounded opacity-75">
                <div>
                  <div className="font-medium text-sm line-through">
                    {cc.issuing_ca_cn || 'Local CA'} → {cc.external_ca_cn}
                  </div>
                  <div className="text-xs text-gray-500">
                    Revoked: {cc.revoked_at ? new Date(cc.revoked_at).toLocaleDateString() : 'N/A'}
                  </div>
                </div>
                <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded">revoked</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
