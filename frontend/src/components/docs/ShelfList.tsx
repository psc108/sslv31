import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { DocShelf, DocLibrary } from './types'

interface Props {
  libraryId: string
  libraryName: string
  onSelect: (shelfId: string, name: string) => void
  onBack: () => void
  onMap: () => void
}

export default function ShelfList({ libraryId, libraryName, onSelect, onBack, onMap }: Props) {
  const { isOperator, isAdmin } = useAuth()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const [movingShelf, setMovingShelf] = useState<DocShelf | null>(null)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<DocShelf[]>({
    queryKey: ['doc-shelves', libraryId],
    queryFn: () => api.get(`/docs/libraries/${libraryId}/shelves`).then(r => r.data),
  })

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setSaving(true)
    try {
      await api.post('/docs/shelves', { library_id: libraryId, name: newName.trim() })
      setNewName('')
      setCreating(false)
      await queryClient.invalidateQueries({ queryKey: ['doc-shelves', libraryId] })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, shelf: DocShelf) => {
    e.stopPropagation()
    if (!confirm(`Delete shelf "${shelf.name}"? This also deletes every document and annotation on it.`)) return
    await api.delete(`/docs/shelves/${shelf.id}`)
    await queryClient.invalidateQueries({ queryKey: ['doc-shelves', libraryId] })
  }

  return (
    <div className="space-y-4">
      <div>
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700 mb-2">← Libraries</button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{libraryName}</h1>
            <p className="text-sm text-gray-500 mt-0.5">Shelves</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onMap}
              className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50">
              🗺️ Map
            </button>
            {isOperator && (
              <button onClick={() => setCreating(true)}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
                + New Shelf
              </button>
            )}
          </div>
        </div>
      </div>

      {isOperator && creating && (
        <form onSubmit={handleCreate} className="flex gap-2 p-3 bg-white border border-gray-200 rounded-lg">
          <input
            type="text" value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="Shelf name" autoFocus
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
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No shelves yet. Create one to get started.</div>
        )}
        {data?.map(shelf => (
          <div key={shelf.id}
            className="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
            onClick={() => onSelect(shelf.id, shelf.name)}>
            <div className="flex items-center gap-2">
              <span>🗄️</span>
              <span className="font-medium text-gray-900">{shelf.name}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-400">{new Date(shelf.created_at).toLocaleDateString()}</span>
              {isOperator && (
                <button onClick={e => { e.stopPropagation(); setMovingShelf(shelf) }}
                  className="text-gray-500 hover:text-gray-700 text-xs font-medium">Move</button>
              )}
              {isAdmin && (
                <button onClick={e => handleDelete(e, shelf)}
                  className="text-red-600 hover:text-red-800 text-xs font-medium">Delete</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {movingShelf && (
        <MoveShelfModal
          shelf={movingShelf}
          currentLibraryId={libraryId}
          onClose={() => setMovingShelf(null)}
          onMoved={async () => {
            setMovingShelf(null)
            await queryClient.invalidateQueries({ queryKey: ['doc-shelves', libraryId] })
          }}
        />
      )}
    </div>
  )
}

function MoveShelfModal({ shelf, currentLibraryId, onClose, onMoved }: {
  shelf: DocShelf; currentLibraryId: string; onClose: () => void; onMoved: () => void
}) {
  const [libraryId, setLibraryId] = useState('')
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState('')

  const { data: libraries } = useQuery<DocLibrary[]>({
    queryKey: ['doc-libraries'],
    queryFn: () => api.get('/docs/libraries').then(r => r.data),
  })

  const handleMove = async () => {
    if (!libraryId) return
    setMoving(true)
    setError('')
    try {
      await api.post(`/docs/shelves/${shelf.id}/move`, { library_id: libraryId })
      onMoved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to move shelf')
    } finally {
      setMoving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-gray-700">Move "{shelf.name}"</h2>
        {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">{error}</div>}
        <select value={libraryId} onChange={e => setLibraryId(e.target.value)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">Select library…</option>
          {libraries?.map(lib => (
            <option key={lib.id} value={lib.id} disabled={lib.id === currentLibraryId}>
              {lib.name}{lib.id === currentLibraryId ? ' (current)' : ''}
            </option>
          ))}
        </select>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleMove} disabled={moving || !libraryId}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
            {moving ? 'Moving…' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  )
}
