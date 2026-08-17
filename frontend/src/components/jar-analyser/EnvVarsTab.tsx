import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface EnvUsage { service: string; config_key: string; config_file: string }
interface EnvEntry {
  var_name: string
  default_value: string | null
  mandatory: boolean
  category: string
  usage_count: number
  services: string[]
  usages: EnvUsage[]
}
interface EnvVarsResponse {
  report_id: string
  total: number
  mandatory_count: number
  categories: string[]
  services: string[]
  items: EnvEntry[]
}

const CAT_STYLE: Record<string, { bg: string; text: string }> = {
  database:  { bg: 'bg-purple-100', text: 'text-purple-700' },
  messaging: { bg: 'bg-orange-100', text: 'text-orange-700' },
  ssl:       { bg: 'bg-blue-100',   text: 'text-blue-700'   },
  port:      { bg: 'bg-gray-100',   text: 'text-gray-600'   },
  security:  { bg: 'bg-red-100',    text: 'text-red-700'    },
  url:       { bg: 'bg-green-100',  text: 'text-green-700'  },
  logging:   { bg: 'bg-yellow-100', text: 'text-yellow-700' },
  actuator:  { bg: 'bg-gray-100',   text: 'text-gray-600'   },
  other:     { bg: 'bg-gray-100',   text: 'text-gray-500'   },
}

