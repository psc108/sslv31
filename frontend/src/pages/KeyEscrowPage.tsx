import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface EscrowEntry {
  id: string
  certificate_serial: string
  certificate_cn: string
  profile: string
  escrowed_at: string
  escrowed_by: string
}

interface RecoveryRequest {
  id: string
  escrow_id: string
  certificate_serial: string
  justification: string
  requested_by: string
  requested_at: string
  approvals: { user: string; at: string }[]
  approvals_required: number
  status: string
  download_expires_at: string | null
  download_token: string | null
}

interface Policy {
  approvals_required: number
  download_window_hours: number
  escrow_profiles: string[]
  never_escrow_profiles: string[]
  recovery_key_configured: boolean
}

export default function KeyEscrowPage() {
  const [activeTab, setActiveTab] = useState<'escrowed' | 'requests' | 'policy'>('escrowed')
  const [escrowed, setEscrowed] = useState<EscrowEntry[]>([])
  const [requests, setRequests] = useState<RecoveryRequest[]>([])
  const [policy, setPolicy] = useState<Policy | null>(null)
  const [total, setTotal] = useState(0)
  const [reqTotal, setReqTotal] = useState(0)

  // Recovery request form
  const [recoverSerial, setRecoverSerial] = useState('')
  const [justification, setJustification] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => { loadEscrowed() }, [])
  useEffect(() => { if (activeTab === 'requests') loadRequests() }, [activeTab])
  useEffect(() => { if (activeTab === 'policy') loadPolicy() }, [activeTab])

  async function loadEscrowed() {
    try {
      const res = await api.get('/key-escrow/escrowed')
      setEscrowed(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch { /* ignore */ }
  }

  async function loadRequests() {
    try {
      const res = await api.get('/key-escrow/requests')
      setRequests(res.data.items || [])
      setReqTotal(res.data.total || 0)
    } catch { /* ignore */ }
  }

  async function loadPolicy() {
    try {
      const res = await api.get('/key-escrow/policy')
      setPolicy(res.data)
    } catch { /* ignore */ }
  }

  async function submitRecovery() {
    if (!recoverSerial || justification.length < 10) return
    setSubmitting(true)
    try {
      await api.post('/key-escrow/requests', {
        certificate_serial: recoverSerial,
        justification,
      })
      setRecoverSerial('')
      setJustification('')
      loadRequests()
      setActiveTab('requests')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to create recovery request')
    }
    setSubmitting(false)
  }

  async function handleAction(requestId: string, action: 'approve' | 'deny') {
    try {
      await api.post(`/key-escrow/requests/${requestId}/action`, { action })
      loadRequests()
    } catch (e: any) {
      alert(e.response?.data?.detail || `Failed to ${action}`)
    }
  }

  async function downloadKey(requestId: string, token: string) {
    try {
      const res = await api.get(`/key-escrow/requests/${requestId}/download?token=${token}`)
      const blob = new Blob([res.data.key_pem], { type: 'application/x-pem-file' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `recovered-key-${requestId.slice(0, 8)}.pem`
      a.click()
      URL.revokeObjectURL(url)
      loadRequests()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Download failed')
    }
  }

  const statusColor = (s: string) => {
    if (s === 'approved') return 'bg-green-100 text-green-800'
    if (s === 'completed') return 'bg-blue-100 text-blue-800'
    if (s === 'denied') return 'bg-red-100 text-red-800'
    if (s === 'expired') return 'bg-gray-100 text-gray-800'
    return 'bg-yellow-100 text-yellow-800'
  }

  const tabs = [
    { id: 'escrowed' as const, label: `Escrowed Keys (${total})` },
    { id: 'requests' as const, label: `Recovery Requests (${reqTotal})` },
    { id: 'policy' as const, label: 'Policy' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">🔐 Key Escrow & Recovery</h1>
        <p className="text-sm text-gray-600 mt-1">Recoverable encryption keys with M-of-N approval workflow</p>
      </div>

      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`py-2 px-1 border-b-2 text-sm font-medium ${activeTab === t.id ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Escrowed Keys Tab */}
      {activeTab === 'escrowed' && (
        <div className="space-y-4">
          {escrowed.length > 0 ? (
            <div className="bg-white rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left">Certificate CN</th>
                    <th className="px-4 py-2 text-left">Serial</th>
                    <th className="px-4 py-2 text-left">Profile</th>
                    <th className="px-4 py-2 text-left">Escrowed By</th>
                    <th className="px-4 py-2 text-left">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {escrowed.map(e => (
                    <tr key={e.id} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-medium">{e.certificate_cn}</td>
                      <td className="px-4 py-2 font-mono text-xs">{e.certificate_serial.slice(0, 16)}...</td>
                      <td className="px-4 py-2">
                        <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-800">{e.profile}</span>
                      </td>
                      <td className="px-4 py-2">{e.escrowed_by}</td>
                      <td className="px-4 py-2 text-gray-500">{e.escrowed_at ? new Date(e.escrowed_at).toLocaleDateString() : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="bg-gray-50 border rounded-lg p-6 text-center">
              <p className="text-gray-600">No escrowed keys. Keys are automatically escrowed when issuing certificates with email/encryption profiles or templates with escrow enabled.</p>
            </div>
          )}

          {/* Request Recovery Form */}
          <div className="bg-white rounded-lg border p-4">
            <h3 className="text-sm font-bold text-gray-900 mb-3">Request Key Recovery</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <input
                type="text" placeholder="Certificate serial number"
                value={recoverSerial} onChange={e => setRecoverSerial(e.target.value)}
                className="border rounded-md px-3 py-2 text-sm"
              />
              <input
                type="text" placeholder="Justification (min 10 chars)"
                value={justification} onChange={e => setJustification(e.target.value)}
                className="border rounded-md px-3 py-2 text-sm"
              />
              <button onClick={submitRecovery} disabled={submitting || !recoverSerial || justification.length < 10}
                className="px-4 py-2 bg-red-600 text-white rounded-md text-sm hover:bg-red-700 disabled:opacity-50">
                {submitting ? 'Submitting...' : 'Request Recovery'}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Recovery requires {policy?.approvals_required || 2} admin approvals. Download link expires after 1 hour.
            </p>
          </div>
        </div>
      )}

      {/* Recovery Requests Tab */}
      {activeTab === 'requests' && (
        <div className="space-y-4">
          {requests.length > 0 ? (
            <div className="space-y-3">
              {requests.map(r => (
                <div key={r.id} className="bg-white rounded-lg border p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor(r.status)}`}>
                          {r.status}
                        </span>
                        <span className="font-mono text-xs text-gray-500">{r.certificate_serial.slice(0, 16)}...</span>
                      </div>
                      <p className="text-sm text-gray-700 mt-1">{r.justification}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        Requested by <span className="font-medium">{r.requested_by}</span> on {r.requested_at ? new Date(r.requested_at).toLocaleString() : ''}
                      </p>
                      <p className="text-xs text-gray-500">
                        Approvals: {r.approvals.length}/{r.approvals_required}
                        {r.approvals.length > 0 && (
                          <span className="ml-2">({r.approvals.map(a => a.user).join(', ')})</span>
                        )}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {r.status === 'pending' && (
                        <>
                          <button onClick={() => handleAction(r.id, 'approve')}
                            className="px-3 py-1 bg-green-600 text-white rounded text-xs hover:bg-green-700">
                            Approve
                          </button>
                          <button onClick={() => handleAction(r.id, 'deny')}
                            className="px-3 py-1 bg-red-600 text-white rounded text-xs hover:bg-red-700">
                            Deny
                          </button>
                        </>
                      )}
                      {r.status === 'approved' && r.download_token && (
                        <button onClick={() => downloadKey(r.id, r.download_token!)}
                          className="px-3 py-1 bg-blue-600 text-white rounded text-xs hover:bg-blue-700">
                          ⬇️ Download Key
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-gray-50 border rounded-lg p-6 text-center">
              <p className="text-gray-600">No recovery requests.</p>
            </div>
          )}
        </div>
      )}

      {/* Policy Tab */}
      {activeTab === 'policy' && policy && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg border p-4">
            <h3 className="text-sm font-bold text-gray-900 mb-3">Escrow Policy</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-gray-500">Approvals Required</p>
                <p className="font-medium">{policy.approvals_required} admins must approve</p>
              </div>
              <div>
                <p className="text-gray-500">Download Window</p>
                <p className="font-medium">{policy.download_window_hours} hour after approval</p>
              </div>
              <div>
                <p className="text-gray-500">Auto-Escrow Profiles</p>
                <p className="font-medium">{policy.escrow_profiles.join(', ') || 'None'}</p>
              </div>
              <div>
                <p className="text-gray-500">Never Escrow</p>
                <p className="font-medium">{policy.never_escrow_profiles.join(', ')}</p>
              </div>
              <div>
                <p className="text-gray-500">Recovery Key</p>
                <p className={`font-medium ${policy.recovery_key_configured ? 'text-green-600' : 'text-yellow-600'}`}>
                  {policy.recovery_key_configured ? '✅ Configured (separate key)' : '⚠️ Derived from master key'}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h4 className="text-sm font-medium text-blue-900 mb-2">How Key Escrow Works</h4>
            <ol className="text-sm text-blue-800 space-y-1 list-decimal list-inside">
              <li>When a certificate is issued with an escrow-enabled template or email profile, the private key is encrypted with a separate recovery key and stored.</li>
              <li>If key recovery is needed (employee departure, lost access), an admin submits a recovery request with justification.</li>
              <li>{policy.approvals_required} other admins must approve the request (the requester cannot self-approve).</li>
              <li>Once approved, a time-limited download link (1 hour) is generated.</li>
              <li>All operations are fully audited (KEY_RECOVERY_REQUESTED, APPROVED, COMPLETED).</li>
            </ol>
          </div>

          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <h4 className="text-sm font-medium text-yellow-900 mb-2">Security Notes</h4>
            <ul className="text-sm text-yellow-800 space-y-1 list-disc list-inside">
              <li>Signing keys (server TLS, code signing) are <strong>never</strong> escrowed — non-repudiation requires sole possession.</li>
              <li>Only encryption keys (email S/MIME, data encryption) should be escrowed.</li>
              <li>Configure <code>KEY_ESCROW_RECOVERY_KEY</code> as a separate Fernet key for production deployments.</li>
              <li>Consider storing the recovery key in an HSM or splitting it with Shamir's Secret Sharing.</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
