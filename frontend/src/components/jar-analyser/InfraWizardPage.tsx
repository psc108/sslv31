import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  service: string
  reportId?: string
  onBack: () => void
  onRunCreated: (runId: string, service: string) => void
}

interface QItem {
  id: string
  label: string
  context: string
  command: string | null
  input_type: string
  required: boolean
}

interface QSection {
  id: string
  title: string
  description: string
  items: QItem[]
}

// Substitute <param_name> placeholders in a command string using current param responses
function resolveCommand(cmd: string, responses: Record<string, string>, servicePrefix: string): string {
  return cmd.replace(/<([^>]+)>/g, (_, name) => {
    const key = `${servicePrefix}.param.${name}`
    return responses[key] || `<${name}>`
  })
}

export default function InfraWizardPage({ service, reportId, onBack, onRunCreated }: Props) {
  const [responses, setResponses] = useState<Record<string, string>>({})
  const [label, setLabel] = useState('')
  const [step, setStep] = useState(0)
  const [copied, setCopied] = useState<string | null>(null)
  const [dismissedBanner, setDismissedBanner] = useState(false)

  const { data: questionnaire, isLoading } = useQuery<{
    display_name: string
    total_sections: number
    required_items: number
    sections: QSection[]
    prefill: Record<string, string>
  }>({
    queryKey: ['infra-questionnaire', service, reportId],
    queryFn: () =>
      api.get(`/infra-diagnostics/${service}/questionnaire`, {
        params: reportId ? { report_id: reportId } : {},
      }).then(r => r.data),
    onSuccess: (data) => {
      // Pre-fill parameter prompts from report context
      if (data.prefill && Object.keys(data.prefill).length > 0) {
        setResponses(prev => ({ ...data.prefill, ...prev }))
      }
    },
  })

  const submitMutation = useMutation({
    mutationFn: () =>
      api.post(`/infra-diagnostics/${service}/analyse`, {
        responses,
        label: label.trim() || undefined,
        report_id: reportId,
      }),
    onSuccess: (res) => {
      onRunCreated(res.data.run_id, service)
    },
  })

  const handleDownloadMarkdown = () => {
    api.get(`/infra-diagnostics/${service}/questionnaire/markdown`, { responseType: 'blob' }).then(res => {
      const cd = res.headers['content-disposition'] || ''
      const match = cd.match(/filename="([^"]+)"/)
      const filename = match ? match[1] : `infra-diag-${service}.md`
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
    })
  }

  const copyCommand = (cmd: string, id: string) => {
    navigator.clipboard.writeText(cmd).then(() => {
      setCopied(id)
      setTimeout(() => setCopied(null), 1500)
    })
  }

  if (isLoading || !questionnaire) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading questionnaire…</div>
  }

  const sections = questionnaire.sections
  const currentSection = sections[step]
  const isLast = step === sections.length - 1
  const hasPrefill = questionnaire.prefill && Object.keys(questionnaire.prefill).length > 0

  const totalRequired = questionnaire.required_items
  const filledRequired = sections.flatMap(s => s.items)
    .filter(i => i.required && responses[i.id]?.trim())
    .length

  const sectionComplete = (sec: QSection) =>
    sec.items.filter(i => i.required).every(i => responses[i.id]?.trim())

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-1">← Back to Infrastructure Diagnostics</button>
          <h2 className="text-xl font-bold text-gray-900">🔧 {questionnaire.display_name} Diagnostics</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Run each command on the {questionnaire.display_name} server and paste the output below.
          </p>
        </div>
        <button
          onClick={handleDownloadMarkdown}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 shrink-0"
        >
          ⬇ Download as Markdown
        </button>
      </div>

      {/* Report context banner */}
      {reportId && hasPrefill && !dismissedBanner && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg flex items-start justify-between gap-3">
          <p className="text-sm text-blue-800">
            ℹ Using JAR report context — parameter prompts have been pre-filled from the report's configuration.
            Cross-reference checks will compare application config against your responses.
          </p>
          <button onClick={() => setDismissedBanner(true)} className="text-blue-400 hover:text-blue-600 shrink-0 text-lg leading-none">✕</button>
        </div>
      )}

      {/* Label */}
      <div className="bg-white border border-gray-200 rounded-lg px-5 py-4">
        <label className="block text-sm font-medium text-gray-700 mb-1">Label <span className="text-gray-400 font-normal">(optional)</span></label>
        <input
          type="text"
          value={label}
          onChange={e => setLabel(e.target.value)}
          placeholder={`e.g. ${questionnaire.display_name} on host-01 — post-deployment check`}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>

      {/* Progress */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
          <span>Required fields completed: {filledRequired} / {totalRequired}</span>
          <span>Section {step + 1} of {sections.length}</span>
        </div>
        <div className="w-full bg-gray-100 rounded-full h-2">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all"
            style={{ width: `${totalRequired > 0 ? (filledRequired / totalRequired) * 100 : 0}%` }}
          />
        </div>
        <div className="flex flex-wrap gap-1.5 mt-3">
          {sections.map((sec, i) => (
            <button
              key={sec.id}
              onClick={() => setStep(i)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                i === step
                  ? 'bg-blue-600 text-white'
                  : sectionComplete(sec)
                  ? 'bg-green-100 text-green-700 hover:bg-green-200'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {sectionComplete(sec) ? '✓ ' : ''}{sec.title}
            </button>
          ))}
        </div>
      </div>

      {/* Current section */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200 bg-gray-50">
          <h3 className="text-base font-semibold text-gray-900">{currentSection.title}</h3>
          <p className="text-sm text-gray-500 mt-0.5">{currentSection.description}</p>
        </div>

        <div className="divide-y divide-gray-100">
          {currentSection.items.map(item => {
            const isParam = item.input_type === 'text' && item.command === null
            const resolvedCmd = item.command ? resolveCommand(item.command, responses, service) : null

            return (
              <div key={item.id} className="px-5 py-4 space-y-2">
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {item.label}
                    {item.required && <span className="ml-1.5 text-xs text-red-500">*required</span>}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{item.context}</p>
                </div>

                {resolvedCmd && (
                  <div className="relative group">
                    <pre className="bg-gray-900 text-green-300 text-xs rounded-md px-4 py-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                      {resolvedCmd}
                    </pre>
                    <button
                      onClick={() => copyCommand(resolvedCmd, item.id)}
                      className="absolute top-2 right-2 px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      {copied === item.id ? '✓ Copied' : 'Copy'}
                    </button>
                  </div>
                )}

                {isParam ? (
                  <input
                    type="text"
                    placeholder={`Enter ${item.label.toLowerCase()}…`}
                    value={responses[item.id] ?? ''}
                    onChange={e => setResponses(r => ({ ...r, [item.id]: e.target.value }))}
                    className={`w-full border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 ${
                      item.required && !responses[item.id]?.trim()
                        ? 'border-amber-300 bg-amber-50'
                        : responses[item.id]?.trim()
                        ? 'border-green-300 bg-green-50'
                        : 'border-gray-300'
                    }`}
                  />
                ) : (
                  <textarea
                    rows={5}
                    placeholder="Paste command output here…"
                    value={responses[item.id] ?? ''}
                    onChange={e => setResponses(r => ({ ...r, [item.id]: e.target.value }))}
                    className={`w-full text-xs font-mono border rounded-md px-3 py-2 resize-y focus:outline-none focus:ring-2 focus:ring-blue-400 ${
                      item.required && !responses[item.id]?.trim()
                        ? 'border-amber-300 bg-amber-50'
                        : responses[item.id]?.trim()
                        ? 'border-green-300 bg-green-50'
                        : 'border-gray-300'
                    }`}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => setStep(s => Math.max(0, s - 1))}
          disabled={step === 0}
          className="px-4 py-2 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40"
        >
          ← Previous
        </button>

        <div className="flex gap-3">
          {!isLast && (
            <button
              onClick={() => setStep(s => Math.min(sections.length - 1, s + 1))}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-700"
            >
              Next →
            </button>
          )}
          {isLast && (
            <button
              onClick={() => submitMutation.mutate()}
              disabled={submitMutation.isPending || filledRequired === 0}
              className="px-5 py-2 bg-green-600 text-white text-sm font-medium rounded hover:bg-green-700 disabled:opacity-50"
            >
              {submitMutation.isPending ? 'Analysing…' : '✓ Submit & Analyse'}
            </button>
          )}
          {!isLast && filledRequired > 0 && (
            <button
              onClick={() => submitMutation.mutate()}
              disabled={submitMutation.isPending}
              className="px-4 py-2 border border-green-400 text-green-700 text-sm rounded hover:bg-green-50 disabled:opacity-50"
            >
              {submitMutation.isPending ? 'Analysing…' : 'Submit partial →'}
            </button>
          )}
        </div>
      </div>

      {submitMutation.isError && (
        <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {(submitMutation.error as any)?.response?.data?.detail || 'Submission failed'}
        </div>
      )}
    </div>
  )
}
