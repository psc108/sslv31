import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import CopyButton from '@/components/CopyButton'
import { daysUntil, authenticatedDownload } from '@/lib/utils'
import { useState } from 'react'

const FORMATS = [
  { key: 'pem', label: 'PEM', desc: 'Leaf cert', ext: 'pem' },
  { key: 'der', label: 'DER', desc: 'Binary cert', ext: 'cer' },
  { key: 'chain', label: 'Chain', desc: 'PEM chain', ext: 'pem' },
  { key: 'key', label: 'Key', desc: 'Private key', ext: 'pem' },
  { key: 'p12', label: 'P12', desc: 'PKCS#12', ext: 'p12' },
  { key: 'pfx', label: 'PFX', desc: 'Windows', ext: 'pfx' },
  { key: 'p7b', label: 'P7B', desc: 'PKCS#7 chain', ext: 'p7b' },
  { key: 'jks', label: 'JKS', desc: 'Java KeyStore', ext: 'jks' },
  { key: 'bundle', label: 'Bundle', desc: 'ZIP all platforms', ext: 'zip' },
] as const

const CHAIN_MODES = [
  { key: 'full', label: 'Full (leaf + intermediates + root)' },
  { key: 'no_root', label: 'No root (leaf + intermediates)' },
  { key: 'intermediates_only', label: 'Intermediates only' },
  { key: 'leaf_only', label: 'Leaf only' },
] as const

const PLATFORMS = [
  { key: 'all', label: 'All platforms' },
  { key: 'linux', label: 'Linux' },
  { key: 'windows', label: 'Windows' },
  { key: 'java', label: 'Java' },
  { key: 'macos', label: 'macOS' },
] as const

