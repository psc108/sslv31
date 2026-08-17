import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { formatDate, authenticatedDownload } from '@/lib/utils'
import type { CAListItem, TrustStore, TrustStoreCreateRequest } from '@/lib/types'

export default function TrustStoreBuilder() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<TrustStoreCreateRequest>({
    name: '',
    store_type: 'JKS',
    ca_ids: [],
    password: '',
  })
  const [showSpringConfig, setShowSpringConfig] = useState<string | null>(null)

  const { data: cas = [] } = useQuery<CAListItem[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  const { data: stores = [] } = useQuery<TrustStore[]>({
    queryKey: ['truststores'],
    queryFn: async () => {
      // No list endpoint in current API — use empty for now
      return []
    },
  })

  const mutation = useMutation({
    mutationFn: (data: TrustStoreCreateRequest) => api.post('/truststore', data),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['truststores'] })
      setShowSpringConfig(res.data.id)
      setForm({ name: '', store_type: 'JKS', ca_ids: [], password: '' })
    },
  })

  const toggleCA = (caId: string) => {
    setForm(prev => ({
      ...prev,
      ca_ids: prev.ca_ids.includes(caId)
        ? prev.ca_ids.filter(id => id !== caId)
        : [...prev.ca_ids, caId],
    }))
  }

  const minPassword = form.store_type === 'JKS' ? 12 : 6
  const passwordValid = form.password.length >= minPassword

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-2">Trust Store Builder</h2>
      <p className="text-sm text-gray-500 mb-6">Build JKS or PKCS#12 truststores for Java applications</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Build form */}
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          <h3 className="font-semibold text-gray-900">Build New TrustStore</h3>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input type="text" value={form.name}
              onChange={e => setForm(prev => ({ ...prev, name: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="production-truststore" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Store Type</label>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" checked={form.store_type === 'JKS'}
                  onChange={() => setForm(prev => ({ ...prev, store_type: 'JKS' }))} />
                JKS (legacy)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" checked={form.store_type === 'PKCS12'}
                  onChange={() => setForm(prev => ({ ...prev, store_type: 'PKCS12' }))} />
                PKCS#12 (Java 9+, recommended)
              </label>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Select CAs to include</label>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {cas.map(ca => (
                <label key={ca.id} className="flex items-center gap-2 text-sm p-2 rounded hover:bg-gray-50">
                  <input type="checkbox" checked={form.ca_ids.includes(ca.id)} onChange={() => toggleCA(ca.id)} />
                  <span className={ca.is_root ? 'font-medium' : 'ml-4'}>{ca.cn}</span>
                  <span className="text-xs text-gray-400">{ca.is_root ? 'Root' : 'Intermediate'}</span>
                </label>
              ))}
              {cas.length === 0 && <p className="text-sm text-gray-400">No CAs available. Create a CA first.</p>}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Password {form.store_type === 'JKS' && <span className="text-gray-400">(min 12 chars)</span>}
            </label>
            <input type="password" value={form.password}
              onChange={e => setForm(prev => ({ ...prev, password: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="Enter store password" />
            {form.password && !passwordValid && (
              <p className="text-xs text-red-500 mt-1">Minimum {minPassword} characters required</p>
            )}
          </div>

          <button
            onClick={() => mutation.mutate(form)}
            disabled={!form.name || form.ca_ids.length === 0 || !passwordValid || mutation.isPending}
            className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'Building...' : 'Build TrustStore'}
          </button>

          {mutation.isError && (
            <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Build failed'}</p>
          )}
        </div>

        {/* Spring Boot config / download */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="font-semibold text-gray-900 mb-4">Spring Boot Configuration</h3>
          {showSpringConfig ? (
            <div className="space-y-3">
              <p className="text-green-600 text-sm font-medium">✅ TrustStore built successfully</p>
              <button
                onClick={() => authenticatedDownload(`/api/v1/truststore/${showSpringConfig}`, `truststore.${form.store_type === 'JKS' ? 'jks' : 'p12'}`)}
                className="inline-block px-4 py-2 bg-green-600 text-white text-sm rounded-md hover:bg-green-700"
              >
                Download TrustStore
              </button>
              <div className="mt-4 p-3 bg-gray-900 rounded-md">
                <p className="text-xs text-gray-400 mb-2">JVM Properties:</p>
                <code className="text-xs text-green-400 whitespace-pre-wrap">
{`-Djavax.net.ssl.trustStore=/path/to/truststore.${form.store_type === 'JKS' ? 'jks' : 'p12'}
-Djavax.net.ssl.trustStorePassword=<password>
-Djavax.net.ssl.trustStoreType=${form.store_type}`}
                </code>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">Build a truststore to see configuration snippets.</p>
          )}
        </div>
      </div>
    </div>
  )
}
