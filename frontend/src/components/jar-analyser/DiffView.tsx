import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DiffReport, ServiceDiff, EndpointDiff, DepDiff, ConfigDiff, MigDiff, SchemaDiff, FieldDiff, ReportListItem, DbSchemaDiff } from './types'
import ExportControls from './ExportControls'

interface Props {
  diffId?: string
  reportAId?: string
  reportBId?: string
  onBack: () => void
}

const CHANGE_STYLES = {
  ADDED: 'bg-green-50 border-l-4 border-green-400',
  REMOVED: 'bg-red-50 border-l-4 border-red-400',
  CHANGED: 'bg-amber-50 border-l-4 border-amber-400',
}
const CHANGE_BADGE = {
  ADDED: 'bg-green-100 text-green-800',
  REMOVED: 'bg-red-100 text-red-800',
  CHANGED: 'bg-amber-100 text-amber-800',
}
const CHANGE_PREFIX = { ADDED: '+', REMOVED: '−', CHANGED: '~' }

export default function DiffView({ diffId: initialDiffId, reportAId, reportBId, onBack }: Props) {
  const [diffId, setDiffId] = useState(initialDiffId)
  const [selA, setSelA] = useState(reportAId ?? '')
  const [selB, setSelB] = useState(reportBId ?? '')
  const [labelA, setLabelA] = useState('')
  const [labelB, setLabelB] = useState('')
  const [filterChange, setFilterChange] = useState<string>('')
  const [openService, setOpenService] = useState<string | null>(null)
  const qc = useQueryClient()

  const { data: reports } = useQuery<{ items: ReportListItem[] }>({
    queryKey: ['jar-reports-all'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 100 } }).then(r => r.data),
    enabled: !diffId,
  })

  const { data: diff } = useQuery<DiffReport>({
    queryKey: ['diff', diffId],
    queryFn: () => api.get(`/jar-analyser/diff/${diffId}`).then(r => r.data),
    enabled: !!diffId,
  })

  const createMutation = useMutation({
    mutationFn: () => api.post('/jar-analyser/diff', {
      report_a_id: selA, report_b_id: selB,
      label_a: labelA || undefined, label_b: labelB || undefined,
    }).then(r => r.data),
    onSuccess: (data) => {
      setDiffId(data.diff_id)
      qc.invalidateQueries({ queryKey: ['diff', data.diff_id] })
    },
  })

  // Selector screen
  if (!diffId) {
    const items = reports?.items ?? []
    return (
      <div className="space-y-4 max-w-2xl">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800">← Back</button>
          <h2 className="text-xl font-bold text-gray-900">Compare Versions</h2>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Version A (baseline)</label>
              <select value={selA} onChange={e => setSelA(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
                <option value="">Select report...</option>
                {items.map(r => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.filename} {r.implementation_version ? `v${r.implementation_version}` : ''}
                  </option>
                ))}
              </select>
              <input type="text" value={labelA} onChange={e => setLabelA(e.target.value)}
                placeholder="Label (optional)" className="mt-2 w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Version B (new)</label>
              <select value={selB} onChange={e => setSelB(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
                <option value="">Select report...</option>
                {items.map(r => (
                  <option key={r.report_id} value={r.report_id}>
                    {r.filename} {r.implementation_version ? `v${r.implementation_version}` : ''}
                  </option>
                ))}
              </select>
              <input type="text" value={labelB} onChange={e => setLabelB(e.target.value)}
                placeholder="Label (optional)" className="mt-2 w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
            </div>
          </div>
          <button
            onClick={() => createMutation.mutate()}
            disabled={!selA || !selB || selA === selB || createMutation.isPending}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {createMutation.isPending ? 'Computing...' : 'Run Comparison'}
          </button>
          {createMutation.isError && (
            <p className="text-red-600 text-sm">{(createMutation.error as any)?.response?.data?.detail || 'Failed'}</p>
          )}
        </div>
      </div>
    )
  }

  if (!diff) return <div className="text-sm text-gray-400 py-8 text-center">Loading diff...</div>

  const s = diff.summary
  const serviceDiffs = diff.service_diffs ?? []
  const filtered = filterChange
    ? serviceDiffs.filter(sd => sd.change === filterChange ||
        sd.endpoint_diffs?.some(e => e.change === filterChange) ||
        sd.dependency_diffs?.some(d => d.change === filterChange))
    : serviceDiffs

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-2">← Back</button>
          <h2 className="text-xl font-bold text-gray-900">
            {diff.label_a ?? 'A'} → {diff.label_b ?? 'B'}
          </h2>
          <p className="text-xs text-gray-400 mt-1">
            {diff.report_a?.report_id?.slice(0, 8)} vs {diff.report_b?.report_id?.slice(0, 8)}
          </p>
        </div>
        <ExportControls reportId="" diffId={diff.diff_id} />
      </div>

      {/* Summary bar */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: 'Services', added: s.services_added, removed: s.services_removed, changed: s.services_changed },
          { label: 'Endpoints', added: s.endpoints_added, removed: s.endpoints_removed, changed: s.endpoints_changed },
          { label: 'Deps (ver)', added: s.dependencies_added, removed: s.dependencies_removed, changed: s.dependencies_version_changed },
          { label: 'Config Keys', added: s.config_keys_added, removed: s.config_keys_removed, changed: s.config_keys_changed },
          { label: 'Migrations', added: s.migration_scripts_added, removed: s.migration_scripts_removed, changed: 0 },
          { label: 'Schema Fields', added: s.schema_fields_added ?? 0, removed: s.schema_fields_removed ?? 0, changed: s.schema_fields_type_changed ?? 0 },
          { label: 'DB Tables', added: s.db_tables_added ?? 0, removed: s.db_tables_dropped ?? 0, changed: 0 },
          { label: 'DB Columns', added: s.db_columns_added ?? 0, removed: s.db_columns_dropped ?? 0, changed: 0 },
        ].map(c => (
          <div key={c.label} className="bg-white border border-gray-200 rounded-lg p-3 text-xs">
            <p className="font-medium text-gray-600 mb-2">{c.label}</p>
            <div className="flex gap-2">
              <span className="text-green-700">+{c.added}</span>
              <span className="text-red-600">−{c.removed}</span>
              <span className="text-amber-600">~{c.changed}</span>
            </div>
          </div>
        ))}
      </div>

      {(s.breaking_changes ?? 0) > 0 && (
        <div className="p-3 bg-red-50 border border-red-400 rounded-lg">
          <p className="text-sm font-bold text-red-800 mb-1">⚠ {s.breaking_changes} breaking change{s.breaking_changes !== 1 ? 's' : ''} — existing plugins may be affected</p>
          <ul className="space-y-0.5">
            {(s.breaking_change_details ?? []).map((d, i) => (
              <li key={i} className="text-xs text-red-700 font-mono">{d}</li>
            ))}
          </ul>
        </div>
      )}

      {s.security_changes > 0 && (
        <div className="p-3 bg-red-50 border border-red-300 rounded-lg text-sm text-red-800 font-medium">
          ⚠️ {s.security_changes} security change{s.security_changes > 1 ? 's' : ''} detected — review carefully
        </div>
      )}

      {/* Filter */}
      <div className="flex gap-2">
        {['', 'ADDED', 'REMOVED', 'CHANGED'].map(f => (
          <button key={f} onClick={() => setFilterChange(f)}
            className={`px-3 py-1 rounded text-xs border transition ${
              filterChange === f ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}>
            {f || 'All'}
          </button>
        ))}
      </div>

      {/* Service accordions */}
      <div className="space-y-2">
        {filtered.length === 0 && (
          <p className="text-sm text-gray-400 py-4 text-center">No changes found.</p>
        )}
        {filtered.map(sd => (
          <ServiceAccordion key={sd.service_name} sd={sd}
            open={openService === sd.service_name}
            onToggle={() => setOpenService(openService === sd.service_name ? null : sd.service_name)} />
        ))}
      </div>

      {/* Warnings */}
      {diff.warnings?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">⚠ Warnings</h3>
          <ul className="space-y-1">
            {diff.warnings.map((w, i) => <li key={i} className="text-xs text-amber-700">{w}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

function ServiceAccordion({ sd, open, onToggle }: { sd: ServiceDiff; open: boolean; onToggle: () => void }) {
  const [subTab, setSubTab] = useState<'endpoints' | 'deps' | 'config' | 'migrations' | 'schemas' | 'dbschema'>('endpoints')
  const hasSecurityChange = sd.endpoint_diffs?.some(e => e.detail?.security_changed)
  const hasBreaking = sd.schema_diffs?.some(s => s.field_diffs.some(f => f.impact === 'breaking'))
    || sd.db_schema_diffs?.some(d => d.risk === 'high')

  const epCount = sd.endpoint_diffs?.length ?? 0
  const depCount = sd.dependency_diffs?.length ?? 0
  const cfgCount = sd.config_diffs?.length ?? 0
  const migCount = sd.migration_diffs?.length ?? 0
  const schemaCount = sd.schema_diffs?.length ?? 0
  const dbSchemaCount = sd.db_schema_diffs?.length ?? 0

  return (
    <div className={`border rounded-lg overflow-hidden ${CHANGE_STYLES[sd.change]}`}>
      <button onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-black/5">
        <div className="flex items-center gap-3">
          <span className={`px-2 py-0.5 rounded text-xs font-bold ${CHANGE_BADGE[sd.change]}`}>
            {CHANGE_PREFIX[sd.change]} {sd.change}
          </span>
          <span className="font-medium text-gray-900">{sd.service_name}</span>
          {hasSecurityChange && <span className="text-red-600 text-xs font-bold">⚠️ SECURITY</span>}
          {hasBreaking && <span className="text-red-600 text-xs font-bold">⚠️ BREAKING</span>}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          {sd.version_change && <span>{sd.version_change.from} → {sd.version_change.to}</span>}
          {sd.port_change && <span>Port: {sd.port_change.from} → {sd.port_change.to}</span>}
          {epCount > 0 && <span>{epCount} endpoint changes</span>}
          {depCount > 0 && <span>{depCount} dep changes</span>}
          <span>{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && sd.change === 'CHANGED' && (
        <div className="border-t border-gray-200 bg-white">
          {/* Sub-tabs */}
          <div className="flex border-b border-gray-200 px-4">
            {([['endpoints', `Endpoints (${epCount})`], ['deps', `Dependencies (${depCount})`],
               ['config', `Config (${cfgCount})`], ['migrations', `Migrations (${migCount})`],
               ['schemas', `Schemas (${schemaCount})`],
               ['dbschema', `DB Schema (${dbSchemaCount})`]] as const).map(([id, label]) => (
              <button key={id} onClick={() => setSubTab(id)}
                className={`px-3 py-2 text-xs font-medium border-b-2 transition ${
                  subTab === id ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}>
                {label}
              </button>
            ))}
          </div>

          <div className="p-4 space-y-2">
            {subTab === 'endpoints' && (sd.endpoint_diffs ?? []).map((ep, i) => (
              <EndpointDiffRow key={i} ep={ep} />
            ))}
            {subTab === 'deps' && (sd.dependency_diffs ?? []).map((d, i) => (
              <DepDiffRow key={i} d={d} />
            ))}
            {subTab === 'config' && (sd.config_diffs ?? []).map((c, i) => (
              <ConfigDiffRow key={i} c={c} />
            ))}
            {subTab === 'migrations' && (sd.migration_diffs ?? []).map((m, i) => (
              <MigDiffRow key={i} m={m} />
            ))}
            {subTab === 'schemas' && (sd.schema_diffs ?? []).map((s, i) => (
              <SchemaDiffRow key={i} s={s} />
            ))}
            {subTab === 'dbschema' && <DbSchemaDiffPanel changes={sd.db_schema_diffs ?? []} />}
            {subTab === 'endpoints' && !epCount && <p className="text-xs text-gray-400">No endpoint changes.</p>}
            {subTab === 'deps' && !depCount && <p className="text-xs text-gray-400">No dependency changes.</p>}
            {subTab === 'config' && !cfgCount && <p className="text-xs text-gray-400">No config changes.</p>}
            {subTab === 'migrations' && !migCount && <p className="text-xs text-gray-400">No migration changes.</p>}
            {subTab === 'schemas' && !schemaCount && <p className="text-xs text-gray-400">No schema field changes — re-analyse both JARs to populate schema data.</p>}
            {subTab === 'dbschema' && !dbSchemaCount && <p className="text-xs text-gray-400">No DB schema changes — both versions have identical reconstructed schemas, or neither has Flyway migrations.</p>}
          </div>
        </div>
      )}
    </div>
  )
}

