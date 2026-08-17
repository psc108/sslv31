import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DocTrashEntry, BugTrashEntry } from './types'

interface Props {
  onBack: () => void
}

const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

export default function Trash({ onBack }: Props) {
  const [tab, setTab] = useState<'docs' | 'bugs'>('docs')
  const queryClient = useQueryClient()

  const { data: docs, isLoading: docsLoading } = useQuery<DocTrashEntry[]>({
    queryKey: ['docs-trash'],
    queryFn: () => api.get('/docs/trash').then(r => r.data),
  })
  const { data: bugs, isLoading: bugsLoading } = useQuery<BugTrashEntry[]>({
    queryKey: ['bugs-trash'],
    queryFn: () => api.get('/bugs/trash').then(r => r.data),
  })

  const restoreDoc = async (id: string) => {
    try {
      await api.post(`/docs/${id}/restore`)
      await queryClient.invalidateQueries({ queryKey: ['docs-trash'] })
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to restore document')
    }
  }
  const purgeDoc = async (id: string, name: string) => {
    if (!confirm(`Permanently delete "${name}"? This cannot be undone.`)) return
    await api.delete(`/docs/trash/${id}`)
    await queryClient.invalidateQueries({ queryKey: ['docs-trash'] })
  }

  const restoreBug = async (id: string) => {
    await api.post(`/bugs/${id}/restore`)
    await queryClient.invalidateQueries({ queryKey: ['bugs-trash'] })
  }
  const purgeBug = async (id: string, title: string) => {
    if (!confirm(`Permanently delete "${title}"? This cannot be undone.`)) return
    await api.delete(`/bugs/trash/${id}`)
    await queryClient.invalidateQueries({ queryKey: ['bugs-trash'] })
  }

  return (
    <div className="space-y-4 max-w-4xl">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700">← Docs</button>
        <h1 className="text-2xl font-bold text-gray-900">🗑️ Rubbish</h1>
      </div>
      <p className="text-xs text-gray-500">
        Deleted documents and bugs stay here for 30 days before being purged automatically — restore them any time before then, or purge immediately.
      </p>

      <div className="flex border border-gray-300 rounded-md overflow-hidden w-fit">
        <button onClick={() => setTab('docs')}
          className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wide ${tab === 'docs' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
          📄 Documents {docs ? `(${docs.length})` : ''}
        </button>
        <button onClick={() => setTab('bugs')}
          className={`px-4 py-1.5 text-xs font-semibold uppercase tracking-wide border-l border-gray-300 ${tab === 'bugs' ? 'bg-blue-600 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}>
          🐛 Bugs {bugs ? `(${bugs.length})` : ''}
        </button>
      </div>

      {tab === 'docs' && (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {docsLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
          {!docsLoading && !docs?.length && (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">Rubbish is empty.</div>
          )}
          {docs?.map(d => (
            <div key={d.id} className="px-4 py-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-gray-900 truncate">{d.name}</p>
                <p className="text-xs text-gray-400">
                  {d.library_name} / {d.shelf_name} · v{d.version} · deleted {fmtDate(d.deleted_at)}
                  {d.created_by && ` · by ${d.created_by}`}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => restoreDoc(d.id)}
                  className="px-3 py-1.5 text-xs bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50">
                  ↩ Restore
                </button>
                <button onClick={() => purgeDoc(d.id, d.name)}
                  className="px-3 py-1.5 text-xs bg-white border border-red-200 text-red-600 rounded-md hover:bg-red-50">
                  Purge
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'bugs' && (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {bugsLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
          {!bugsLoading && !bugs?.length && (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">Rubbish is empty.</div>
          )}
          {bugs?.map(b => (
            <div key={b.id} className="px-4 py-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-gray-900 truncate">{b.title}</p>
                <p className="text-xs text-gray-400">
                  {b.severity} · {b.status} · deleted {fmtDate(b.deleted_at)}
                  {b.reporter && ` · reported by ${b.reporter}`}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => restoreBug(b.id)}
                  className="px-3 py-1.5 text-xs bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50">
                  ↩ Restore
                </button>
                <button onClick={() => purgeBug(b.id, b.title)}
                  className="px-3 py-1.5 text-xs bg-white border border-red-200 text-red-600 rounded-md hover:bg-red-50">
                  Purge
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
