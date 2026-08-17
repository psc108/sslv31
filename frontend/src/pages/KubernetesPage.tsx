import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface IssuerConfig {
  ca_id: string
  profile: string
  validity_days: number
  allowed_namespaces: string[]
  allowed_dns_patterns: string[]
  enabled: boolean
}

interface CA {
  id: string
  cn: string
}

export default function KubernetesPage() {
  const [config, setConfig] = useState<IssuerConfig | null>(null)
  const [cas, setCas] = useState<CA[]>([])
  const [manifests, setManifests] = useState<Record<string, string> | null>(null)
  const [activeTab, setActiveTab] = useState<'config' | 'manifests' | 'guide'>('config')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [health, setHealth] = useState<{ status: string; enabled: boolean } | null>(null)

  // Form state
  const [caId, setCaId] = useState('')
  const [profile, setProfile] = useState('server')
  const [validityDays, setValidityDays] = useState(90)
  const [namespaces, setNamespaces] = useState('')
  const [dnsPatterns, setDnsPatterns] = useState('')
  const [enabled, setEnabled] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  async function loadData() {
    try {
      const [cfgRes, caRes, healthRes] = await Promise.all([
        api.get('/api/v1/k8s/config'),
        api.get('/api/v1/ca'),
        api.get('/api/v1/k8s/health'),
      ])
      const cfg = cfgRes.data
      setConfig(cfg)
      setCaId(cfg.ca_id || '')
      setProfile(cfg.profile)
      setValidityDays(cfg.validity_days)
      setNamespaces(cfg.allowed_namespaces.join(', '))
      setDnsPatterns(cfg.allowed_dns_patterns.join(', '))
      setEnabled(cfg.enabled)
      setCas(caRes.data)
      setHealth(healthRes.data)
    } catch { /* ignore */ }
  }

  async function saveConfig() {
    setSaving(true)
    setMsg('')
    try {
      const body: IssuerConfig = {
        ca_id: caId,
        profile,
        validity_days: validityDays,
        allowed_namespaces: namespaces ? namespaces.split(',').map(s => s.trim()).filter(Boolean) : [],
        allowed_dns_patterns: dnsPatterns ? dnsPatterns.split(',').map(s => s.trim()).filter(Boolean) : [],
        enabled,
      }
      const res = await api.put('/api/v1/k8s/config', body)
      setConfig(res.data)
      setMsg('Configuration saved')
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function loadManifests() {
    try {
      const res = await api.get('/api/v1/k8s/manifests')
      setManifests(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (activeTab === 'manifests' && !manifests) loadManifests()
  }, [activeTab])

  const tabs = [
    { id: 'config' as const, label: 'Configuration' },
    { id: 'manifests' as const, label: 'Manifests' },
    { id: 'guide' as const, label: 'Integration Guide' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">☸️ Kubernetes Integration</h1>
          <p className="text-sm text-gray-600 mt-1">cert-manager webhook issuer for automated TLS</p>
        </div>
        {health && (
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${health.enabled ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
            {health.enabled ? '● Issuer Active' : '○ Issuer Disabled'}
          </span>
        )}
      </div>

      {/* Tabs */}
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

      {/* Config Tab */}
      {activeTab === 'config' && (
        <div className="bg-white rounded-lg border p-6 space-y-4">
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}
                className="rounded border-gray-300" />
              <span className="text-sm font-medium">Issuer Enabled</span>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Signing CA</label>
              <select value={caId} onChange={e => setCaId(e.target.value)}
                className="w-full border rounded-md px-3 py-2 text-sm">
                <option value="">Auto-select (first available)</option>
                {cas.map(ca => <option key={ca.id} value={ca.id}>{ca.cn}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Certificate Profile</label>
              <select value={profile} onChange={e => setProfile(e.target.value)}
                className="w-full border rounded-md px-3 py-2 text-sm">
                <option value="server">Server TLS</option>
                <option value="client">Client mTLS</option>
                <option value="code_sign">Code Signing</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Default Validity (days)</label>
              <input type="number" value={validityDays} onChange={e => setValidityDays(Number(e.target.value))}
                className="w-full border rounded-md px-3 py-2 text-sm" min={1} max={398} />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Allowed Namespaces (comma-separated, empty = all)</label>
            <input type="text" value={namespaces} onChange={e => setNamespaces(e.target.value)}
              placeholder="default, production, staging"
              className="w-full border rounded-md px-3 py-2 text-sm" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Allowed DNS Patterns (comma-separated, empty = all)</label>
            <input type="text" value={dnsPatterns} onChange={e => setDnsPatterns(e.target.value)}
              placeholder="*.svc.cluster.local, *.internal.corp"
              className="w-full border rounded-md px-3 py-2 text-sm" />
          </div>

          {msg && <p className={`text-sm ${msg.includes('failed') ? 'text-red-600' : 'text-green-600'}`}>{msg}</p>}

          <button onClick={saveConfig} disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
        </div>
      )}

      {/* Manifests Tab */}
      {activeTab === 'manifests' && manifests && (
        <div className="space-y-4">
          {[
            { key: 'secret', title: '1. API Key Secret' },
            { key: 'cluster_issuer', title: '2. ClusterIssuer' },
            { key: 'webhook_deployment', title: '3. Webhook Deployment' },
            { key: 'certificate_example', title: '4. Certificate Resource (Example)' },
            { key: 'acme_issuer', title: '5. ACME Alternative (Optional)' },
            { key: 'helm_values', title: '6. Helm Values' },
          ].map(({ key, title }) => (
            <details key={key} className="bg-white rounded-lg border">
              <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-gray-900 hover:bg-gray-50">
                {title}
              </summary>
              <div className="px-4 pb-4">
                <pre className="bg-gray-900 text-green-300 p-4 rounded text-xs overflow-x-auto whitespace-pre-wrap">
                  {manifests[key]}
                </pre>
                <button onClick={() => navigator.clipboard.writeText(manifests[key])}
                  className="mt-2 text-xs text-blue-600 hover:underline">
                  📋 Copy to clipboard
                </button>
              </div>
            </details>
          ))}
        </div>
      )}

      {/* Guide Tab */}
      {activeTab === 'guide' && (
        <div className="bg-white rounded-lg border p-6 prose prose-sm max-w-none">
          <h2 className="text-lg font-bold">Integration Guide</h2>

          <h3 className="text-md font-semibold mt-4">Overview</h3>
          <p>This CA acts as a cert-manager external issuer. Kubernetes workloads get TLS certificates automatically via cert-manager's Certificate resources.</p>

          <h3 className="text-md font-semibold mt-4">Prerequisites</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li>cert-manager v1.12+ installed in the cluster</li>
            <li>Network connectivity from cluster to this CA's API endpoint</li>
            <li>An API key with cert:write permission (or the legacy admin key)</li>
          </ul>

          <h3 className="text-md font-semibold mt-4">Option A: Direct Webhook (Recommended)</h3>
          <ol className="list-decimal pl-5 space-y-2">
            <li>Create the API key secret in the cert-manager namespace</li>
            <li>Deploy the webhook adapter (see Manifests tab)</li>
            <li>Create a ClusterIssuer pointing to the webhook service</li>
            <li>Create Certificate resources — cert-manager handles the rest</li>
          </ol>

          <h3 className="text-md font-semibold mt-4">Option B: ACME Protocol</h3>
          <p>If the ACME endpoint is enabled (Medium Priority Stage 1), cert-manager can use its built-in ACME issuer with no webhook needed.</p>

          <h3 className="text-md font-semibold mt-4">How It Works</h3>
          <ol className="list-decimal pl-5 space-y-1">
            <li>cert-manager creates a CSR for the Certificate resource</li>
            <li>The webhook adapter sends the CSR to <code>POST /api/v1/k8s/sign</code></li>
            <li>This CA signs the CSR and returns the certificate + chain</li>
            <li>cert-manager stores the cert in the specified Kubernetes Secret</li>
            <li>cert-manager auto-renews before expiry (configurable via <code>renewBefore</code>)</li>
          </ol>

          <h3 className="text-md font-semibold mt-4">Policy Enforcement</h3>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Namespace restriction:</strong> Limit which namespaces can request certs</li>
            <li><strong>DNS patterns:</strong> Only allow specific domain patterns (e.g. *.svc.cluster.local)</li>
            <li><strong>Validity cap:</strong> Maximum cert lifetime enforced server-side</li>
            <li><strong>Profile:</strong> Controls key usage and EKU extensions</li>
          </ul>

          <h3 className="text-md font-semibold mt-4">Monitoring</h3>
          <p>All K8s-issued certificates appear in the Certificates list with the tag <code>k8s-cert-manager</code>. Expiry monitoring and audit logging apply as normal.</p>

          <h3 className="text-md font-semibold mt-4">mTLS Between cert-manager and Webhook</h3>
          <p>For production, the webhook should serve HTTPS using a certificate issued by this CA. cert-manager validates the webhook's TLS cert using the <code>caBundle</code> field in the ClusterIssuer spec.</p>
        </div>
      )}
    </div>
  )
}
