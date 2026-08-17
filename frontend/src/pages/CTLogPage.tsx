import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface CTEntry {
  id: string
  log_index: number
  cert_serial: string
  cert_der_hash: string
  issuer_ca_id: string | null
  subject_cn: string
  san: { type: string; value: string }[]
  leaf_hash: string
  timestamp: string
  sct: { version: number; log_id: string; timestamp: number; log_index: number; signature: string } | null
}

interface TreeHead {
  tree_size: number
  root_hash: string
  timestamp: string
  signature: string
}

interface VerifyResult {
  total_entries: number
  computed_root: string
  issues: string[]
  consistent: boolean
  root_matches_stored: boolean
}

interface Anomaly {
  type: string
  severity: string
  log_index: number
  cert_serial: string
  subject_cn: string
  timestamp: string
  message: string
}

export default function CTLogPage() {
  const [entries, setEntries] = useState<CTEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [domain, setDomain] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [treeHead, setTreeHead] = useState<TreeHead | null>(null)
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [tab, setTab] = useState<'log' | 'verify' | 'anomalies'>('log')
  const [loading, setLoading] = useState(false)

  const fetchEntries = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '25' })
      if (domain) params.set('domain', domain)
      const res = await api.get(`/ct/entries?${params}`)
      setEntries(res.data.items)
      setTotal(res.data.total)
    } catch { /* ignore */ }
    setLoading(false)
  }

  const fetchTreeHead = async () => {
    try {
      const res = await api.get('/ct/sth')
      setTreeHead(res.data)
    } catch { /* ignore */ }
  }

  const runVerify = async () => {
    setLoading(true)
    try {
      const res = await api.post('/ct/verify')
      setVerifyResult(res.data)
    } catch { /* ignore */ }
    setLoading(false)
  }

  const fetchAnomalies = async () => {
    setLoading(true)
    try {
      const res = await api.get('/ct/anomalies')
      setAnomalies(res.data.alerts)
    } catch { /* ignore */ }
    setLoading(false)
  }

  useEffect(() => { fetchEntries(); fetchTreeHead() }, [page, domain])

  const handleSearch = () => {
    setPage(1)
    setDomain(searchInput)
  }

  const totalPages = Math.ceil(total / 25)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Certificate Transparency Log</h1>
        <p className="text-sm text-gray-500 mt-1">Append-only Merkle tree of all issued certificates</p>
      </div>

      {/* Tree Head Summary */}
      {treeHead && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-500">Tree Size</span>
              <p className="font-mono font-bold">{treeHead.tree_size}</p>
            </div>
            <div>
              <span className="text-gray-500">Root Hash</span>
              <p className="font-mono text-xs truncate" title={treeHead.root_hash}>{treeHead.root_hash.slice(0, 16)}…</p>
            </div>
            <div>
              <span className="text-gray-500">Last Updated</span>
              <p className="text-xs">{new Date(treeHead.timestamp).toLocaleString()}</p>
            </div>
            <div>
              <span className="text-gray-500">Signature</span>
              <p className="font-mono text-xs truncate" title={treeHead.signature}>{treeHead.signature.slice(0, 16)}…</p>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-gray-200">
        {(['log', 'verify', 'anomalies'] as const).map(t => (
          <button key={t} onClick={() => { setTab(t); if (t === 'verify') runVerify(); if (t === 'anomalies') fetchAnomalies() }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === t ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            {t === 'log' ? '📋 Log Entries' : t === 'verify' ? '✅ Verify Tree' : '⚠️ Anomalies'}
          </button>
        ))}
      </div>

      {/* Log Tab */}
      {tab === 'log' && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input value={searchInput} onChange={e => setSearchInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSearch()}
              placeholder="Search by domain (e.g. *.corp.internal)"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm" />
            <button onClick={handleSearch}
              className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700">Search</button>
          </div>

          {loading ? (
            <p className="text-sm text-gray-500">Loading…</p>
          ) : entries.length === 0 ? (
            <p className="text-sm text-gray-500">No CT log entries found. Entries are created when certificates are issued.</p>
          ) : (
            <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-2 text-left">#</th>
                    <th className="px-3 py-2 text-left">Subject CN</th>
                    <th className="px-3 py-2 text-left">Serial</th>
                    <th className="px-3 py-2 text-left">Leaf Hash</th>
                    <th className="px-3 py-2 text-left">Timestamp</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {entries.map(e => (
                    <tr key={e.id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono">{e.log_index}</td>
                      <td className="px-3 py-2 font-medium">{e.subject_cn || '—'}</td>
                      <td className="px-3 py-2 font-mono text-xs">{e.cert_serial.slice(0, 16)}…</td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-500">{e.leaf_hash.slice(0, 12)}…</td>
                      <td className="px-3 py-2 text-xs text-gray-500">{new Date(e.timestamp).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t bg-gray-50">
                  <span className="text-xs text-gray-500">{total} entries</span>
                  <div className="flex gap-2">
                    <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}
                      className="px-3 py-1 text-xs border rounded disabled:opacity-50">Prev</button>
                    <span className="text-xs py-1">Page {page}/{totalPages}</span>
                    <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}
                      className="px-3 py-1 text-xs border rounded disabled:opacity-50">Next</button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Verify Tab */}
      {tab === 'verify' && (
        <div className="space-y-4">
          {loading ? (
            <p className="text-sm text-gray-500">Verifying Merkle tree…</p>
          ) : verifyResult ? (
            <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-4">
              <div className="flex items-center gap-3">
                <span className={`text-2xl`}>{verifyResult.consistent ? '✅' : '❌'}</span>
                <div>
                  <p className="font-bold">{verifyResult.consistent ? 'Tree is consistent' : 'Inconsistencies detected'}</p>
                  <p className="text-sm text-gray-500">{verifyResult.total_entries} entries verified</p>
                </div>
              </div>
              <div className="text-sm space-y-1">
                <p><span className="text-gray-500">Computed Root:</span> <code className="text-xs">{verifyResult.computed_root}</code></p>
                <p><span className="text-gray-500">Root Matches Stored:</span> {verifyResult.root_matches_stored ? '✓ Yes' : '✗ No'}</p>
              </div>
              {verifyResult.issues.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded p-3">
                  <p className="text-sm font-medium text-red-800 mb-2">Issues Found:</p>
                  <ul className="text-sm text-red-700 list-disc list-inside">
                    {verifyResult.issues.map((issue, i) => <li key={i}>{issue}</li>)}
                  </ul>
                </div>
              )}
              <button onClick={runVerify} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                Re-verify
              </button>
            </div>
          ) : null}
        </div>
      )}

      {/* Anomalies Tab */}
      {tab === 'anomalies' && (
        <div className="space-y-4">
          {loading ? (
            <p className="text-sm text-gray-500">Scanning for anomalies…</p>
          ) : anomalies.length === 0 ? (
            <div className="bg-green-50 border border-green-200 rounded-lg p-6 text-center">
              <p className="text-green-800 font-medium">No anomalies detected</p>
              <p className="text-sm text-green-600 mt-1">All logged certificates appear normal</p>
            </div>
          ) : (
            <div className="space-y-3">
              {anomalies.map((a, i) => (
                <div key={i} className={`border rounded-lg p-4 ${a.severity === 'high' ? 'border-red-300 bg-red-50' : 'border-yellow-300 bg-yellow-50'}`}>
                  <div className="flex items-center justify-between">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${a.severity === 'high' ? 'bg-red-200 text-red-800' : 'bg-yellow-200 text-yellow-800'}`}>
                      {a.severity.toUpperCase()}
                    </span>
                    <span className="text-xs text-gray-500">{new Date(a.timestamp).toLocaleString()}</span>
                  </div>
                  <p className="text-sm font-medium mt-2">{a.message}</p>
                  <p className="text-xs text-gray-500 mt-1">Log #{a.log_index} · Serial: {a.cert_serial.slice(0, 16)}…</p>
                </div>
              ))}
              <button onClick={fetchAnomalies} className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700">
                Refresh
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
