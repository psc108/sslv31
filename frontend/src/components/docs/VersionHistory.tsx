import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DocSummary, DocDiffResult } from './types'

interface Props {
  docId: string
  onClose: () => void
}

const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

export default function VersionHistory({ docId, onClose }: Props) {
  const { data: versions, isLoading } = useQuery<DocSummary[]>({
    queryKey: ['doc-versions', docId],
    queryFn: () => api.get(`/docs/${docId}/versions`).then(r => r.data),
  })

  // Defaults to comparing the two most recent versions — the shape most
  // people actually want ("what changed since last time") — once the list
  // loads; versions come back newest-first from the API.
  const [versionA, setVersionA] = useState('')
  const [versionB, setVersionB] = useState('')
  useEffect(() => {
    if (versions && versions.length >= 2 && !versionA && !versionB) {
      setVersionA(versions[1]!.id)
      setVersionB(versions[0]!.id)
    }
  }, [versions])

  const { data: diff, isFetching: diffLoading, error: diffError } = useQuery<DocDiffResult>({
    queryKey: ['doc-diff', versionA, versionB],
    queryFn: () => api.get(`/docs/${versionA}/diff`, { params: { against: versionB } }).then(r => r.data),
    enabled: !!versionA && !!versionB && versionA !== versionB,
  })

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-4 pb-2 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700">🕐 Version History</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg">×</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          {isLoading && <p className="text-sm text-gray-400 text-center py-8">Loading…</p>}

          {versions && versions.length < 2 && (
            <p className="text-sm text-gray-500 text-center py-8">This document only has one version — nothing to compare yet.</p>
          )}

          {versions && versions.length >= 2 && (
            <>
              <div className="flex items-center gap-2 text-sm flex-wrap">
                <span className="text-gray-500">Compare</span>
                <select value={versionA} onChange={e => setVersionA(e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                  {versions.map(v => (
                    <option key={v.id} value={v.id}>v{v.version} — {fmtDate(v.created_at)} ({v.created_by ?? 'unknown'})</option>
                  ))}
                </select>
                <span className="text-gray-500">against</span>
                <select value={versionB} onChange={e => setVersionB(e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm">
                  {versions.map(v => (
                    <option key={v.id} value={v.id}>v{v.version} — {fmtDate(v.created_at)} ({v.created_by ?? 'unknown'})</option>
                  ))}
                </select>
              </div>

              {versionA === versionB && (
                <p className="text-xs text-amber-600">Pick two different versions to see what changed between them.</p>
              )}
              {diffError && (
                <p className="text-xs text-red-600">Failed to load diff.</p>
              )}
              {diffLoading && <p className="text-sm text-gray-400 text-center py-4">Comparing…</p>}

              {diff && !diffLoading && (
                <div className="space-y-2">
                  <div className="text-xs text-gray-500 flex items-center gap-3">
                    <span>v{diff.doc_a.version} → v{diff.doc_b.version}</span>
                    <span className="text-green-700">+{diff.added}</span>
                    <span className="text-red-700">−{diff.removed}</span>
                  </div>
                  <div className="border border-gray-200 rounded-md overflow-hidden font-mono text-xs">
                    {diff.rows.map((row, idx) => (
                      <div key={idx}
                        className={`flex ${
                          row.tag === 'insert' ? 'bg-green-50' : row.tag === 'delete' ? 'bg-red-50' : 'bg-white'
                        }`}>
                        <span className="w-10 shrink-0 text-right pr-2 text-gray-400 select-none border-r border-gray-100">
                          {row.a_line ?? ''}
                        </span>
                        <span className="w-10 shrink-0 text-right pr-2 text-gray-400 select-none border-r border-gray-100">
                          {row.b_line ?? ''}
                        </span>
                        <span className={`px-2 select-none ${
                          row.tag === 'insert' ? 'text-green-700' : row.tag === 'delete' ? 'text-red-700' : 'text-gray-300'
                        }`}>
                          {row.tag === 'insert' ? '+' : row.tag === 'delete' ? '−' : ' '}
                        </span>
                        <span className={`flex-1 whitespace-pre-wrap break-all pr-3 ${
                          row.tag === 'insert' ? 'text-green-900' : row.tag === 'delete' ? 'text-red-900' : 'text-gray-700'
                        }`}>
                          {row.text || ' '}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
