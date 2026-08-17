import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { DocSummary, DocLibrary, DocShelf } from './types'

interface Props {
  shelfId: string
  shelfName: string
  onSelect: (docId: string, name: string) => void
  onCreate: (docId: string, name: string) => void
  onBack: () => void
}

export default function DocList({ shelfId, shelfName, onSelect, onCreate, onBack }: Props) {
  const { isOperator, isAdmin } = useAuth()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [movingDoc, setMovingDoc] = useState<DocSummary | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkMoving, setBulkMoving] = useState(false)
  const [bulkError, setBulkError] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<DocSummary[]>({
    queryKey: ['docs', shelfId],
    queryFn: () => api.get(`/docs/shelves/${shelfId}/docs`).then(r => r.data),
  })

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!newName.trim()) return
    setSaving(true)
    setError('')
    try {
      // Created empty and opened straight in the editor (Stage 3) — no
      // more entering initial content through a bare textarea here.
      const res = await api.post('/docs', { shelf_id: shelfId, name: newName.trim(), content: '' })
      setNewName('')
      setCreating(false)
      await queryClient.invalidateQueries({ queryKey: ['docs', shelfId] })
      onCreate(res.data.id, res.data.name)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create document')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, doc: DocSummary) => {
    e.stopPropagation()
    if (!confirm(`Delete document "${doc.name}"? It'll move to Rubbish (with all its versions) and can be restored by an admin within 30 days.`)) return
    await api.delete(`/docs/${doc.id}`)
    await queryClient.invalidateQueries({ queryKey: ['docs', shelfId] })
  }

  const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

  const toggleSelected = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleBulkDelete = async () => {
    if (!confirm(`Delete ${selected.size} document(s)? They'll move to Rubbish and can be restored by an admin within 30 days.`)) return
    setBulkError('')
    try {
      const res = await api.post('/docs/bulk-delete', { doc_ids: Array.from(selected) })
      if (res.data.failed.length) {
        setBulkError(`${res.data.deleted.length} deleted, ${res.data.failed.length} failed: ${res.data.failed.map((f: any) => f.error).join('; ')}`)
      }
      setSelected(new Set())
      await queryClient.invalidateQueries({ queryKey: ['docs', shelfId] })
    } catch (err: any) {
      setBulkError(err.response?.data?.detail || 'Bulk delete failed')
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700 mb-2">← Shelves</button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{shelfName}</h1>
            <p className="text-sm text-gray-500 mt-0.5">Documents</p>
          </div>
          {isOperator && (
            <button onClick={() => setCreating(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
              + New Document
            </button>
          )}
        </div>
      </div>

      {isOperator && creating && (
        <form onSubmit={handleCreate} className="p-4 bg-white border border-gray-200 rounded-lg space-y-3">
          {error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
          )}
          <input
            type="text" value={newName} onChange={e => setNewName(e.target.value)}
            placeholder="Document name" autoFocus
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          />
          <div className="flex gap-2">
            <button type="submit" disabled={saving || !newName.trim()}
              className="px-3 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Creating…' : 'Create & Edit'}
            </button>
            <button type="button" onClick={() => { setCreating(false); setNewName(''); setError('') }}
              className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </form>
      )}

      {isOperator && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 p-3 bg-blue-50 border border-blue-200 rounded-md text-sm">
          <span className="font-medium text-blue-800">{selected.size} selected</span>
          {bulkError && <span className="text-xs text-red-600">{bulkError}</span>}
          <button onClick={() => setBulkMoving(true)}
            className="px-3 py-1.5 text-xs bg-white border border-gray-300 rounded-md hover:bg-gray-50">
            Move selected
          </button>
          {isAdmin && (
            <button onClick={handleBulkDelete}
              className="px-3 py-1.5 text-xs bg-white border border-red-200 text-red-600 rounded-md hover:bg-red-50">
              Delete selected
            </button>
          )}
          <button onClick={() => setSelected(new Set())} className="ml-auto text-xs text-gray-500 hover:text-gray-700">
            Clear selection
          </button>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
        {isLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
        {!isLoading && !data?.length && (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No documents yet. Create one to get started.</div>
        )}
        {data?.map(doc => (
          <div key={doc.id}
            className="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
            onClick={() => onSelect(doc.id, doc.name)}>
            <div className="flex items-center gap-2">
              {isOperator && (
                <input type="checkbox" checked={selected.has(doc.id)}
                  onClick={e => e.stopPropagation()}
                  onChange={() => toggleSelected(doc.id)}
                  className="shrink-0" />
              )}
              <span>📄</span>
              <span className="font-medium text-gray-900">{doc.name}</span>
              <span className="text-xs text-gray-400 font-mono">v{doc.version}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-400">{fmtDate(doc.updated_at)}</span>
              {isOperator && (
                <button onClick={e => { e.stopPropagation(); setMovingDoc(doc) }}
                  className="text-gray-500 hover:text-gray-700 text-xs font-medium">Move</button>
              )}
              {isAdmin && (
                <button onClick={e => handleDelete(e, doc)}
                  className="text-red-600 hover:text-red-800 text-xs font-medium">Delete</button>
              )}
            </div>
          </div>
        ))}
      </div>

      {movingDoc && (
        <MoveDocModal
          doc={movingDoc}
          currentShelfId={shelfId}
          onClose={() => setMovingDoc(null)}
          onMoved={async () => {
            setMovingDoc(null)
            await queryClient.invalidateQueries({ queryKey: ['docs', shelfId] })
          }}
        />
      )}

      {bulkMoving && (
        <BulkMoveModal
          docIds={Array.from(selected)}
          currentShelfId={shelfId}
          onClose={() => setBulkMoving(false)}
          onMoved={async (failedCount) => {
            setBulkMoving(false)
            setSelected(new Set())
            if (failedCount > 0) setBulkError(`${failedCount} document(s) couldn't be moved (name conflict on destination) — see them still on this shelf.`)
            await queryClient.invalidateQueries({ queryKey: ['docs', shelfId] })
          }}
        />
      )}
    </div>
  )
}

function MoveDocModal({ doc, currentShelfId, onClose, onMoved }: {
  doc: DocSummary; currentShelfId: string; onClose: () => void; onMoved: () => void
}) {
  const [libraryId, setLibraryId] = useState('')
  const [shelfId, setShelfId] = useState('')
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState('')

  const { data: libraries } = useQuery<DocLibrary[]>({
    queryKey: ['doc-libraries'],
    queryFn: () => api.get('/docs/libraries').then(r => r.data),
  })
  const { data: shelves } = useQuery<DocShelf[]>({
    queryKey: ['doc-shelves', libraryId],
    queryFn: () => api.get(`/docs/libraries/${libraryId}/shelves`).then(r => r.data),
    enabled: !!libraryId,
  })

  const handleMove = async () => {
    if (!shelfId) return
    setMoving(true)
    setError('')
    try {
      await api.post(`/docs/${doc.id}/move`, { shelf_id: shelfId })
      onMoved()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to move document')
    } finally {
      setMoving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-gray-700">Move "{doc.name}"</h2>
        {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">{error}</div>}
        <div className="space-y-2">
          <select value={libraryId} onChange={e => { setLibraryId(e.target.value); setShelfId('') }}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="">Select library…</option>
            {libraries?.map(lib => <option key={lib.id} value={lib.id}>{lib.name}</option>)}
          </select>
          <select value={shelfId} onChange={e => setShelfId(e.target.value)} disabled={!libraryId}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm disabled:opacity-50">
            <option value="">Select shelf…</option>
            {shelves?.map(s => (
              <option key={s.id} value={s.id} disabled={s.id === currentShelfId}>
                {s.name}{s.id === currentShelfId ? ' (current)' : ''}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleMove} disabled={moving || !shelfId}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
            {moving ? 'Moving…' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  )
}

function BulkMoveModal({ docIds, currentShelfId, onClose, onMoved }: {
  docIds: string[]; currentShelfId: string; onClose: () => void; onMoved: (failedCount: number) => void
}) {
  const [libraryId, setLibraryId] = useState('')
  const [shelfId, setShelfId] = useState('')
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState('')

  const { data: libraries } = useQuery<DocLibrary[]>({
    queryKey: ['doc-libraries'],
    queryFn: () => api.get('/docs/libraries').then(r => r.data),
  })
  const { data: shelves } = useQuery<DocShelf[]>({
    queryKey: ['doc-shelves', libraryId],
    queryFn: () => api.get(`/docs/libraries/${libraryId}/shelves`).then(r => r.data),
    enabled: !!libraryId,
  })

  const handleMove = async () => {
    if (!shelfId) return
    setMoving(true)
    setError('')
    try {
      const res = await api.post('/docs/bulk-move', { doc_ids: docIds, shelf_id: shelfId })
      onMoved(res.data.failed.length)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to move documents')
    } finally {
      setMoving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24 px-4" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40" />
      <div className="relative bg-white rounded-xl shadow-2xl w-full max-w-md p-5 space-y-3" onClick={e => e.stopPropagation()}>
        <h2 className="text-sm font-semibold text-gray-700">Move {docIds.length} document(s)</h2>
        {error && <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">{error}</div>}
        <div className="space-y-2">
          <select value={libraryId} onChange={e => { setLibraryId(e.target.value); setShelfId('') }}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="">Select library…</option>
            {libraries?.map(lib => <option key={lib.id} value={lib.id}>{lib.name}</option>)}
          </select>
          <select value={shelfId} onChange={e => setShelfId(e.target.value)} disabled={!libraryId}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm disabled:opacity-50">
            <option value="">Select shelf…</option>
            {shelves?.map(s => (
              <option key={s.id} value={s.id} disabled={s.id === currentShelfId}>
                {s.name}{s.id === currentShelfId ? ' (current)' : ''}
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleMove} disabled={moving || !shelfId}
            className="px-3 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
            {moving ? 'Moving…' : 'Move'}
          </button>
        </div>
      </div>
    </div>
  )
}
