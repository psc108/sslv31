import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { Endpoint, EndpointParam, DtoSchema, ErrorResponse } from './types'
import SchemaViewer from './SchemaViewer'

interface Props {
  endpoints: Endpoint[]
  loading?: boolean
  total?: number
  page?: number
  pages?: number
  declaredPort?: number | null
  reportId: string
  subReportId: string
  serviceName?: string
  onPageChange?: (p: number) => void
  onFilterChange?: (filters: { http_method?: string; path_contains?: string; confidence?: string; auth_filter?: string; paginated_only?: boolean; internal_only?: boolean; opaque_only?: boolean }) => void
}

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-green-100 text-green-800',
  POST: 'bg-blue-100 text-blue-800',
  PUT: 'bg-amber-100 text-amber-800',
  PATCH: 'bg-orange-100 text-orange-800',
  DELETE: 'bg-red-100 text-red-800',
}

export default function EndpointTable({
  endpoints, loading, total, page = 1, pages = 1,
  declaredPort, reportId, subReportId, serviceName = '',
  onPageChange, onFilterChange,
}: Props) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [methodFilter, setMethodFilter] = useState('')
  const [pathFilter, setPathFilter] = useState('')
  const [confFilter, setConfFilter] = useState('')
  const [authFilter, setAuthFilter] = useState('')
  const [paginatedOnly, setPaginatedOnly] = useState(false)
  const [internalOnly, setInternalOnly] = useState(false)
  const [opaqueOnly, setOpaqueOnly] = useState(false)

  const baseUrl = 'http://localhost:' + (declaredPort ?? 8080)

  const applyFilters = (overrides: Record<string, string | boolean | undefined> = {}) => {
    onFilterChange?.({
      http_method: methodFilter || undefined,
      path_contains: pathFilter || undefined,
      confidence: confFilter || undefined,
      auth_filter: authFilter || undefined,
      paginated_only: paginatedOnly || undefined,
      internal_only: internalOnly || undefined,
      opaque_only: opaqueOnly || undefined,
      ...overrides,
    })
  }

  return (
    <div className="space-y-3">
      {/* Filters + OpenAPI export */}
      <div className="flex flex-wrap gap-2 items-center justify-between">
        <div className="flex flex-wrap gap-2">
          {['', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map(m => (
            <button key={m} onClick={() => { setMethodFilter(m); applyFilters({ http_method: m || undefined }) }}
              className={`px-3 py-1 rounded text-xs font-medium border transition ${
                methodFilter === m ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
              }`}>
              {m || 'All'}
            </button>
          ))}
          <input
            type="text" value={pathFilter}
            onChange={e => setPathFilter(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && applyFilters()}
            placeholder="Filter path..."
            className="border border-gray-300 rounded px-3 py-1 text-xs w-48"
          />
          <select value={confFilter} onChange={e => { setConfFilter(e.target.value); applyFilters({ confidence: e.target.value || undefined }) }}
            className="border border-gray-300 rounded px-2 py-1 text-xs">
            <option value="">All Confidence</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>
          <select value={authFilter} onChange={e => { setAuthFilter(e.target.value); applyFilters({ auth_filter: e.target.value || undefined }) }}
            className="border border-gray-300 rounded px-2 py-1 text-xs">
            <option value="">All Auth</option>
            <option value="public">Public</option>
            <option value="authenticated">Requires Auth</option>
          </select>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={paginatedOnly}
              onChange={e => { setPaginatedOnly(e.target.checked); applyFilters({ paginated_only: e.target.checked || undefined }) }}
            />
            Paginated only
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={internalOnly}
              onChange={e => { setInternalOnly(e.target.checked); applyFilters({ internal_only: e.target.checked || undefined }) }}
            />
            Internal only
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none" title="Return/request type is a generic container, Object, or unresolvable external type">
            <input
              type="checkbox"
              checked={opaqueOnly}
              onChange={e => { setOpaqueOnly(e.target.checked); applyFilters({ opaque_only: e.target.checked || undefined }) }}
            />
            Opaque payload only
          </label>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400 py-4 text-center">Loading endpoints...</p>}
      {!loading && endpoints.length === 0 && (
        <p className="text-sm text-gray-400 py-4 text-center">No endpoints found.</p>
      )}

      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-20">Method</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Path</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Controller</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Security</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600 w-16">Conf.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {endpoints.map(ep => (
              <>
                <tr key={ep.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => setExpanded(expanded === ep.id ? null : ep.id)}>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${METHOD_COLORS[ep.http_method] ?? 'bg-gray-100 text-gray-700'}`}>
                      {ep.http_method}
                    </span>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-800">
                    {ep.full_path}
                    {ep.is_paginated && (
                      <span className="ml-2 px-1.5 py-0.5 bg-cyan-100 text-cyan-700 rounded text-xs font-medium align-middle">paginated</span>
                    )}
                    {ep.is_proxied === false && (
                      <span className="ml-2 px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-xs font-medium align-middle">internal</span>
                    )}
                    {ep.payload_shape_known === false && (
                      <span className="ml-2 px-1.5 py-0.5 bg-orange-100 text-orange-700 rounded text-xs font-medium align-middle" title="Return/request payload shape could not be statically resolved">opaque payload</span>
                    )}
                    {ep.doc_summary && (
                      <span className="block font-sans text-gray-500 italic mt-0.5 normal-case">{ep.doc_summary}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{ep.controller_simple}</td>
                  <td className="px-4 py-2">
                    <AuthBadges security={ep.security} />
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs ${ep.confidence === 'HIGH' ? 'text-green-600' : ep.confidence === 'MEDIUM' ? 'text-amber-600' : 'text-red-500'}`}>
                      {ep.confidence}
                    </span>
                  </td>
                </tr>
                {expanded === ep.id && (
                  <tr key={`${ep.id}-detail`} className="bg-blue-50">
                    <td colSpan={5} className="px-6 py-4">
                      <EndpointDetail ep={ep} baseUrl={baseUrl} reportId={reportId} subReportId={subReportId} serviceName={serviceName} />
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>{total} endpoints</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => onPageChange?.(page - 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">← Prev</button>
            <span className="px-2">{page} / {pages}</span>
            <button disabled={page >= pages} onClick={() => onPageChange?.(page + 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Auth badges
// ---------------------------------------------------------------------------

function AuthBadges({ security }: { security: Endpoint['security'] }) {
  if (!security) return <span className="text-xs text-gray-300">—</span>
  const pa = security.parsed_auth
  if (!pa) return <span className="text-xs text-gray-400 font-mono truncate max-w-xs">{security.expression}</span>
  if (pa.deny_all) return <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded text-xs font-medium">DENY ALL</span>
  if (pa.public) return <span className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded text-xs font-medium">PUBLIC</span>
  return (
    <div className="flex flex-wrap gap-1">
      {pa.authenticated_only && (
        <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-xs">authenticated</span>
      )}
      {pa.roles.map(r => (
        <span key={r} className="px-1.5 py-0.5 bg-purple-100 text-purple-700 rounded text-xs font-medium">{r}</span>
      ))}
      {pa.authorities.map(a => (
        <span key={a} className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs font-mono">{a}</span>
      ))}
      {!pa.authenticated_only && pa.roles.length === 0 && pa.authorities.length === 0 && (
        <span className="text-xs text-gray-400 font-mono truncate max-w-xs">{security.expression}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Example builders
// ---------------------------------------------------------------------------

function buildExampleJson(typeName: string, enumLookup?: Record<string, string>): string {
  if (enumLookup) {
    const first = enumLookup[typeName]
    if (first !== undefined) return JSON.stringify(first)
  }
  const t = typeName.toLowerCase()
  if (t.includes('string')) return '"<value>"'
  if (t.includes('int') || t.includes('long') || t.includes('number')) return '0'
  if (t.includes('bool')) return 'true'
  if (t.includes('list') || t.includes('array') || t.endsWith('[]')) return '[{}]'
  if (t === 'void' || t === 'object') return '{}'
  return '{ /* ' + typeName + ' */ }'
}

function buildBodyExample(schema: DtoSchema | undefined, fallbackType: string, enumLookup: Record<string, string>): string {
  if (!schema || schema.fields.length === 0) return buildExampleJson(fallbackType, enumLookup)
  const obj: Record<string, unknown> = {}
  for (const f of schema.fields) {
    if (f.json_ignored) continue
    const enumFirst = enumLookup[f.simple_type] ?? (f.collection_element_type ? enumLookup[f.collection_element_type] : undefined)
    if (enumFirst !== undefined) {
      obj[f.json_name] = f.is_collection ? [enumFirst] : enumFirst
    } else if (f.is_collection) {
      obj[f.json_name] = []
    } else if (f.is_map) {
      obj[f.json_name] = {}
    } else {
      const t = f.openapi_type
      obj[f.json_name] = t === 'integer' ? 0 : t === 'number' ? 0.0 : t === 'boolean' ? false : t === 'array' ? [] : t === 'object' ? {} : `<${f.json_name}>`
    }
  }
  return JSON.stringify(obj, null, 2)
}

function resolvePath(template: string, params: EndpointParam[], placeholder: (name: string) => string): string {
  let path = template
  for (const p of params) {
    if (p.location === 'path') path = path.replace('{' + p.name + '}', placeholder(p.name))
  }
  return path
}

function buildQs(params: EndpointParam[], placeholder: (name: string) => string): string {
  const qp = params.filter(p => p.location === 'query')
  return qp.length ? '?' + qp.map(p => p.name + '=' + placeholder(p.name)).join('&') : ''
}

function buildCurl(ep: Endpoint, baseUrl: string, bodySchema?: DtoSchema, enumLookup: Record<string, string> = {}): string {
  const path = resolvePath(ep.full_path, ep.parameters, n => '<' + n + '>')
  const qs = buildQs(ep.parameters, n => '<' + n + '>')
  const headerParams = ep.parameters.filter(p => p.location === 'header')

  const lines: string[] = [`curl -X ${ep.http_method} '${baseUrl}${path}${qs}' \\`]
  lines.push(`  -H 'Authorization: Bearer <token>' \\`)
  for (const p of headerParams) lines.push(`  -H '${p.name}: <${p.name}>' \\`)
  if (ep.request_body) {
    lines.push(`  -H 'Content-Type: application/json' \\`)
    lines.push(`  -d '${buildBodyExample(bodySchema, ep.request_body.simple_type ?? ep.request_body.java_type ?? 'Object', enumLookup)}'`)
  } else {
    lines[lines.length - 1] = lines[lines.length - 1]!.replace(/ \\$/, '')
  }
  return lines.join('\n')
}

function buildFetch(ep: Endpoint, baseUrl: string, bodySchema?: DtoSchema, enumLookup: Record<string, string> = {}): string {
  const path = resolvePath(ep.full_path, ep.parameters, n => '${' + n + '}')
  const qs = buildQs(ep.parameters, n => '${' + n + '}')
  const headerParams = ep.parameters.filter(p => p.location === 'header')

  const extraHeaders = Object.fromEntries(headerParams.map(p => [p.name, '<' + p.name + '>'] as [string, string]))
  const headers: Record<string, string> = {
    Authorization: 'Bearer <token>',
    ...extraHeaders,
    ...(ep.request_body ? { 'Content-Type': 'application/json' } : {}),
  }
  const headersStr = JSON.stringify(headers, null, 2).replace(/"/g, "'")
  const bodyLine = ep.request_body
    ? ',\n  body: JSON.stringify(' + buildBodyExample(bodySchema, ep.request_body.simple_type ?? ep.request_body.java_type ?? 'Object', enumLookup) + ')'
    : ''

  return [
    'const response = await fetch(`' + baseUrl + path + qs + '`, {',
    "  method: '" + ep.http_method + "',",
    '  headers: ' + headersStr + bodyLine,
    '})',
    'const data = await response.json()',
  ].join('\n')
}

function buildHttpie(ep: Endpoint, baseUrl: string, bodySchema?: DtoSchema, enumLookup: Record<string, string> = {}): string {
  const headerParams = ep.parameters.filter(p => p.location === 'header')
  const queryParams = ep.parameters.filter(p => p.location === 'query')
  const resolvedPath = resolvePath(ep.full_path, ep.parameters, n => '<' + n + '>')

  const args: string[] = [ep.http_method, baseUrl + resolvedPath]
  args.push("Authorization:'Bearer <token>'")
  for (const p of headerParams) args.push(p.name + ":'<" + p.name + ">'")
  for (const p of queryParams) args.push(p.name + '==<' + p.name + '>')
  if (ep.request_body && bodySchema && bodySchema.fields.length > 0) {
    for (const f of bodySchema.fields) {
      if (f.json_ignored) continue
      const enumFirst = enumLookup[f.simple_type]
      const val = enumFirst !== undefined ? JSON.stringify(enumFirst) : `<${f.json_name}>`
      args.push(`${f.json_name}=${val}`)
    }
  } else if (ep.request_body) {
    const bodyType = ep.request_body.simple_type ?? ep.request_body.java_type ?? 'Object'
    args.push('# body (' + bodyType + '):')
    args.push('field=value')
  }

  const lines = ['http ' + args[0] + ' ' + args[1]]
  for (const a of args.slice(2)) lines.push('  ' + a)
  return lines.join(' \\\n')
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
      className="text-xs px-2 py-0.5 rounded border border-gray-300 hover:bg-gray-100 text-gray-500 transition"
    >
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

type ExampleTab = 'curl' | 'fetch' | 'httpie' | 'sdk' | 'json'

function buildSdk(ep: Endpoint, serviceName: string): string {
  const method = ep.http_method.toLowerCase()
  const prefixes: Record<string, string> = { get: 'get', post: 'create', put: 'update', patch: 'patch', delete: 'delete' }
  const verb = prefixes[method] ?? method
  const segments = ep.full_path.replace(/\{[^}]+\}/g, '').split('/').filter(Boolean)
  const meaningful = segments.slice(-2)
  let name = meaningful.join('_').replace(/[-_](\w)/g, (_, c: string) => c.toUpperCase())
  if (!name.toLowerCase().startsWith(verb)) name = verb + name.charAt(0).toUpperCase() + name.slice(1)

  const className = serviceName
    .replace(/[-_\s]+(\w)/g, (_, c: string) => c.toUpperCase())
    .replace(/^(\w)/, (c: string) => c.toUpperCase()) + 'Client'

  const pathParams = ep.parameters.filter(p => p.location === 'path')
  const queryParams = ep.parameters.filter(p => p.location === 'query')
  const hasBody = !!ep.request_body

  const args: string[] = pathParams.map(p => p.name)
  if (hasBody) args.push(`{ /* ${ep.request_body!.simple_type ?? ep.request_body!.java_type ?? 'body'} */ }`)
  if (queryParams.length) args.push(`{ ${queryParams.map(p => `${p.name}: '<${p.name}>'`).join(', ')} }`)

  const baseUrl = ep.full_path.split('/').slice(0, 3).join('/') || 'http://localhost:8080'
  return [
    `// Using the generated SDK:`,
    `const client = new ${className}({ baseUrl: '${baseUrl}', token: '<token>' })`,
    `const result = await client.${name}(${args.join(', ')})`,
  ].join('\n')
}

function EndpointDetail({ ep, baseUrl, reportId, subReportId, serviceName }: { ep: Endpoint; baseUrl: string; reportId: string; subReportId: string; serviceName: string }) {
  const [exampleTab, setExampleTab] = useState<ExampleTab>('curl')

  // Fetch generated JSON examples
  const { data: jsonExamples } = useQuery<{ request: unknown; response: unknown }>({
    queryKey: ['ep-examples', subReportId, ep.id],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/endpoints/${ep.id}/examples`
    ).then(r => r.data),
    retry: false,
  })

  // Fetch schema for request body type if present
  const bodyType = ep.request_body?.java_type
  const { data: bodySchema } = useQuery<DtoSchema>({
    queryKey: ['schema', subReportId, bodyType],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schemas/${encodeURIComponent(bodyType!)}`
    ).then(r => r.data),
    enabled: !!bodyType,
    retry: false,
  })

  // Fetch all enum schemas to build lookup for inline pills + example bodies
  const { data: allEnums } = useQuery<DtoSchema[]>({
    queryKey: ['schemas-enums', subReportId],
    queryFn: () => api.get(
      `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/schemas`,
      { params: { enums_only: true } }
    ).then(r => r.data),
    retry: false,
  })

  // Fetch error responses applicable to this endpoint's controller
  const { data: allErrors } = useQuery<ErrorResponse[]>({
    queryKey: ['sub-errors', subReportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/errors`).then(r => r.data),
    retry: false,
  })
  const applicableErrors = (allErrors ?? []).filter(
    e => e.scope === 'global' || e.controller_class?.endsWith(ep.controller_simple)
  )

  // simple_name -> first serialised_as value (for example generation)
  const enumFirstValue: Record<string, string> = {}
  // simple_name -> full values array (for SchemaViewer pills)
  const enumLookup: Record<string, { name: string; serialised_as: string }[]> = {}
  for (const s of allEnums ?? []) {
    if (s.enum_values.length > 0) {
      enumLookup[s.simple_name] = s.enum_values
      enumFirstValue[s.simple_name] = s.enum_values[0]!.serialised_as
    }
  }

  const examples: Record<ExampleTab, string> = {
    curl: buildCurl(ep, baseUrl, bodySchema, enumFirstValue),
    fetch: buildFetch(ep, baseUrl, bodySchema, enumFirstValue),
    httpie: buildHttpie(ep, baseUrl, bodySchema, enumFirstValue),
    sdk: buildSdk(ep, serviceName),
    json: jsonExamples
      ? [
          ep.request_body && jsonExamples.request != null
            ? `// Request body:\n${JSON.stringify(jsonExamples.request, null, 2)}`
            : null,
          jsonExamples.response != null
            ? `// Response:\n${JSON.stringify(jsonExamples.response, null, 2)}`
            : null,
        ].filter(Boolean).join('\n\n') || '// No examples available'
      : '// Loading...',
  }

  return (
    <div className="space-y-3 text-xs">
      {(ep.doc_summary || ep.doc_description) && (
        <div className="p-2 bg-emerald-50 border border-emerald-200 rounded space-y-1">
          <span className="inline-block px-1.5 py-0.5 bg-emerald-600 text-white rounded text-xs font-medium">
            Developer-authored (@Operation)
          </span>
          {ep.doc_summary && <p className="font-medium text-emerald-900">{ep.doc_summary}</p>}
          {ep.doc_description && ep.doc_description !== ep.doc_summary && (
            <p className="text-emerald-800 whitespace-pre-wrap">{ep.doc_description}</p>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div>
          <span className="text-gray-500">Controller:</span>{' '}
          <span className="font-mono">{ep.controller_class}</span>
        </div>
        <div>
          <span className="text-gray-500">Method:</span>{' '}
          <span className="font-mono">{ep.method_name}</span>
        </div>
        <div>
          <span className="text-gray-500">Annotation:</span>{' '}
          <span className="font-mono">{ep.source_annotation}</span>
        </div>
        {ep.return_type && (
          <div>
            <span className="text-gray-500">Returns:</span>{' '}
            <span className="font-mono">{ep.return_type.simple_type}</span>
          </div>
        )}
      </div>

      {ep.payload_shape_known === false && (
        <p className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded px-2 py-1">
          ⚠ Payload shape not known — the return or request type is a generic container (its element
          type is erased at the bytecode level), a raw Object, or a type not found in this bundle.
          Treat the shown type name as a container, not a resolved contract.
        </p>
      )}

      {ep.parameters.length > 0 && (
        <div>
          <p className="font-medium text-gray-700 mb-1">Parameters</p>
          <table className="w-full border border-gray-200 rounded">
            <thead className="bg-gray-100">
              <tr>
                <th className="px-3 py-1 text-left">Name</th>
                <th className="px-3 py-1 text-left">Location</th>
                <th className="px-3 py-1 text-left">Type</th>
                <th className="px-3 py-1 text-left">Required</th>
                <th className="px-3 py-1 text-left">Default</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {ep.parameters.map((p: EndpointParam, i: number) => (
                <tr key={i}>
                  <td className="px-3 py-1 font-mono">{p.name}</td>
                  <td className="px-3 py-1 text-gray-500">{p.location}</td>
                  <td className="px-3 py-1 font-mono">{p.simple_type ?? p.java_type ?? '—'}</td>
                  <td className="px-3 py-1">{p.required ? 'yes' : 'no'}</td>
                  <td className="px-3 py-1 text-gray-400">{p.default_value ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {ep.security && (
        <div className="p-2 bg-amber-50 border border-amber-200 rounded space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-amber-800 text-xs">{ep.security.annotation}</span>
            <AuthBadges security={ep.security} />
          </div>
          <p className="font-mono text-xs text-amber-600 break-all">{ep.security.expression}</p>
        </div>
      )}

      {ep.linked_tables && ep.linked_tables.length > 0 && (
        <div>
          <p className="font-medium text-gray-700 mb-1">DB Tables</p>
          <div className="flex flex-wrap gap-1">
            {ep.linked_tables.map(t => (
              <span key={t} className="px-2 py-0.5 bg-violet-100 text-violet-800 rounded text-xs font-mono">{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* Request body schema */}
      {ep.request_body && (
        <div>
          <p className="font-medium text-gray-700 mb-1 text-xs">
            Request Body: <span className="font-mono">{ep.request_body.simple_type ?? ep.request_body.java_type}</span>
          </p>
          {bodySchema
            ? <SchemaViewer schema={bodySchema} inline enumLookup={enumLookup} />
            : <p className="text-xs text-gray-400 italic">Schema not available — re-analyse JAR to extract field definitions.</p>
          }
        </div>
      )}

      {/* Error responses */}
      {applicableErrors.length > 0 && (
        <div>
          <p className="font-medium text-gray-700 mb-1 text-xs">Error Responses</p>
          <div className="border border-gray-200 rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-1 text-left font-medium text-gray-600 w-14">Status</th>
                  <th className="px-3 py-1 text-left font-medium text-gray-600">Exception</th>
                  <th className="px-3 py-1 text-left font-medium text-gray-600">Schema</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {applicableErrors.map(e => (
                  <tr key={e.id}>
                    <td className="px-3 py-1">
                      <span className={`font-mono font-bold ${
                        (e.http_status ?? 0) >= 500 ? 'text-red-600' :
                        (e.http_status ?? 0) >= 400 ? 'text-amber-600' : 'text-gray-600'
                      }`}>{e.http_status ?? '?'}</span>
                    </td>
                    <td className="px-3 py-1 font-mono text-gray-700">{e.exception_class ?? '—'}</td>
                    <td className="px-3 py-1 font-mono text-blue-700">{e.response_schema_class ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Usage example */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <p className="font-medium text-gray-700">Usage Example</p>
          <div className="flex gap-1">
            {(['curl', 'fetch', 'httpie', 'sdk', 'json'] as ExampleTab[]).map(t => (
              <button key={t} onClick={() => setExampleTab(t)}
                className={`px-2 py-0.5 rounded text-xs border transition ${
                  exampleTab === t ? 'bg-gray-800 text-white border-gray-800' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
                }`}>
                {t}
              </button>
            ))}
            <CopyButton text={examples[exampleTab]} />
          </div>
        </div>
        <pre className="bg-gray-900 text-green-300 rounded p-3 text-xs overflow-x-auto whitespace-pre font-mono leading-relaxed">
          {examples[exampleTab]}
        </pre>
        {ep.security && (
          <p className="text-xs text-amber-600 mt-1">
            {ep.security.parsed_auth?.public
              ? '✅ Public endpoint — no token required.'
              : ep.security.parsed_auth?.deny_all
              ? '❌ This endpoint is always denied.'
              : ep.security.parsed_auth?.roles?.length
              ? `⚠ Requires role: ${ep.security.parsed_auth.roles.join(' or ')}`
              : ep.security.parsed_auth?.authorities?.length
              ? `⚠ Requires authority: ${ep.security.parsed_auth.authorities.join(', ')}`
              : `⚠ ${ep.security.annotation} — replace <token> with a valid bearer token.`
            }
          </p>
        )}
        <p className="text-xs text-gray-400 mt-1">
          Base URL uses declared port {baseUrl} — replace host as needed for your environment.
        </p>
      </div>
    </div>
  )
}
