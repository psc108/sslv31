import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

interface Template {
  id: string
  name: string
  display_name: string
  description: string
  allowed_key_algos: string[]
  min_key_size: number
  max_validity_days: number
  allowed_san_types: string[]
  require_san: boolean
  key_usage: string[]
  extended_key_usage: string[]
  allowed_cn_pattern: string
  require_org: boolean
  is_builtin: boolean
  created_at: string | null
}

export default function TemplatesPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Template | null>(null)
  const [creating, setCreating] = useState(false)

  const { data: templates = [] } = useQuery<Template[]>({
    queryKey: ['templates'],
    queryFn: async () => (await api.get('/templates')).data,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/templates/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['templates'] }),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Certificate Templates</h2>
          <p className="text-sm text-gray-500 mt-1">Define and enforce policies for certificate issuance</p>
        </div>
        <button onClick={() => { setCreating(true); setEditing(null) }}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
          + New Template
        </button>
      </div>

      {(creating || editing) && (
        <TemplateForm
          template={editing}
          onClose={() => { setCreating(false); setEditing(null) }}
          onSaved={() => { setCreating(false); setEditing(null); queryClient.invalidateQueries({ queryKey: ['templates'] }) }}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {templates.map(t => (
          <div key={t.id} className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-start justify-between mb-2">
              <div>
                <h3 className="font-semibold text-gray-900">{t.display_name}</h3>
                <p className="text-xs text-gray-400 font-mono">{t.name}</p>
              </div>
              {t.is_builtin && (
                <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-[10px] font-bold rounded">BUILT-IN</span>
              )}
            </div>
            <p className="text-sm text-gray-600 mb-3">{t.description}</p>

            <div className="space-y-1.5 text-xs text-gray-500">
              <div className="flex justify-between">
                <span>Key Algos:</span>
                <span className="font-medium text-gray-700">{t.allowed_key_algos.join(', ')}</span>
              </div>
              <div className="flex justify-between">
                <span>Min Key Size:</span>
                <span className="font-medium text-gray-700">{t.min_key_size}</span>
              </div>
              <div className="flex justify-between">
                <span>Max Validity:</span>
                <span className="font-medium text-gray-700">{t.max_validity_days} days</span>
              </div>
              <div className="flex justify-between">
                <span>SAN Required:</span>
                <span className={`font-medium ${t.require_san ? 'text-amber-600' : 'text-gray-700'}`}>
                  {t.require_san ? 'Yes' : 'No'}
                </span>
              </div>
              {t.allowed_san_types.length > 0 && (
                <div className="flex justify-between">
                  <span>SAN Types:</span>
                  <span className="font-medium text-gray-700">{t.allowed_san_types.join(', ')}</span>
                </div>
              )}
              {t.extended_key_usage.length > 0 && (
                <div className="flex justify-between">
                  <span>EKU:</span>
                  <span className="font-medium text-gray-700">{t.extended_key_usage.join(', ')}</span>
                </div>
              )}
            </div>

            <div className="flex gap-2 mt-3 pt-3 border-t border-gray-100">
              <button onClick={() => { setEditing(t); setCreating(false) }}
                className="px-3 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 rounded">
                Edit
              </button>
              {!t.is_builtin && (
                <button onClick={() => { if (confirm(`Delete template "${t.display_name}"?`)) deleteMutation.mutate(t.id) }}
                  className="px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 rounded">
                  Delete
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function TemplateForm({ template, onClose, onSaved }: { template: Template | null; onClose: () => void; onSaved: () => void }) {
  const isEdit = !!template
  const [name, setName] = useState(template?.name || '')
  const [displayName, setDisplayName] = useState(template?.display_name || '')
  const [description, setDescription] = useState(template?.description || '')
  const [allowedKeyAlgos, setAllowedKeyAlgos] = useState<string[]>(template?.allowed_key_algos || ['RSA', 'ECDSA', 'Ed25519'])
  const [minKeySize, setMinKeySize] = useState(template?.min_key_size || 2048)
  const [maxValidityDays, setMaxValidityDays] = useState(template?.max_validity_days || 398)
  const [allowedSanTypes, setAllowedSanTypes] = useState<string[]>(template?.allowed_san_types || ['dns', 'ip', 'email', 'uri'])
  const [requireSan, setRequireSan] = useState(template?.require_san || false)
  const [extendedKeyUsage, setExtendedKeyUsage] = useState<string[]>(template?.extended_key_usage || [])
  const [allowedCnPattern, setAllowedCnPattern] = useState(template?.allowed_cn_pattern || '')
  const [requireOrg, setRequireOrg] = useState(template?.require_org || false)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name, display_name: displayName, description,
        allowed_key_algos: allowedKeyAlgos, min_key_size: minKeySize,
        max_validity_days: maxValidityDays, allowed_san_types: allowedSanTypes,
        require_san: requireSan, key_usage: [], extended_key_usage: extendedKeyUsage,
        allowed_cn_pattern: allowedCnPattern, require_org: requireOrg,
      }
      if (isEdit) return api.put(`/templates/${template!.id}`, payload)
      return api.post('/templates', payload)
    },
    onSuccess: () => onSaved(),
    onError: (e: any) => setError(e.response?.data?.detail || 'Failed to save template'),
  })

  const toggleArray = (arr: string[], val: string, setter: (v: string[]) => void) => {
    setter(arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val])
  }

  return (
    <div className="bg-white rounded-lg border border-blue-200 p-5 mb-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-gray-900">{isEdit ? 'Edit Template' : 'New Template'}</h3>
        <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">✕ Close</button>
      </div>

      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Name (slug)</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)} disabled={isEdit}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm disabled:bg-gray-100"
            placeholder="my-template" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Display Name</label>
          <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm" placeholder="My Template" />
        </div>
        <div className="md:col-span-2">
          <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
          <input type="text" value={description} onChange={e => setDescription(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm" />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Allowed Key Algorithms</label>
          <div className="flex gap-3">
            {['RSA', 'ECDSA', 'Ed25519'].map(a => (
              <label key={a} className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={allowedKeyAlgos.includes(a)}
                  onChange={() => toggleArray(allowedKeyAlgos, a, setAllowedKeyAlgos)} />
                {a}
              </label>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Min Key Size (RSA)</label>
          <select value={minKeySize} onChange={e => setMinKeySize(Number(e.target.value))}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm">
            <option value={2048}>2048</option>
            <option value={3072}>3072</option>
            <option value={4096}>4096</option>
          </select>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Max Validity (days)</label>
          <input type="number" value={maxValidityDays} onChange={e => setMaxValidityDays(Number(e.target.value))}
            min={1} max={7300} className="w-32 border border-gray-300 rounded-md px-3 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Allowed SAN Types</label>
          <div className="flex gap-3">
            {['dns', 'ip', 'email', 'uri'].map(t => (
              <label key={t} className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={allowedSanTypes.includes(t)}
                  onChange={() => toggleArray(allowedSanTypes, t, setAllowedSanTypes)} />
                {t.toUpperCase()}
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Extended Key Usage</label>
          <div className="flex flex-wrap gap-3">
            {['serverAuth', 'clientAuth', 'codeSigning', 'emailProtection'].map(e => (
              <label key={e} className="flex items-center gap-1 text-xs">
                <input type="checkbox" checked={extendedKeyUsage.includes(e)}
                  onChange={() => toggleArray(extendedKeyUsage, e, setExtendedKeyUsage)} />
                {e}
              </label>
            ))}
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">CN Pattern (regex, optional)</label>
          <input type="text" value={allowedCnPattern} onChange={e => setAllowedCnPattern(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-1.5 text-sm font-mono"
            placeholder=".*\.example\.com$" />
        </div>

        <div className="flex gap-6">
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={requireSan} onChange={e => setRequireSan(e.target.checked)} />
            Require SAN
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={requireOrg} onChange={e => setRequireOrg(e.target.checked)} />
            Require Organisation
          </label>
        </div>
      </div>

      <div className="flex gap-3 mt-4 pt-4 border-t border-gray-100">
        <button onClick={() => mutation.mutate()} disabled={mutation.isPending || !name || !displayName}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Saving...' : isEdit ? 'Update Template' : 'Create Template'}
        </button>
        <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
      </div>
    </div>
  )
}
