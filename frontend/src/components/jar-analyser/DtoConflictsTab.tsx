import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Difference {
  kind: 'FIELD_ADDED' | 'FIELD_REMOVED' | 'TYPE_CHANGED' | 'ENUM_VALUE_ADDED' | 'ENUM_VALUE_REMOVED'
  field?: string
  value?: string
  type_a?: string | null
  type_b?: string | null
}

interface Mismatch {
  service_a: string
  service_b: string
  differences: Difference[]
}

interface Definition {
  service: string
  fields: { json_name: string; java_type: string; nullable: boolean; required: boolean }[]
  enum_values: { name: string; serialised_as: string }[]
}

interface Conflict {
  simple_name: string
  is_enum: boolean
  services: string[]
  mismatches: Mismatch[]
  definitions: Definition[]
}

interface ConflictsResponse {
  total_conflicts: number
  enum_conflicts: number
  dto_conflicts: number
  conflicts: Conflict[]
}

interface Props {
  reportId: string
}

const KIND_LABEL: Record<string, { label: string; colour: string }> = {
  FIELD_ADDED:         { label: 'field added',   colour: 'bg-green-100 text-green-700' },
  FIELD_REMOVED:       { label: 'field removed', colour: 'bg-red-100 text-red-700' },
  TYPE_CHANGED:        { label: 'type changed',  colour: 'bg-amber-100 text-amber-700' },
  ENUM_VALUE_ADDED:    { label: 'value added',   colour: 'bg-green-100 text-green-700' },
  ENUM_VALUE_REMOVED:  { label: 'value removed', colour: 'bg-red-100 text-red-700' },
}

