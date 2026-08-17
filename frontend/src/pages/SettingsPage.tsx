import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import CopyButton from '@/components/CopyButton'
import { authenticatedDownload } from '@/lib/utils'
import CategoryRulesSettings from '@/components/docs/CategoryRulesSettings'

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const [apiKey, setApiKey] = useState(localStorage.getItem('api_key') || '')
  const [saved, setSaved] = useState(false)

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await fetch('/api/v1/health')).json(),
    refetchInterval: 30000,
  })

  const { data: backups = [] } = useQuery<any[]>({
    queryKey: ['backups'],
    queryFn: async () => (await api.get('/backup')).data,
  })

  const backupMutation = useMutation({
    mutationFn: () => api.post('/backup'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
  })

  const rotateMutation = useMutation({
    mutationFn: () => api.post('/settings/rotate-api-key'),
  })

  const saveApiKey = () => {
    localStorage.setItem('api_key', apiKey)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const handleRotate = () => {
    if (!confirm('Rotate API key? The current key will be immediately invalidated.')) return
    rotateMutation.mutate(undefined, {
      onSuccess: (res) => {
        const newKey = res.data.new_api_key
        setApiKey(newKey)
        localStorage.setItem('api_key', newKey)
      },
    })
  }

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Settings</h2>

      <div className="space-y-6">
        {/* API Key */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="font-semibold text-gray-900 mb-3">API Key</h3>
          <p className="text-sm text-gray-500 mb-3">
            Set your API key for authenticating with the backend. This is stored in your browser only.
          </p>
          <p className="text-xs text-gray-400 mb-3">
            Find your key in: <code className="bg-gray-100 px-1 rounded">backend/.env</code> → <code className="bg-gray-100 px-1 rounded">API_KEY=...</code>
          </p>
          <div className="flex gap-3">
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
              placeholder="Paste API_KEY from backend/.env"
            />
            <button onClick={saveApiKey}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
              Save
            </button>
          </div>
          {saved && <p className="text-green-600 text-sm mt-2">✓ API key saved to browser storage</p>}
          {rotateMutation.isSuccess && (
            <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded">
              <p className="text-green-800 text-sm font-medium">✓ API key rotated successfully</p>
              <p className="text-xs text-green-700 mt-1">New key has been saved to your browser. Update <code className="bg-green-100 px-1 rounded">backend/.env</code> with the new value.</p>
            </div>
          )}
          <div className="mt-3 pt-3 border-t border-gray-100">
            <button onClick={handleRotate}
              disabled={rotateMutation.isPending}
              className="px-3 py-1.5 bg-red-50 border border-red-200 text-red-700 text-xs font-medium rounded-md hover:bg-red-100 disabled:opacity-50">
              {rotateMutation.isPending ? 'Rotating...' : '🔄 Rotate API Key'}
            </button>
            <p className="text-xs text-gray-400 mt-1">Generates a new key and invalidates the current one immediately.</p>
          </div>
        </section>

        {/* PKI Infrastructure */}
        <PKISettings />

        {/* LDAP / Active Directory */}
        <LDAPSettings />

        {/* Structured View Categories */}
        <CategoryRulesSettings />

        {/* Automatic Bug Filing (Improvements Plan Stage 22) */}
        <BugAutoFilingSettings />

        {/* Neural ML Layer */}
        <NeuralSettings />

        {/* System Health */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="font-semibold text-gray-900 mb-3">System Health</h3>
          {health ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Status:</span>{' '}
                <span className={`font-medium ${health.status === 'ok' ? 'text-green-600' : 'text-amber-600'}`}>
                  {health.status}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Version:</span>{' '}
                <span className="font-medium">{health.version}</span>
              </div>
              <div>
                <span className="text-gray-500">Database:</span>{' '}
                <span className={`font-medium ${health.database === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                  {health.database}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Keytool:</span>{' '}
                <span className={`font-medium ${health.keytool === 'ok' ? 'text-green-600' : 'text-amber-600'}`}>
                  {health.keytool}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Loading...</p>
          )}
        </section>

        {/* Root CA Download */}
        <RootCADownload />

        {/* Backups */}
        <section className="bg-white rounded-lg border border-gray-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900">Backups</h3>
            <button onClick={() => backupMutation.mutate()}
              disabled={backupMutation.isPending}
              className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded-md text-xs font-medium hover:bg-gray-200 disabled:opacity-50">
              {backupMutation.isPending ? 'Creating...' : 'Create Backup'}
            </button>
          </div>
          {backupMutation.isSuccess && (
            <p className="text-green-600 text-sm mb-3">✓ Backup created successfully</p>
          )}
          {backups.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-gray-500 font-medium">Filename</th>
                  <th className="text-left py-2 text-gray-500 font-medium">Size</th>
                  <th className="text-left py-2 text-gray-500 font-medium">Created</th>
                  <th className="text-left py-2 text-gray-500 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {backups.map((b: any) => (
                  <tr key={b.filename}>
                    <td className="py-2 font-mono text-xs">{b.filename}</td>
                    <td className="py-2 text-gray-600">{(b.size / 1024).toFixed(1)} KB</td>
                    <td className="py-2 text-gray-600">{new Date(b.created_at).toLocaleString()}</td>
                    <td className="py-2">
                      <button onClick={() => authenticatedDownload(`/api/v1/backup/${b.filename}`, b.filename)}
                        className="text-blue-600 hover:text-blue-800 text-xs font-medium">Download</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-sm text-gray-400">No backups yet. Create one to protect your CA keys and certificates.</p>
          )}
        </section>
      </div>
    </div>
  )
}

function PKISettings() {
  const [baseUrl, setBaseUrl] = useState('')
  const [crlDays, setCrlDays] = useState(7)
  const [loaded, setLoaded] = useState(false)

  const { data: pkiData } = useQuery({
    queryKey: ['pki-settings'],
    queryFn: async () => (await api.get('/settings/pki')).data,
  })

  useEffect(() => {
    if (pkiData && !loaded) {
      setBaseUrl(pkiData.pki_base_url || '')
      setCrlDays(pkiData.crl_validity_days || 7)
      setLoaded(true)
    }
  }, [pkiData, loaded])

  const mutation = useMutation({
    mutationFn: () => api.put('/settings/pki', { pki_base_url: baseUrl, crl_validity_days: crlDays }),
  })

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-1">PKI Infrastructure</h3>
      <p className="text-sm text-gray-500 mb-3">
        Configure the base URL for CRL Distribution Points (CDP) and Authority Information Access (AIA)
        extensions embedded in issued certificates.
      </p>

      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">PKI Base URL</label>
          <input type="text" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="http://pki.internal (leave empty to disable)" />
          <p className="text-xs text-gray-400 mt-1">Must be reachable by all relying parties. Used in CDP, AIA, and OCSP URLs.</p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">CRL Validity (days)</label>
          <input type="number" value={crlDays} onChange={e => setCrlDays(Number(e.target.value))}
            min={1} max={90}
            className="w-32 border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
        <button onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Saving...' : 'Save PKI Settings'}
        </button>
        {mutation.isSuccess && <p className="text-green-600 text-sm">{'\u2713'} PKI settings saved. New certificates will include CDP/AIA extensions.</p>}
      </div>

      {pkiData?.enabled && (
        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded text-xs space-y-1">
          <p className="font-medium text-green-800">{'\u2713'} PKI extensions enabled</p>
          <p><span className="text-gray-500">CRL:</span> {pkiData.crl_endpoint}</p>
          <p><span className="text-gray-500">CA Cert:</span> {pkiData.ca_cert_endpoint}</p>
          <p><span className="text-gray-500">OCSP:</span> {pkiData.ocsp_endpoint}</p>
        </div>
      )}

      {pkiData && !pkiData.enabled && (
        <div className="mt-4 p-3 bg-amber-50 border border-amber-200 rounded text-xs">
          <p className="text-amber-800">{'\u26a0\ufe0f'} PKI extensions disabled. Certificates will not contain CDP/AIA/OCSP URLs until a base URL is configured.</p>
        </div>
      )}
    </section>
  )
}


function BugAutoFilingSettings() {
  const { data, isLoading } = useQuery({
    queryKey: ['bm-settings'],
    queryFn: async () => (await api.get('/settings/build-manager')).data,
  })

  const mutation = useMutation({
    mutationFn: (next: boolean) => api.put('/settings/build-manager', { auto_file_bugs_on_failure: next }),
  })

  const enabled = mutation.isSuccess
    ? (mutation.variables as boolean)
    : !!data?.auto_file_bugs_on_failure

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-1">Automatic Bug Filing</h3>
      <p className="text-sm text-gray-500 mb-3">
        When a Build Manager job finishes failed, Bug Tracker always checks it against existing open
        bugs (Improvements Plan Stage 21). This setting goes one step further: if nothing matches
        closely enough, automatically file a new bug instead of just leaving the failure in the job
        log for someone to notice. A match against an existing bug is recorded as a recurrence
        instead of a duplicate. Auto-filed bugs are clearly marked and reported by "Automated (Ansible
        failure scan)" rather than a real user — off by default.
      </p>

      <label className="flex items-center gap-2 text-sm text-gray-700">
        <input type="checkbox" checked={enabled} disabled={isLoading || mutation.isPending}
          onChange={e => mutation.mutate(e.target.checked)} />
        Automatically file a bug when an Ansible job fails and no existing bug matches
      </label>
      {mutation.isSuccess && <p className="text-green-600 text-xs mt-2">{'✓'} Saved.</p>}
      {mutation.isError && <p className="text-red-600 text-xs mt-2">Failed to save — try again.</p>}
    </section>
  )
}


function RootCADownload() {
  const { data: cas = [] } = useQuery<any[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  const rootCAs = cas.filter((ca: any) => ca.is_root && ca.has_key)

  const downloadPEM = async (caId: string, cn: string) => {
    const res = await api.get(`/ca/${caId}`)
    const pem = res.data.cert_pem
    const blob = new Blob([pem], { type: 'application/x-pem-file' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${cn.replace(/[^a-zA-Z0-9-_]/g, '_')}-root-ca.pem`
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadDER = async (caId: string, cn: string) => {
    // Use the public PKI endpoint which returns DER
    const res = await api.get(`/pki/ca/${caId}/cert`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = `${cn.replace(/[^a-zA-Z0-9-_]/g, '_')}-root-ca.cer`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="bg-white rounded-lg border border-blue-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-2">🔐 Root CA Download</h3>
      <p className="text-sm text-gray-500 mb-4">
        Download the root CA certificate to import into browsers, OS trust stores, and Java keystores.
      </p>

      {rootCAs.length > 0 ? (
        <div className="space-y-3 mb-4">
          {rootCAs.map((ca: any) => (
            <div key={ca.id} className="flex items-center justify-between p-3 bg-gray-50 rounded border border-gray-100">
              <div>
                <p className="text-sm font-medium text-gray-900">{ca.cn}</p>
                <p className="text-xs text-gray-500">{ca.key_algo} {ca.key_size} • Expires {new Date(ca.expires_at).toLocaleDateString()}</p>
              </div>
              <div className="flex gap-2">
                <button onClick={() => downloadPEM(ca.id, ca.cn)}
                  className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-md hover:bg-blue-700">
                  PEM
                </button>
                <button onClick={() => downloadDER(ca.id, ca.cn)}
                  className="px-3 py-1.5 bg-gray-600 text-white text-xs font-medium rounded-md hover:bg-gray-700">
                  DER (.cer)
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400 mb-4">No root CAs found. Create one in CA Management first.</p>
      )}

      <div className="p-3 bg-gray-50 rounded text-xs text-gray-600 space-y-1">
        <p><strong>Linux:</strong> <code className="bg-gray-100 px-1 rounded">sudo cp root-ca.pem /usr/local/share/ca-certificates/root-ca.crt && sudo update-ca-certificates</code></p>
        <p><strong>Windows:</strong> Double-click the .cer file → Install Certificate → Local Machine → Trusted Root CAs</p>
        <p><strong>Java:</strong> <code className="bg-gray-100 px-1 rounded">keytool -importcert -alias root-ca -file root-ca.pem -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit</code></p>
        <p><strong>Browser:</strong> Settings → Certificates → Authorities → Import root-ca.pem</p>
      </div>
    </section>
  )
}

function LDAPSettings() {
  const [config, setConfig] = useState({
    enabled: false,
    url: '',
    starttls: false,
    bind_dn: '',
    bind_password: '',
    search_base: '',
    search_filter: '(uid={username})',
    user_dn_template: '',
    tls_ca_cert: '',
    timeout: 10,
    role_admin: '',
    role_operator: '',
    role_auditor: '',
    role_default: 'readonly',
    group_attribute: 'memberOf',
  })
  const [loaded, setLoaded] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)

  const { data: ldapData } = useQuery({
    queryKey: ['ldap-settings'],
    queryFn: async () => (await api.get('/settings/ldap')).data,
  })

  useEffect(() => {
    if (ldapData && !loaded) {
      setConfig({
        enabled: ldapData.enabled || false,
        url: ldapData.url || '',
        starttls: ldapData.starttls || false,
        bind_dn: ldapData.bind_dn || '',
        bind_password: '',
        search_base: ldapData.search_base || '',
        search_filter: ldapData.search_filter || '(uid={username})',
        user_dn_template: ldapData.user_dn_template || '',
        tls_ca_cert: ldapData.tls_ca_cert || '',
        timeout: ldapData.timeout || 10,
        role_admin: ldapData.role_admin || '',
        role_operator: ldapData.role_operator || '',
        role_auditor: ldapData.role_auditor || '',
        role_default: ldapData.role_default || 'readonly',
        group_attribute: ldapData.group_attribute || 'memberOf',
      })
      setLoaded(true)
    }
  }, [ldapData, loaded])

  const saveMutation = useMutation({
    mutationFn: () => api.put('/settings/ldap', config),
  })

  const testMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/settings/ldap/test')
      setTestResult(res.data)
      return res.data
    },
  })

  const update = (field: string, value: any) => setConfig(prev => ({ ...prev, [field]: value }))

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-1">LDAP / Active Directory</h3>
      <p className="text-sm text-gray-500 mb-4">
        Authenticate users against an external LDAP or Active Directory server. Local admin account always works as fallback.
      </p>

      <div className="space-y-4">
        {/* Enable toggle */}
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={config.enabled} onChange={e => update('enabled', e.target.checked)}
            className="rounded border-gray-300" />
          <span className="text-sm font-medium text-gray-700">Enable LDAP Authentication</span>
        </label>

        {/* Connection */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">LDAP URL</label>
            <input type="text" value={config.url} onChange={e => update('url', e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="ldaps://dc.corp.internal:636" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Timeout (seconds)</label>
            <input type="number" value={config.timeout} onChange={e => update('timeout', Number(e.target.value))}
              min={1} max={60}
              className="w-32 border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
        </div>

        <label className="flex items-center gap-2">
          <input type="checkbox" checked={config.starttls} onChange={e => update('starttls', e.target.checked)}
            className="rounded border-gray-300" />
          <span className="text-sm text-gray-700">Use STARTTLS (for ldap:// on port 389)</span>
        </label>

        {/* Bind credentials */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-2">Service Account (for user search)</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Bind DN</label>
              <input type="text" value={config.bind_dn} onChange={e => update('bind_dn', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="cn=svc-pki,ou=Service,dc=corp,dc=internal" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Bind Password</label>
              <input type="password" value={config.bind_password} onChange={e => update('bind_password', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder={ldapData?.bind_password_set ? '(unchanged — leave empty to keep)' : 'Service account password'} />
            </div>
          </div>
        </div>

        {/* User lookup */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-2">User Lookup</p>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Search Base</label>
              <input type="text" value={config.search_base} onChange={e => update('search_base', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="ou=People,dc=corp,dc=internal" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Search Filter</label>
              <input type="text" value={config.search_filter} onChange={e => update('search_filter', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="(uid={username}) or (sAMAccountName={username})" />
              <p className="text-xs text-gray-400 mt-1">{'{username}'} is replaced with the login username. Use (sAMAccountName={'{username}'}) for Active Directory.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">User DN Template (alternative to search)</label>
              <input type="text" value={config.user_dn_template} onChange={e => update('user_dn_template', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="uid={username},ou=People,dc=corp,dc=internal" />
              <p className="text-xs text-gray-400 mt-1">Direct bind without search. Leave empty to use search mode above.</p>
            </div>
          </div>
        </div>

        {/* TLS */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-2">TLS Certificate</p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">CA Certificate Path</label>
            <input type="text" value={config.tls_ca_cert} onChange={e => update('tls_ca_cert', e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="/etc/ssl/certs/ldap-ca.pem (leave empty to skip TLS verification)" />
          </div>
        </div>

        {/* Group-to-role mapping */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-2">Group → Role Mapping</p>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Group Attribute</label>
              <input type="text" value={config.group_attribute} onChange={e => update('group_attribute', e.target.value)}
                className="w-64 border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="memberOf" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Admin Group DN</label>
                <input type="text" value={config.role_admin} onChange={e => update('role_admin', e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder="cn=pki-admins,ou=Groups,dc=corp,dc=internal" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Operator Group DN</label>
                <input type="text" value={config.role_operator} onChange={e => update('role_operator', e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder="cn=pki-operators,ou=Groups,dc=corp,dc=internal" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Auditor Group DN</label>
                <input type="text" value={config.role_auditor} onChange={e => update('role_auditor', e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder="cn=pki-auditors,ou=Groups,dc=corp,dc=internal" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Default Role (no group match)</label>
                <select value={config.role_default} onChange={e => update('role_default', e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
                  <option value="readonly">Read-Only</option>
                  <option value="auditor">Auditor</option>
                  <option value="operator">Operator</option>
                  <option value="admin">Admin</option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-2">
          <button onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
            {saveMutation.isPending ? 'Saving...' : 'Save LDAP Settings'}
          </button>
          <button onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending || !config.url}
            className="px-4 py-2 bg-gray-100 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-200 disabled:opacity-50">
            {testMutation.isPending ? 'Testing...' : 'Test Connection'}
          </button>
        </div>

        {saveMutation.isSuccess && <p className="text-green-600 text-sm">✓ LDAP settings saved</p>}
        {saveMutation.isError && <p className="text-red-600 text-sm">✗ Failed to save LDAP settings</p>}

        {testResult && (
          <div className={`p-3 rounded text-sm ${testResult.status === 'ok' ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800'}`}>
            <p className="font-medium">{testResult.status === 'ok' ? '✓' : '✗'} {testResult.message}</p>
            {testResult.server_info && (
              <div className="mt-1 text-xs">
                <p>Vendor: {testResult.server_info.vendor || 'unknown'}</p>
                {testResult.server_info.naming_contexts?.length > 0 && (
                  <p>Naming contexts: {testResult.server_info.naming_contexts.join(', ')}</p>
                )}
              </div>
            )}
          </div>
        )}

        {!config.url && (
          <div className="p-3 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
            ⚠️ No LDAP server configured. Users will authenticate with local accounts only. Configure the LDAP URL when your directory server is available.
          </div>
        )}
      </div>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Neural ML Layer settings
// ---------------------------------------------------------------------------

const HELP: Record<string, string> = {
  scorer_path:
    'Absolute path to a fitted AnomalyScorer .pkl file inside the container. ' +
    'If unset or the file is missing, anomaly scoring is skipped and the pipeline ' +
    'runs in stack-trace-only mode — KB matching and thread hints still work. ' +
    'Default container path: /data/models/anomaly_scorer.pkl',

  log_path:
    'Path to the primary application log file. Neural reads only the tail ' +
    '(controlled by Tail Lines) to avoid loading multi-GB files into memory. ' +
    'Leave empty to disable log windowing. Example: /var/log/ecs/fulfillment/application.log',

  log_paths:
    'Colon-separated list of additional log paths, globs, or directories to ingest ' +
    'alongside the primary log. Useful when your service writes to multiple files or ' +
    'you want to correlate gateway + app logs together. ' +
    'Example: /var/log/gateway/*.log:/var/log/app/',

  tail_lines:
    'Maximum number of lines to read from the tail of each log file per diagnostic ' +
    'request. Higher values give more context but use more memory. ' +
    '10 000 lines ≈ 30–60 minutes of typical Spring Boot traffic. ' +
    'Minimum: 100. Default: 10 000.',

  anomaly_threshold:
    'IsolationForest score below which a log window is flagged as anomalous. ' +
    'Scores range from roughly −0.5 (very anomalous) to +0.1 (very normal). ' +
    'The default −0.05 is a conservative starting point — lower it (e.g. −0.10) ' +
    'to reduce false positives, raise it (e.g. 0.0) to catch more borderline windows. ' +
    'This value is patched directly into the .pkl without retraining.',

  contamination:
    'Expected fraction of anomalous windows in your training corpus, used by ' +
    'IsolationForest to set its internal decision boundary. ' +
    'Must be between 0.01 and 0.49. The synthetic corpus auto-computes this from ' +
    'labelled data (~0.30). For production logs where most traffic is healthy, ' +
    '0.05–0.10 is typical. Changing this requires a retrain to take effect.',

  epochs:
    'Number of autoencoder training epochs for the WindowEmbedder (TF-IDF → 102-dim ' +
    'projection). More epochs = better embeddings but longer training time. ' +
    '40 is the recommended default; 20 is sufficient for a quick baseline.',

  train_log_path:
    'Optional: path to a real production log file to mix into the synthetic training ' +
    'corpus. Real windows are treated as healthy (unlabelled). Leave empty to train ' +
    'on the synthetic corpus only — this is fine for a first deployment.',

  evaluate:
    'After training, run precision/recall/F1 evaluation on the synthetic labelled ' +
    'corpus and include the metrics in the training log. Useful for comparing ' +
    'threshold/contamination settings without needing labelled production data.',
}

function HelpTip({ field }: { field: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-block ml-1">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-gray-400 hover:text-blue-500 text-xs leading-none align-middle"
        aria-label="Help"
      >
        ⓘ
      </button>
      {open && (
        <div className="absolute z-10 left-0 top-5 w-72 bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs text-gray-600 leading-relaxed">
          {HELP[field]}
          <button onClick={() => setOpen(false)} className="block mt-2 text-blue-500 hover:underline">
            Close
          </button>
        </div>
      )}
    </span>
  )
}

function NeuralSettings() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    scorer_path: '',
    log_path: '',
    log_paths: '',
    tail_lines: 10000,
    anomaly_threshold: -0.05,
    contamination: 0.1,
  })
  const [loaded, setLoaded] = useState(false)
  const [trainForm, setTrainForm] = useState({
    epochs: 40,
    threshold: -0.05,
    contamination: '',
    log_path: '',
    evaluate: false,
  })
  const [trainLog, setTrainLog] = useState('')
  const [pollInterval, setPollInterval] = useState<number | false>(false)

  const { data } = useQuery({
    queryKey: ['neural-settings'],
    queryFn: async () => (await api.get('/settings/neural')).data,
  })

  useEffect(() => {
    if (data && !loaded) {
      setForm({
        scorer_path: data.scorer_path || '',
        log_path: data.log_path || '',
        log_paths: data.log_paths || '',
        tail_lines: data.tail_lines ?? 10000,
        anomaly_threshold: data.anomaly_threshold ?? -0.05,
        contamination: data.contamination ?? 0.1,
      })
      setLoaded(true)
    }
  }, [data, loaded])

  // Poll training status while a job is running
  const { data: trainStatus } = useQuery({
    queryKey: ['neural-train-status'],
    queryFn: async () => (await api.get('/settings/neural/train')).data,
    refetchInterval: pollInterval,
  })

  useEffect(() => {
    if (!trainStatus) return
    if (trainStatus.status === 'running') {
      setPollInterval(2000)
    } else {
      setPollInterval(false)
      if (trainStatus.log) setTrainLog(trainStatus.log)
      if (trainStatus.status === 'completed') {
        queryClient.invalidateQueries({ queryKey: ['neural-settings'] })
        setLoaded(false)
      }
    }
  }, [trainStatus, queryClient])

  const saveMutation = useMutation({
    mutationFn: () => api.put('/settings/neural', {
      scorer_path: form.scorer_path || null,
      log_path: form.log_path || null,
      log_paths: form.log_paths || null,
      tail_lines: form.tail_lines,
      anomaly_threshold: form.anomaly_threshold,
      contamination: form.contamination,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['neural-settings'] })
      setLoaded(false)
    },
  })

  const trainMutation = useMutation({
    mutationFn: () => api.post('/settings/neural/train', {
      epochs: trainForm.epochs,
      threshold: trainForm.threshold,
      contamination: trainForm.contamination ? parseFloat(trainForm.contamination) : null,
      log_path: trainForm.log_path || null,
      evaluate: trainForm.evaluate,
    }),
    onSuccess: () => {
      setTrainLog('')
      setPollInterval(2000)
      queryClient.invalidateQueries({ queryKey: ['neural-train-status'] })
    },
  })

  const upd = (k: string, v: any) => setForm(p => ({ ...p, [k]: v }))
  const updT = (k: string, v: any) => setTrainForm(p => ({ ...p, [k]: v }))

  const model = data?.model
  const isTraining = trainStatus?.status === 'running'

  return (
    <section className="bg-white rounded-lg border border-purple-200 p-5">
      <div className="flex items-center gap-2 mb-1">
        <h3 className="font-semibold text-gray-900">🧠 Neural ML Layer</h3>
        {model?.present
          ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">Model loaded</span>
          : <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">No model — stack-trace-only mode</span>
        }
      </div>
      <p className="text-sm text-gray-500 mb-4">
        Configure the Phase 5 ML diagnostic pipeline. All settings degrade gracefully —
        the pipeline runs in stack-trace-only mode when no scorer model is present.
      </p>

      {/* Model info */}
      {model?.present && (
        <div className="mb-4 p-3 bg-purple-50 border border-purple-100 rounded text-xs text-gray-600 space-y-0.5">
          <p><span className="text-gray-400">Path:</span> {model.path}</p>
          <p><span className="text-gray-400">Size:</span> {model.size_kb} KB</p>
          <p><span className="text-gray-400">Last trained:</span> {model.mtime ? new Date(model.mtime * 1000).toLocaleString() : '—'}</p>
        </div>
      )}

      <div className="space-y-4">
        {/* Paths */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-3">Paths</p>
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Scorer Model Path <HelpTip field="scorer_path" />
              </label>
              <input type="text" value={form.scorer_path} onChange={e => upd('scorer_path', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="/data/models/anomaly_scorer.pkl" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Log File Path <HelpTip field="log_path" />
              </label>
              <input type="text" value={form.log_path} onChange={e => upd('log_path', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="/var/log/ecs/fulfillment/application.log" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Additional Log Paths <HelpTip field="log_paths" />
              </label>
              <input type="text" value={form.log_paths} onChange={e => upd('log_paths', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="/var/log/gateway/*.log:/var/log/app/ (colon-separated)" />
            </div>
          </div>
        </div>

        {/* Tuning */}
        <div className="border-t border-gray-100 pt-3">
          <p className="text-xs font-medium text-gray-500 uppercase mb-3">Tuning</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Tail Lines <HelpTip field="tail_lines" />
              </label>
              <input type="number" value={form.tail_lines} onChange={e => upd('tail_lines', Number(e.target.value))}
                min={100} max={100000} step={1000}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anomaly Threshold <HelpTip field="anomaly_threshold" />
              </label>
              <input type="number" value={form.anomaly_threshold}
                onChange={e => upd('anomaly_threshold', parseFloat(e.target.value))}
                min={-0.5} max={0.1} step={0.01}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
              <p className="text-xs text-gray-400 mt-1">Patched into .pkl immediately — no retrain needed.</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Contamination <HelpTip field="contamination" />
              </label>
              <input type="number" value={form.contamination}
                onChange={e => upd('contamination', parseFloat(e.target.value))}
                min={0.01} max={0.49} step={0.01}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
              <p className="text-xs text-gray-400 mt-1">Requires retrain to take effect.</p>
            </div>
          </div>
        </div>

        <button onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-md hover:bg-purple-700 disabled:opacity-50">
          {saveMutation.isPending ? 'Saving...' : 'Save Neural Settings'}
        </button>
        {saveMutation.isSuccess && <p className="text-green-600 text-sm">✓ Settings saved.</p>}
        {saveMutation.isError && <p className="text-red-600 text-sm">✗ Failed to save.</p>}

        {/* Training */}
        <div className="border-t border-gray-100 pt-4">
          <p className="text-xs font-medium text-gray-500 uppercase mb-3">Retrain Scorer</p>
          <p className="text-sm text-gray-500 mb-3">
            Trains a new AnomalyScorer from the synthetic corpus (optionally mixed with real logs)
            and saves it to the configured scorer path. The new model is live on the next request.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Epochs <HelpTip field="epochs" />
              </label>
              <input type="number" value={trainForm.epochs} onChange={e => updT('epochs', Number(e.target.value))}
                min={5} max={200}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Anomaly Threshold (for new model) <HelpTip field="anomaly_threshold" />
              </label>
              <input type="number" value={trainForm.threshold}
                onChange={e => updT('threshold', parseFloat(e.target.value))}
                min={-0.5} max={0.1} step={0.01}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Contamination override <HelpTip field="contamination" />
              </label>
              <input type="text" value={trainForm.contamination}
                onChange={e => updT('contamination', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="Leave empty to auto-compute from corpus" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Real Log Path (optional) <HelpTip field="train_log_path" />
              </label>
              <input type="text" value={trainForm.log_path} onChange={e => updT('log_path', e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                placeholder="/var/log/ecs/fulfillment/application.log" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700 mb-3">
            <input type="checkbox" checked={trainForm.evaluate} onChange={e => updT('evaluate', e.target.checked)} />
            Run precision/recall evaluation after training <HelpTip field="evaluate" />
          </label>

          <button onClick={() => trainMutation.mutate()}
            disabled={trainMutation.isPending || isTraining}
            className="px-4 py-2 bg-gray-800 text-white text-sm font-medium rounded-md hover:bg-gray-900 disabled:opacity-50">
            {isTraining ? '⏳ Training…' : '▶ Start Training'}
          </button>
          {trainMutation.isError && <p className="text-red-600 text-sm mt-2">✗ Failed to start training job.</p>}

          {/* Training log */}
          {(isTraining || trainLog) && (
            <div className="mt-3">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-xs font-medium text-gray-500">Training output</p>
                {isTraining && <span className="text-xs text-purple-600 animate-pulse">● running</span>}
                {trainStatus?.status === 'completed' && <span className="text-xs text-green-600">✓ completed</span>}
                {trainStatus?.status === 'failed' && <span className="text-xs text-red-600">✗ failed</span>}
              </div>
              <pre className="bg-gray-900 text-green-400 text-xs rounded-md p-3 overflow-auto max-h-64 whitespace-pre-wrap">
                {isTraining ? (trainStatus?.log || 'Starting…') : trainLog}
              </pre>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
