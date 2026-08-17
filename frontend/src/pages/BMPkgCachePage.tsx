import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'

interface OsFamilyStatus {
  os_family: string
  label: string
  status: 'ready' | 'incomplete' | 'empty'
  package_count: number
  synced_at: string | null
  synced_by_host: string | null
  packages: string[]
}

interface BinStatus {
  nodejs_x64: boolean
  nodejs_arm64: boolean
  go_amd64: boolean
  go_arm64: boolean
}

interface CacheStatus {
  status: 'empty' | 'ready' | 'incomplete'
  message: string
  generated_at: string | null
  os_families: Record<string, OsFamilyStatus>
  bin: BinStatus
}

interface Host {
  id: string
  hostname: string
  os_type: string
  os_version: string
  service_role: string
}

const OS_ICONS: Record<string, string> = {
  Debian: '🟠',
  RedHat: '🔴',
  Alpine: '🔵',
}

const STATUS_STYLE = {
  ready:      'bg-green-50 border-green-200 text-green-800',
  incomplete: 'bg-yellow-50 border-yellow-200 text-yellow-800',
  empty:      'bg-gray-50 border-gray-200 text-gray-500',
}
const STATUS_ICON = { ready: '✅', incomplete: '⚠️', empty: '📭' }

export default function BMPkgCachePage() {
  const navigate = useNavigate()
  const [cacheStatus, setCacheStatus] = useState<CacheStatus | null>(null)
  const [hosts, setHosts] = useState<Host[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedFamily, setExpandedFamily] = useState<string | null>(null)

  // Sync host selections — one per OS family
  const [ubuntuHost, setUbuntuHost] = useState('')
  const [rhelHost, setRhelHost] = useState('')
  const [alpineHost, setAlpineHost] = useState('')

  const loadData = useCallback(async () => {
    try {
      const [statusRes, hostsRes] = await Promise.all([
        api.get('/build/pkg-cache/status'),
        api.get('/build/hosts'),
      ])
      setCacheStatus(statusRes.data)
      setHosts(hostsRes.data)
      setError(null)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to load cache status')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const handleSync = async () => {
    setSyncing(true)
    setError(null)
    try {
      const res = await api.post('/build/pkg-cache/sync', {
        ubuntu_host: ubuntuHost,
        rhel_host: rhelHost,
        alpine_host: alpineHost,
      })
      navigate(`/jobs?job_id=${res.data.job_id}`)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to start sync')
      setSyncing(false)
    }
  }

  // Filter hosts by OS family for the dropdowns
  const ubuntuHosts = hosts.filter(h => h.os_type === 'ubuntu' || h.os_type === 'debian')
  const rhelHosts   = hosts.filter(h => h.os_type === 'rhel' || h.os_type === 'centos' || h.os_type === 'almalinux' || h.os_type === 'rocky')
  const alpineHosts = hosts.filter(h => h.os_type === 'alpine')

  const anySyncHostSelected = ubuntuHost || rhelHost || alpineHost

  const osFamilyDefs = [
    { key: 'Debian',  label: 'Ubuntu / Debian', hosts: ubuntuHosts, value: ubuntuHost, setter: setUbuntuHost },
    { key: 'RedHat',  label: 'RHEL / CentOS',   hosts: rhelHosts,   value: rhelHost,   setter: setRhelHost },
    { key: 'Alpine',  label: 'Alpine',           hosts: alpineHosts, value: alpineHost, setter: setAlpineHost },
  ]

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Package Cache</h1>
        <p className="text-sm text-gray-500 mt-1">
          Pre-download catalogue packages per OS family for offline provisioning — eliminates
          network dependencies and package manager timeout failures during builds.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="text-sm text-gray-500">Loading…</div>
      ) : (
        <>
          {/* Overall status */}
          {cacheStatus && (
            <div className={`p-4 border rounded-lg ${STATUS_STYLE[cacheStatus.status]}`}>
              <div className="flex items-start gap-3">
                <span className="text-xl">{STATUS_ICON[cacheStatus.status]}</span>
                <div>
                  <p className="font-medium">{cacheStatus.message}</p>
                  {cacheStatus.generated_at && (
                    <p className="text-xs mt-0.5 opacity-70">
                      Last sync: {new Date(cacheStatus.generated_at).toLocaleString()}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Per-OS status cards */}
          {cacheStatus && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {osFamilyDefs.map(({ key, label }) => {
                const s = cacheStatus.os_families[key]
                if (!s) return null
                return (
                  <div
                    key={key}
                    className={`border rounded-lg p-4 cursor-pointer transition-colors ${STATUS_STYLE[s.status]} ${expandedFamily === key ? 'ring-2 ring-blue-400' : ''}`}
                    onClick={() => setExpandedFamily(expandedFamily === key ? null : key)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-sm">{OS_ICONS[key]} {label}</span>
                      <span className="text-lg">{STATUS_ICON[s.status]}</span>
                    </div>
                    <div className="text-2xl font-bold">{s.package_count}</div>
                    <div className="text-xs opacity-70">packages cached</div>
                    {s.synced_at && (
                      <div className="text-xs opacity-60 mt-1 truncate">
                        via {s.synced_by_host} · {new Date(s.synced_at).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Expanded package list */}
          {expandedFamily && (() => {
            const fam = cacheStatus?.os_families[expandedFamily]
            if (!fam || fam.packages.length === 0) return null
            return (
              <div className="bg-white border border-gray-200 rounded-lg p-4">
                <p className="text-sm font-medium text-gray-700 mb-2">
                  {OS_ICONS[expandedFamily]} {fam.label} — cached packages
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {fam.packages.map(pkg => (
                    <span key={pkg} className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs font-mono">{pkg}</span>
                  ))}
                </div>
              </div>
            )
          })()}

          {/* Binary tarballs */}
          {cacheStatus && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <p className="text-sm font-medium text-gray-700 mb-3">Binary Tarballs (OS-agnostic)</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {[
                  { label: 'Node.js x64',   cached: cacheStatus.bin.nodejs_x64 },
                  { label: 'Node.js arm64', cached: cacheStatus.bin.nodejs_arm64 },
                  { label: 'Go amd64',      cached: cacheStatus.bin.go_amd64 },
                  { label: 'Go arm64',      cached: cacheStatus.bin.go_arm64 },
                ].map(b => (
                  <div key={b.label} className={`rounded p-2 text-center text-xs border ${b.cached ? 'bg-green-50 border-green-200 text-green-700' : 'bg-gray-50 border-gray-200 text-gray-400'}`}>
                    <div className="text-base mb-0.5">{b.cached ? '✅' : '📭'}</div>
                    {b.label}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sync form */}
          <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
            <div>
              <h2 className="font-semibold text-gray-900">Sync Cache</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                Select one inventory host per OS family to sync. The host downloads packages
                native to its OS into the shared volume. Binaries (Node.js, Go) are always
                synced from this container regardless of host selection.
              </p>
            </div>

            <div className="space-y-3">
              {osFamilyDefs.map(({ key, label, hosts: familyHosts, value, setter }) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="w-36 text-sm text-gray-600 shrink-0">{OS_ICONS[key]} {label}</span>
                  <select
                    value={value}
                    onChange={e => setter(e.target.value)}
                    className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="">— skip —</option>
                    {familyHosts.length === 0 ? (
                      <option disabled>No {label} hosts in inventory</option>
                    ) : (
                      familyHosts.map(h => (
                        <option key={h.id} value={h.hostname}>
                          {h.hostname} ({h.os_type} {h.os_version})
                        </option>
                      ))
                    )}
                  </select>
                  {value && cacheStatus?.os_families[key] && cacheStatus.os_families[key]!.status === 'ready' && (
                    <span className="text-xs text-green-600 shrink-0">✓ cached</span>
                  )}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-1">
              <p className="text-xs text-gray-400">
                {anySyncHostSelected
                  ? 'Sync will run on selected hosts + download binaries on this container.'
                  : 'No OS hosts selected — only binary tarballs will be synced.'}
              </p>
              <button
                onClick={handleSync}
                disabled={syncing}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {syncing ? 'Starting…' : '🔄 Sync Cache'}
              </button>
            </div>
          </div>

          {/* How it works */}
          <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-2">
            <h2 className="font-semibold text-gray-900">How it works</h2>
            <ol className="text-sm text-gray-600 space-y-1.5 list-decimal list-inside">
              <li>Select one host per OS family and click <strong>Sync Cache</strong>. The sync job SSHes into each host and runs the native package manager download command there.</li>
              <li>Downloaded packages are saved into the shared Docker volume at <code className="bg-gray-100 px-1 rounded">/certmanager-data/pkg-cache/&lt;os&gt;/</code> — accessible read-only on all targets.</li>
              <li>At the start of every build, the <code className="bg-gray-100 px-1 rounded">local_repo</code> role detects the target OS and configures the matching local source (apt, dnf, or apk) at highest priority.</li>
              <li>All package installs resolve from the local cache — no internet access required during provisioning.</li>
            </ol>
            <p className="text-xs text-gray-400 pt-1">
              Re-sync after adding new catalogue products or monthly to pick up security patches.
              Each OS family is independent — you can sync Ubuntu without having a RHEL host.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