function EndpointDiffRow({ ep }: { ep: EndpointDiff }) {
  const [open, setOpen] = useState(false)
  const hasDetail = ep.detail && Object.keys(ep.detail).length > 0

  return (
    <div className={`rounded p-2 text-xs ${CHANGE_STYLES[ep.change]}`}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => hasDetail && setOpen(!open)}>
        <span className={`px-1.5 py-0.5 rounded font-bold text-xs ${CHANGE_BADGE[ep.change]}`}>
          {CHANGE_PREFIX[ep.change]}
        </span>
        <span className="font-mono font-bold text-gray-700">{ep.http_method}</span>
        <span className="font-mono text-gray-800">{ep.path}</span>
        {ep.detail?.security_changed && <span className="text-red-600 font-bold">⚠️ SECURITY</span>}
        {hasDetail && <span className="ml-auto text-gray-400">{open ? '▲' : '▼'}</span>}
      </div>
      {open && ep.detail && (
        <div className="mt-2 pl-4 space-y-1 border-l-2 border-gray-300">
          {ep.detail.parameters_added?.map((p, i) => (
            <div key={i} className="text-green-700">+ param <span className="font-mono">{p.name}</span> ({p.location}) ADDED</div>
          ))}
          {ep.detail.parameters_removed?.map((p, i) => (
            <div key={i} className="text-red-600">− param <span className="font-mono">{p.name}</span> REMOVED</div>
          ))}
          {ep.detail.security_changed && (
            <div className="p-2 bg-red-50 border border-red-200 rounded">
              <div className="text-red-600">− <span className="font-mono">{ep.detail.security_changed.from ?? 'none'}</span></div>
              <div className="text-green-700">+ <span className="font-mono">{ep.detail.security_changed.to ?? 'none'}</span></div>
            </div>
          )}
          {ep.detail.return_type_changed && (
            <div className="text-amber-700">
              Return type: <span className="font-mono">{ep.detail.return_type_changed.from?.simple_type}</span> → <span className="font-mono">{ep.detail.return_type_changed.to?.simple_type}</span>
            </div>
          )}
          {ep.detail.controller_changed && (
            <div className="text-amber-700">
              Controller: <span className="font-mono">{ep.detail.controller_changed.from}</span> → <span className="font-mono">{ep.detail.controller_changed.to}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DepDiffRow({ d }: { d: DepDiff }) {
  return (
    <div className={`rounded p-2 text-xs flex items-center gap-2 ${CHANGE_STYLES[d.change]}`}>
      <span className={`px-1.5 py-0.5 rounded font-bold ${CHANGE_BADGE[d.change]}`}>{CHANGE_PREFIX[d.change]}</span>
      <span className="font-mono text-gray-800">{d.maven_coordinates}</span>
      {d.change === 'CHANGED'
        ? <span className="text-gray-500">{d.version_from} → <span className="font-medium text-gray-800">{d.version_to}</span></span>
        : <span className="text-gray-500">{d.version}</span>
      }
    </div>
  )
}

function ConfigDiffRow({ c }: { c: ConfigDiff }) {
  return (
    <div className={`rounded p-2 text-xs ${CHANGE_STYLES[c.change]}`}>
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded font-bold ${CHANGE_BADGE[c.change]}`}>{CHANGE_PREFIX[c.change]}</span>
        <span className="text-gray-500">{c.file}</span>
        <span className="font-mono text-gray-800">{c.key}</span>
      </div>
      {c.change === 'CHANGED' && (
        <div className="mt-1 pl-4 space-y-0.5">
          <div className="text-red-600">− <span className="font-mono">{c.value_from}</span></div>
          <div className="text-green-700">+ <span className="font-mono">{c.value_to}</span></div>
        </div>
      )}
    </div>
  )
}

function MigDiffRow({ m }: { m: MigDiff }) {
  return (
    <div className={`rounded p-2 text-xs flex items-center gap-2 ${CHANGE_STYLES[m.change]}`}>
      <span className={`px-1.5 py-0.5 rounded font-bold ${CHANGE_BADGE[m.change]}`}>{CHANGE_PREFIX[m.change]}</span>
      <span className="font-mono text-gray-800">{m.filename}</span>
      {m.description && <span className="text-gray-500">{m.description}</span>}
      {m.warning && <span className="text-amber-600 font-bold">⚠️ removed</span>}
    </div>
  )
}

const IMPACT_BADGE: Record<string, string> = {
  breaking: 'bg-red-100 text-red-700 font-bold',
  potentially_breaking: 'bg-orange-100 text-orange-700',
  none: 'bg-gray-100 text-gray-500',
  review: 'bg-yellow-100 text-yellow-700',
}
const IMPACT_LABEL: Record<string, string> = {
  breaking: 'BREAKING',
  potentially_breaking: 'POTENTIALLY BREAKING',
  none: 'safe',
  review: 'REVIEW',
}

const RISK_STYLES: Record<string, string> = {
  high:   'bg-red-50 border-l-4 border-red-400',
  medium: 'bg-amber-50 border-l-4 border-amber-400',
  low:    'bg-green-50 border-l-4 border-green-400',
}
const RISK_BADGE: Record<string, string> = {
  high:   'bg-red-100 text-red-700 font-bold',
  medium: 'bg-amber-100 text-amber-700',
  low:    'bg-green-100 text-green-700',
}
const DB_CHANGE_LABEL: Record<string, string> = {
  TABLE_ADDED:        'Table added',
  TABLE_DROPPED:      'Table dropped',
  COLUMN_ADDED:       'Column added',
  COLUMN_DROPPED:     'Column dropped',
  TYPE_CHANGED:       'Type changed',
  CONSTRAINT_CHANGED: 'Constraint changed',
  INDEX_CHANGED:      'Index changed',
  FK_CHANGED:         'FK changed',
}

function DbSchemaDiffPanel({ changes }: { changes: DbSchemaDiff[] }) {
  const byTable = changes.reduce<Record<string, DbSchemaDiff[]>>((acc, c) => {
    acc[c.table] = [...(acc[c.table] ?? []), c]
    return acc
  }, {})
  const highCount = changes.filter(c => c.risk === 'high').length

  return (
    <div className="space-y-2">
      {highCount > 0 && (
        <div className="p-2 bg-red-50 border border-red-300 rounded text-xs text-red-700 font-medium">
          🔴 {highCount} high-risk change{highCount !== 1 ? 's' : ''} — review before deploying
          {changes.some(c => c.change === 'COLUMN_ADDED' && c.risk === 'high') &&
            ' (NOT NULL column added without default will fail on non-empty tables)'}
        </div>
      )}
      {Object.entries(byTable).sort().map(([table, rows]) => {
        const tableRisk = rows.some(r => r.risk === 'high') ? 'high' : rows.some(r => r.risk === 'medium') ? 'medium' : 'low'
        return (
          <div key={table} className={`rounded overflow-hidden ${RISK_STYLES[tableRisk]}`}>
            <div className="px-3 py-2 flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs ${RISK_BADGE[tableRisk]}`}>{tableRisk}</span>
              <span className="font-mono font-semibold text-sm text-gray-800">{table}</span>
              <span className="text-xs text-gray-400">{rows.length} change{rows.length !== 1 ? 's' : ''}</span>
            </div>
            <div className="bg-white divide-y divide-gray-100">
              {rows.map((c, i) => (
                <div key={i} className="px-4 py-1.5 text-xs flex items-start gap-3">
                  <span className={`shrink-0 px-1.5 py-0.5 rounded ${RISK_BADGE[c.risk]}`}>
                    {DB_CHANGE_LABEL[c.change] ?? c.change}
                  </span>
                  {c.column && <span className="font-mono text-gray-700">{c.column}</span>}
                  <DbSchemaDetail c={c} />
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DbSchemaDetail({ c }: { c: DbSchemaDiff }) {
  const d = c.detail ?? {}
  if (c.change === 'TYPE_CHANGED')
    return <span className="text-gray-500"><span className="font-mono">{d.from}</span> → <span className="font-mono">{d.to}</span></span>
  if (c.change === 'COLUMN_ADDED')
    return (
      <span className="text-gray-500">
        <span className="font-mono">{d.type}</span>
        {!d.nullable && d.default == null && <span className="ml-2 text-red-600 font-bold">NOT NULL, no default ⚠</span>}
        {d.default != null && <span className="ml-1 text-gray-400">default={d.default}</span>}
      </span>
    )
  if (c.change === 'CONSTRAINT_CHANGED')
    return <span className="text-gray-500">nullable: <span className="font-mono">{String(d.nullable_from)}</span> → <span className="font-mono">{String(d.nullable_to)}</span></span>
  if (c.change === 'INDEX_CHANGED' || c.change === 'FK_CHANGED') {
    const cols = (d.columns ?? []).join(', ')
    return <span className="text-gray-500 font-mono">{d.kind} {d.name}{cols ? ` (${cols})` : ''}{d.references ? ` → ${d.references}` : ''}</span>
  }
  return null
}

function SchemaDiffRow({ s }: { s: SchemaDiff }) {
  const [open, setOpen] = useState(false)
  const breakingCount = s.field_diffs.filter(f => f.impact === 'breaking').length
  const potentialCount = s.field_diffs.filter(f => f.impact === 'potentially_breaking').length

  return (
    <div className="border border-gray-200 rounded text-xs mb-1">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-50 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-gray-800">{s.simple_name}</span>
          {s.is_enum && <span className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded">enum</span>}
          <span className="text-gray-400">{s.field_diffs.length} field change{s.field_diffs.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="flex items-center gap-2">
          {breakingCount > 0 && (
            <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded font-bold">⚠ {breakingCount} breaking</span>
          )}
          {potentialCount > 0 && (
            <span className="px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded">{potentialCount} potential</span>
          )}
          <span className="text-gray-400">{open ? '▲' : '▼'}</span>
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-100 divide-y divide-gray-50">
          {s.field_diffs.map((f, i) => (
            <div key={i} className={`flex items-center gap-2 px-4 py-1.5 ${
              f.change === 'ADDED' || f.change === 'ENUM_VALUE_ADDED' ? 'bg-green-50' :
              f.change === 'REMOVED' || f.change === 'ENUM_VALUE_REMOVED' ? 'bg-red-50' : 'bg-amber-50'
            }`}>
              <span className={`font-bold w-3 ${
                f.change === 'ADDED' || f.change === 'ENUM_VALUE_ADDED' ? 'text-green-600' :
                f.change === 'REMOVED' || f.change === 'ENUM_VALUE_REMOVED' ? 'text-red-600' : 'text-amber-600'
              }`}>
                {f.change === 'ADDED' || f.change === 'ENUM_VALUE_ADDED' ? '+' :
                 f.change === 'REMOVED' || f.change === 'ENUM_VALUE_REMOVED' ? '−' : '~'}
              </span>
              <span className="font-mono text-gray-800 w-40 truncate">{f.field}</span>
              {f.change === 'TYPE_CHANGED'
                ? <span className="text-gray-500"><span className="font-mono">{f.type_from}</span> → <span className="font-mono">{f.type_to}</span></span>
                : f.type && <span className="text-gray-400 font-mono">{f.type}</span>
              }
              {f.required && f.change === 'ADDED' && (
                <span className="text-gray-500 italic">required</span>
              )}
              <span className={`ml-auto px-1.5 py-0.5 rounded text-xs ${IMPACT_BADGE[f.impact] ?? IMPACT_BADGE.none}`}>
                {IMPACT_LABEL[f.impact] ?? f.impact}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