function ExportPanel({ serial, cn }: { serial: string; cn: string }) {
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [chainMode, setChainMode] = useState('full')
  const [platform, setPlatform] = useState('all')

  const doExport = (fmt: string) => {
    const params = new URLSearchParams()
    if (fmt === 'chain') params.set('chain_mode', chainMode)
    if (fmt === 'bundle') params.set('platform', platform)
    const qs = params.toString() ? `?${params.toString()}` : ''
    const ext = FORMATS.find(f => f.key === fmt)?.ext || fmt
    authenticatedDownload(`/api/v1/export/${serial}/${fmt}${qs}`, `${cn}.${ext}`)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {FORMATS.map(f => (
          <button key={f.key} onClick={() => doExport(f.key)}
            title={f.desc}
            className="px-2.5 py-1.5 bg-gray-100 border border-gray-300 rounded text-xs font-medium hover:bg-gray-200 uppercase">
            {f.label}
          </button>
        ))}
      </div>
      <button onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-xs text-blue-600 hover:text-blue-800">
        {showAdvanced ? '▾ Hide options' : '▸ Chain & platform options'}
      </button>
      {showAdvanced && (
        <div className="flex gap-4 text-xs">
          <label className="flex items-center gap-1">
            <span className="text-gray-500">Chain:</span>
            <select value={chainMode} onChange={e => setChainMode(e.target.value)}
              className="border border-gray-300 rounded px-1.5 py-1 text-xs">
              {CHAIN_MODES.map(m => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1">
            <span className="text-gray-500">Bundle:</span>
            <select value={platform} onChange={e => setPlatform(e.target.value)}
              className="border border-gray-300 rounded px-1.5 py-1 text-xs">
              {PLATFORMS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
          </label>
        </div>
      )}
    </div>
  )
}

interface CertInspect {
  serial: string
  serial_decimal: string
  subject: Record<string, string>
  subject_rfc4514: string
  issuer: Record<string, string>
  issuer_rfc4514: string
  san: { type: string; value: string }[]
  not_valid_before: string
  not_valid_after: string
  days_remaining: number
  key_algo: string
  key_size: number
  signature_algorithm: string
  extensions: { oid: string; name: string; critical: boolean; value: string }[]
  fingerprints: { sha256: string; sha1: string }
  profile: string
  status: string
  pem: string
  tags: string[]
}

export default function CertificateDetail() {
  const { serial } = useParams<{ serial: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [newTag, setNewTag] = useState('')

  const { data: cert, isLoading, error } = useQuery<CertInspect>({
    queryKey: ['cert-inspect', serial],
    queryFn: async () => (await api.get(`/cert/${serial}/inspect`)).data,
    enabled: !!serial,
  })

  const { data: ocspStatus } = useQuery<{ serial: string; status: string; revoked_at: string | null; expires_at: string; signing_ca_id: string | null }>({
    queryKey: ['ocsp-status', serial],
    queryFn: async () => (await fetch(`/api/v1/pki/ocsp/status/${serial}`)).json(),
    enabled: !!serial,
    refetchInterval: 60000,
  })

  const tagsMutation = useMutation({
    mutationFn: (tags: string[]) => api.patch(`/cert/${serial}/tags`, { tags }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['cert-inspect', serial] }),
  })

  const addTag = () => {
    if (!newTag.trim() || !cert) return
    const updated = [...(cert.tags || []), newTag.trim().toLowerCase()]
    tagsMutation.mutate(updated)
    setNewTag('')
  }

  const removeTag = (tag: string) => {
    if (!cert) return
    tagsMutation.mutate(cert.tags.filter(t => t !== tag))
  }

  if (isLoading) return <div className="p-6 text-gray-400">Loading certificate details...</div>
  if (error || !cert) return <div className="p-6 text-red-600">Certificate not found</div>

  const statusColor = cert.status === 'valid'
    ? (cert.days_remaining <= 7 ? 'text-red-600' : cert.days_remaining <= 30 ? 'text-amber-600' : 'text-green-600')
    : cert.status === 'revoked' ? 'text-red-600' : 'text-gray-600'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <button onClick={() => navigate('/certificates')} className="text-sm text-blue-600 hover:text-blue-800 mb-2">
            ← Back to Certificates
          </button>
          <h2 className="text-2xl font-bold text-gray-900">{cert.subject.commonName || cert.serial}</h2>
          <p className="text-sm text-gray-500 mt-1">Certificate Inspector</p>
        </div>
        <ExportPanel serial={serial!} cn={cert.subject.commonName || serial} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left column — Identity & Validity */}
        <div className="space-y-4">
          {/* Status */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Status</h3>
            <div className="flex items-center gap-3">
              <span className={`text-lg font-bold capitalize ${statusColor}`}>{cert.status}</span>
              {cert.status === 'valid' && (
                <span className="text-sm text-gray-500">({cert.days_remaining} days remaining)</span>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
              <div><span className="text-gray-500">Profile:</span> <span className="capitalize">{cert.profile}</span></div>
              <div><span className="text-gray-500">Algorithm:</span> {cert.key_algo} {cert.key_size}</div>
              <div><span className="text-gray-500">Signature:</span> {cert.signature_algorithm}</div>
              <div><span className="text-gray-500">Not Before:</span> {new Date(cert.not_valid_before).toLocaleDateString()}</div>
              <div><span className="text-gray-500">Not After:</span> {new Date(cert.not_valid_after).toLocaleDateString()}</div>
            </div>
          </section>

          {/* Tags */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Tags</h3>
            <div className="flex flex-wrap gap-2 mb-3">
              {cert.tags?.map(tag => (
                <span key={tag} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                  {tag}
                  <button onClick={() => removeTag(tag)} className="hover:text-red-600">×</button>
                </span>
              ))}
              {(!cert.tags || cert.tags.length === 0) && (
                <span className="text-xs text-gray-400">No tags</span>
              )}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newTag}
                onChange={e => setNewTag(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag() } }}
                className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-xs"
                placeholder="Add tag (e.g. production, staging, dev)"
              />
              <button onClick={addTag}
                className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded-md text-xs font-medium hover:bg-gray-200">
                Add
              </button>
            </div>
          </section>

          {/* Subject */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700">Subject</h3>
              <CopyButton text={cert.subject_rfc4514} label="Copy DN" />
            </div>
            <div className="space-y-1 text-sm">
              {Object.entries(cert.subject).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-gray-500">{k}:</span>
                  <span className="font-mono text-gray-900">{v}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Issuer */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700">Issuer</h3>
              <CopyButton text={cert.issuer_rfc4514} label="Copy DN" />
            </div>
            <div className="space-y-1 text-sm">
              {Object.entries(cert.issuer).map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span className="text-gray-500">{k}:</span>
                  <span className="font-mono text-gray-900">{v}</span>
                </div>
              ))}
            </div>
          </section>

          {/* SANs */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Subject Alternative Names ({cert.san.length})</h3>
            {cert.san.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {cert.san.map((s, i) => (
                  <span key={i} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${
                    s.type === 'dns' ? 'bg-blue-100 text-blue-800' :
                    s.type === 'ip' ? 'bg-purple-100 text-purple-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    <span className="font-semibold uppercase">{s.type}</span>
                    {s.value}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400">No SANs</p>
            )}
          </section>
        </div>

        {/* Right column — Technical details */}
        <div className="space-y-4">
          {/* Serial & Fingerprints */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Identifiers & Fingerprints</h3>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-gray-500">Serial (hex):</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-900 truncate max-w-[200px]">{cert.serial}</span>
                  <CopyButton text={cert.serial} />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500">SHA-256:</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-900 truncate max-w-[200px]">{cert.fingerprints.sha256}</span>
                  <CopyButton text={cert.fingerprints.sha256} />
                </div>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-500">SHA-1:</span>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-900 truncate max-w-[200px]">{cert.fingerprints.sha1}</span>
                  <CopyButton text={cert.fingerprints.sha1} />
                </div>
              </div>
            </div>
          </section>

          {/* OCSP Status */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">OCSP Status</h3>
            {ocspStatus ? (
              <div className="flex items-center gap-3">
                <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold ${
                  ocspStatus.status === 'valid' ? 'bg-green-100 text-green-800' :
                  ocspStatus.status === 'revoked' ? 'bg-red-100 text-red-800' :
                  'bg-gray-100 text-gray-800'
                }`}>
                  <span className={`w-2 h-2 rounded-full ${
                    ocspStatus.status === 'valid' ? 'bg-green-500' :
                    ocspStatus.status === 'revoked' ? 'bg-red-500' :
                    'bg-gray-500'
                  }`} />
                  {ocspStatus.status === 'valid' ? 'GOOD' : ocspStatus.status.toUpperCase()}
                </span>
                {ocspStatus.revoked_at && (
                  <span className="text-xs text-gray-500">Revoked: {new Date(ocspStatus.revoked_at).toLocaleString()}</span>
                )}
              </div>
            ) : (
              <span className="text-xs text-gray-400">Checking...</span>
            )}
            <p className="text-xs text-gray-400 mt-2">Real-time revocation status via OCSP responder</p>
          </section>

          {/* Extensions */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">X.509 Extensions ({cert.extensions.length})</h3>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {cert.extensions.map((ext, i) => (
                <div key={i} className="text-xs border-b border-gray-100 pb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{ext.name}</span>
                    {ext.critical && (
                      <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-[10px] cursor-help"
                        title="Critical extensions MUST be understood and enforced by the verifying system. If a system encounters a critical extension it does not recognise, it MUST reject the certificate.">
                        CRITICAL
                      </span>
                    )}
                  </div>
                  <span className="text-gray-500 font-mono">{ext.oid}</span>
                  <p className="text-gray-600 mt-1 break-all">{ext.value}</p>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-gray-400 mt-3 border-t border-gray-100 pt-2">
              <span className="px-1 py-0.5 bg-red-100 text-red-700 rounded">CRITICAL</span> = the verifying system must understand and enforce this extension or reject the certificate.
              Non-critical extensions may be ignored if not recognised.
            </p>
          </section>

          {/* PEM */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-700">PEM Certificate</h3>
              <CopyButton text={cert.pem} label="Copy PEM" />
            </div>
            <pre className="text-xs font-mono bg-gray-900 text-green-400 p-3 rounded overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">
              {cert.pem}
            </pre>
          </section>
        </div>
      </div>
    </div>
  )
}