export default function DtoConflictsTab({ reportId }: Props) {
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'dto' | 'enum'>('all')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [defView, setDefView] = useState<Record<string, boolean>>({})

  const { data, isLoading } = useQuery<ConflictsResponse>({
    queryKey: ['dto-conflicts', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/dto-conflicts`).then(r => r.data),
  })

  if (isLoading) return <p className="text-sm text-gray-400 py-8 text-center">Checking DTO consistency…</p>

  const conflicts = data?.conflicts ?? []

  const filtered = conflicts.filter(c => {
    if (filter === 'dto' && c.is_enum) return false
    if (filter === 'enum' && !c.is_enum) return false
    if (search && !c.simple_name.toLowerCase().includes(search.toLowerCase()) &&
        !c.services.some(s => s.toLowerCase().includes(search.toLowerCase()))) return false
    return true
  })

  if (conflicts.length === 0) {
    return (
      <div className="py-12 text-center space-y-2">
        <div className="text-3xl">✅</div>
        <p className="text-sm font-medium text-gray-700">No DTO conflicts detected</p>
        <p className="text-xs text-gray-400">All shared class names have consistent field definitions across services.</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-red-600">{data!.total_conflicts}</div>
          <div className="text-xs text-gray-500 mt-1">Total conflicts</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-amber-600">{data!.dto_conflicts}</div>
          <div className="text-xs text-gray-500 mt-1">DTO conflicts</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 text-center">
          <div className="text-2xl font-bold text-purple-600">{data!.enum_conflicts}</div>
          <div className="text-xs text-gray-500 mt-1">Enum conflicts</div>
        </div>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-800">
        ⚠ These classes share the same simple name across services but have different definitions.
        Mismatches in shared event payloads or API contracts can cause silent deserialization failures.
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search by class or service name…"
          className="border border-gray-300 rounded px-3 py-1.5 text-xs w-64"
        />
        <div className="flex gap-1">
          {(['all', 'dto', 'enum'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded text-xs border transition-colors ${
                filter === f
                  ? 'bg-gray-700 text-white border-gray-700'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
              }`}>
              {f === 'all' ? `All (${conflicts.length})` : f === 'dto' ? `DTOs (${data!.dto_conflicts})` : `Enums (${data!.enum_conflicts})`}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-400 ml-auto">{filtered.length} conflict{filtered.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Conflict list */}
      <div className="space-y-2">
        {filtered.map(c => {
          const isOpen = expanded === c.simple_name
          const showDefs = defView[c.simple_name] ?? false
          const totalDiffs = c.mismatches.reduce((n, m) => n + m.differences.length, 0)

          return (
            <div key={c.simple_name} className="border border-gray-200 rounded-lg overflow-hidden">
              {/* Header row */}
              <button
                onClick={() => setExpanded(isOpen ? null : c.simple_name)}
                className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ${
                    c.is_enum ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'
                  }`}>
                    {c.is_enum ? 'enum' : 'dto'}
                  </span>
                  <span className="font-mono text-sm font-semibold text-gray-800 truncate">{c.simple_name}</span>
                  <span className="text-xs text-gray-500 shrink-0">{c.services.length} services</span>
                </div>
                <div className="flex items-center gap-3 shrink-0 ml-3">
                  <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                    {totalDiffs} difference{totalDiffs !== 1 ? 's' : ''}
                  </span>
                  <div className="flex gap-1">
                    {c.services.map(s => (
                      <span key={s} className="px-1.5 py-0.5 bg-gray-200 text-gray-600 rounded text-xs font-mono">{s}</span>
                    ))}
                  </div>
                  <span className="text-gray-400 text-xs">{isOpen ? '▲' : '▼'}</span>
                </div>
              </button>

              {/* Expanded detail */}
              {isOpen && (
                <div className="divide-y divide-gray-100">
                  {/* Pairwise mismatches */}
                  {c.mismatches.map((m, mi) => (
                    <div key={mi} className="px-4 py-3 space-y-2">
                      <div className="flex items-center gap-2 text-xs font-medium text-gray-600">
                        <span className="font-mono bg-gray-100 px-2 py-0.5 rounded">{m.service_a}</span>
                        <span className="text-gray-400">vs</span>
                        <span className="font-mono bg-gray-100 px-2 py-0.5 rounded">{m.service_b}</span>
                        <span className="text-gray-400 ml-1">— {m.differences.length} difference{m.differences.length !== 1 ? 's' : ''}</span>
                      </div>
                      <div className="space-y-1">
                        {m.differences.map((d, di) => {
                          const meta = KIND_LABEL[d.kind] ?? { label: d.kind, colour: 'bg-gray-100 text-gray-600' }
                          return (
                            <div key={di} className="flex items-center gap-2 text-xs">
                              <span className={`px-2 py-0.5 rounded shrink-0 ${meta.colour}`}>{meta.label}</span>
                              {d.field && <span className="font-mono text-gray-800">{d.field}</span>}
                              {d.value && <span className="font-mono text-gray-800">{d.value}</span>}
                              {d.kind === 'TYPE_CHANGED' && (
                                <span className="text-gray-500">
                                  <span className="font-mono text-red-600">{d.type_a}</span>
                                  <span className="mx-1">→</span>
                                  <span className="font-mono text-green-600">{d.type_b}</span>
                                </span>
                              )}
                              {d.kind === 'FIELD_ADDED' && d.type_b && (
                                <span className="font-mono text-gray-400">({d.type_b})</span>
                              )}
                              {d.kind === 'FIELD_REMOVED' && d.type_a && (
                                <span className="font-mono text-gray-400">({d.type_a})</span>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}

                  {/* Side-by-side definitions toggle */}
                  <div className="px-4 py-2 bg-gray-50">
                    <button
                      onClick={() => setDefView(v => ({ ...v, [c.simple_name]: !showDefs }))}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      {showDefs ? '▲ Hide' : '▼ Show'} full definitions ({c.definitions.length} services)
                    </button>
                  </div>

                  {showDefs && (
                    <div className="px-4 py-3 overflow-x-auto">
                      <div className="flex gap-4 min-w-0">
                        {c.definitions.map(def => (
                          <div key={def.service} className="flex-1 min-w-48 border border-gray-200 rounded-lg overflow-hidden">
                            <div className="px-3 py-2 bg-gray-100 text-xs font-semibold text-gray-700 font-mono border-b border-gray-200">
                              {def.service}
                            </div>
                            {c.is_enum ? (
                              <div className="p-2 space-y-0.5">
                                {def.enum_values.length === 0
                                  ? <p className="text-xs text-gray-400 italic">No values</p>
                                  : def.enum_values.map((v, i) => (
                                    <div key={i} className="text-xs font-mono text-gray-700 py-0.5 border-b border-gray-50 last:border-0">
                                      {v.serialised_as || v.name}
                                    </div>
                                  ))
                                }
                              </div>
                            ) : (
                              <table className="w-full text-xs">
                                <thead className="bg-white border-b border-gray-100">
                                  <tr>
                                    <th className="px-3 py-1 text-left font-medium text-gray-500">Field</th>
                                    <th className="px-3 py-1 text-left font-medium text-gray-500">Type</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-50">
                                  {def.fields.length === 0
                                    ? <tr><td colSpan={2} className="px-3 py-2 text-gray-400 italic">No fields</td></tr>
                                    : def.fields.map((f, i) => (
                                      <tr key={i} className="hover:bg-gray-50">
                                        <td className="px-3 py-1 font-mono text-gray-800">{f.json_name}</td>
                                        <td className="px-3 py-1 font-mono text-blue-700">{f.java_type}</td>
                                      </tr>
                                    ))
                                  }
                                </tbody>
                              </table>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
