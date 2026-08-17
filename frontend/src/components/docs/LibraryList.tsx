import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { DocLibrary } from './types'

interface Props {
  onSelect: (libraryId: string, name: string) => void
  onErrorKb: () => void
  onBugs: () => void
  onTrash: () => void
  onSearch: () => void
  // Improvements Plan Stage 14 — the relationship map across every library
  // at once, not just one. Only reachable from here (the library list),
  // since a single library's own map is reached from within ShelfList.
  onAllLibrariesMap: () => void
}

export default function LibraryList({ onSelect, onErrorKb, onBugs, onTrash, onSearch, onAllLibrariesMap }: Props) {
  const { isOperator, isAdmin } = useAuth()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<DocLibrary[]>({
    queryKey: ['doc-libraries'],
    queryFn: () => api.get('/docs/libraries').then(r => r.data),
  })

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setSaving(true)
    try {
      await api.post('/docs/libraries', { name: newName.trim() })
      setNewName('')
      setCreating(false)
      await queryClient.invalidateQueries({ queryKey: ['doc-libraries'] })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, lib: DocLibrary) => {
    e.stopPropagation()
    if (!confirm(`Delete library "${lib.name}"? This also deletes every shelf, document, and annotation inside it.`)) return
    await api.delete(`/docs/libraries/${lib.id}`)
    await queryClient.invalidateQueries({ queryKey: ['doc-libraries'] })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Docs</h1>
          <p className="text-sm text-gray-500 mt-0.5">Libraries</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={onSearch}
            className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
            🔎 Search Docs
          </button>
          <button onClick={onErrorKb}
            className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
            🔍 Error KB Search
          </button>
          <button onClick={onAllLibrariesMap}
            className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
            🗺️ All Libraries Map
          </button>
          <button onClick={onBugs}
            className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
            🐛 Bugs
          </button>
          {isAdmin && (
            <button onClick={onTrash}
              className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
              🗑️ Rubbish
            </button>
          )}
          {isOperator && (
            <button onClick={() => setCreating(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
              + New Library
            </button>
          )}
        </div>
      </div>

      {isOperator && creating && (
        <form onSubmit={handleCreate} className="flex gap-2 p-3 bg-white border border-gray-200 rounded-lg">
          <input
            type="text" value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="Library name" autoFocus
            className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
          />
          <button type="submit" disabled={saving || !newName.trim()}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Creating…' : 'Create'}
          </button>
          <button type="button" onClick={() => { setCreating(false); setNewName('') }}
            className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
            Cancel
          </button>
        </form>
      )}

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
        {isLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
        {!isLoading && !data?.length && (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No libraries yet. Create one to get started.</div>
        )}
        {data?.map(lib => (
          <div key={lib.id}
            className="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
            onClick={() => onSelect(lib.id, lib.name)}>
            <div className="flex items-center gap-2">
              <span>📚</span>
              <span className="font-medium text-gray-900">{lib.name}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-400">{new Date(lib.created_at).toLocaleDateString()}</span>
              {isAdmin && (
                <button onClick={e => handleDelete(e, lib)}
                  className="text-red-600 hover:text-red-800 text-xs font-medium">Delete</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