function CategoryBadge({ cat }: { cat: string }) {
  const s = CAT_STYLE[cat] ?? CAT_STYLE.other
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${s.bg} ${s.text}`}>
      {cat}
    </span>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="ml-1 px-1.5 py-0.5 text-xs text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition"
      title="Copy variable name">
      {copied ? '✓' : '⎘'}
    </button>
  )
}

type MandatoryFilter = 'all' | 'mandatory' | 'optional'

export default function EnvVarsTab({ reportId }: { reportId: string }) {
  const [q, setQ] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [svcFilter, setSvcFilter] = useState('')
  const [mandatoryFilter, setMandatoryFilter] = useState<MandatoryFilter>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const { data, isLoading, error } = useQuery<EnvVarsResponse>({
    queryKey: ['env-vars', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/env-vars`).then(r => r.data),
  })

  const filtered = useMemo(() => {
    if (!data) return []
    const ql = q.toLowerCase()
    return data.items.filter(e => {
      if (ql && !e.var_name.toLowerCase().includes(ql) &&
          !e.usages.some(u => u.config_key.toLowerCase().includes(ql))) return false
      if (catFilter && e.category !== catFilter) return false
      if (svcFilter && !e.services.includes(svcFilter)) return false
      if (mandatoryFilter === 'mandatory' && !e.mandatory) return false
      if (mandatoryFilter === 'optional' && e.mandatory) return false
      return true
    })
  }, [data, q, catFilter, svcFilter, mandatoryFilter])

  const toggleExpand = (varName: string) =>
    setExpanded(s => { const n = new Set(s); n.has(varName) ? n.delete(varName) : n.add(varName); return n })

  const clearFilters = () => { setQ(''); setCatFilter(''); setSvcFilter(''); setMandatoryFilter('all') }
  const hasFilters = q || catFilter || svcFilter || mandatoryFilter !== 'all'

  if (isLoading) return <div className="text-sm text-gray-400 py-8 text-center">Loading environment variables…</div>
  if (error || !data) return <div className="text-sm text-red-500 py-4">Failed to load environment variables.</div>

  const mandatoryCount = data.mandatory_count ?? data.items.filter(e => e.mandatory).length
  const optionalCount = data.total - mandatoryCount

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex flex-wrap gap-3">
        <div className="px-3 py-2 bg-blue-50 border border-blue-200 rounded text-sm">
          <span className="font-semibold text-blue-800">{data.total}</span>
          <span className="text-blue-600 ml-1">unique variables</span>
        </div>
        <div className="px-3 py-2 bg-amber-50 border border-amber-200 rounded text-sm">
          <span className="font-semibold text-amber-800">{mandatoryCount}</span>
          <span className="text-amber-700 ml-1">required (no default)</span>
        </div>
        <div className="px-3 py-2 bg-gray-50 border border-gray-200 rounded text-sm">
          <span className="font-semibold text-gray-700">{optionalCount}</span>
          <span className="text-gray-500 ml-1">optional</span>
        </div>
        <div className="px-3 py-2 bg-gray-50 border border-gray-200 rounded text-sm">
          <span className="font-semibold text-gray-700">{data.services.length}</span>
          <span className="text-gray-500 ml-1">services</span>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        <input
          value={q} onChange={e => setQ(e.target.value)}
          placeholder="Search variable name or config key…"
          className="flex-1 min-w-48 px-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
        <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All categories</option>
          {data.categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={svcFilter} onChange={e => setSvcFilter(e.target.value)}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400">
          <option value="">All services</option>
          {data.services.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="flex rounded border border-gray-300 overflow-hidden text-sm">
          {(['all', 'mandatory', 'optional'] as MandatoryFilter[]).map(v => (
            <button key={v} onClick={() => setMandatoryFilter(v)}
              className={`px-3 py-1.5 transition ${
                mandatoryFilter === v
                  ? v === 'mandatory'
                    ? 'bg-amber-500 text-white'
                    : 'bg-blue-600 text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}>
              {v === 'all' ? 'All' : v === 'mandatory' ? '⚠ Required' : 'Optional'}
            </button>
          ))}
        </div>
        {hasFilters && (
          <button onClick={clearFilters}
            className="px-3 py-1.5 border border-gray-200 rounded text-sm text-gray-500 hover:bg-gray-50">
            Clear
          </button>
        )}
      </div>

      {/* Result count */}
      {hasFilters && (
        <p className="text-xs text-gray-500">{filtered.length} of {data.total} variables</p>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-8"></th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Variable</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Category</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Default</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Services</th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">Usages</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No variables match the current filters.</td></tr>
            )}
            {filtered.map(e => (
              <>
                <tr key={e.var_name}
                  className={`hover:bg-gray-50 cursor-pointer ${e.mandatory ? 'bg-amber-50/40' : ''}`}
                  onClick={() => toggleExpand(e.var_name)}>
                  <td className="px-4 py-2 text-gray-400 text-xs select-none">
                    {expanded.has(e.var_name) ? '▾' : '▸'}
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5">
                      {e.mandatory && (
                        <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-medium" title="No default value — must be set before deployment">
                          ⚠ required
                        </span>
                      )}
                      <span className="font-mono text-xs text-gray-900">{e.var_name}</span>
                      <CopyButton text={e.var_name} />
                    </div>
                  </td>
                  <td className="px-4 py-2"><CategoryBadge cat={e.category} /></td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-500">
                    {e.mandatory
                      ? <span className="text-amber-600 font-medium">— no default</span>
                      : e.default_value !== null
                        ? e.default_value || <em className="not-italic text-gray-400">(empty)</em>
                        : <span className="text-gray-300">—</span>
                    }
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {e.services.map(s => (
                        <span key={s} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{s}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2 text-right text-xs text-gray-400">{e.usage_count}</td>
                </tr>
                {expanded.has(e.var_name) && (
                  <tr key={`${e.var_name}-detail`} className="bg-gray-50">
                    <td />
                    <td colSpan={5} className="px-4 py-3">
                      {e.mandatory && (
                        <p className="text-xs text-amber-700 mb-2 font-medium">
                          ⚠ This variable has no default value and must be set in the deployment environment before the service will start.
                        </p>
                      )}
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-gray-500">
                            <th className="text-left font-medium pb-1 pr-4">Service</th>
                            <th className="text-left font-medium pb-1 pr-4">Config file</th>
                            <th className="text-left font-medium pb-1">Config key</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {e.usages.map((u, i) => (
                            <tr key={i}>
                              <td className="py-1 pr-4 text-gray-700 font-medium">{u.service}</td>
                              <td className="py-1 pr-4 font-mono text-gray-500">{u.config_file}</td>
                              <td className="py-1 font-mono text-gray-600">{u.config_key}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
