import { useState, useMemo } from 'react'
import type React from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { SubReportFull, Endpoint, Dependency, ConfigFile, MigrationScript, EventFile, DtoSchema, Workflow, ErrorResponse, ScheduledJob } from './types'
import EndpointTable from './EndpointTable'
import DependencyTable from './DependencyTable'
import ConfigViewer from './ConfigViewer'
import MigrationViewer from './MigrationViewer'
import EventViewer from './EventViewer'
import ExportControls from './ExportControls'
import SchemaViewer from './SchemaViewer'
import WorkflowView from './WorkflowView'
import DecompileTab from './DecompileTab'
import ConfigExamplesTab from './ConfigExamplesTab'
import StringsTab from './StringsTab'
import { OutboundIntegrationsSubTab } from './OutboundIntegrationsTab'
import type { ConfigExample } from './types'

type Tab = 'overview' | 'endpoints' | 'dependencies' | 'config' | 'migrations' | 'events' | 'schemas' | 'workflows' | 'scheduled_jobs' | 'errors' | 'source' | 'guide' | 'config_examples' | 'strings' | 'outbound'

interface Props {
  reportId: string
  subReportId: string
  initialTab?: string
  onBack: () => void
  onBugTracker?: (mode: 'new' | 'list') => void
  onFirstSeenDocs?: () => void
}

