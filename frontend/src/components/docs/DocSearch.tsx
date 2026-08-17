import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DocSearchResult } from './types'

interface Props {
  onBack: () => void
  onOpenDoc: (docId: string, shelfId: string, docName: string) => void
}

export default function DocSearch({ onBack, onOpenDoc }: Props) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['docs-search', query],
    queryFn: () => api.get('/docs/search', { params: { q: query, page_size: 50 } }).then(r => r.data),
    enabled: !!query,
  })
  const results: DocSearchResult[] = data?.items ?? []

  const doSearch = () => setQuery(input.trim())

  // The snippet comes straight from document content, which is untrusted —
  // escape it before turning the "**match**" markers (chosen ourselves as
  // the FTS5 snippet() delimiters) into <mark> tags, so raw HTML sitting
  // in a doc's own text can never get interpreted as markup here.
  const renderSnippet = (snippet: string) => {
    const escaped = snippet
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
    return escaped.replace(/\*\*(.+?)\*\*/g, '<mark>$1</mark>')
  }

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">← Docs</button>
        <h1 className="text-2xl font-bold text-gray-900">🔎 Search Docs</h1>
      </div>

      <div className="flex gap-2">
        <input
          type="text" value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') doSearch() }}
          placeholder="Search document names and content…" autoFocus
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
        />
        <button onClick={doSearch} disabled={!input.trim()}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          Search
        </button>
      </div>

      {isLoading && <div className="text-sm text-gray-400 text-center py-8">Searching…</div>}

      {query && !isLoading && (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {results.length === 0 && (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">No documents matched "{query}".</div>
          )}
          {results.map(r => (
            <button key={r.id}
              onClick={() => onOpenDoc(r.id, r.shelf_id, r.name)}
              className="w-full text-left px-4 py-3 hover:bg-gray-50">
              <div className="font-medium text-gray-900">{r.name}</div>
              {r.snippet && (
                <div
                  className="text-xs text-gray-500 mt-1 [&_mark]:bg-yellow-200 [&_mark]:text-gray-900 [&_mark]:rounded [&_mark]:px-0.5"
                  dangerouslySetInnerHTML={{ __html: renderSnippet(r.snippet) }}
                />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
