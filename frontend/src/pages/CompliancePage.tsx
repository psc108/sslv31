import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface Finding {
  severity: string
  rule: string
  category: string
  subject: string
  subject_cn: string
  subject_type: string
  message: string
}

interface ScanResult {
  id: string
  scan_type: string
  scanned_at: string
  total_checked: number
  total_violations: number
  total_warnings: number
  summary: { violations_by_rule: Record<string, number>; warnings_by_rule: Record<string, number> }
  findings: Finding[]
}

interface HistoryEntry {
  id: string
  scanned_at: string
  total_checked: number
  total_violations: number
  total_warnings: number
}

export default function CompliancePage() {
  const [latest, setLatest] = useState<ScanResult | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [scanning, setScanning] = useState(false)
  const [activeTab, setActiveTab] = useState<'results' | 'history' | 'rules'>('results')
  const [scanType, setScanType] = useState('full')
  const [rules, setRules] = useState<any>(null)

  useEffect(() => { loadData() }, [scanType])

  async function loadData() {
    try {
      const latestRes = await api.get(`/compliance/latest?scan_type=${scanType}`)
      if (latestRes.data && latestRes.data.total_checked !== undefined) {
        setLatest(latestRes.data)
      }
    } catch { /* no previous scan */ }
    try {
      const histRes = await api.get(`/compliance/history?scan_type=${scanType}&limit=20`)
      setHistory(histRes.data.scans || [])
    } catch { /* ignore */ }
  }

  async function runScan() {
    setScanning(true)
    try {
      const res = await api.post('/compliance/scan', null, { params: { scan_type: scanType } })
      if (res.data) {
        setLatest(res.data)
      }
    } catch (e) {
      console.error('Compliance scan error', e)
    }
    try {
      const histRes = await api.get(`/compliance/history?scan_type=${scanType}&limit=20`)
      setHistory(histRes.data.scans || [])
    } catch { /* ignore */ }
    setScanning(false)
  }

  async function loadRules() {
    if (rules) return
    try {
      const res = await api.get('/compliance/rules')
      setRules(res.data)
    } catch { /* ignore */ }
  }

  useEffect(() => { if (activeTab === 'rules') loadRules() }, [activeTab])

  async function exportReport(format: string) {
    try {
      const res = await api.get(`/compliance/export?format=${format}`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `compliance-report.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
  }

  const severityColor = (s: string) => {
    if (s === 'violation') return 'bg-red-100 text-red-800'
    if (s === 'warning') return 'bg-yellow-100 text-yellow-800'
    return 'bg-blue-100 text-blue-800'
  }

  const tabs = [
    { id: 'results' as const, label: 'Scan Results' },
    { id: 'history' as const, label: 'History' },
    { id: 'rules' as const, label: 'Rules Reference' },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🛡️ Compliance & Reporting</h1>
          <p className="text-sm text-gray-600 mt-1">CA/Browser Forum BR & CIS PKI benchmark compliance</p>
        </div>
        <div className="flex items-center gap-3">
          <select value={scanType} onChange={e => setScanType(e.target.value)}
            className="border rounded-md px-3 py-2 text-sm">
            <option value="full">Full Scan (BR + CIS)</option>
            <option value="br">BR Only</option>
            <option value="cis">CIS Only</option>
          </select>
          <button onClick={runScan} disabled={scanning}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:opacity-50">
            {scanning ? 'Scanning...' : 'Run Scan'}
          </button>
          <button onClick={() => exportReport('csv')}
            className="px-3 py-2 border rounded-md text-sm hover:bg-gray-50">📥 CSV</button>
          <button onClick={() => exportReport('json')}
            className="px-3 py-2 border rounded-md text-sm hover:bg-gray-50">📥 JSON</button>
        </div>
      </div>

      {/* Summary Cards */}
      {latest && latest.total_checked > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border p-4">
            <p className="text-sm text-gray-500">Checked</p>
            <p className="text-2xl font-bold text-gray-900">{latest.total_checked}</p>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <p className="text-sm text-gray-500">Violations</p>
            <p className={`text-2xl font-bold ${latest.total_violations > 0 ? 'text-red-600' : 'text-green-600'}`}>
              {latest.total_violations}
            </p>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <p className="text-sm text-gray-500">Warnings</p>
            <p className={`text-2xl font-bold ${latest.total_warnings > 0 ? 'text-yellow-600' : 'text-green-600'}`}>
              {latest.total_warnings}
            </p>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <p className="text-sm text-gray-500">Last Scan</p>
            <p className="text-sm font-medium text-gray-900">
              {latest.scanned_at ? new Date(latest.scanned_at).toLocaleString() : 'Never'}
            </p>
          </div>
        </div>
      )}

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

      {/* Results Tab */}
      {activeTab === 'results' && (
        <div className="space-y-4">
          {latest && latest.findings && latest.findings.length > 0 ? (
            <div className="bg-white rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-2 text-left">Severity</th>
                    <th className="px-4 py-2 text-left">Rule</th>
                    <th className="px-4 py-2 text-left">Subject</th>
                    <th className="px-4 py-2 text-left">Message</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {latest.findings.map((f, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-4 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${severityColor(f.severity)}`}>
                          {f.severity}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{f.rule}</td>
                      <td className="px-4 py-2">
                        <span className="text-xs text-gray-500">{f.subject_type}:</span> {f.subject_cn}
                      </td>
                      <td className="px-4 py-2 text-gray-700">{f.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : latest && latest.total_checked ? (
            <div className="bg-green-50 border border-green-200 rounded-lg p-6 text-center">
              <p className="text-green-800 font-medium">✅ All {latest.total_checked} checks passed — no violations or warnings</p>
            </div>
          ) : (
            <div className="bg-gray-50 border rounded-lg p-6 text-center">
              <p className="text-gray-600">No scan results yet. Click &quot;Run Scan&quot; to check compliance.</p>
            </div>
          )}
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          {history.length > 0 ? (
            <>
              {/* Trend visualization */}
              <div className="bg-white rounded-lg border p-4">
                <h3 className="text-sm font-medium text-gray-700 mb-3">Violation Trend (last {history.length} scans)</h3>
                <div className="flex items-end gap-1 h-24">
                  {[...history].reverse().map((h, i) => {
                    const max = Math.max(...history.map(x => x.total_violations + x.total_warnings), 1)
                    const vHeight = (h.total_violations / max) * 100
                    const wHeight = (h.total_warnings / max) * 100
                    return (
                      <div key={i} className="flex-1 flex flex-col items-center gap-0.5" title={`${h.scanned_at}: ${h.total_violations}V ${h.total_warnings}W`}>
                        <div className="w-full flex flex-col justify-end" style={{ height: '96px' }}>
                          <div className="bg-red-400 rounded-t" style={{ height: `${vHeight}%`, minHeight: h.total_violations > 0 ? '2px' : '0' }}></div>
                          <div className="bg-yellow-400" style={{ height: `${wHeight}%`, minHeight: h.total_warnings > 0 ? '2px' : '0' }}></div>
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div className="flex gap-4 mt-2 text-xs text-gray-500">
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-400 rounded"></span> Violations</span>
                  <span className="flex items-center gap-1"><span className="w-3 h-3 bg-yellow-400 rounded"></span> Warnings</span>
                </div>
              </div>

              {/* History table */}
              <div className="bg-white rounded-lg border overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-2 text-left">Date</th>
                      <th className="px-4 py-2 text-left">Checked</th>
                      <th className="px-4 py-2 text-left">Violations</th>
                      <th className="px-4 py-2 text-left">Warnings</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {history.map(h => (
                      <tr key={h.id} className="hover:bg-gray-50">
                        <td className="px-4 py-2">{h.scanned_at ? new Date(h.scanned_at).toLocaleString() : ''}</td>
                        <td className="px-4 py-2">{h.total_checked}</td>
                        <td className="px-4 py-2">
                          <span className={h.total_violations > 0 ? 'text-red-600 font-medium' : 'text-green-600'}>
                            {h.total_violations}
                          </span>
                        </td>
                        <td className="px-4 py-2">
                          <span className={h.total_warnings > 0 ? 'text-yellow-600 font-medium' : 'text-green-600'}>
                            {h.total_warnings}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="bg-gray-50 border rounded-lg p-6 text-center">
              <p className="text-gray-600">No scan history. Run scans to build trend data.</p>
            </div>
          )}
        </div>
      )}

      {/* Rules Tab */}
      {activeTab === 'rules' && rules && (
        <div className="space-y-6">
          <div className="bg-white rounded-lg border p-4">
            <h3 className="text-sm font-bold text-gray-900 mb-3">CA/Browser Forum Baseline Requirements</h3>
            <div className="space-y-2">
              {rules.br_rules?.map((r: any) => (
                <div key={r.id} className="flex items-start gap-3 text-sm">
                  <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded whitespace-nowrap">{r.id}</span>
                  <div>
                    <span className="font-medium">{r.name}</span>
                    <span className="text-gray-500 ml-2">— {r.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="bg-white rounded-lg border p-4">
            <h3 className="text-sm font-bold text-gray-900 mb-3">CIS PKI Benchmark</h3>
            <div className="space-y-2">
              {rules.cis_rules?.map((r: any) => (
                <div key={r.id} className="flex items-start gap-3 text-sm">
                  <span className="font-mono text-xs bg-gray-100 px-2 py-0.5 rounded whitespace-nowrap">{r.id}</span>
                  <div>
                    <span className="font-medium">{r.name}</span>
                    <span className="text-gray-500 ml-2">— {r.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
