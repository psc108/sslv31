import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

interface Tenant {
  id: string
  name: string
  slug: string
  description: string
  created_at: string
  member_count: number
}

interface Member {
  user_id: string
  username: string
  tenant_role: string | null
  global_role: string
}

export default function TenantsPage() {
  const { isAdmin } = useAuth()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [selectedTenant, setSelectedTenant] = useState<string | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', slug: '', description: '' })
  const [error, setError] = useState('')

  useEffect(() => { loadTenants() }, [])

  const loadTenants = () => {
    api.get('/tenants').then(r => setTenants(r.data)).catch(() => {})
  }

  const loadMembers = (tenantId: string) => {
    setSelectedTenant(tenantId)
    api.get(`/tenants/${tenantId}/members`).then(r => setMembers(r.data)).catch(() => {})
  }

  const createTenant = async () => {
    setError('')
    try {
      await api.post('/tenants', form)
      setShowCreate(false)
      setForm({ name: '', slug: '', description: '' })
      loadTenants()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to create tenant')
    }
  }

  const deleteTenant = async (id: string) => {
    if (!confirm('Delete this tenant? All resources must be moved first.')) return
    try {
      await api.delete(`/tenants/${id}`)
      loadTenants()
      if (selectedTenant === id) setSelectedTenant(null)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to delete')
    }
  }

  if (!isAdmin) {
    return <div className="p-6 text-gray-500">Global admin access required.</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Tenant Management</h1>
        <button onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700">
          Create Tenant
        </button>
      </div>

      {showCreate && (
        <div className="bg-white border rounded-lg p-4 space-y-3">
          <h3 className="font-medium">New Tenant</h3>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <div className="grid grid-cols-3 gap-3">
            <input placeholder="Name" value={form.name}
              onChange={e => setForm({...form, name: e.target.value})}
              className="border rounded px-3 py-2 text-sm" />
            <input placeholder="Slug (lowercase, hyphens)" value={form.slug}
              onChange={e => setForm({...form, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '')})}
              className="border rounded px-3 py-2 text-sm" />
            <input placeholder="Description" value={form.description}
              onChange={e => setForm({...form, description: e.target.value})}
              className="border rounded px-3 py-2 text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={createTenant}
              className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm">Create</button>
            <button onClick={() => setShowCreate(false)}
              className="px-3 py-1.5 bg-gray-200 rounded text-sm">Cancel</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Tenant list */}
        <div className="bg-white border rounded-lg">
          <div className="p-4 border-b">
            <h2 className="font-medium">Tenants ({tenants.length})</h2>
          </div>
          <div className="divide-y">
            {tenants.map(t => (
              <div key={t.id} className={`p-3 flex items-center justify-between cursor-pointer hover:bg-gray-50 ${selectedTenant === t.id ? 'bg-blue-50' : ''}`}
                onClick={() => loadMembers(t.id)}>
                <div>
                  <p className="font-medium text-sm">{t.name}</p>
                  <p className="text-xs text-gray-500">{t.slug} · {t.member_count} members</p>
                </div>
                {t.slug !== 'default' && (
                  <button onClick={(e) => { e.stopPropagation(); deleteTenant(t.id) }}
                    className="text-xs text-red-500 hover:text-red-700">Delete</button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Members panel */}
        {selectedTenant && (
          <div className="bg-white border rounded-lg">
            <div className="p-4 border-b">
              <h2 className="font-medium">Members</h2>
            </div>
            <div className="divide-y">
              {members.length === 0 && (
                <p className="p-3 text-sm text-gray-500">No members</p>
              )}
              {members.map(m => (
                <div key={m.user_id} className="p-3 flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">{m.username}</p>
                    <p className="text-xs text-gray-500">
                      {m.tenant_role || m.global_role}
                    </p>
                  </div>
                  <button onClick={() => {
                    api.delete(`/tenants/${selectedTenant}/members/${m.user_id}`).then(() => loadMembers(selectedTenant!))
                  }} className="text-xs text-red-500 hover:text-red-700">Remove</button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
