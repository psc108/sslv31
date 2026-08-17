import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { MigrationScript } from './types'

interface MigrationWithRisk extends MigrationScript {
  risk?: 'high' | 'medium' | 'low'
  risk_reasons?: string[]
}

interface Props {
  migrations: MigrationWithRisk[]
  reportId: string
  subReportId: string
}

type PanelTab = 'migrations' | 'schema'

interface ColumnDef {
  name: string
  type: string
  nullable: boolean
  primary_key: boolean
  default: string | null
}

interface IndexDef {
  name: string
  columns: string[]
  unique: boolean
}

interface ForeignKeyDef {
  name: string | null
  columns: string[]
  references: string
  ref_columns: string[]
}

interface TableDef {
  table: string
  columns: ColumnDef[]
  primary_key: string[]
  indexes: IndexDef[]
  foreign_keys: ForeignKeyDef[]
}

interface SchemaResult {
  migration_count: number
  table_count: number
  tables: TableDef[]
}

export default function MigrationViewer({ migrations, reportId, subReportId }: Props) {
  const [panel, setPanel] = useState<PanelTab>('migrations')
  const [open, setOpen] = useState<string | null>(null)
  const [riskFilter, setRiskFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all')
  const [tableSearch, setTableSearch] = useState('')
  const [expandedTable, setExpandedTable] = useState<string | null>(null)

  const { data: schema, isLoading: schemaLoading } = useQuery<SchemaResult>({
    queryKey: ['schema-reconstruction', subReportId],
    queryFn: () =>
      api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schema-reconstruction`)
        .then(r => r.data),
    enabled: panel === 'schema',
  })

  const filteredTables = (schema?.tables ?? []).filter(t =>
    !tableSearch || t.table.toLowerCase().includes(tableSearch.toLowerCase())
  )

  const riskBadge = (risk?: string) => {
    if (risk === 'high') return <span title="High risk">🔴</span>
    if (risk === 'medium') return <span title="Medium risk">🟡</span>
    return <span title="Low risk">🟢</span>
  }

  const filteredMigrations = riskFilter === 'all'
    ? migrations
    : migrations.filter(m => (m.risk ?? 'low') === riskFilter)

  const highCount = migrations.filter(m => m.risk === 'high').length
  const medCount = migrations.filter(m => m.risk === 'medium').length

  if (!migrations.length) return <p className="text-sm text-gray-400 py-4">No migration scripts found.</p>

  return (
    <div className="space-y-3">
      {/* Panel toggle */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['migrations', 'schema'] as PanelTab[]).map(p => (
          <button key={p} onClick={() => setPanel(p)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              panel === p
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}>
            {p === 'migrations'
              ? `Migration Scripts (${migrations.length})`
              : `Current Schema${schema ? ` (${schema.table_count} tables)` : ''}`}
          </button>
        ))}
      </div>

      {/* Migration list */}
      {panel === 'migrations' && (
        <div className="space-y-3">
          {/* Risk summary + filter */}
          {(highCount > 0 || medCount > 0) && (
            <div className="flex items-center gap-3 flex-wrap">
              {highCount > 0 && (
                <span className="flex items-center gap-1 px-2 py-1 bg-red-50 border border-red-200 rounded text-xs text-red-700">
                  🔴 {highCount} high-risk migration{highCount !== 1 ? 's' : ''}
                </span>
              )}
              {medCount > 0 && (
                <span className="flex items-center gap-1 px-2 py-1 bg-amber-50 border border-amber-200 rounded text-xs text-amber-700">
                  🟡 {medCount} medium-risk migration{medCount !== 1 ? 's' : ''}
                </span>
              )}
              <div className="ml-auto flex gap-1">
                {(['all', 'high', 'medium', 'low'] as const).map(f => (
                  <button key={f} onClick={() => setRiskFilter(f)}
                    className={`px-2 py-0.5 rounded text-xs border transition-colors ${
                      riskFilter === f
                        ? 'bg-gray-700 text-white border-gray-700'
                        : 'bg-white text-gray-600 border-gray-300 hover:border-gray-400'
                    }`}>
                    {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-600">Risk</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Version</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Description</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Type</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-600">Statements</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Tables</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredMigrations.map(m => (
                  <>
                    <tr key={m.id}
                      className={`cursor-pointer ${
                        m.risk === 'high' ? 'bg-red-50 hover:bg-red-100'
                        : m.risk === 'medium' ? 'bg-amber-50 hover:bg-amber-100'
                        : 'hover:bg-gray-50'
                      }`}
                      onClick={() => setOpen(open === m.id ? null : m.id)}>
                      <td className="px-3 py-2 text-center">{riskBadge(m.risk)}</td>
                      <td className="px-4 py-2 font-mono text-xs font-bold text-blue-700">{m.version ?? '—'}</td>
                      <td className="px-4 py-2 text-gray-700">{m.description ?? m.filename}</td>
                      <td className="px-4 py-2">
                        <span className={`px-2 py-0.5 rounded text-xs ${m.script_type === 'versioned' ? 'bg-blue-100 text-blue-700' : 'bg-purple-100 text-purple-700'}`}>
                          {m.script_type}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-right text-gray-600">{m.statement_count ?? '—'}</td>
                      <td className="px-4 py-2 text-xs text-gray-500">{(m.tables_affected ?? []).join(', ') || '—'}</td>
                    </tr>
                    {open === m.id && (
                      <tr key={`${m.id}-detail`} className="bg-gray-50">
                        <td colSpan={6} className="px-4 py-3 space-y-2">
                          {/* Risk reasons */}
                          {m.risk_reasons && m.risk_reasons.length > 0 && (
                            <div className={`rounded p-2 text-xs space-y-1 ${
                              m.risk === 'high' ? 'bg-red-100 text-red-800'
                              : 'bg-amber-100 text-amber-800'
                            }`}>
                              <p className="font-semibold">Risk factors:</p>
                              {m.risk_reasons.map((r, i) => (
                                <p key={i}>• {r}</p>
                              ))}
                            </div>
                          )}
                          <div className="flex items-center gap-2">
                            {m.ddl_operations?.map((op, i) => (
                              <span key={i} className="px-2 py-0.5 bg-gray-200 text-gray-700 rounded text-xs">{op}</span>
                            ))}
                          </div>
                          {m.content && (
                            <pre className="bg-gray-900 text-gray-100 rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-80 overflow-y-auto">
                              {m.content}
                            </pre>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Current Schema panel */}
      {panel === 'schema' && (
        <div className="space-y-3">
          {schemaLoading && (
            <p className="text-sm text-gray-400 py-4 text-center">Reconstructing schema…</p>
          )}
          {!schemaLoading && schema && (
            <>
              <div className="flex items-center gap-3">
                <input
                  type="text" value={tableSearch} onChange={e => setTableSearch(e.target.value)}
                  placeholder="Filter tables…"
                  className="border border-gray-300 rounded px-3 py-1 text-xs w-56"
                />
                <span className="text-xs text-gray-400 ml-auto">
                  {filteredTables.length} of {schema.table_count} table{schema.table_count !== 1 ? 's' : ''} · replayed {schema.migration_count} migration{schema.migration_count !== 1 ? 's' : ''}
                </span>
              </div>

              {filteredTables.length === 0 && (
                <p className="text-sm text-gray-400 py-4 text-center">
                  {schema.table_count === 0
                    ? 'No tables could be reconstructed — migration scripts may not contain CREATE TABLE statements.'
                    : 'No tables match the filter.'}
                </p>
              )}

              <div className="space-y-2">
                {filteredTables.map(tbl => (
                  <div key={tbl.table} className="border border-gray-200 rounded-lg overflow-hidden">
                    <button
                      onClick={() => setExpandedTable(expandedTable === tbl.table ? null : tbl.table)}
                      className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 text-left"
                    >
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-sm font-semibold text-gray-800">{tbl.table}</span>
                        <span className="text-xs text-gray-500">{tbl.columns.length} col{tbl.columns.length !== 1 ? 's' : ''}</span>
                        {tbl.primary_key.length > 0 && (
                          <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-mono">
                            PK: {tbl.primary_key.join(', ')}
                          </span>
                        )}
                        {tbl.indexes.length > 0 && (
                          <span className="text-xs text-gray-400">{tbl.indexes.length} index{tbl.indexes.length !== 1 ? 'es' : ''}</span>
                        )}
                        {tbl.foreign_keys.length > 0 && (
                          <span className="text-xs text-gray-400">{tbl.foreign_keys.length} FK{tbl.foreign_keys.length !== 1 ? 's' : ''}</span>
                        )}
                      </div>
                      <span className="text-gray-400 text-xs">{expandedTable === tbl.table ? '▲' : '▼'}</span>
                    </button>

                    {expandedTable === tbl.table && (
                      <div className="divide-y divide-gray-100">
                        {/* Columns */}
                        <table className="w-full text-xs">
                          <thead className="bg-white border-b border-gray-100">
                            <tr>
                              <th className="px-4 py-1.5 text-left font-medium text-gray-500">Column</th>
                              <th className="px-4 py-1.5 text-left font-medium text-gray-500">Type</th>
                              <th className="px-4 py-1.5 text-left font-medium text-gray-500">Nullable</th>
                              <th className="px-4 py-1.5 text-left font-medium text-gray-500">Default</th>
                              <th className="px-4 py-1.5 text-left font-medium text-gray-500">Flags</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-gray-50">
                            {tbl.columns.map(col => {
                              const isPK = col.primary_key || tbl.primary_key.includes(col.name)
                              return (
                                <tr key={col.name} className={isPK ? 'bg-amber-50' : 'hover:bg-gray-50'}>
                                  <td className="px-4 py-1.5 font-mono font-medium text-gray-800">{col.name}</td>
                                  <td className="px-4 py-1.5 font-mono text-blue-700">{col.type}</td>
                                  <td className="px-4 py-1.5">
                                    {col.nullable
                                      ? <span className="text-gray-400">NULL</span>
                                      : <span className="text-red-600 font-medium">NOT NULL</span>}
                                  </td>
                                  <td className="px-4 py-1.5 font-mono text-gray-500">{col.default ?? '—'}</td>
                                  <td className="px-4 py-1.5">
                                    <div className="flex gap-1">
                                      {isPK && <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded">PK</span>}
                                    </div>
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>

                        {/* Indexes */}
                        {tbl.indexes.length > 0 && (
                          <div className="px-4 py-2 bg-white">
                            <p className="text-xs font-medium text-gray-500 mb-1">Indexes</p>
                            <div className="space-y-0.5">
                              {tbl.indexes.map((ix, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs font-mono">
                                  {ix.unique && <span className="px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded">UNIQUE</span>}
                                  <span className="text-gray-700">{ix.name}</span>
                                  <span className="text-gray-400">({ix.columns.join(', ')})</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Foreign keys */}
                        {tbl.foreign_keys.length > 0 && (
                          <div className="px-4 py-2 bg-white">
                            <p className="text-xs font-medium text-gray-500 mb-1">Foreign Keys</p>
                            <div className="space-y-0.5">
                              {tbl.foreign_keys.map((fk, i) => (
                                <div key={i} className="text-xs font-mono text-gray-600">
                                  {fk.name && <span className="text-gray-400 mr-1">{fk.name}:</span>}
                                  <span className="text-gray-800">({fk.columns.join(', ')})</span>
                                  <span className="text-gray-400 mx-1">→</span>
                                  <span className="text-blue-700">{fk.references}</span>
                                  <span className="text-gray-400">({fk.ref_columns.join(', ')})</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
