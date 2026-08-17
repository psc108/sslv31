import { useState, useEffect, useCallback } from 'react'
import api from '@/lib/api'

interface Template {
  id: string
  name: string
  description: string
  tags: string
  origin: string
  version_count: number
  current_version: number
  current_spec: any
  current_change_note: string
  created_by: string
  created_at: string
}

interface TemplateVersion {
  id: string
  version: number
  change_note: string
  is_current: boolean
  created_by: string
  created_at: string
}

export default function BMTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [selected, setSelected] = useState<Template | null>(null)
  const [versions, setVersions] = useState<TemplateVersion[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [createForm, setCreateForm] = useState({ name: '', description: '', spec: '', change_note: 'Initial version' })
  const [editForm, setEditForm] = useState({ spec: '', change_note: '' })

  const loadTemplates = useCallback(async () => {
    try {
      const res = await api.get('/build/templates')
      setTemplates(res.data)
    } catch { setError('Failed to load templates') }
  }, [])

  useEffect(() => { loadTemplates() }, [loadTemplates])

  const selectTemplate = async (t: Template) => {
    setSelected(t)
    try {
      const [detail, vers] = await Promise.all([
        api.get(`/build/templates/${t.id}`),
        api.get(`/build/templates/${t.id}/versions`),
      ])
      setSelected(detail.data)
      setVersions(vers.data)
    } catch { setError('Failed to load template details') }
  }

  const createTemplate = async () => {
    try {
      const spec = JSON.parse(createForm.spec)
      await api.post('/build/templates', { ...createForm, spec })
      setShowCreate(false)
      setCreateForm({ name: '', description: '', spec: '', change_note: 'Initial version' })
      setSuccess('Template created')
      loadTemplates()
    } catch (e: any) {
      setError(e.response?.data?.detail?.validation_errors?.join(', ') || e.response?.data?.detail || 'Failed to create template')
    }
  }

  const saveNewVersion = async () => {
    if (!selected) return
    try {
      const spec = JSON.parse(editForm.spec)
      await api.put(`/build/templates/${selected.id}`, { spec, change_note: editForm.change_note })
      setShowEdit(false)
      setSuccess('New version saved')
      selectTemplate(selected)
      loadTemplates()
    } catch (e: any) {
      setError(e.response?.data?.detail?.validation_errors?.join(', ') || e.response?.data?.detail || 'Failed to save version')
    }
  }

  const deleteTemplate = async (id: string) => {
    if (!confirm('Delete this template? This cannot be undone.')) return
    try {
      await api.delete(`/build/templates/${id}`)
      setSelected(null)
      setVersions([])
      loadTemplates()
    } catch (e: any) { setError(e.response?.data?.detail || 'Failed to delete') }
  }

  const seedReferenceTemplates = async () => {
    try {
      const res = await api.post('/build/templates/seed')
      setSuccess(res.data.templates_added > 0 ? `Added ${res.data.templates_added} reference template(s)` : 'Reference templates already present')
      loadTemplates()
    } catch (e: any) { setError(e.response?.data?.detail || 'Seed failed') }
  }

  const exportYaml = async (templateId: string, version: number) => {
    try {
      const res = await api.get(`/build/templates/${templateId}/versions/${version}/export`)
      const blob = new Blob([res.data.yaml], { type: 'text/yaml' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = res.data.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch { setError('Export failed') }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Build Manager — Templates</h1>
          <p className="text-sm text-gray-500 mt-1">Versioned blueprints for environment deployment</p>
        </div>
        <div className="flex gap-2">
          <button onClick={seedReferenceTemplates} className="px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded-md hover:bg-gray-200">
            🌱 Seed Reference Templates
          </button>
          <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
            + New Template
          </button>
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">{error}<button onClick={() => setError('')} className="ml-2">✕</button></div>}
      {success && <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-700">{success}<button onClick={() => setSuccess('')} className="ml-2">✕</button></div>}

      {/* Create Modal */}
      {showCreate && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          <h3 className="font-medium text-gray-900">Create Template</h3>
          <div className="grid grid-cols-2 gap-3">
            <input placeholder="Template Name" value={createForm.name} onChange={e => setCreateForm({ ...createForm, name: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm" />
            <input placeholder="Description" value={createForm.description} onChange={e => setCreateForm({ ...createForm, description: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm" />
          </div>
          <textarea placeholder='Template Spec (JSON) — e.g. {"hosts": [{"role": "frontend"}], "network": {"pool": "192.168.50.0/24"}}' value={createForm.spec}
            onChange={e => setCreateForm({ ...createForm, spec: e.target.value })}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono h-48" />
          <input placeholder="Change note" value={createForm.change_note} onChange={e => setCreateForm({ ...createForm, change_note: e.target.value })}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm" />
          <div className="flex gap-2">
            <button onClick={createTemplate} className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Create</button>
            <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Template List */}
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-gray-600 uppercase tracking-wide">Templates</h2>
          {templates.map(t => (
            <div key={t.id} onClick={() => selectTemplate(t)}
              className={`p-3 rounded-lg border cursor-pointer transition ${selected?.id === t.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
              <div className="flex items-center justify-between">
                <span className="font-medium text-gray-900 text-sm">{t.name}</span>
                <span className="text-xs text-gray-500">v{t.current_version}</span>
              </div>
              <p className="text-xs text-gray-500 mt-1 truncate">{t.description || 'No description'}</p>
              <div className="flex items-center gap-2 mt-2">
                <span className="text-xs text-gray-400">{t.version_count} version{t.version_count !== 1 ? 's' : ''}</span>
                {t.origin === 'builtin' && <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">🌱 reference</span>}
              </div>
            </div>
          ))}
          {templates.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No templates yet</p>}
        </div>

        {/* Template Detail */}
        <div className="lg:col-span-2">
          {selected ? (
            <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{selected.name}</h2>
                  <p className="text-sm text-gray-500">{selected.description}</p>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => { setEditForm({ spec: JSON.stringify(selected.current_spec, null, 2), change_note: '' }); setShowEdit(true) }}
                    className="px-3 py-1.5 bg-yellow-50 text-yellow-700 text-xs rounded hover:bg-yellow-100">✏️ New Version</button>
                  <button onClick={() => exportYaml(selected.id, selected.current_version)}
                    className="px-3 py-1.5 bg-gray-50 text-gray-700 text-xs rounded hover:bg-gray-100">📥 Export YAML</button>
                  <button onClick={() => deleteTemplate(selected.id)}
                    className="px-3 py-1.5 bg-red-50 text-red-700 text-xs rounded hover:bg-red-100">🗑️ Delete</button>
                </div>
              </div>

              {/* Edit Form */}
              {showEdit && (
                <div className="border border-yellow-200 bg-yellow-50 rounded-lg p-3 space-y-2">
                  <h4 className="text-sm font-medium text-yellow-800">Save New Version</h4>
                  <textarea value={editForm.spec} onChange={e => setEditForm({ ...editForm, spec: e.target.value })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono h-48" />
                  <input placeholder="Change note (required) — why this version?" value={editForm.change_note}
                    onChange={e => setEditForm({ ...editForm, change_note: e.target.value })}
                    className="w-full border border-gray-300 rounded px-3 py-2 text-sm" />
                  <div className="flex gap-2">
                    <button onClick={saveNewVersion} disabled={!editForm.change_note}
                      className="px-3 py-1.5 bg-yellow-600 text-white text-sm rounded hover:bg-yellow-700 disabled:opacity-50">Save Version</button>
                    <button onClick={() => setShowEdit(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded">Cancel</button>
                  </div>
                </div>
              )}

              {/* Current Spec */}
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-2">Current Spec (v{selected.current_version})</h3>
                <p className="text-xs text-gray-500 mb-2 italic">"{selected.current_change_note}"</p>
                <pre className="bg-gray-900 text-green-400 rounded-lg p-3 text-xs overflow-auto max-h-64">
                  {JSON.stringify(selected.current_spec, null, 2)}
                </pre>
              </div>

              {/* Version History */}
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-2">Version History</h3>
                <div className="space-y-1">
                  {versions.map(v => (
                    <div key={v.id} className={`flex items-center justify-between px-3 py-2 rounded text-sm ${v.is_current ? 'bg-blue-50 border border-blue-200' : 'bg-gray-50'}`}>
                      <div>
                        <span className="font-medium">v{v.version}</span>
                        <span className="text-gray-500 ml-2">— {v.change_note}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">{v.created_by}</span>
                        {v.is_current && <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">current</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center text-gray-400">
              Select a template to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
