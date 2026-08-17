import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'

interface Host {
  id: string
  hostname: string
  ip: string
  connection_type: string
  container_name: string
  ansible_host: string
  port: number
  ssh_user: string
  os_type: string
  os_version: string
  service_role: string
  tags: string
  status: string
  last_seen: string | null
  groups: { id: string; name: string }[]
  ssh_auth_method: string
  ssh_credential_set: boolean
  host_key_pinned: boolean
  host_key_pinned_at: string | null
}

interface HostGroup {
  id: string
  name: string
  description: string
  member_count: number
}

interface NetworkPool {
  id: string
  name: string
  cidr: string
  gateway: string
  dns_servers: string
  reserved: string[]
  description: string
  created_at: string
}

const SERVICE_ROLES = ['frontend', 'backend', 'mysql', 'rabbitmq', 'keystone', 'generic']
const SSH_AUTH_METHODS = ['shared_key', 'private_key', 'password'] as const
const SSH_AUTH_LABELS: Record<string, string> = {
  shared_key: 'Shared key (default)', private_key: 'Per-host private key', password: 'Per-host password',
}

function apiError(e: any): string {
  const detail = e?.response?.data?.detail
  if (!detail) return 'Request failed'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d: any) => {
    const field = Array.isArray(d.loc) ? d.loc.filter((s: any) => s !== 'body').join('.') : null
    const msg = d.msg ?? JSON.stringify(d)
    return field ? `${field}: ${msg}` : msg
  }).join('; ')
  return JSON.stringify(detail)
}

