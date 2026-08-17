import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import type { CategoryRule } from './structuredParse'

// Improvements Plan Stage 13 — admin UI for the Structured View heading ->
// category badge mapping (backend/app/api/v1/category_rules.py). Mirrors
// SettingsPage.tsx's own section pattern (PKISettings/LDAPSettings) exactly
// — no client-side role gating here either, matching that file's own
// convention of relying on the backend RBAC (admin-only mutations) rather
// than duplicating the check in every settings section.
export default function CategoryRulesSettings() {
  const queryClient = useQueryClient()
  const [newPattern, setNewPattern] = useState('')
  const [newLabel, setNewLabel] = useState('')
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editPattern, setEditPattern] = useState('')
  const [editLabel, setEditLabel] = useState('')

  const { data: rules = [] } = useQuery<CategoryRule[]>({
    queryKey: ['category-rules'],
    queryFn: () => api.get('/category-rules').then(r => r.data),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['category-rules'] })

  const createMutation = useMutation({
    mutationFn: () => api.post('/category-rules', { pattern: newPattern, label: newLabel }),
    onSuccess: () => { setNewPattern(''); setNewLabel(''); setError(''); invalidate() },
    onError: (e: any) => setError(e?.response?.data?.detail || 'Failed to create rule'),
  })

  const updateMutation = useMutation({
    mutationFn: (vars: { id: string; body: Partial<Pick<CategoryRule, 'pattern' | 'label' | 'sort_order'>> }) =>
      api.patch(`/category-rules/${vars.id}`, vars.body),
    onSuccess: () => { setError(''); invalidate() },
    onError: (e: any) => setError(e?.response?.data?.detail || 'Failed to update rule'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/category-rules/${id}`),
    onSuccess: invalidate,
  })

  const startEdit = (r: CategoryRule) => {
    setEditingId(r.id)
    setEditPattern(r.pattern)
    setEditLabel(r.label)
  }

  const saveEdit = (id: string) => {
    updateMutation.mutate({ id, body: { pattern: editPattern, label: editLabel } }, {
      onSuccess: () => setEditingId(null),
    })
  }

  const move = (index: number, direction: -1 | 1) => {
    const target = rules[index + direction]
    const current = rules[index]
    if (!target || !current) return
    // Swap sort_order between the two adjacent rows — simplest possible
    // reordering primitive that doesn't need a dedicated bulk-reorder
    // endpoint; ties just mean stable-ish ordering, not a correctness issue.
    updateMutation.mutate({ id: current.id, body: { sort_order: target.sort_order } })
    updateMutation.mutate({ id: target.id, body: { sort_order: current.sort_order } })
  }

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-1">Structured View Categories</h3>
      <p className="text-sm text-gray-500 mb-3">
        Controls the badge a card gets in Docs' Structured View, based on a keyword match against its
        heading — first matching pattern wins, checked top to bottom. A heading matching nothing falls
        back to a generic "Section" badge. Patterns are regular expressions, matched case-insensitively.
      </p>

      {error && <p className="text-sm text-red-600 mb-2">{error}</p>}

      <div className="space-y-1.5 mb-4 max-h-96 overflow-y-auto">
        {rules.map((r, i) => (
          <div key={r.id} className="flex items-center gap-2 text-sm border-b border-gray-100 pb-1.5 last:border-0">
            <div className="flex flex-col">
              <button onClick={() => move(i, -1)} disabled={i === 0}
                className="text-gray-400 hover:text-gray-700 disabled:opacity-20 leading-none" title="Move up">▲</button>
              <button onClick={() => move(i, 1)} disabled={i === rules.length - 1}
                className="text-gray-400 hover:text-gray-700 disabled:opacity-20 leading-none" title="Move down">▼</button>
            </div>
            {editingId === r.id ? (
              <>
                <input value={editPattern} onChange={e => setEditPattern(e.target.value)}
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs font-mono" />
                <input value={editLabel} onChange={e => setEditLabel(e.target.value)}
                  className="w-28 border border-gray-300 rounded px-2 py-1 text-xs" />
                <button onClick={() => saveEdit(r.id)} className="text-green-600 hover:text-green-800 text-xs font-medium">Save</button>
                <button onClick={() => setEditingId(null)} className="text-gray-400 hover:text-gray-600 text-xs">Cancel</button>
              </>
            ) : (
              <>
                <span className="flex-1 font-mono text-xs text-gray-700 truncate" title={r.pattern}>{r.pattern}</span>
                <span className="w-28 shrink-0 inline-block px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 text-xs font-medium text-center">{r.label}</span>
                <button onClick={() => startEdit(r)} className="text-gray-400 hover:text-gray-700 text-xs">Edit</button>
                <button onClick={() => { if (confirm(`Delete the "${r.label}" rule?`)) deleteMutation.mutate(r.id) }}
                  className="text-red-400 hover:text-red-600 text-xs">Delete</button>
              </>
            )}
          </div>
        ))}
        {rules.length === 0 && <p className="text-xs text-gray-400 italic">No category rules — every heading will show as "Section".</p>}
      </div>

      <div className="flex items-center gap-2 border-t border-gray-100 pt-3">
        <input value={newPattern} onChange={e => setNewPattern(e.target.value)}
          placeholder="pattern (regex), e.g. billing|payment"
          className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-xs font-mono" />
        <input value={newLabel} onChange={e => setNewLabel(e.target.value)}
          placeholder="label, e.g. Billing"
          className="w-28 border border-gray-300 rounded px-2 py-1.5 text-xs" />
        <button
          onClick={() => createMutation.mutate()}
          disabled={!newPattern.trim() || !newLabel.trim() || createMutation.isPending}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded hover:bg-blue-700 disabled:opacity-50">
          + Add
        </button>
      </div>
    </section>
  )
}
