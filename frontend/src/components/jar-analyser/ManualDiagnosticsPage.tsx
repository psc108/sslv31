import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  reportId: string
  onBack: () => void
  onRunCreated: (runId: string) => void
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

export default function ManualDiagnosticsPage({ reportId, onBack, onRunCreated }: Props) {
  const [responses, setResponses] = useState<Record<string, string>>({})
  const [step, setStep] = useState(0)
  const [copied, setCopied] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: questionnaire, isLoading } = useQuery<{
    platform_title: string
    platform_version: string
    total_sections: number
    required_items: number
    sections: QSection[]
  }>({
    queryKey: ['diag-questionnaire', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/diagnostic-questionnaire`).then(r => r.data),
  })

  const submitMutation = useMutation({
    mutationFn: () =>
      api.post(`/jar-analyser/reports/${reportId}/diagnostic-questionnaire/analyse`, { responses }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['diag-runs', reportId] })
      onRunCreated(res.data.run_id)
    },
  })

  const handleDownloadMarkdown = () => {
    api.get(`/jar-analyser/reports/${reportId}/diagnostic-questionnaire/markdown`, { responseType: 'blob' })
      .then(res => {
        const cd = res.headers['content-disposition'] || ''
        const match = cd.match(/filename="([^"]+)"/)
        const filename = match ? match[1] : 'diag-questionnaire.md'
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

  // Count filled required items across all sections
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
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-800 mb-1">← Back to Diagnostics</button>
          <h2 className="text-xl font-bold text-gray-900">📋 Manual Information Collection</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Run each command on the target server and paste the output below.
            Use this when the full collection script cannot be run or the bundle cannot be uploaded.
          </p>
        </div>
        <button
          onClick={handleDownloadMarkdown}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 shrink-0"
        >
          ⬇ Download as Markdown
        </button>
      </div>

      {/* Progress bar */}
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
        {/* Section pills */}
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
          {currentSection.items.map(item => (
            <div key={item.id} className="px-5 py-4 space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-gray-900">
                    {item.label}
                    {item.required && <span className="ml-1.5 text-xs text-red-500">*required</span>}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{item.context}</p>
                </div>
              </div>

              {item.command && (
                <div className="relative group">
                  <pre className="bg-gray-900 text-green-300 text-xs rounded-md px-4 py-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                    {item.command}
                  </pre>
                  <button
                    onClick={() => copyCommand(item.command!, item.id)}
                    className="absolute top-2 right-2 px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    {copied === item.id ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
              )}

              {item.input_type === 'yes_no' ? (
                <div className="flex gap-3">
                  {['yes', 'no'].map(v => (
                    <label key={v} className="flex items-center gap-1.5 text-sm cursor-pointer">
                      <input
                        type="radio"
                        name={item.id}
                        value={v}
                        checked={responses[item.id] === v}
                        onChange={() => setResponses(r => ({ ...r, [item.id]: v }))}
                      />
                      {v.charAt(0).toUpperCase() + v.slice(1)}
                    </label>
                  ))}
                </div>
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
          ))}
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
          {/* Allow submit from any step if enough data */}
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