function fmtBytes(b: number) {
  if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

export default function SubReportView({ reportId, subReportId, initialTab, onBack, onBugTracker, onFirstSeenDocs }: Props) {
  const [tab, setTab] = useState<Tab>((initialTab as Tab) ?? 'overview')
  const [epPage, setEpPage] = useState(1)
  const [epFilters, setEpFilters] = useState<Record<string, string | boolean>>({})
  const [depPage, setDepPage] = useState(1)
  const [depCat, setDepCat] = useState('')

  const { data: sub } = useQuery<SubReportFull>({
    queryKey: ['sub-report', reportId, subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}`).then(r => r.data),
  })

  const { data: bugCount } = useQuery({
    queryKey: ['bug-count', subReportId],
    queryFn: () => api.get('/bugs', { params: { sub_report_id: subReportId, page_size: 1 } }).then(r => r.data.total as number),
    enabled: !!onBugTracker,
  })

  const { data: firstSeenDocCount } = useQuery({
    queryKey: ['first-seen-doc-count', subReportId],
    queryFn: () => api.get('/docs/search', { params: { first_seen_sub_report_id: subReportId, page_size: 1 } }).then(r => r.data.total as number),
    enabled: !!onFirstSeenDocs,
  })

  // Fetched eagerly (not gated on tab click like the others below) — the
  // tab's own presence in the tab bar depends on this list being non-empty,
  // since most services have no config/design documents at all.
  const { data: configExamples } = useQuery<ConfigExample[]>({
    queryKey: ['sub-config-examples', reportId, subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/config-examples`).then(r => r.data),
  })

  const { data: epData, isLoading: epLoading } = useQuery({
    queryKey: ['sub-endpoints', subReportId, epPage, epFilters],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/endpoints`, {
      params: { page: epPage, page_size: 50, ...epFilters },
    }).then(r => r.data),
    enabled: tab === 'endpoints',
  })

  const { data: depData, isLoading: depLoading } = useQuery({
    queryKey: ['sub-deps', subReportId, depPage, depCat],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/dependencies`, {
      params: { page: depPage, page_size: 50, category: depCat || undefined },
    }).then(r => r.data),
    enabled: tab === 'dependencies',
  })

  const { data: configs } = useQuery<ConfigFile[]>({
    queryKey: ['sub-config', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/config`).then(r => r.data),
    enabled: tab === 'config',
  })

  const { data: migrations } = useQuery<MigrationScript[]>({
    queryKey: ['sub-migrations', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/migrations`).then(r => r.data),
    enabled: tab === 'migrations',
  })

  const { data: events } = useQuery<EventFile[]>({
    queryKey: ['sub-events', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/events`).then(r => r.data),
    enabled: tab === 'events',
  })

  const { data: schemas } = useQuery<DtoSchema[]>({
    queryKey: ['sub-schemas', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schemas`).then(r => r.data),
    enabled: tab === 'schemas',
  })

  const { data: workflows } = useQuery<Workflow[]>({
    queryKey: ['sub-workflows', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/workflows`).then(r => r.data),
    enabled: tab === 'workflows',
  })

  const { data: errorResponses } = useQuery<ErrorResponse[]>({
    queryKey: ['sub-errors', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/errors`).then(r => r.data),
    enabled: tab === 'errors',
  })

  const { data: scheduledJobs } = useQuery<ScheduledJob[]>({
    queryKey: ['sub-scheduled-jobs', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/scheduled-jobs`).then(r => r.data),
    enabled: tab === 'scheduled_jobs',
  })

  const { data: guideText } = useQuery<string>({
    queryKey: ['sub-guide', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/export/markdown`, { responseType: 'text' }).then(r => r.data as string),
    enabled: tab === 'guide',
  })

  const isFrontend = sub?.jar_type === 'frontend_installer'

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    ...(!isFrontend ? [{ id: 'endpoints' as Tab, label: `Endpoints${epData ? ` (${epData.total})` : ''}` }] : []),
    { id: 'dependencies', label: isFrontend
        ? `NPM Packages${depData ? ` (${depData.total})` : ''}`
        : `Dependencies${depData ? ` (${depData.total})` : ''}` },
    { id: 'config', label: 'Configuration' },
    ...(!isFrontend ? [{ id: 'migrations' as Tab, label: 'Migrations' }] : []),
    ...(!isFrontend ? [{ id: 'events' as Tab, label: 'Events' }] : []),
    ...(!isFrontend ? [{ id: 'schemas' as Tab, label: `Schemas${schemas ? ` (${schemas.length})` : ''}` }] : []),
    ...(!isFrontend ? [{ id: 'workflows' as Tab, label: `Workflows${workflows ? ` (${workflows.length})` : ''}` }] : []),
    ...(!isFrontend ? [{ id: 'scheduled_jobs' as Tab, label: `Scheduled Jobs${scheduledJobs ? ` (${scheduledJobs.length})` : ''}` }] : []),
    ...(!isFrontend ? [{ id: 'errors' as Tab, label: `Errors${errorResponses ? ` (${errorResponses.length})` : ''}` }] : []),
    ...(!isFrontend ? [{ id: 'source' as Tab, label: '🧬 Source' }] : []),
    ...(!isFrontend ? [{ id: 'strings' as Tab, label: '🔤 Strings' }] : []),
    ...(!isFrontend ? [{ id: 'outbound' as Tab, label: '🌐 Outbound' }] : []),
    { id: 'guide' as Tab, label: '📖 Service Guide' },
    ...(configExamples && configExamples.length > 0 ? [{ id: 'config_examples' as Tab, label: '🧩 Config Examples' }] : []),
  ]

  if (!sub) return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-2 flex items-center gap-1">
            ← Back to report
          </button>
          <h2 className="text-xl font-bold text-gray-900">{sub.filename}</h2>
          <div className="flex flex-wrap gap-3 mt-1 text-sm text-gray-500">
            {sub.spring_boot_version && <span>Spring Boot {sub.spring_boot_version}</span>}
            {sub.declared_port && <span>Port {sub.declared_port}</span>}
            {sub.group_name && <span>Group: {sub.group_name}</span>}
            {sub.install_path && <span>📁 {sub.install_path}</span>}
            <span>{fmtBytes(sub.size_bytes)}</span>
          </div>
          {sub.start_class && (
            <p className="text-xs text-gray-400 mt-1 font-mono">{sub.start_class}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onBugTracker && (
            <>
              <button
                onClick={() => onBugTracker('new')}
                className="px-3 py-1.5 border border-rose-300 rounded text-sm text-rose-700 hover:bg-rose-50">
                🐛 Report Bug
              </button>
              {!!bugCount && (
                <button
                  onClick={() => onBugTracker('list')}
                  className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50">
                  🐛 {bugCount} bug{bugCount !== 1 ? 's' : ''}
                </button>
              )}
            </>
          )}
          {!!onFirstSeenDocs && !!firstSeenDocCount && (
            <button
              onClick={() => onFirstSeenDocs()}
              className="px-3 py-1.5 border border-indigo-300 rounded text-sm text-indigo-700 hover:bg-indigo-50">
              📄 {firstSeenDocCount} doc{firstSeenDocCount !== 1 ? 's' : ''} first seen here
            </button>
          )}
          <ExportControls reportId={reportId} subReportId={subReportId} />
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {tab === 'overview' && <OverviewTab sub={sub} reportId={reportId} />}

      {tab === 'endpoints' && !isFrontend && (
        <EndpointTable
          endpoints={(epData?.items ?? []) as Endpoint[]}
          loading={epLoading}
          total={epData?.total}
          page={epPage}
          pages={epData?.pages}
          declaredPort={sub.declared_port}
          reportId={reportId}
          subReportId={subReportId}
          serviceName={sub.service_name ?? sub.filename}
          onPageChange={setEpPage}
          onFilterChange={f => { setEpFilters(f as Record<string, string | boolean>); setEpPage(1) }}
        />
      )}

      {tab === 'dependencies' && (
        <DependencyTable
          dependencies={(depData?.items ?? []) as Dependency[]}
          loading={depLoading}
          total={depData?.total}
          page={depPage}
          pages={depData?.pages}
          onPageChange={setDepPage}
          onCategoryChange={c => { setDepCat(c); setDepPage(1) }}
        />
      )}

      {tab === 'config' && <ConfigViewer configs={configs ?? []} />}
      {tab === 'migrations' && !isFrontend && <MigrationViewer migrations={migrations ?? []} reportId={reportId} subReportId={subReportId} />}
      {tab === 'events' && !isFrontend && <EventViewer events={events ?? []} reportId={reportId} subReportId={subReportId} />}
      {tab === 'schemas' && !isFrontend && (
        <SchemasTab schemas={schemas ?? []} />
      )}
      {tab === 'workflows' && !isFrontend && (
        <WorkflowView workflows={workflows ?? []} reportId={reportId} subReportId={subReportId} />
      )}
      {tab === 'scheduled_jobs' && !isFrontend && (
        <ScheduledJobsTab jobs={scheduledJobs ?? []} />
      )}
      {tab === 'errors' && !isFrontend && (
        <ErrorsTab errors={errorResponses ?? []} reportId={reportId} subReportId={subReportId} />
      )}
      {tab === 'source' && !isFrontend && (
        <DecompileTab reportId={reportId} subReportId={subReportId} />
      )}
      {tab === 'strings' && !isFrontend && (
        <StringsTab reportId={reportId} subReportId={subReportId} />
      )}
      {tab === 'outbound' && !isFrontend && (
        <OutboundIntegrationsSubTab reportId={reportId} subReportId={subReportId} />
      )}
      {tab === 'guide' && <ServiceGuideTab text={guideText} />}
      {tab === 'config_examples' && (
        <ConfigExamplesTab reportId={reportId} subReportId={subReportId} />
      )}
    </div>
  )
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-gray-500 shrink-0 w-36">{label}:</span>
      <span className="font-mono text-gray-800 break-all">{value}</span>
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
      {children}
    </div>
  )
}

