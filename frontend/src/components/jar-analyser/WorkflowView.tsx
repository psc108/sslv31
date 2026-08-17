import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { Workflow, WorkflowStep } from './types'

const METHOD_COLORS: Record<string, string> = {
  GET:    'bg-green-100 text-green-800',
  POST:   'bg-blue-100 text-blue-800',
  PUT:    'bg-amber-100 text-amber-800',
  PATCH:  'bg-orange-100 text-orange-800',
  DELETE: 'bg-red-100 text-red-800',
}

const CATEGORY_COLORS: Record<string, string> = {
  ordering:   'bg-purple-100 text-purple-700',
  management: 'bg-blue-100 text-blue-700',
  monitoring: 'bg-green-100 text-green-700',
  admin:      'bg-red-100 text-red-700',
}

// ---------------------------------------------------------------------------
// JS code generation
// ---------------------------------------------------------------------------

function generateJs(wf: Workflow): string {
  const fnName = wf.name
    .replace(/[^a-zA-Z0-9 ]/g, '')
    .split(' ')
    .map((w, i) => i === 0 ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join('')

  // Collect all input variables that aren't produced by a prior step
  const produced = new Set(wf.steps.map(s => s.output).filter(Boolean))
  const externalInputs = new Set<string>()
  for (const s of wf.steps) {
    for (const varName of Object.keys(s.input_from)) {
      if (!produced.has(varName)) externalInputs.add(varName)
    }
    for (const f of s.body_fields) {
      if (f && !produced.has(f)) externalInputs.add(f)
    }
  }

  const params = externalInputs.size > 0
    ? `client, { ${[...externalInputs].join(', ')} }`
    : 'client'

  const lines: string[] = [
    `// ${wf.name}`,
    ...(wf.description ? [`// ${wf.description}`] : []),
    `async function ${fnName}(${params}) {`,
  ]

  for (let i = 0; i < wf.steps.length; i++) {
    const s = wf.steps[i]!
    lines.push(`  // Step ${i + 1}: ${s.name}`)
    if (s.description) lines.push(`  // ${s.description}`)

    // Resolve path variables
    let resolvedPath = s.path
    for (const [varName] of Object.entries(s.input_from)) {
      resolvedPath = resolvedPath.replace(`{${varName}}`, `\${${varName}}`)
    }
    const pathExpr = resolvedPath.includes('${') ? `\`${resolvedPath}\`` : `'${resolvedPath}'`

    // Query params
    const qpEntries = Object.entries(s.query_params)
    const qpStr = qpEntries.length > 0
      ? `, { params: { ${qpEntries.map(([k, v]) => `${k}: ${v}`).join(', ')} } }`
      : ''

    if (s.poll_until) {
      // Polling step
      lines.push(`  let pollResult`)
      lines.push(`  do {`)
      lines.push(`    await new Promise(r => setTimeout(r, 5000))`)
      lines.push(`    pollResult = await client.get(${pathExpr}${qpStr})`)
      lines.push(`  } while (!(${s.poll_until.replace('response.', 'pollResult.')}))`)
      if (s.output) lines.push(`  const ${s.output} = pollResult`)
    } else if (s.method === 'GET' || s.method === 'DELETE') {
      const resultExpr = s.output ? `const ${s.output} = ` : ''
      lines.push(`  ${resultExpr}await client.${s.method.toLowerCase()}(${pathExpr}${qpStr})`)
    } else {
      // POST / PUT / PATCH — build body
      const bodyFields = s.body_fields.filter(Boolean)
      const bodyStr = bodyFields.length > 0
        ? `{ ${bodyFields.join(', ')} }`
        : '{}'
      const resultExpr = s.output ? `const ${s.output} = ` : ''
      lines.push(`  ${resultExpr}await client.${s.method.toLowerCase()}(${pathExpr}, ${bodyStr})`)
    }

    lines.push('')
  }

  // Return last output variable if any
  const lastOutput = [...wf.steps].reverse().find(s => s.output)?.output
  if (lastOutput) lines.push(`  return ${lastOutput}`)

  lines.push('}')
  return lines.join('\n')
}

// ---------------------------------------------------------------------------
// Step card
// ---------------------------------------------------------------------------

function StepCard({ step, index, total }: { step: WorkflowStep; index: number; total: number }) {
  const inputs = Object.entries(step.input_from)
  const qps = Object.entries(step.query_params)

  return (
    <div className="flex gap-3">
      {/* Step number + connector */}
      <div className="flex flex-col items-center">
        <div className="w-7 h-7 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center shrink-0">
          {index + 1}
        </div>
        {index < total - 1 && <div className="w-px flex-1 bg-gray-200 mt-1" />}
      </div>

      {/* Card */}
      <div className="flex-1 pb-4">
        <div className="border border-gray-200 rounded-lg p-3 bg-white space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${METHOD_COLORS[step.method] ?? 'bg-gray-100 text-gray-700'}`}>
              {step.method}
            </span>
            <span className="font-mono text-xs text-gray-800">{step.path}</span>
            <span className="font-semibold text-sm text-gray-700 ml-auto">{step.name}</span>
          </div>

          {step.description && (
            <p className="text-xs text-gray-500">{step.description}</p>
          )}

          <div className="flex flex-wrap gap-3 text-xs">
            {inputs.length > 0 && (
              <span className="text-gray-500">
                ← uses: {inputs.map(([k]) => <code key={k} className="bg-gray-100 px-1 rounded mx-0.5">{k}</code>)}
              </span>
            )}
            {step.output && (
              <span className="text-gray-500">
                → produces: <code className="bg-green-50 text-green-700 px-1 rounded">{step.output}</code>
              </span>
            )}
            {qps.length > 0 && (
              <span className="text-gray-500">
                params: {qps.map(([k, v]) => <code key={k} className="bg-gray-100 px-1 rounded mx-0.5">{k}={v}</code>)}
              </span>
            )}
            {step.poll_until && (
              <span className="text-amber-600">
                ⏳ poll until: <code className="bg-amber-50 px-1 rounded">{step.poll_until}</code>
              </span>
            )}
            {step.body_fields.filter(Boolean).length > 0 && (
              <span className="text-gray-500">
                body: {step.body_fields.filter(Boolean).map(f => <code key={f} className="bg-blue-50 text-blue-700 px-1 rounded mx-0.5">{f}</code>)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Workflow card
// ---------------------------------------------------------------------------

function WorkflowCard({ wf }: { wf: Workflow }) {
  const [showCode, setShowCode] = useState(false)
  const [copied, setCopied] = useState(false)
  const code = generateJs(wf)

  const copy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-200 flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-gray-900">{wf.name}</span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${CATEGORY_COLORS[wf.category] ?? 'bg-gray-100 text-gray-600'}`}>
              {wf.category}
            </span>
            {wf.source === 'manual' && (
              <span className="px-2 py-0.5 rounded text-xs bg-indigo-50 text-indigo-700">manual</span>
            )}
          </div>
          {wf.description && <p className="text-xs text-gray-500">{wf.description}</p>}
          <p className="text-xs text-gray-400">{wf.steps.length} step{wf.steps.length !== 1 ? 's' : ''}</p>
        </div>
        <button
          onClick={() => setShowCode(v => !v)}
          className="px-3 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 transition shrink-0"
        >
          {showCode ? 'Hide code' : '{ } JS'}
        </button>
      </div>

      {/* Steps */}
      <div className="p-4">
        {wf.steps.map((s, i) => (
          <StepCard key={i} step={s} index={i} total={wf.steps.length} />
        ))}
      </div>

      {/* Generated JS */}
      {showCode && (
        <div className="border-t border-gray-200">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-900">
            <span className="text-xs text-gray-400">Generated JavaScript</span>
            <button onClick={copy} className="text-xs text-gray-400 hover:text-white transition">
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          </div>
          <pre className="bg-gray-950 text-green-300 text-xs font-mono p-4 overflow-x-auto whitespace-pre leading-relaxed">
            {code}
          </pre>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// YAML upload panel
// ---------------------------------------------------------------------------

function YamlUploadPanel({ reportId, subReportId, onSuccess }: {
  reportId: string
  subReportId: string
  onSuccess: () => void
}) {
  const [yaml, setYaml] = useState('')
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()

  const mutation = useMutation({
    mutationFn: (content: string) =>
      api.post(
        `/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/workflows`,
        { yaml_content: content }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sub-workflows', subReportId] })
      setYaml('')
      setOpen(false)
      onSuccess()
    },
  })

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="px-3 py-1.5 text-xs border border-dashed border-gray-300 rounded text-gray-500 hover:border-blue-400 hover:text-blue-600 transition"
      >
        + Upload workflows.yml
      </button>
    )
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
      <p className="text-xs font-medium text-gray-700">Paste workflows.yml content</p>
      <textarea
        value={yaml}
        onChange={e => setYaml(e.target.value)}
        rows={10}
        className="w-full border border-gray-300 rounded px-3 py-2 text-xs font-mono resize-y"
        placeholder={'workflows:\n  - name: "My Workflow"\n    category: ordering\n    steps:\n      - name: List items\n        method: GET\n        path: /items'}
      />
      {mutation.isError && (
        <p className="text-xs text-red-600">
          {(mutation.error as any)?.response?.data?.detail ?? 'Upload failed'}
        </p>
      )}
      <div className="flex gap-2">
        <button
          onClick={() => mutation.mutate(yaml)}
          disabled={!yaml.trim() || mutation.isPending}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition"
        >
          {mutation.isPending ? 'Uploading…' : 'Upload'}
        </button>
        <button
          onClick={() => setOpen(false)}
          className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-100 transition"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

interface Props {
  workflows: Workflow[]
  reportId: string
  subReportId: string
}

export default function WorkflowView({ workflows, reportId, subReportId }: Props) {
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')

  const categories = [...new Set(workflows.map(w => w.category))].sort()

  const filtered = workflows.filter(w => {
    if (catFilter && w.category !== catFilter) return false
    if (sourceFilter && w.source !== sourceFilter) return false
    if (search && !w.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search workflows…"
          className="border border-gray-300 rounded px-3 py-1 text-xs w-48"
        />
        <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1 text-xs">
          <option value="">All categories</option>
          {categories.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1 text-xs">
          <option value="">All sources</option>
          <option value="auto_detected">Auto-detected</option>
          <option value="manual">Manual</option>
        </select>
        <span className="text-xs text-gray-400 ml-auto">
          {filtered.length} workflow{filtered.length !== 1 ? 's' : ''}
        </span>
        <YamlUploadPanel
          reportId={reportId}
          subReportId={subReportId}
          onSuccess={() => {}}
        />
      </div>

      {filtered.length === 0 && (
        <p className="text-sm text-gray-400 py-6 text-center">
          {workflows.length === 0
            ? 'No workflows detected — re-analyse the JAR or upload a workflows.yml.'
            : 'No workflows match the filter.'}
        </p>
      )}

      <div className="space-y-4">
        {filtered.map(wf => <WorkflowCard key={wf.id} wf={wf} />)}
      </div>
    </div>
  )
}
