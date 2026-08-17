import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  reportId: string
  subReportId: string
}

interface StringConstant {
  id: string
  class_name: string
  value: string
}

export default function StringsTab({ reportId, subReportId }: Props) {
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => {
    const t = setTimeout(() => { setDebouncedQ(q); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [q])

  const { data, isFetching } = useQuery({
    queryKey: ['jar-strings', reportId, subReportId, debouncedQ, page],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/strings`, {
      params: { q: debouncedQ || undefined, page, page_size: 50 },
    }).then(r => r.data),
    placeholderData: prev => prev,
  })

  const items: StringConstant[] = data?.items ?? []

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Every string literal this jar's own code embeds (log messages, exception text, doc
        comments, JSON keys, etc.) — resolved straight from the class bytecode, not decompiled
        source. To search across every analysed jar at once, use "🔍 Search Reports" from the
        JAR Analyser home page instead.
      </p>

      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
        <input
          type="text" value={q} onChange={e => setQ(e.target.value)}
          placeholder="Filter this jar's strings…"
          className="w-full border border-gray-300 rounded-lg pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {isFetching && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 animate-pulse">loading…</span>
        )}
      </div>

      {!isFetching && items.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">
          {debouncedQ ? <>No strings match <strong>{debouncedQ}</strong></> : 'No string constants found for this jar.'}
        </p>
      )}

      <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
        {items.map(s => (
          <div key={s.id} className="px-4 py-2.5">
            <p className="text-xs font-mono text-gray-400 truncate">{s.class_name}</p>
            <p className="text-sm text-gray-800 whitespace-pre-wrap break-words mt-0.5">{s.value}</p>
          </div>
        ))}
      </div>

      {(data?.pages ?? 1) > 1 && (
        <div className="flex items-center justify-between text-xs text-gray-500 pt-1">
          <span>{data?.total} total strings</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => setPage(p => p - 1)}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">← Prev</button>
            <span className="px-2 py-1">{page} / {data?.pages}</span>
            <button disabled={page >= (data?.pages ?? 1)} onClick={() => setPage(p => p + 1)}
              className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
