import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '@/lib/api'
import { authenticatedDownload } from '@/lib/utils'

interface CertRow {
  binding_id: string
  role: string
  cert_type: string
  cert_serial: string
  cert_status: string | null
  key_algo: string | null
  key_size: number | null
  weak_key: boolean
  signing_ca_chain: string[]
  expires_at: string | null
  risk: 'expired' | 'critical' | 'warning' | 'ok' | 'unknown'
  auto_renew: boolean
  renewal_count: number
}

interface EnvPosture {
  environment_id: string
  environment_name: string
  environment_status: string
  certs: CertRow[]
}

interface SecretPosture {
  id: string
  name: string
  category: string
  linked_service: string
  rotate_every_days: number | null
  rotation_due_at: string | null
  rotation_overdue: boolean
}

interface Posture {
  environments: EnvPosture[]
  secrets: SecretPosture[]
  summary: {
    total_certs: number
    expired_count: number
    critical_count: number
    warning_count: number
    weak_key_count: number
    secrets_overdue_count: number
  }
}

const RISK_STYLES: Record<string, string> = {
  expired: 'bg-red-100 text-red-700',
  critical: 'bg-red-100 text-red-700',
  warning: 'bg-amber-100 text-amber-700',
  ok: 'bg-green-100 text-green-700',
  unknown: 'bg-gray-100 text-gray-500',
}

const RISK_LABELS: Record<string, string> = {
  expired: 'Expired',
  critical: 'Critical',
  warning: 'Warning',
  ok: 'OK',
  unknown: 'Unknown',
}

export default function BMPkiPosturePage() {
  const [posture, setPosture] = useState<Posture | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/build/pki-posture').then(r => setPosture(r.data)).finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-sm text-gray-400">Loading...</p>
  if (!posture) return <p className="text-sm text-red-500">Failed to load PKI posture.</p>

  const { environments, secrets, summary } = posture

  const exportReport = (format: 'json' | 'csv' | 'markdown' | 'pdf') => {
    const ext = format === 'markdown' ? 'md' : format
    authenticatedDownload(`/api/v1/build/pki-posture/export/${format}`, `pki-compliance-report.${ext}`)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">PKI Posture Dashboard</h1>
          <p className="text-sm text-gray-500 mt-1">Certificate/CA topology, expiry risk, key strength, and secret rotation staleness across every environment.</p>
        </div>
        <div className="flex gap-1">
          <span className="text-xs text-gray-400 self-center mr-1">Export:</span>
          {(['pdf', 'csv', 'markdown', 'json'] as const).map(fmt => (
            <button key={fmt} onClick={() => exportReport(fmt)}
              className="text-xs px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50 uppercase">
              {fmt === 'markdown' ? 'md' : fmt}
            </button>
          ))}
        </div>
      </div>

      {/* Summary tiles */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Total Certs</div>
          <div className="text-xl font-bold text-gray-900">{summary.total_certs}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Expired</div>
          <div className={`text-xl font-bold ${summary.expired_count ? 'text-red-600' : 'text-gray-900'}`}>{summary.expired_count}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Critical (&le;7d)</div>
          <div className={`text-xl font-bold ${summary.critical_count ? 'text-red-600' : 'text-gray-900'}`}>{summary.critical_count}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Warning (&le;30d)</div>
          <div className={`text-xl font-bold ${summary.warning_count ? 'text-amber-600' : 'text-gray-900'}`}>{summary.warning_count}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Weak Keys</div>
          <div className={`text-xl font-bold ${summary.weak_key_count ? 'text-red-600' : 'text-gray-900'}`}>{summary.weak_key_count}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3">
          <div className="text-xs text-gray-500">Secrets Overdue</div>
          <div className={`text-xl font-bold ${summary.secrets_overdue_count ? 'text-red-600' : 'text-gray-900'}`}>{summary.secrets_overdue_count}</div>
        </div>
      </div>

      {/* Per-environment cert posture */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold text-gray-800">Certificates by Environment</h2>
        {environments.length === 0 ? (
          <p className="text-sm text-gray-500">No environments with certificate bindings yet.</p>
        ) : environments.map(env => (
          <div key={env.environment_id} className="bg-white rounded-lg border border-gray-200">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
              <span className="text-lg">🌍</span>
              <span className="font-semibold text-gray-800">{env.environment_name}</span>
              <span className="text-xs text-gray-400">{env.environment_status}</span>
              <span className="text-xs text-gray-400 ml-auto">{env.certs.length} cert{env.certs.length !== 1 ? 's' : ''}</span>
            </div>
            {env.certs.length === 0 ? (
              <p className="px-4 py-3 text-sm text-gray-400">No certificate bindings for this environment.</p>
            ) : (
              <div className="divide-y divide-gray-50">
                {env.certs.map(c => (
                  <div key={c.binding_id} className="px-4 py-3 flex items-center gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-medium text-gray-800">{c.role}</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">{c.cert_type}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${RISK_STYLES[c.risk]}`}>{RISK_LABELS[c.risk]}</span>
                        {c.weak_key && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium" title="Below BR minimum (RSA<2048 / ECDSA<256)">⚠ weak key</span>
                        )}
                        <span className={`text-xs px-1.5 py-0.5 rounded ${c.auto_renew ? 'bg-green-50 text-green-700' : 'bg-gray-50 text-gray-500'}`}>
                          {c.auto_renew ? '🔄 auto-renew' : '⏸ manual'}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                        <Link to={`/certificates/${c.cert_serial}`} className="text-blue-600 hover:underline font-mono">
                          {c.cert_serial.substring(0, 16)}...
                        </Link>
                        <span>{c.key_algo}{c.key_size ? ` ${c.key_size}` : ''}</span>
                        {c.signing_ca_chain.length > 0 && (
                          <span title="Signing chain, leaf → root">🔗 {c.signing_ca_chain.join(' → ')}</span>
                        )}
                        {c.expires_at && <span>expires {new Date(c.expires_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Secret rotation staleness */}
      <div className="space-y-2">
        <h2 className="text-lg font-semibold text-gray-800">Secret Rotation Staleness</h2>
        {secrets.filter(s => s.rotate_every_days).length === 0 ? (
          <p className="text-sm text-gray-500">No secrets have a rotation policy configured yet — see the <Link to="/bm-secrets" className="text-blue-600 hover:underline">Secrets</Link> page.</p>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-50">
            {secrets.filter(s => s.rotate_every_days).map(s => (
              <div key={s.id} className="px-4 py-3 flex items-center gap-3">
                <span className="text-sm font-mono text-gray-800">{s.name}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-gray-50 text-gray-600">{s.category}</span>
                {s.rotation_overdue ? (
                  <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium">⚠ overdue</span>
                ) : (
                  <span className="text-xs text-gray-400">due {s.rotation_due_at ? new Date(s.rotation_due_at).toLocaleDateString() : '—'}</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
