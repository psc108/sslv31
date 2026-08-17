import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Guide { id: string; label: string; available: boolean }
interface Section { id: string; title: string }

export default function BMHelpPage() {
  const [activeGuide, setActiveGuide] = useState('bm')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: guides } = useQuery<Guide[]>({
    queryKey: ['bm-help-guides'],
    queryFn: async () => (await api.get('/build/help/guides')).data,
  })

  const { data: toc } = useQuery<{ available: boolean; label: string; sections: Section[] }>({
    queryKey: ['bm-help-sections', activeGuide],
    queryFn: async () => (await api.get('/build/help/sections', { params: { guide: activeGuide } })).data,
  })

  const { data: section, isLoading: sectionLoading } = useQuery<{ title: string; content: string }>({
    queryKey: ['bm-help-section', activeGuide, selectedId],
    queryFn: async () => (await api.get(`/build/help/sections/${selectedId}`, { params: { guide: activeGuide } })).data,
    enabled: !!selectedId,
  })

  const sections = toc?.sections || []
  const availableGuides = guides || []

  const switchGuide = (id: string) => {
    setActiveGuide(id)
    setSelectedId(null)
  }

  return (
    <div className="flex gap-6">
      <aside className="w-56 flex-shrink-0">
        <h2 className="text-lg font-bold text-gray-900 mb-3">Help</h2>

        {/* Guide tabs */}
        {availableGuides.length > 1 && (
          <div className="flex gap-1 mb-4 p-1 bg-gray-100 rounded-lg">
            {availableGuides.map(g => (
              <button
                key={g.id}
                onClick={() => g.available && switchGuide(g.id)}
                disabled={!g.available}
                className={`flex-1 px-2 py-1 rounded text-xs font-medium transition ${
                  activeGuide === g.id
                    ? 'bg-white text-blue-700 shadow-sm'
                    : g.available
                      ? 'text-gray-500 hover:text-gray-700'
                      : 'text-gray-300 cursor-not-allowed'
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>
        )}

        <nav className="space-y-1 max-h-[calc(100vh-12rem)] overflow-y-auto">
          {sections.map(s => (
            <button key={s.id} onClick={() => setSelectedId(s.id)}
              className={`w-full text-left px-3 py-2 rounded-md text-sm transition ${
                selectedId === s.id
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}>
              <span className="text-xs text-gray-400 mr-1">{s.id}.</span>
              {s.title}
            </button>
          ))}
        </nav>
      </aside>

      <div className="flex-1 min-w-0">
        {!selectedId && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-1">
              Build Manager — {toc?.label ?? 'Operations Guide'}
            </h2>
            <p className="text-sm text-gray-500 mb-4">
              Select a section from the left to view detailed operational documentation.
            </p>

            {activeGuide === 'bm' && availableGuides.some(g => g.id === 'aws' && g.available) && (
              <div className="mb-6 flex items-center justify-between p-3 rounded-lg border border-orange-200 bg-orange-50">
                <div>
                  <span className="text-sm font-medium text-orange-900">AWS Provisioning Guide</span>
                  <p className="text-xs text-orange-700 mt-0.5">OpenTofu, VPC/EC2/RDS/ALB, CloudWatch, and AWS troubleshooting</p>
                </div>
                <button onClick={() => switchGuide('aws')}
                  className="ml-4 px-3 py-1.5 rounded-md bg-orange-600 text-white text-xs font-medium hover:bg-orange-700 transition whitespace-nowrap">
                  Open AWS Guide →
                </button>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {sections.map(s => (
                <button key={s.id} onClick={() => setSelectedId(s.id)}
                  className="flex items-center gap-3 p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition text-left">
                  <span className="text-lg font-bold text-blue-600 w-8">{s.id}</span>
                  <span className="text-sm font-medium text-gray-800">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {selectedId && sectionLoading && (
          <div className="p-6 text-gray-400">Loading...</div>
        )}

        {selectedId && section && (
          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900">{section.title}</h2>
              <button onClick={() => setSelectedId(null)}
                className="text-sm text-blue-600 hover:text-blue-800">
                ← Back to Contents
              </button>
            </div>
            <div className="prose prose-sm max-w-none">
              <MarkdownContent content={section.content} onGuideSwitch={switchGuide} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function MarkdownContent({ content, onGuideSwitch }: { content: string; onGuideSwitch?: (id: string) => void }) {
  const lines = content.split('\n')
  const elements: JSX.Element[] = []
  let inCodeBlock = false
  let codeLines: string[] = []
  let inTable = false
  let tableRows: string[][] = []
  let tableHeaders: string[] = []

  const flushCode = () => {
    if (codeLines.length > 0) {
      elements.push(
        <pre key={elements.length} className="text-xs font-mono bg-gray-900 text-green-400 p-3 rounded overflow-x-auto my-3 whitespace-pre-wrap">
          {codeLines.join('\n')}
        </pre>
      )
      codeLines = []
    }
  }

  const flushTable = () => {
    if (tableHeaders.length > 0) {
      elements.push(
        <div key={elements.length} className="overflow-x-auto my-3">
          <table className="w-full text-xs border border-gray-200 rounded">
            <thead className="bg-gray-50">
              <tr>
                {tableHeaders.map((h, i) => (
                  <th key={i} className="px-3 py-2 text-left font-medium text-gray-600 border-b">{h.trim()}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {tableRows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} className="px-3 py-2 text-gray-700">{cell.trim()}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      tableHeaders = []
      tableRows = []
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (line.startsWith('```')) {
      if (inCodeBlock) { inCodeBlock = false; flushCode() }
      else { inCodeBlock = true }
      continue
    }
    if (inCodeBlock) { codeLines.push(line); continue }

    if (line.includes('|') && line.trim().startsWith('|')) {
      const cells = line.split('|').filter(c => c.trim() !== '')
      if (!inTable) { inTable = true; tableHeaders = cells }
      else if (cells.every(c => c.trim().match(/^[-:]+$/))) { continue }
      else { tableRows.push(cells) }
      continue
    } else if (inTable) { inTable = false; flushTable() }

    if (line.startsWith('### ')) {
      elements.push(<h3 key={elements.length} className="text-base font-semibold text-gray-900 mt-6 mb-2">{line.slice(4)}</h3>)
      continue
    }
    if (line.startsWith('#### ')) {
      elements.push(<h4 key={elements.length} className="text-sm font-semibold text-gray-800 mt-4 mb-1">{line.slice(5)}</h4>)
      continue
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(<li key={elements.length} className="text-sm text-gray-700 ml-4 list-disc">{renderInline(line.slice(2), onGuideSwitch)}</li>)
      continue
    }
    const numMatch = line.match(/^(\d+)\.\s+(.+)$/)
    if (numMatch) {
      elements.push(<li key={elements.length} className="text-sm text-gray-700 ml-4 list-decimal">{renderInline(numMatch[2], onGuideSwitch)}</li>)
      continue
    }
    if (line.trim() === '') { elements.push(<div key={elements.length} className="h-2" />); continue }
    if (line.trim() === '---') { elements.push(<hr key={elements.length} className="my-4 border-gray-200" />); continue }

    elements.push(<p key={elements.length} className="text-sm text-gray-700 my-1">{renderInline(line, onGuideSwitch)}</p>)
  }

  if (inCodeBlock) flushCode()
  if (inTable) flushTable()

  return <>{elements}</>
}

function renderInline(text: string, onGuideSwitch?: (id: string) => void): (string | JSX.Element)[] {
  const parts: (string | JSX.Element)[] = []
  let remaining = text
  let key = 0

  while (remaining.length > 0) {
    const codeMatch = remaining.match(/`([^`]+)`/)
    const boldMatch = remaining.match(/\*\*([^*]+)\*\*/)
    const linkMatch = remaining.match(/\[([^\]]+)\]\(([^)]+)\)/)

    let firstMatch: { index: number; length: number; element: JSX.Element } | null = null

    if (codeMatch && codeMatch.index !== undefined) {
      const candidate = { index: codeMatch.index, length: codeMatch[0].length, element: <code key={key++} className="px-1 py-0.5 bg-gray-100 rounded text-xs font-mono text-gray-800">{codeMatch[1]}</code> }
      if (!firstMatch || candidate.index < firstMatch.index) firstMatch = candidate
    }
    if (boldMatch && boldMatch.index !== undefined) {
      const candidate = { index: boldMatch.index, length: boldMatch[0].length, element: <strong key={key++} className="font-semibold">{boldMatch[1]}</strong> }
      if (!firstMatch || candidate.index < firstMatch.index) firstMatch = candidate
    }
    if (linkMatch && linkMatch.index !== undefined) {
      const [, label, href] = linkMatch
      const guideMatch = href.match(/^guide:(.+)$/)
      const el = guideMatch && onGuideSwitch
        ? <button key={key++} onClick={() => onGuideSwitch(guideMatch[1])} className="text-blue-600 hover:underline">{label}</button>
        : <a key={key++} href={href} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{label}</a>
      const candidate = { index: linkMatch.index, length: linkMatch[0].length, element: el }
      if (!firstMatch || candidate.index < firstMatch.index) firstMatch = candidate
    }

    if (firstMatch) {
      if (firstMatch.index > 0) parts.push(remaining.slice(0, firstMatch.index))
      parts.push(firstMatch.element)
      remaining = remaining.slice(firstMatch.index + firstMatch.length)
    } else {
      parts.push(remaining)
      break
    }
  }

  return parts
}
