import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatDate, daysUntil } from '@/lib/utils'
import type { CAListItem, CACreateRequest, Subject } from '@/lib/types'

export default function CAPage() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)

  const { data: cas = [], isLoading } = useQuery<CAListItem[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Certificate Authorities</h2>
          <p className="text-sm text-gray-500 mt-1">Manage root and intermediate CAs</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : '+ Create CA'}
        </button>
      </div>

      {showForm && <CACreateForm cas={cas} onSuccess={() => setShowForm(false)} />}

      {/* CA Chain Visualiser */}
      {!isLoading && cas.length > 0 && (
        <div className="mb-6 p-4 bg-white rounded-lg border border-gray-200">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">CA Hierarchy</h3>
          <div className="space-y-2">
            {cas.filter(ca => ca.is_root).map(root => (
              <div key={root.id}>
                <div className="flex items-center gap-2">
                  <span className="text-green-600">🏛️</span>
                  <span className="font-medium text-sm">{root.cn}</span>
                  <span className="text-xs text-gray-400">Root</span>
                </div>
                {cas.filter(c => c.parent_ca_id === root.id).map(child => (
                  <div key={child.id} className="ml-8 flex items-center gap-2 mt-1">
                    <span className="text-blue-600">└─</span>
                    <span className="text-sm">{child.cn}</span>
                    <span className="text-xs text-gray-400">Intermediate</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* CA List Table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Common Name</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Type</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Key</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Expires</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Certs Issued</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {!isLoading && cas.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No CAs created yet</td></tr>
            )}
            {cas.map(ca => (
              <tr key={ca.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900">{ca.cn}</td>
                <td className="px-4 py-3">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                    ca.is_root ? 'bg-green-100 text-green-800' : 'bg-blue-100 text-blue-800'
                  }`}>
                    {ca.is_root ? 'Root' : 'Intermediate'}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-600">{ca.key_algo} {ca.key_size}</td>
                <td className="px-4 py-3 text-gray-600">
                  {formatDate(ca.expires_at)}
                  <span className="text-xs text-gray-400 ml-1">({daysUntil(ca.expires_at)}d)</span>
                </td>
                <td className="px-4 py-3 text-gray-600">{ca.cert_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CACreateForm({ cas, onSuccess }: { cas: CAListItem[]; onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const [isRoot, setIsRoot] = useState(true)
  const [form, setForm] = useState<CACreateRequest>({
    subject: { cn: '', o: '', ou: '', c: '', st: '', l: '' },
    key_algo: 'RSA',
    key_size: 4096,
    validity_days: 3650,
    parent_ca_id: null,
    path_length: 1,
  })

  const mutation = useMutation({
    mutationFn: (data: CACreateRequest) => api.post('/ca', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cas'] })
      onSuccess()
    },
  })

  const updateSubject = (field: keyof Subject, value: string) => {
    setForm(prev => ({ ...prev, subject: { ...prev.subject, [field]: value } }))
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const payload = {
      ...form,
      parent_ca_id: isRoot ? null : form.parent_ca_id,
      path_length: isRoot ? 1 : 0,
    }
    mutation.mutate(payload)
  }

  return (
    <form onSubmit={handleSubmit} className="mb-6 p-4 bg-white rounded-lg border border-gray-200 space-y-4">
      <h3 className="font-semibold text-gray-900">Create Certificate Authority</h3>

      {/* Type toggle */}
      <div className="flex gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={isRoot} onChange={() => setIsRoot(true)} />
          Root CA
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={!isRoot} onChange={() => setIsRoot(false)} />
          Intermediate CA
        </label>
      </div>

      {/* Parent CA selector */}
      {!isRoot && (
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Parent CA</label>
          <select
            value={form.parent_ca_id || ''}
            onChange={e => setForm(prev => ({ ...prev, parent_ca_id: e.target.value }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            required
          >
            <option value="">Select parent CA...</option>
            {cas.filter(c => c.is_root).map(ca => (
              <option key={ca.id} value={ca.id}>{ca.cn}</option>
            ))}
          </select>
        </div>
      )}

      {/* Subject fields */}
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-1">Common Name *</label>
          <input
            type="text"
            value={form.subject.cn}
            onChange={e => updateSubject('cn', e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="Internal Root CA"
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Organisation</label>
          <input type="text" value={form.subject.o} onChange={e => updateSubject('o', e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Org Unit</label>
          <input type="text" value={form.subject.ou} onChange={e => updateSubject('ou', e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
          <input type="text" value={form.subject.c} onChange={e => updateSubject('c', e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" maxLength={2} placeholder="GB" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">State</label>
          <input type="text" value={form.subject.st} onChange={e => updateSubject('st', e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>

      {/* Key options */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Algorithm</label>
          <select value={form.key_algo} onChange={e => setForm(prev => ({ ...prev, key_algo: e.target.value }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="RSA">RSA</option>
            <option value="ECDSA">ECDSA</option>
            <option value="Ed25519">Ed25519</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Key Size</label>
          <select value={form.key_size} onChange={e => setForm(prev => ({ ...prev, key_size: Number(e.target.value) }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            {form.key_algo === 'RSA' && <><option value={2048}>2048</option><option value={3072}>3072</option><option value={4096}>4096</option></>}
            {form.key_algo === 'ECDSA' && <><option value={256}>P-256</option><option value={384}>P-384</option><option value={521}>P-521</option></>}
            {form.key_algo === 'Ed25519' && <option value={256}>256 (fixed)</option>}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Validity (days)</label>
          <input type="number" value={form.validity_days}
            onChange={e => setForm(prev => ({ ...prev, validity_days: Number(e.target.value) }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" min={1} max={7300} />
        </div>
      </div>

      {/* Submit */}
      <div className="flex justify-end gap-3">
        {mutation.isError && (
          <p className="text-red-600 text-sm self-center">
            {(mutation.error as any)?.response?.data?.detail || 'Failed to create CA'}
          </p>
        )}
        <button
          type="submit"
          disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {mutation.isPending ? 'Creating...' : 'Create CA'}
        </button>
      </div>
    </form>
  )
}
