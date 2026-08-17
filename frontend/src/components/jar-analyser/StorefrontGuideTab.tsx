import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props { reportId: string }

// Section metadata — matches the "// SECTION N — Title" markers in the generated file
const SECTIONS = [
  { key: 'interfaces', label: '① Interfaces',    icon: '🧩' },
  { key: 'client',     label: '② ApiClient',     icon: '🔌' },
  { key: 'services',   label: '③ Service Clients', icon: '📡' },
  { key: 'pagination', label: '④ Pagination',    icon: '📄' },
  { key: 'examples',   label: '⑤ Code Examples', icon: '💡' },
  { key: 'auth',       label: '⑥ Auth',          icon: '🔐' },
  { key: 'topology',   label: '⑦ Topology',      icon: '🗺' },
  { key: 'envvars',    label: '⑧ Env Vars',      icon: '🔧' },
] as const

type SectionKey = typeof SECTIONS[number]['key']

// Split the full guide text into named sections by the "// SECTION N" markers
function parseSections(text: string): Record<SectionKey, string> {
  const result = {} as Record<SectionKey, string>
  const sectionOrder: SectionKey[] = SECTIONS.map(s => s.key)

  // Find each section boundary — map by the actual number in "// SECTION N"
  // so JS mode (which omits Section 1) still maps correctly
  const boundaries: { idx: number; key: SectionKey }[] = []
  const lines = text.split('\n')

  lines.forEach((line, i) => {
    const m = line.match(/^\/\/ SECTION (\d+)/)
    if (m) {
      const num = parseInt(m[1], 10) - 1  // 1-based → 0-based
      const key = sectionOrder[num]
      if (key) boundaries.push({ idx: i, key })
    }
  })

  boundaries.forEach(({ idx, key }, bi) => {
    const nextIdx = boundaries[bi + 1]?.idx ?? lines.length
    // Include the separator line before the SECTION header (the ─── line)
    const startIdx = idx > 0 && lines[idx - 1]?.startsWith('// ─') ? idx - 1 : idx
    result[key] = lines.slice(startIdx, nextIdx).join('\n').trimEnd()
  })

  return result
}

function CodePane({ text, search }: { text: string; search: string }) {
  const lines = useMemo(() => text.split('\n'), [text])

  const matchingLineNums = useMemo(() => {
    if (!search.trim()) return new Set<number>()
    const q = search.toLowerCase()
    const set = new Set<number>()
    lines.forEach((l, i) => { if (l.toLowerCase().includes(q)) set.add(i) })
    return set
  }, [lines, search])

  const highlightLine = (line: string) => {
    if (!search.trim()) return line
    const q = search.toLowerCase()
    const idx = line.toLowerCase().indexOf(q)
    if (idx === -1) return line
    return (
      line.slice(0, idx) +
      `\x00${line.slice(idx, idx + search.length)}\x00` +
      line.slice(idx + search.length)
    )
  }

  return (
    <div className="bg-gray-950 rounded-lg overflow-auto max-h-[65vh] text-xs font-mono leading-5">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            const isMatch = matchingLineNums.has(i)
            const highlighted = highlightLine(line)
            const parts = highlighted.split('\x00')
            return (
              <tr key={i} className={isMatch ? 'bg-yellow-900/40' : ''}>
                <td className="select-none text-right pr-4 pl-3 py-0 text-gray-600 w-12 shrink-0 border-r border-gray-800">
                  {i + 1}
                </td>
                <td className="pl-4 pr-3 py-0 text-gray-200 whitespace-pre">
                  {parts.length === 1
                    ? parts[0]
                    : parts.map((p, pi) =>
                        pi % 2 === 1
                          ? <mark key={pi} className="bg-yellow-400 text-gray-900 rounded-sm">{p}</mark>
                          : p
                      )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function StorefrontGuideTab({ reportId }: Props) {
  const [search, setSearch] = useState('')
  const [lang, setLang] = useState<'ts' | 'js'>('ts')
  const [activeSection, setActiveSection] = useState<SectionKey>('interfaces')

  const { data: guideText, isLoading, isError } = useQuery<string>({
    queryKey: ['storefront-guide', reportId, lang],
    queryFn: () =>
      api.get(`/jar-analyser/reports/${reportId}/export/storefront-guide?lang=${lang}`, {
        responseType: 'text',
      }).then(r => r.data as string),
  })

  const sections = useMemo(() => guideText ? parseSections(guideText) : null, [guideText])
  const activeText = sections?.[activeSection] ?? ''
  const totalLines = (guideText ?? '').split('\n').length

  const matchCount = useMemo(() => {
    if (!search.trim() || !activeText) return 0
    const q = search.toLowerCase()
    return activeText.split('\n').filter(l => l.toLowerCase().includes(q)).length
  }, [activeText, search])

  if (isLoading) return <div className="text-sm text-gray-400 py-8 text-center">Loading guide…</div>
  if (isError) return <div className="text-sm text-red-500 py-8 text-center">Failed to load storefront guide.</div>

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search section…"
          className="border border-gray-300 rounded px-3 py-1.5 text-sm w-56 font-mono"
        />
        {search && (
          <span className="text-xs text-gray-500">
            {matchCount === 0 ? 'No matches' : `${matchCount} line${matchCount !== 1 ? 's' : ''}`}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-gray-500">Language:</span>
          {(['ts', 'js'] as const).map(l => (
            <button key={l} onClick={() => setLang(l)}
              className={`px-3 py-1 rounded text-xs font-medium border transition ${
                lang === l ? 'bg-blue-600 text-white border-blue-600' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
              }`}>
              {l === 'ts' ? 'TypeScript' : 'JavaScript'}
            </button>
          ))}
        </div>
      </div>

      {/* Section tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1 flex-wrap">
          {SECTIONS.map(s => (
            <button key={s.key} onClick={() => setActiveSection(s.key)}
              className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeSection === s.key
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {s.icon} {s.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Code pane */}
      {activeText
        ? <CodePane text={activeText} search={search} />
        : <div className="text-xs text-gray-400 py-4 text-center">Section not found in this guide version.</div>
      }

      <p className="text-xs text-gray-400">
        {activeText.split('\n').length} lines in section · {totalLines} total · Read-only — always reflects current analysis.
      </p>
    </div>
  )
}