export default function InventoryPage() {
  const [hosts, setHosts] = useState<Host[]>([])
  const [groups, setGroups] = useState<HostGroup[]>([])
  const [pools, setPools] = useState<NetworkPool[]>([])
  const [tab, setTab] = useState<'hosts' | 'groups' | 'pools'>('hosts')
  const [showAddHost, setShowAddHost] = useState(false)
  const [showAddGroup, setShowAddGroup] = useState(false)
  const [showAddPool, setShowAddPool] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string; latency_ms?: number; host_key_status?: string | null } | null>(null)
  const [error, setError] = useState('')

  // Host form
  const [form, setForm] = useState({
    hostname: '', ip: '', connection_type: 'docker', container_name: '', port: 22, ssh_user: 'root',
    os_type: 'ubuntu', os_version: '24.04', service_role: 'generic', tags: '', group_ids: [] as string[],
    ssh_auth_method: 'shared_key', ssh_credential: '',
  })
  const [selectedPoolId, setSelectedPoolId] = useState('')
  const [availableIps, setAvailableIps] = useState<string[]>([])
  const [ipMode, setIpMode] = useState<'pool' | 'manual'>('pool')
  const [editSsh, setEditSsh] = useState<{ id: string; hostname: string; auth_method: string; credential: string } | null>(null)
  const [osFamilies, setOsFamilies] = useState<{ name: string; display_name: string; versions: { version: string; display_name: string; is_latest: boolean }[] }[]>([])

  const [groupForm, setGroupForm] = useState({ name: '', description: '' })
  const [poolForm, setPoolForm] = useState({ name: '', cidr: '', gateway: '', dns_servers: '', reserved: '', description: '' })
  const [poolMode, setPoolMode] = useState<'manual' | 'docker'>('manual')
  const [dockerNetworks, setDockerNetworks] = useState<{name: string; cidr: string; gateway: string; allocated_ips: string[]}[]>([])
  const [dockerNetworksLoading, setDockerNetworksLoading] = useState(false)
  const [showCreateNetwork, setShowCreateNetwork] = useState(false)
  const [newNetName, setNewNetName] = useState('')
  const [newNetSubnet, setNewNetSubnet] = useState('')
  const [creatingNetwork, setCreatingNetwork] = useState(false)

  const loadHosts = useCallback(async () => {
    try {
      const res = await api.get('/build/hosts')
      setHosts(res.data)
    } catch { setError('Failed to load hosts') }
  }, [])

  const loadGroups = useCallback(async () => {
    try {
      const res = await api.get('/build/groups')
      setGroups(res.data)
    } catch { setError('Failed to load groups') }
  }, [])

  const loadPools = useCallback(async () => {
    try {
      const res = await api.get('/build/network-pools')
      setPools(res.data)
    } catch { /* pools are optional */ }
  }, [])

  useEffect(() => { loadHosts(); loadGroups(); loadPools() }, [loadHosts, loadGroups, loadPools])

  useEffect(() => {
    api.get('/build/os-catalogue').then(res => {
      setOsFamilies(res.data)
      // Form starts with a hardcoded ubuntu/24.04 default before this fetch
      // resolves — if an admin has since removed/renamed that family (the
      // catalogue is admin-editable), snap to a combination that actually
      // exists rather than silently submitting an invalid os_type/os_version.
      setForm(f => {
        const family = res.data.find((fam: { name: string }) => fam.name === f.os_type)
        if (family?.versions.some((v: { version: string }) => v.version === f.os_version)) return f
        const fallbackFamily = family || res.data[0]
        const fallbackVersion = fallbackFamily?.versions.find((v: { is_latest: boolean }) => v.is_latest)?.version || fallbackFamily?.versions[0]?.version || ''
        return fallbackFamily ? { ...f, os_type: fallbackFamily.name, os_version: fallbackVersion } : f
      })
    }).catch(() => {})
  }, [])

  // When pool selection changes, fetch available IPs
  useEffect(() => {
    if (!selectedPoolId) { setAvailableIps([]); return }
    api.get(`/build/network-pools/${selectedPoolId}/available?count=50`)
      .then(res => setAvailableIps(res.data.available || []))
      .catch(() => setAvailableIps([]))
  }, [selectedPoolId])

  // Default to manual mode if no pools exist
  useEffect(() => {
    if (pools.length === 0) setIpMode('manual')
    else setIpMode('pool')
  }, [pools])

  const addHost = async () => {
    try {
      const { ssh_credential, ...rest } = form
      await api.post('/build/hosts', { ...rest, ...(ssh_credential ? { ssh_credential } : {}) })
      setShowAddHost(false)
      setForm({ hostname: '', ip: '', connection_type: 'docker', container_name: '', port: 22, ssh_user: 'root', os_type: 'ubuntu', os_version: '24.04', service_role: 'generic', tags: '', group_ids: [], ssh_auth_method: 'shared_key', ssh_credential: '' })
      setSelectedPoolId('')
      setAvailableIps([])
      loadHosts()
    } catch (e: any) { setError(apiError(e)) }
  }

  const saveSshAuth = async () => {
    if (!editSsh) return
    try {
      const body: Record<string, string> = { ssh_auth_method: editSsh.auth_method }
      if (editSsh.auth_method !== 'shared_key' && editSsh.credential) body.ssh_credential = editSsh.credential
      await api.put(`/build/hosts/${editSsh.id}`, body)
      setEditSsh(null)
      loadHosts()
    } catch (e: any) { setError(apiError(e)) }
  }

  const loadDockerNetworks = async () => {
    setDockerNetworksLoading(true)
    try {
      const res = await api.get('/build/network-pools/docker-networks')
      setDockerNetworks(res.data)
    } catch { setDockerNetworks([]) }
    setDockerNetworksLoading(false)
  }

  const createDockerNetwork = async () => {
    if (!newNetName.trim()) return
    setCreatingNetwork(true)
    try {
      const res = await api.post('/build/network-pools/docker-networks', {
        name: newNetName.trim(),
        subnet: newNetSubnet.trim(),
      })
      selectDockerNetwork(res.data)
      setShowCreateNetwork(false)
      setNewNetName('')
      setNewNetSubnet('')
      await loadDockerNetworks()
    } catch (e: any) { setError(apiError(e)) }
    setCreatingNetwork(false)
  }

  const selectDockerNetwork = (net: {name: string; cidr: string; gateway: string; allocated_ips: string[]}) => {
    setPoolForm({
      name: net.name,
      cidr: net.cidr,
      gateway: net.gateway,
      dns_servers: net.gateway || '',
      reserved: [net.gateway, ...net.allocated_ips].filter(Boolean).join(', '),
      description: `Docker network: ${net.name}`,
    })
  }

  const addPool = async () => {
    try {
      await api.post('/build/network-pools', {
        ...poolForm,
        reserved: poolForm.reserved ? poolForm.reserved.split(',').map(s => s.trim()) : []
      })
      setShowAddPool(false)
      setPoolForm({ name: '', cidr: '', gateway: '', dns_servers: '', reserved: '', description: '' })
      loadPools()
    } catch (e: any) { setError(apiError(e)) }
  }

  const deletePool = async (id: string) => {
    if (!confirm('Delete this network pool?')) return
    await api.delete(`/build/network-pools/${id}`)
    loadPools()
  }

  const deleteHost = async (id: string) => {
    if (!confirm('Delete this host?')) return
    await api.delete(`/build/hosts/${id}`)
    loadHosts()
  }

  const testHost = async (id: string) => {
    setTesting(id)
    setTestResult(null)
    try {
      const res = await api.post(`/build/hosts/${id}/test`)
      setTestResult({ id, ...res.data })
      loadHosts()
    } catch { setTestResult({ id, success: false, message: 'Test request failed' }) }
    setTesting(null)
  }

  const acceptHostKey = async (id: string) => {
    if (!confirm('Re-pin this host to its currently-observed SSH host key? Only do this if you\'ve confirmed the change is legitimate (e.g. the host was reinstalled).')) return
    try {
      await api.post(`/build/hosts/${id}/accept-host-key`)
      setTestResult(null)
      loadHosts()
    } catch (e: any) { setTestResult({ id, success: false, message: e.response?.data?.detail || 'Accept failed' }) }
  }

  const addGroup = async () => {
    try {
      await api.post('/build/groups', groupForm)
      setShowAddGroup(false)
      setGroupForm({ name: '', description: '' })
      loadGroups()
    } catch (e: any) { setError(apiError(e)) }
  }

  const deleteGroup = async (id: string) => {
    if (!confirm('Delete this group?')) return
    await api.delete(`/build/groups/${id}`)
    loadGroups()
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      online: 'bg-green-100 text-green-800',
      offline: 'bg-red-100 text-red-800',
      unknown: 'bg-gray-100 text-gray-600',
    }
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || colors.unknown}`}>{status}</span>
  }

  const roleBadge = (role: string) => {
    const colors: Record<string, string> = {
      frontend: 'bg-blue-100 text-blue-800',
      backend: 'bg-purple-100 text-purple-800',
      mysql: 'bg-orange-100 text-orange-800',
      rabbitmq: 'bg-green-100 text-green-800',
      keystone: 'bg-yellow-100 text-yellow-800',
      generic: 'bg-gray-100 text-gray-600',
    }
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[role] || colors.generic}`}>{role}</span>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Build Manager — Inventory</h1>
          <p className="text-sm text-gray-500 mt-1">Manage target hosts and groups for Ansible deployments</p>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-500 hover:text-red-700">✕</button>
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-4">
          <button onClick={() => setTab('hosts')}
            className={`pb-2 px-1 text-sm font-medium border-b-2 ${tab === 'hosts' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            Hosts ({hosts.length})
          </button>
          <button onClick={() => setTab('groups')}
            className={`pb-2 px-1 text-sm font-medium border-b-2 ${tab === 'groups' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            Groups ({groups.length})
          </button>
          <button onClick={() => setTab('pools')}
            className={`pb-2 px-1 text-sm font-medium border-b-2 ${tab === 'pools' ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            Network Pools ({pools.length})
          </button>
        </nav>
      </div>

      {/* Hosts Tab */}
      {tab === 'hosts' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowAddHost(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
              + Add Host
            </button>
          </div>

          {showAddHost && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <h3 className="font-medium text-gray-900">Add Host</h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <input placeholder="Hostname" value={form.hostname} onChange={e => setForm({ ...form, hostname: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                {/* Connection Type */}
                <div className="space-y-1">
                  <label className="text-xs text-gray-500">Connection Type</label>
                  <select value={form.connection_type} onChange={e => setForm({ ...form, connection_type: e.target.value })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
                    <option value="docker">Docker Container</option>
                    <option value="ssh">SSH (Real Host/VM)</option>
                  </select>
                </div>
                {/* Container name (docker only) */}
                {form.connection_type === 'docker' && (
                  <input placeholder="Container Name (e.g. target-test)" value={form.container_name}
                    onChange={e => setForm({ ...form, container_name: e.target.value })}
                    className="border border-gray-300 rounded px-3 py-2 text-sm" />
                )}
                {/* IP Address - pool picker or manual */}
                <div className="space-y-1">
                  {pools.length > 0 && (
                    <div className="flex gap-2 text-xs">
                      <label className="flex items-center gap-1">
                        <input type="radio" name="ipMode" checked={ipMode === 'pool'} onChange={() => setIpMode('pool')} />
                        From Pool
                      </label>
                      <label className="flex items-center gap-1">
                        <input type="radio" name="ipMode" checked={ipMode === 'manual'} onChange={() => setIpMode('manual')} />
                        Manual
                      </label>
                    </div>
                  )}
                  {ipMode === 'pool' && pools.length > 0 ? (
                    <div className="flex gap-1">
                      <select value={selectedPoolId} onChange={e => { setSelectedPoolId(e.target.value); setForm({ ...form, ip: '' }) }}
                        className="border border-gray-300 rounded px-2 py-2 text-sm w-1/2">
                        <option value="">Pool…</option>
                        {pools.map(p => <option key={p.id} value={p.id}>{p.name} ({p.cidr})</option>)}
                      </select>
                      <select value={form.ip} onChange={e => setForm({ ...form, ip: e.target.value })}
                        className="border border-gray-300 rounded px-2 py-2 text-sm w-1/2" disabled={!selectedPoolId}>
                        <option value="">Select IP…</option>
                        {availableIps.map(ip => <option key={ip} value={ip}>{ip}</option>)}
                      </select>
                    </div>
                  ) : (
                    <input placeholder="IP Address" value={form.ip} onChange={e => setForm({ ...form, ip: e.target.value })}
                      className="border border-gray-300 rounded px-3 py-2 text-sm w-full" />
                  )}
                </div>
                <input placeholder="Port" type="number" value={form.port} onChange={e => setForm({ ...form, port: parseInt(e.target.value) || 22 })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="SSH User" value={form.ssh_user} onChange={e => setForm({ ...form, ssh_user: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <select value={form.os_type} onChange={e => {
                    const family = osFamilies.find(f => f.name === e.target.value)
                    const defaultVersion = family?.versions.find(v => v.is_latest)?.version || family?.versions[0]?.version || ''
                    setForm({ ...form, os_type: e.target.value, os_version: defaultVersion })
                  }}
                  className="border border-gray-300 rounded px-3 py-2 text-sm">
                  {osFamilies.map(t => <option key={t.name} value={t.name}>{t.display_name}</option>)}
                </select>
                <select value={form.os_version} onChange={e => setForm({ ...form, os_version: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm">
                  {(osFamilies.find(f => f.name === form.os_type)?.versions || []).map(v => (
                    <option key={v.version} value={v.version}>{v.display_name}</option>
                  ))}
                </select>
                <select value={form.service_role} onChange={e => setForm({ ...form, service_role: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm">
                  {SERVICE_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <input placeholder="Tags (comma-separated)" value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <div className="space-y-1">
                  <label className="text-xs text-gray-500">SSH Auth Method</label>
                  <select value={form.ssh_auth_method} onChange={e => setForm({ ...form, ssh_auth_method: e.target.value, ssh_credential: '' })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
                    {SSH_AUTH_METHODS.map(m => <option key={m} value={m}>{SSH_AUTH_LABELS[m]}</option>)}
                  </select>
                </div>
                {form.ssh_auth_method === 'private_key' && (
                  <textarea placeholder="Private key (PEM)" value={form.ssh_credential} onChange={e => setForm({ ...form, ssh_credential: e.target.value })}
                    rows={2} className="border border-gray-300 rounded px-3 py-2 text-sm font-mono col-span-2" />
                )}
                {form.ssh_auth_method === 'password' && (
                  <input type="password" placeholder="SSH Password" value={form.ssh_credential} onChange={e => setForm({ ...form, ssh_credential: e.target.value })}
                    className="border border-gray-300 rounded px-3 py-2 text-sm" />
                )}
              </div>
              {groups.length > 0 && (
                <div>
                  <label className="text-xs text-gray-500">Groups:</label>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {groups.map(g => (
                      <label key={g.id} className="flex items-center gap-1 text-sm">
                        <input type="checkbox" checked={form.group_ids.includes(g.id)}
                          onChange={e => {
                            const ids = e.target.checked ? [...form.group_ids, g.id] : form.group_ids.filter(id => id !== g.id)
                            setForm({ ...form, group_ids: ids })
                          }} />
                        {g.name}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex gap-2">
                <button type="button" onClick={addHost} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Save</button>
                <button type="button" onClick={() => setShowAddHost(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
              </div>
            </div>
          )}

          {/* Host Table */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Host</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">IP</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Role</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">OS</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Groups</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {hosts.map(host => (
                  <tr key={host.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900">{host.hostname}</div>
                      <div className="text-xs text-gray-500">
                        {host.connection_type === 'docker' ? `🐳 ${host.container_name || host.hostname}` : `🖥️ ${host.ssh_user}@${host.ip}:${host.port}`}
                      </div>
                      {host.ssh_auth_method && host.ssh_auth_method !== 'shared_key' && (
                        <div className="text-xs text-amber-600 mt-0.5">
                          🔑 {SSH_AUTH_LABELS[host.ssh_auth_method] || host.ssh_auth_method}{host.ssh_credential_set ? '' : ' (not set)'}
                        </div>
                      )}
                      {host.connection_type === 'ssh' && (
                        <div className="text-xs text-gray-400 mt-0.5" title={host.host_key_pinned ? `Pinned ${host.host_key_pinned_at}` : 'Not yet pinned — will pin on next successful test/build'}>
                          {host.host_key_pinned ? '🔒 key pinned' : '🔓 key not pinned'}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-gray-700 font-mono text-xs">
                      {host.ip}
                      {host.connection_type === 'docker' && host.container_name && (
                        <div className="text-gray-400">→ {host.container_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">{roleBadge(host.service_role)}</td>
                    <td className="px-4 py-3 text-gray-600">{host.os_type} {host.os_version}</td>
                    <td className="px-4 py-3">{statusBadge(host.status)}</td>
                    <td className="px-4 py-3 text-xs text-gray-500">{host.groups.map(g => g.name).join(', ') || '—'}</td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button onClick={() => testHost(host.id)} disabled={testing === host.id}
                        className="text-xs px-2 py-1 bg-green-50 text-green-700 rounded hover:bg-green-100 disabled:opacity-50">
                        {testing === host.id ? '⏳' : '🔌'} Test
                      </button>
                      <button onClick={() => setEditSsh({ id: host.id, hostname: host.hostname, auth_method: host.ssh_auth_method || 'shared_key', credential: '' })}
                        className="text-xs px-2 py-1 bg-amber-50 text-amber-700 rounded hover:bg-amber-100">
                        🔑 SSH
                      </button>
                      <button onClick={() => deleteHost(host.id)}
                        className="text-xs px-2 py-1 bg-red-50 text-red-700 rounded hover:bg-red-100">
                        🗑️
                      </button>
                    </td>
                  </tr>
                ))}
                {hosts.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-400">No hosts configured. Add one to get started.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Test Result */}
          {testResult && (
            <div className={`p-3 rounded-md text-sm ${testResult.success ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-800'}`}>
              <span className="font-medium">{testResult.success ? '✓ Connected' : '✗ Failed'}:</span> {testResult.message}
              {testResult.latency_ms && <span className="ml-2 text-xs">({testResult.latency_ms}ms)</span>}
              {!testResult.success && testResult.host_key_status?.includes('CHANGED') && (
                <button onClick={() => acceptHostKey(testResult.id)}
                  className="ml-3 text-xs px-2 py-1 bg-red-100 text-red-800 rounded hover:bg-red-200 font-medium">
                  ⚠ Accept New Key
                </button>
              )}
            </div>
          )}

          {/* Edit SSH Auth Modal */}
          {editSsh && (
            <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setEditSsh(null)}>
              <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3 w-full max-w-md" onClick={e => e.stopPropagation()}>
                <h3 className="font-medium text-gray-900">SSH Credentials — {editSsh.hostname}</h3>
                <div className="space-y-1">
                  <label className="text-xs text-gray-500">SSH Auth Method</label>
                  <select value={editSsh.auth_method}
                    onChange={e => setEditSsh({ ...editSsh, auth_method: e.target.value, credential: '' })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
                    {SSH_AUTH_METHODS.map(m => <option key={m} value={m}>{SSH_AUTH_LABELS[m]}</option>)}
                  </select>
                </div>
                {editSsh.auth_method === 'private_key' && (
                  <textarea placeholder="Private key (PEM) — leave blank to keep the current key" value={editSsh.credential}
                    onChange={e => setEditSsh({ ...editSsh, credential: e.target.value })}
                    rows={4} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" />
                )}
                {editSsh.auth_method === 'password' && (
                  <input type="password" placeholder="SSH Password — leave blank to keep the current password" value={editSsh.credential}
                    onChange={e => setEditSsh({ ...editSsh, credential: e.target.value })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm" />
                )}
                {editSsh.auth_method === 'shared_key' && (
                  <p className="text-xs text-gray-500">Reverting to the shared key clears any per-host credential stored for this host.</p>
                )}
                <div className="flex gap-2">
                  <button type="button" onClick={saveSshAuth} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Save</button>
                  <button type="button" onClick={() => setEditSsh(null)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Groups Tab */}
      {tab === 'groups' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowAddGroup(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
              + Add Group
            </button>
          </div>

          {showAddGroup && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <h3 className="font-medium text-gray-900">Add Group</h3>
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Group Name" value={groupForm.name} onChange={e => setGroupForm({ ...groupForm, name: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="Description" value={groupForm.description} onChange={e => setGroupForm({ ...groupForm, description: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={addGroup} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Save</button>
                <button type="button" onClick={() => setShowAddGroup(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {groups.map(group => (
              <div key={group.id} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-gray-900">{group.name}</h3>
                  <button onClick={() => deleteGroup(group.id)} className="text-xs text-red-500 hover:text-red-700">🗑️</button>
                </div>
                <p className="text-sm text-gray-500 mt-1">{group.description || 'No description'}</p>
                <p className="text-xs text-gray-400 mt-2">{group.member_count} member{group.member_count !== 1 ? 's' : ''}</p>
              </div>
            ))}
            {groups.length === 0 && (
              <p className="text-gray-400 text-sm col-span-full text-center py-8">No groups defined.</p>
            )}
          </div>
        </div>
      )}

      {/* Network Pools Tab */}
      {tab === 'pools' && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowAddPool(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
              + Add Pool
            </button>
          </div>

          {showAddPool && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="font-medium text-gray-900">Add Network Pool</h3>
                <div className="flex gap-2 text-xs">
                  <label className="flex items-center gap-1">
                    <input type="radio" name="poolMode" checked={poolMode === 'manual'} onChange={() => setPoolMode('manual')} />
                    Manual
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="radio" name="poolMode" checked={poolMode === 'docker'}
                      onChange={() => { setPoolMode('docker'); if (dockerNetworks.length === 0) loadDockerNetworks() }} />
                    From Docker Network
                  </label>
                </div>
              </div>

              {/* Docker network picker */}
              {poolMode === 'docker' && (
                <div className="border border-blue-100 bg-blue-50 rounded-lg p-3 space-y-3">
                  {dockerNetworksLoading ? (
                    <p className="text-sm text-gray-500">Loading Docker networks...</p>
                  ) : (
                    <>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {dockerNetworks.map(net => (
                          <button type="button" key={net.name} onClick={() => selectDockerNetwork(net)}
                            className={`text-left p-2 border rounded-md hover:border-blue-400 hover:bg-white ${
                              poolForm.name === net.name ? 'border-blue-500 bg-white' : 'border-gray-200'
                            }`}>
                            <div className="text-sm font-medium">🐳 {net.name}</div>
                            <div className="text-xs text-gray-500 font-mono">{net.cidr}</div>
                            <div className="text-xs text-gray-400">GW: {net.gateway || 'none'} · {net.allocated_ips.length} allocated</div>
                          </button>
                        ))}
                        <button type="button" onClick={() => setShowCreateNetwork(v => !v)}
                          className="text-left p-2 border border-dashed border-blue-300 rounded-md hover:border-blue-500 hover:bg-white text-blue-600">
                          <div className="text-sm font-medium">＋ Create new network</div>
                          <div className="text-xs text-gray-400">Docker auto-assigns gateway &amp; DNS</div>
                        </button>
                      </div>
                      {showCreateNetwork && (
                        <div className="bg-white border border-blue-200 rounded-md p-3 space-y-2">
                          <p className="text-xs text-gray-500">Docker will create a bridge network with NAT, internet routing, and embedded DNS (<code>127.0.0.11</code>). Leave subnet blank to let Docker pick one automatically.</p>
                          <div className="flex gap-2">
                            <input
                              placeholder="Network name (e.g. certmanager-net)"
                              value={newNetName}
                              onChange={e => setNewNetName(e.target.value)}
                              className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm"
                            />
                            <input
                              placeholder="Subnet (e.g. 172.20.0.0/16) — optional"
                              value={newNetSubnet}
                              onChange={e => setNewNetSubnet(e.target.value)}
                              className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm"
                            />
                            <button type="button" onClick={createDockerNetwork} disabled={creatingNetwork || !newNetName.trim()}
                              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50 shrink-0">
                              {creatingNetwork ? 'Creating…' : 'Create'}
                            </button>
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* Form fields (shown for both modes, pre-filled for docker) */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                <input placeholder="Pool Name" value={poolForm.name} onChange={e => setPoolForm({ ...poolForm, name: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="CIDR (e.g. 10.0.1.0/24)" value={poolForm.cidr} onChange={e => setPoolForm({ ...poolForm, cidr: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="Gateway (e.g. 10.0.1.1)" value={poolForm.gateway} onChange={e => setPoolForm({ ...poolForm, gateway: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="DNS Servers (comma-sep)" value={poolForm.dns_servers} onChange={e => setPoolForm({ ...poolForm, dns_servers: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="Reserved IPs (e.g. 10.0.1.1,10.0.1.2-10.0.1.5)" value={poolForm.reserved} onChange={e => setPoolForm({ ...poolForm, reserved: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
                <input placeholder="Description" value={poolForm.description} onChange={e => setPoolForm({ ...poolForm, description: e.target.value })}
                  className="border border-gray-300 rounded px-3 py-2 text-sm" />
              </div>
              <div className="flex gap-2">
                <button type="button" onClick={addPool} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Save</button>
                <button type="button" onClick={() => setShowAddPool(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pools.map(pool => (
              <div key={pool.id} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-gray-900">{pool.name}</h3>
                  <button onClick={() => deletePool(pool.id)} className="text-xs text-red-500 hover:text-red-700">🗑️</button>
                </div>
                <div className="mt-2 space-y-1 text-sm text-gray-600">
                  <p><span className="font-medium">CIDR:</span> <span className="font-mono">{pool.cidr}</span></p>
                  <p><span className="font-medium">Gateway:</span> <span className="font-mono">{pool.gateway}</span></p>
                  {pool.dns_servers && <p><span className="font-medium">DNS:</span> {pool.dns_servers}</p>}
                  {pool.reserved.length > 0 && <p><span className="font-medium">Reserved:</span> {pool.reserved.join(', ')}</p>}
                  {pool.description && <p className="text-gray-400 text-xs mt-1">{pool.description}</p>}
                </div>
              </div>
            ))}
            {pools.length === 0 && (
              <p className="text-gray-400 text-sm col-span-full text-center py-8">No network pools defined. Add one to enable IP selection when creating hosts.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
