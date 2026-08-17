import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Secret {
  id: string
  name: string
  category: string
  linked_service: string
  description: string
  created_by: string
  rotated_at: string | null
  created_at: string | null
  value?: string
  rotate_every_days: number | null
  rotation_due_at: string | null
  rotation_overdue: boolean
}

const CATEGORIES = ['database', 'messaging', 'identity', 'custom']

export default function BMSecretsPage() {
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', value: '', category: 'custom', linked_service: '', description: '', rotate_every_days: '' })
  const [revealedId, setRevealedId] = useState<string | null>(null)
  const [revealedValue, setRevealedValue] = useState('')
  const [saving, setSaving] = useState(false)

  const load = () => {
    setLoading(true)
    api.get('/build/secrets').then(r => { setSecrets(r.data); setLoading(false) }).catch(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const openCreate = () => {
    setEditId(null)
    setForm({ name: '', value: '', category: 'custom', linked_service: '', description: '', rotate_every_days: '' })
    setShowModal(true)
  }

  const openEdit = (s: Secret) => {
    setEditId(s.id)
    setForm({ name: s.name, value: '', category: s.category, linked_service: s.linked_service, description: s.description, rotate_every_days: s.rotate_every_days ? String(s.rotate_every_days) : '' })
    setShowModal(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      if (editId) {
        const payload: any = { category: form.category, linked_service: form.linked_service, description: form.description }
        if (form.value) payload.value = form.value
        if (form.rotate_every_days) {
          payload.rotate_every_days = Number(form.rotate_every_days)
        } else {
          payload.clear_rotation_policy = true
        }
        await api.put(`/build/secrets/${editId}`, payload)
      } else {
        const payload: any = { ...form }
        payload.rotate_every_days = form.rotate_every_days ? Number(form.rotate_every_days) : null
        await api.post('/build/secrets', payload)
      }
      setShowModal(false)
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to save secret')
    }
    setSaving(false)
  }

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete secret "${name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/build/secrets/${id}`)
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to delete')
    }
  }

  const handleReveal = async (id: string) => {
    if (revealedId === id) { setRevealedId(null); setRevealedValue(''); return }
    try {
      const res = await api.get(`/build/secrets/${id}`)
      setRevealedId(id)
      setRevealedValue(res.data.value || '')
    } catch {
      alert('Failed to retrieve secret value')
    }
  }

  const handleRotate = async (id: string) => {
    const newValue = prompt('Enter new value for rotation:')
    if (!newValue) return
    try {
      await api.post(`/build/secrets/${id}/rotate`, { name: '_', value: newValue })
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Rotation failed')
    }
  }

  const categoryBadge = (cat: string) => {
    const colors: Record<string, string> = {
      database: 'bg-blue-50 text-blue-700',
      messaging: 'bg-purple-50 text-purple-700',
      identity: 'bg-green-50 text-green-700',
      custom: 'bg-gray-50 text-gray-600',
    }
    return colors[cat] || colors.custom
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Secrets</h1>
        <button onClick={openCreate} className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">
          + Add Secret
        </button>
      </div>

      <p className="text-sm text-gray-500">
        Encrypted secrets injected into Ansible runs as <code className="text-xs bg-gray-100 px-1 rounded">vault_&lt;name&gt;</code> variables. Never stored in plaintext on disk.
      </p>

      {loading ? (
        <p className="text-sm text-gray-400">Loading...</p>
      ) : secrets.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
          <p className="text-gray-500">No secrets stored yet.</p>
          <p className="text-sm text-gray-400 mt-1">Add secrets like database passwords, API tokens, or service credentials.</p>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {secrets.map(s => (
            <div key={s.id} className="px-4 py-3 flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-gray-800 font-mono">{s.name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${categoryBadge(s.category)}`}>{s.category}</span>
                  {s.linked_service && (
                    <span className="text-xs text-gray-400">→ {s.linked_service}</span>
                  )}
                  {s.rotation_overdue && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-medium" title={`Rotation policy: every ${s.rotate_every_days} days`}>
                      ⚠ rotation overdue
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-3 mt-1">
                  {s.description && <span className="text-xs text-gray-500">{s.description}</span>}
                  {s.rotated_at && (
                    <span className="text-xs text-gray-400">rotated {new Date(s.rotated_at).toLocaleDateString()}</span>
                  )}
                  {s.rotate_every_days && !s.rotation_overdue && (
                    <span className="text-xs text-gray-400">rotates every {s.rotate_every_days}d — due {s.rotation_due_at ? new Date(s.rotation_due_at).toLocaleDateString() : '—'}</span>
                  )}
                </div>
                {revealedId === s.id && (
                  <div className="mt-2 p-2 bg-gray-50 rounded border border-gray-200">
                    <code className="text-xs text-gray-700 break-all">{revealedValue}</code>
                  </div>
                )}
              </div>

              <div className="flex gap-1">
                <button onClick={() => handleReveal(s.id)} className="text-xs px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">
                  {revealedId === s.id ? 'Hide' : 'Reveal'}
                </button>
                <button onClick={() => handleRotate(s.id)} className="text-xs px-2 py-1 rounded border border-orange-200 text-orange-700 hover:bg-orange-50">
                  Rotate
                </button>
                <button onClick={() => openEdit(s)} className="text-xs px-2 py-1 rounded border border-blue-200 text-blue-700 hover:bg-blue-50">
                  Edit
                </button>
                <button onClick={() => handleDelete(s.id, s.name)} className="text-xs px-2 py-1 rounded border border-red-200 text-red-700 hover:bg-red-50">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">{editId ? 'Edit Secret' : 'Add Secret'}</h2>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                disabled={!!editId}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm disabled:bg-gray-50"
                placeholder="e.g. mysql_root_password"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Value {editId && <span className="text-gray-400 font-normal">(leave blank to keep current)</span>}
              </label>
              <input
                type="password"
                value={form.value}
                onChange={e => setForm({ ...form, value: e.target.value })}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
                placeholder={editId ? '••••••••' : 'secret value'}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
                <select
                  value={form.category}
                  onChange={e => setForm({ ...form, category: e.target.value })}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                >
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Linked Service</label>
                <input
                  value={form.linked_service}
                  onChange={e => setForm({ ...form, linked_service: e.target.value })}
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  placeholder="e.g. mysql"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <input
                value={form.description}
                onChange={e => setForm({ ...form, description: e.target.value })}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                placeholder="Optional description"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rotation Policy <span className="text-gray-400 font-normal">(optional — flags as overdue, never auto-rotates)</span>
              </label>
              <input
                type="number"
                min={1}
                value={form.rotate_every_days}
                onChange={e => setForm({ ...form, rotate_every_days: e.target.value })}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                placeholder="e.g. 90 (days) — leave blank for no policy"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setShowModal(false)} className="px-3 py-1.5 text-sm border border-gray-300 rounded text-gray-700 hover:bg-gray-50">
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving || (!editId && (!form.name || !form.value))}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Saving...' : editId ? 'Update' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