function FrontendOverview({ fe }: { fe: any }) {
  return (
    <>
      <Card title="Frontend Application">
        <KV label="Package" value={fe.package_name} />
        <KV label="Version" value={fe.app_version ?? fe.package_version} />
        <KV label="Framework" value={<span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs font-medium">{fe.framework ?? 'Unknown'}</span>} />
        {fe.description && <KV label="Description" value={fe.description} />}
      </Card>

      {fe.server_entry_points?.length > 0 && (
        <Card title="Node.js Server Entry Points">
          {fe.server_entry_points.map((ep: string) => (
            <div key={ep} className="text-xs font-mono text-gray-700 py-0.5">📄 {ep}</div>
          ))}
        </Card>
      )}

      {fe.node_scripts && Object.keys(fe.node_scripts).length > 0 && (
        <Card title="NPM Scripts">
          <div className="space-y-1">
            {Object.entries(fe.node_scripts).map(([name, cmd]) => (
              <div key={name} className="flex gap-2 text-xs">
                <span className="font-medium text-blue-700 w-28 shrink-0">{name}</span>
                <span className="font-mono text-gray-600 break-all">{String(cmd)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {fe.api_urls?.length > 0 && (
        <Card title="Backend API Endpoints">
          <div className="space-y-1">
            {fe.api_urls.map((u: any, i: number) => (
              <div key={i} className="flex gap-2 text-xs">
                <span className="text-gray-500 w-48 shrink-0">{u.key}</span>
                <span className="font-mono text-gray-700 break-all">{u.value}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {fe.app_yml && Object.keys(fe.app_yml).length > 0 && (
        <Card title="Runtime Config (app.yml)">
          {fe.app_yml.configService && (
            <KV label="Config service URI" value={String(fe.app_yml.configService.uri ?? '')} />
          )}
          {fe.app_yml.server && (
            <>
              <KV label="SSL enabled" value={String(fe.app_yml.server.ssl ?? '')} />
              {fe.app_yml.server.cert && <KV label="TLS cert" value={fe.app_yml.server.cert} />}
              {fe.app_yml.server.ca && <KV label="CA cert" value={fe.app_yml.server.ca} />}
            </>
          )}
        </Card>
      )}

      {fe.env_vars?.length > 0 && (
        <Card title="Environment Variables (sysconfig)">
          <div className="space-y-1">
            {fe.env_vars.map((e: any) => (
              <div key={e.key} className="flex gap-2 text-xs">
                <span className="font-mono text-gray-600 w-48 shrink-0">{e.key}</span>
                <span className="font-mono text-gray-400 break-all">{e.value}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {fe.dependencies && Object.keys(fe.dependencies).length > 0 && (
        <Card title={`Runtime Dependencies (${Object.keys(fe.dependencies).length})`}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(fe.dependencies).map(([pkg, ver]) => (
              <div key={pkg} className="flex justify-between text-xs">
                <span className="text-gray-700">{pkg}</span>
                <span className="font-mono text-gray-500">{String(ver)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {fe.dev_dependencies && Object.keys(fe.dev_dependencies).length > 0 && (
        <Card title={`Dev Dependencies (${Object.keys(fe.dev_dependencies).length})`}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(fe.dev_dependencies).map(([pkg, ver]) => (
              <div key={pkg} className="flex justify-between text-xs">
                <span className="text-gray-700">{pkg}</span>
                <span className="font-mono text-gray-500">{String(ver)}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  )
}

function NginxOverview({ ng }: { ng: any }) {
  return (
    <>
      {ng.service_dependencies?.length > 0 && (
        <Card title="Service Dependencies">
          <div className="flex flex-wrap gap-2">
            {ng.service_dependencies.map((s: string) => (
              <span key={s} className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs font-mono">{s}</span>
            ))}
          </div>
        </Card>
      )}

      {ng.upstreams?.length > 0 && (
        <Card title="Nginx Upstreams">
          <div className="space-y-3">
            {ng.upstreams.map((u: any) => (
              <div key={u.name} className="border border-gray-100 rounded p-2">
                <div className="text-xs font-semibold text-gray-700 mb-1">{u.name}</div>
                {u.servers.map((s: string) => (
                  <div key={s} className="text-xs font-mono text-gray-600 ml-2">→ {s}</div>
                ))}
                {u.keepalive && <div className="text-xs text-gray-400 ml-2">keepalive: {u.keepalive}</div>}
              </div>
            ))}
          </div>
        </Card>
      )}

      {ng.ha_upstreams?.length > 0 && (
        <Card title="HA Upstreams">
          <div className="space-y-3">
            {ng.ha_upstreams.map((u: any) => (
              <div key={u.name} className="border border-gray-100 rounded p-2">
                <div className="text-xs font-semibold text-gray-700 mb-1">{u.name} <span className="text-orange-500">(HA)</span></div>
                {u.servers.map((s: string) => (
                  <div key={s} className="text-xs font-mono text-gray-600 ml-2">→ {s}</div>
                ))}
              </div>
            ))}
          </div>
        </Card>
      )}

      {ng.server_blocks?.length > 0 && (
        <Card title="Server Blocks">
          {ng.server_blocks.map((b: any, i: number) => (
            <div key={i} className="text-xs space-y-1 border-b border-gray-100 pb-2 mb-2 last:border-0">
              {b.listen_ports?.length > 0 && <KV label="Listen" value={b.listen_ports.join(', ')} />}
              {b.server_names?.length > 0 && <KV label="Server names" value={b.server_names.join(', ')} />}
              {b.ssl && <span className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs">SSL</span>}
            </div>
          ))}
        </Card>
      )}
    </>
  )
}

function MonitoringOverview({ mon }: { mon: any }) {
  return (
    <>
      {mon.grafana_datasources?.length > 0 && (
        <Card title="Grafana Datasources">
          {mon.grafana_datasources.map((ds: any, i: number) => (
            <div key={i} className="text-xs space-y-0.5 border-b border-gray-100 pb-2 mb-2 last:border-0">
              <KV label="Name" value={ds.name} />
              <KV label="Type" value={ds.type} />
              <KV label="URL" value={ds.url} />
            </div>
          ))}
        </Card>
      )}

      {mon.grafana_dashboards?.length > 0 && (
        <Card title="Grafana Dashboards">
          {mon.grafana_dashboards.map((d: any) => (
            <div key={d.filename} className="border border-gray-100 rounded p-2 mb-2">
              <div className="text-xs font-semibold text-gray-700">{d.title ?? d.filename}</div>
              <div className="text-xs text-gray-500">{d.panel_count} panels</div>
              {d.panel_titles?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {d.panel_titles.filter(Boolean).map((t: string) => (
                    <span key={t} className="px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-xs">{t}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </Card>
      )}

      {mon.prometheus_jobs?.length > 0 && (
        <Card title="Prometheus Scrape Jobs">
          {mon.prometheus_jobs.map((j: any) => (
            <div key={j.job_name} className="border border-gray-100 rounded p-2 mb-2">
              <div className="text-xs font-semibold text-gray-700 mb-1">{j.job_name}</div>
              {j.metrics_path && <KV label="Metrics path" value={j.metrics_path} />}
              {j.scheme && <KV label="Scheme" value={j.scheme} />}
              {j.targets?.map((t: string) => (
                <div key={t} className="text-xs font-mono text-gray-600 ml-2">→ {t}</div>
              ))}
              <div className="flex gap-2 mt-1">
                {j.has_auth && <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded text-xs">Auth</span>}
                {j.has_tls && <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs">TLS</span>}
              </div>
            </div>
          ))}
        </Card>
      )}

      {mon.grafana_ini && Object.keys(mon.grafana_ini).length > 0 && (
        <Card title="Grafana Config (grafana.ini)">
          {Object.entries(mon.grafana_ini).map(([section, keys]: [string, any]) => (
            <div key={section} className="mb-2">
              <div className="text-xs font-semibold text-gray-600 mb-1">[{section}]</div>
              {Object.entries(keys).map(([k, v]) => (
                <KV key={k} label={k} value={String(v)} />
              ))}
            </div>
          ))}
        </Card>
      )}
    </>
  )
}

function InstallerBaseInfo({ meta }: { meta: any }) {
  const base: Record<string, any> = Object.fromEntries(
    Object.entries(meta).filter(([k]) => !['frontend', 'nginx', 'monitoring'].includes(k))
  )
  if (Object.keys(base).length === 0) return null
  return (
    <Card title="Installer Metadata">
      {base.name && <KV label="Name" value={base.name} />}
      {base.install_path && <KV label="Install path" value={base.install_path} />}
      {base.group && <KV label="Group" value={base.group} />}
      {base.build_info && (
        <div className="mt-2 space-y-1">
          {Object.entries(base.build_info as Record<string, string>).map(([k, v]) => (
            <KV key={k} label={k} value={v} />
          ))}
        </div>
      )}
      {(base.firewall_ports as number[])?.length > 0 && (
        <KV label="Firewall ports" value={(base.firewall_ports as number[]).join(', ')} />
      )}
      {(base.templates as any[])?.length > 0 && (
        <div className="mt-2">
          <div className="text-xs text-gray-500 mb-1">Templates:</div>
          {(base.templates as any[]).map((t: any, i: number) => (
            <div key={i} className="text-xs font-mono text-gray-600 ml-2">{t.in}: {t.ref}</div>
          ))}
        </div>
      )}
    </Card>
  )
}

const LAYER_COLOURS: Record<string, string> = {
  controller: 'bg-blue-100 text-blue-800',
  service:    'bg-green-100 text-green-800',
  repository: 'bg-purple-100 text-purple-800',
  model:      'bg-yellow-100 text-yellow-800',
  config:     'bg-orange-100 text-orange-800',
  event:      'bg-pink-100 text-pink-800',
  security:   'bg-red-100 text-red-800',
  util:       'bg-gray-100 text-gray-700',
  other:      'bg-gray-50 text-gray-500',
}

function PackageStructureCard({ layerSummary, totalClasses }: { layerSummary: any[]; totalClasses: number }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const grouped = useMemo((): [string, { packages: string[]; total: number }][] => {
    const map: Record<string, { packages: string[]; total: number }> = {}
    for (const ls of layerSummary) {
      if (!map[ls.layer]) map[ls.layer] = { packages: [], total: 0 }
      map[ls.layer]!.packages.push(`${ls.package} (${ls.class_count})`)
      map[ls.layer]!.total += ls.class_count
    }
    return Object.entries(map).sort((a, b) => b[1].total - a[1].total)
  }, [layerSummary])

  return (
    <Card title={`Package Structure — ${totalClasses} classes across ${layerSummary.length} packages`}>
      <div className="space-y-1">
        {grouped.map(([layer, info]) => (
          <div key={layer}>
            <button
              onClick={() => setExpanded(e => ({ ...e, [layer]: !e[layer] }))}
              className="w-full flex items-center justify-between px-2 py-1.5 rounded hover:bg-gray-50 text-xs"
            >
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded font-medium capitalize ${LAYER_COLOURS[layer] ?? LAYER_COLOURS.other}`}>
                  {layer}
                </span>
                <span className="text-gray-500">{info.packages.length} package{info.packages.length !== 1 ? 's' : ''}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-gray-700">{info.total} classes</span>
                <span className="text-gray-400">{expanded[layer] ? '▲' : '▼'}</span>
              </div>
            </button>
            {expanded[layer] && (
              <div className="ml-4 mb-1 space-y-0.5">
                {info.packages.map(p => (
                  <div key={p} className="text-xs font-mono text-gray-500 py-0.5 border-l-2 border-gray-200 pl-2">{p}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function SchemasTab({ schemas }: { schemas: DtoSchema[] }) {
  const [search, setSearch] = useState('')
  const [enumsOnly, setEnumsOnly] = useState(false)
  const filtered = schemas.filter(s => {
    if (enumsOnly && !s.is_enum) return false
    if (search && !s.simple_name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })
  return (
    <div className="space-y-3">
      <div className="flex gap-2 items-center">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search schemas..."
          className="border border-gray-300 rounded px-3 py-1 text-xs w-56"
        />
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
          <input type="checkbox" checked={enumsOnly} onChange={e => setEnumsOnly(e.target.checked)} />
          Enums only
        </label>
        <span className="text-xs text-gray-400 ml-auto">{filtered.length} schema{filtered.length !== 1 ? 's' : ''}</span>
      </div>
      {filtered.length === 0 && (
        <p className="text-sm text-gray-400 py-4 text-center">
          {schemas.length === 0 ? 'No schemas extracted — re-analyse the JAR to generate schemas.' : 'No schemas match the filter.'}
        </p>
      )}
      <div className="space-y-2">
        {filtered.map(s => <SchemaViewer key={s.id} schema={s} />)}
      </div>
    </div>
  )
}

function ScheduledJobsTab({ jobs }: { jobs: ScheduledJob[] }) {
  if (jobs.length === 0) {
    return <p className="text-sm text-gray-400 py-4 text-center">No @Scheduled methods found — re-analyse JAR to extract scheduled jobs.</p>
  }

  return (
    <div className="space-y-2">
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Class</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Method</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Schedule</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-32">Config-driven</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {jobs.map(j => (
              <tr key={j.id} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-mono text-xs text-gray-800">{j.declaring_class_simple}</td>
                <td className="px-4 py-2 font-mono text-xs text-gray-600">{j.method_name}</td>
                <td className="px-4 py-2 font-mono text-xs text-blue-700">{j.display}</td>
                <td className="px-4 py-2">
                  {j.is_config_driven && (
                    <span className="px-2 py-0.5 bg-amber-100 text-amber-700 rounded text-xs">config-driven</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ErrorsTab({ errors, reportId, subReportId }: { errors: ErrorResponse[]; reportId: string; subReportId: string }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (errors.length === 0) {
    return <p className="text-sm text-gray-400 py-4 text-center">No @ExceptionHandler methods found — re-analyse JAR to extract error responses.</p>
  }

  const statusColour = (s: number | null) => {
    if (!s) return 'bg-gray-100 text-gray-600'
    if (s < 400) return 'bg-green-100 text-green-700'
    if (s < 500) return 'bg-amber-100 text-amber-700'
    return 'bg-red-100 text-red-700'
  }

  return (
    <div className="space-y-2">
      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-16">Status</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Exception</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Response Schema</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-20">Scope</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {errors.map(e => (
              <>
                <tr key={e.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => setExpanded(expanded === e.id ? null : e.id)}>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${statusColour(e.http_status)}`}>
                      {e.http_status ?? '?'}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-800">{e.exception_class ?? '—'}</td>
                  <td className="px-4 py-2 text-xs">
                    {e.response_schema_class
                      ? <span className="font-mono text-blue-700">{e.response_schema_class}</span>
                      : <span className="text-gray-400">void / unknown</span>}
                  </td>
                  <td className="px-4 py-2">
                    <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{e.scope}</span>
                  </td>
                </tr>
                {expanded === e.id && (
                  <tr key={`${e.id}-detail`} className="bg-blue-50">
                    <td colSpan={4} className="px-6 py-3">
                      <ErrorDetail error={e} reportId={reportId} subReportId={subReportId} />
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

function ErrorDetail({ error, reportId, subReportId }: { error: ErrorResponse; reportId: string; subReportId: string }) {
  const { data: schema } = useQuery<import('./types').DtoSchema>({
    queryKey: ['schema', subReportId, error.response_schema_class],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schemas/${encodeURIComponent(error.response_schema_class!)}`
    ).then(r => r.data),
    enabled: !!error.response_schema_class,
    retry: false,
  })

  return (
    <div className="space-y-2 text-xs">
      {error.controller_class && (
        <div><span className="text-gray-500">Handler class: </span><span className="font-mono">{error.controller_class}</span></div>
      )}
      {error.response_schema_class && (
        <div>
          <p className="font-medium text-gray-700 mb-1">Response Schema: <span className="font-mono">{error.response_schema_class}</span></p>
          {schema
            ? <SchemaViewer schema={schema} inline />
            : <p className="text-gray-400 italic">Schema not yet extracted — re-analyse JAR to populate.</p>}
        </div>
      )}
    </div>
  )
}

function ServiceGuideTab({ text }: { text: string | undefined }) {
  const [search, setSearch] = useState('')
  const lines = useMemo(() => (text ?? '').split('\n'), [text])

  const matchingLineNums = useMemo(() => {
    if (!search.trim()) return new Set<number>()
    const q = search.toLowerCase()
    const set = new Set<number>()
    lines.forEach((l, i) => { if (l.toLowerCase().includes(q)) set.add(i) })
    return set
  }, [lines, search])

  if (!text) return <div className="text-sm text-gray-400 py-8 text-center">Loading guide…</div>

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search guide…"
          className="border border-gray-300 rounded px-3 py-1.5 text-sm w-64 font-mono"
        />
        {search && (
          <span className="text-xs text-gray-500">
            {matchingLineNums.size === 0 ? 'No matches' : `${matchingLineNums.size} line${matchingLineNums.size !== 1 ? 's' : ''}`}
          </span>
        )}
      </div>
      <div className="bg-gray-950 rounded-lg overflow-auto max-h-[70vh] text-xs font-mono leading-5">
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, i) => {
              const isMatch = matchingLineNums.has(i)
              const q = search.toLowerCase()
              const idx = search.trim() ? line.toLowerCase().indexOf(q) : -1
              return (
                <tr key={i} className={isMatch ? 'bg-yellow-900/40' : ''}>
                  <td className="select-none text-right pr-4 pl-3 py-0 text-gray-600 w-12 shrink-0 border-r border-gray-800">{i + 1}</td>
                  <td className="pl-4 pr-3 py-0 text-gray-200 whitespace-pre">
                    {idx === -1 ? line : <>{line.slice(0, idx)}<mark className="bg-yellow-400 text-gray-900 rounded-sm">{line.slice(idx, idx + search.length)}</mark>{line.slice(idx + search.length)}</>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400">{lines.length} lines · Read-only view — always reflects the current analysis.</p>
    </div>
  )
}

function OverviewTab({ sub, reportId }: { sub: SubReportFull; reportId: string }) {
  const cfv = sub.class_file_versions ?? {}
  const pkg = sub.package_structure ?? {}
  const meta = sub.installer_metadata ?? {}
  const fe = meta.frontend
  const ng = meta.nginx
  const mon = meta.monitoring

  const { data: posture } = useQuery({
    queryKey: ['security-posture', sub.sub_report_id],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${sub.sub_report_id}/security-posture`).then(r => r.data),
    enabled: sub.jar_type !== 'frontend_installer' && sub.jar_type !== 'nginx_installer' && sub.jar_type !== 'monitoring_installer',
  })

  return (
    <div className="space-y-4">
      {/* Perceived Purpose (Stage 6) */}
      {sub.purpose_narrative && sub.purpose_narrative.length > 0 && (
        <Card title="Perceived Purpose">
          <p className="text-xs text-gray-400 mb-2">
            Synthesised from static evidence extracted by this tool — inferred statements are hedged
            and cite their evidence; facts (developer-authored text, platform metadata) are stated plainly.
          </p>
          <div className="space-y-2">
            {sub.purpose_narrative.map((st, i) => (
              <div key={i} className={`p-2 rounded border text-sm ${
                st.is_inference ? 'bg-indigo-50 border-indigo-200 text-indigo-900' : 'bg-emerald-50 border-emerald-200 text-emerald-900'
              }`}>
                <span className={`inline-block mb-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                  st.is_inference ? 'bg-indigo-600 text-white' : 'bg-emerald-600 text-white'
                }`}>
                  {st.is_inference ? 'Inferred' : 'Fact'}
                </span>
                <p>{st.text}</p>
                {st.category === 'authored_intent' && Array.isArray(st.evidence) && (
                  <ul className="mt-1 space-y-1 list-disc list-inside">
                    {(st.evidence as string[]).map((snippet, j) => (
                      <li key={j} className="text-emerald-800">{snippet}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Security Posture */}
      {posture && posture.total_endpoints > 0 && (
        <Card title="Security Posture">
          <div className="grid grid-cols-3 gap-3 mb-3">
            {[
              { label: 'Public', count: posture.summary.public_count, colour: posture.summary.public_count > 0 ? 'text-amber-600' : 'text-gray-400' },
              { label: 'Authenticated', count: posture.summary.authenticated_only_count, colour: 'text-blue-600' },
              { label: 'Role-gated', count: posture.summary.role_gated_count, colour: 'text-green-600' },
              { label: 'Authority-gated', count: posture.summary.authority_gated_count, colour: 'text-purple-600' },
              { label: 'Deny-all', count: posture.summary.deny_all_count, colour: 'text-red-600' },
              { label: 'Unannotated', count: posture.summary.unannotated_count, colour: posture.summary.unannotated_count > 0 ? 'text-red-500' : 'text-gray-400' },
            ].map(({ label, count, colour }) => (
              <div key={label} className="text-center">
                <div className={`text-2xl font-bold ${colour}`}>{count}</div>
                <div className="text-xs text-gray-500">{label}</div>
              </div>
            ))}
          </div>
          {posture.summary.unique_roles.length > 0 && (
            <div className="mb-2">
              <span className="text-xs text-gray-500 mr-2">Roles required:</span>
              {posture.summary.unique_roles.map((r: string) => (
                <span key={r} className="inline-block mr-1 mb-1 px-2 py-0.5 bg-amber-100 text-amber-800 rounded text-xs font-mono">{r}</span>
              ))}
            </div>
          )}
          {posture.summary.unique_authorities.length > 0 && (
            <div className="mb-2">
              <span className="text-xs text-gray-500 mr-2">Authorities required:</span>
              {posture.summary.unique_authorities.map((a: string) => (
                <span key={a} className="inline-block mr-1 mb-1 px-2 py-0.5 bg-purple-100 text-purple-800 rounded text-xs font-mono">{a}</span>
              ))}
            </div>
          )}
          {posture.public_endpoints.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-amber-600 cursor-pointer font-medium">⚠ {posture.public_endpoints.length} public endpoint{posture.public_endpoints.length !== 1 ? 's' : ''}</summary>
              <div className="mt-1 space-y-0.5 ml-2">
                {posture.public_endpoints.map((ep: any) => (
                  <div key={ep.endpoint_id} className="text-xs font-mono text-gray-600">
                    <span className="text-gray-400 mr-1">{ep.method}</span>{ep.path}
                  </div>
                ))}
              </div>
            </details>
          )}
          {posture.unannotated_endpoints.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-red-500 cursor-pointer font-medium">⚠ {posture.unannotated_endpoints.length} unannotated endpoint{posture.unannotated_endpoints.length !== 1 ? 's' : ''} — treat as requiring auth</summary>
              <div className="mt-1 space-y-0.5 ml-2">
                {posture.unannotated_endpoints.map((ep: any) => (
                  <div key={ep.endpoint_id} className="text-xs font-mono text-gray-600">
                    <span className="text-gray-400 mr-1">{ep.method}</span>{ep.path}
                  </div>
                ))}
              </div>
            </details>
          )}
        </Card>
      )}

      {/* Manifest — only show for Java types */}
      {sub.start_class && Object.keys(sub.manifest ?? {}).length > 0 && (
        <Card title="Manifest">
          <div className="space-y-1">
            {Object.entries(sub.manifest).filter(([, v]) => v).map(([k, v]) => (
              <KV key={k} label={k} value={String(v)} />
            ))}
          </div>
        </Card>
      )}

      {/* Base installer info (name, group, build_info, templates) */}
      <InstallerBaseInfo meta={meta} />

      {/* Type-specific rich views */}
      {fe && <FrontendOverview fe={fe} />}
      {ng && <NginxOverview ng={ng} />}
      {mon && <MonitoringOverview mon={mon} />}

      {/* Java: Bytecode */}
      {cfv.java_version && (
        <Card title="Bytecode">
          <div className="flex gap-6 text-sm">
            <div><span className="text-gray-500">Java Version:</span> <span className="font-medium">{cfv.java_version}</span></div>
            {cfv.min != null && <div><span className="text-gray-500">Class file:</span> <span className="font-mono">{cfv.min}–{cfv.max}</span></div>}
          </div>
        </Card>
      )}

      {Array.isArray(pkg.layer_summary) && pkg.layer_summary.length > 0 && (
        <PackageStructureCard layerSummary={pkg.layer_summary} totalClasses={pkg.class_count} />
      )}
    </div>
  )
}
