import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

interface User {
  id: string
  username: string
  email: string
  role: string
  active: boolean
  created_at: string
  last_login: string | null
}

export default function UsersPage() {
  const queryClient = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [editUser, setEditUser] = useState<User | null>(null)

  const { data: users = [] } = useQuery<User[]>({
    queryKey: ['users'],
    queryFn: async () => (await api.get('/users')).data,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/users/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900">User Management</h2>
        <button
          onClick={() => { setEditUser(null); setShowForm(true) }}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
        >
          + Create User
        </button>
      </div>

      {showForm && (
        <UserForm
          user={editUser}
          onClose={() => { setShowForm(false); setEditUser(null) }}
          onSaved={() => { setShowForm(false); setEditUser(null); queryClient.invalidateQueries({ queryKey: ['users'] }) }}
        />
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Username</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Email</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Last Login</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users.map(u => (
              <tr key={u.id}>
                <td className="px-4 py-3 font-medium">{u.username}</td>
                <td className="px-4 py-3 text-gray-600">{u.email || '—'}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                    u.role === 'admin' ? 'bg-red-100 text-red-700' :
                    u.role === 'operator' ? 'bg-blue-100 text-blue-700' :
                    u.role === 'auditor' ? 'bg-amber-100 text-amber-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {u.role}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {u.active
                    ? <span className="text-green-600 text-xs font-medium">Active</span>
                    : <span className="text-red-600 text-xs font-medium">Disabled</span>
                  }
                </td>
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {u.last_login ? new Date(u.last_login).toLocaleString() : 'Never'}
                </td>
                <td className="px-4 py-3 space-x-2">
                  <button
                    onClick={() => { setEditUser(u); setShowForm(true) }}
                    className="text-blue-600 hover:text-blue-800 text-xs font-medium"
                  >Edit</button>
                  {u.username !== 'admin' && (
                    <button
                      onClick={() => { if (confirm(`Delete user ${u.username}?`)) deleteMutation.mutate(u.id) }}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >Delete</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* API Keys Section */}
      <APIKeysSection />
    </div>
  )
}

function UserForm({ user, onClose, onSaved }: { user: User | null; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState(user?.username || '')
  const [email, setEmail] = useState(user?.email || '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState(user?.role || 'readonly')
  const [active, setActive] = useState(user?.active ?? true)
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: async () => {
      if (user) {
        const body: any = { email, role, active }
        if (password) body.password = password
        return api.put(`/users/${user.id}`, body)
      } else {
        return api.post('/users', { username, email, password, role })
      }
    },
    onSuccess: () => onSaved(),
    onError: (err: any) => setError(err.response?.data?.detail || 'Failed'),
  })

  return (
    <div className="mb-6 bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-semibold text-gray-900 mb-4">{user ? 'Edit User' : 'Create User'}</h3>
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
          <input
            type="text" value={username} onChange={e => setUsername(e.target.value)}
            disabled={!!user}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm disabled:bg-gray-50"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
          <input
            type="email" value={email} onChange={e => setEmail(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Password {user && <span className="text-gray-400">(leave blank to keep)</span>}
          </label>
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            minLength={8}
            required={!user}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
          <select value={role} onChange={e => setRole(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="admin">Admin</option>
            <option value="operator">Operator</option>
            <option value="auditor">Auditor</option>
            <option value="readonly">Read Only</option>
          </select>
        </div>
        {user && (
          <div className="flex items-center gap-2">
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} id="active" />
            <label htmlFor="active" className="text-sm text-gray-700">Active</label>
          </div>
        )}
      </div>
      <div className="flex gap-3 mt-4">
        <button onClick={() => mutation.mutate()} disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Saving...' : user ? 'Update' : 'Create'}
        </button>
        <button onClick={onClose}
          className="px-4 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-200">
          Cancel
        </button>
      </div>
    </div>
  )
}

function APIKeysSection() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [newKey, setNewKey] = useState('')

  const { data: keys = [] } = useQuery<any[]>({
    queryKey: ['api-keys'],
    queryFn: async () => (await api.get('/api-keys')).data,
  })

  const revokeMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/api-keys/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['api-keys'] }),
  })

  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-gray-900">Scoped API Keys</h3>
        <button
          onClick={() => setShowCreate(true)}
          className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded-md text-xs font-medium hover:bg-gray-200"
        >
          + Create Key
        </button>
      </div>

      {newKey && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded">
          <p className="text-green-800 text-sm font-medium mb-1">New API key created — copy it now (shown only once):</p>
          <code className="text-xs bg-white px-2 py-1 rounded border block break-all">{newKey}</code>
          <button onClick={() => setNewKey('')} className="text-xs text-green-700 mt-2 underline">Dismiss</button>
        </div>
      )}

      {showCreate && <APIKeyForm onClose={() => setShowCreate(false)} onCreated={(key) => { setNewKey(key); setShowCreate(false); queryClient.invalidateQueries({ queryKey: ['api-keys'] }) }} />}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Prefix</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Role</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Expires</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Last Used</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {keys.map((k: any) => (
              <tr key={k.id}>
                <td className="px-4 py-3 font-medium">{k.name}</td>
                <td className="px-4 py-3 font-mono text-xs">{k.key_prefix}...</td>
                <td className="px-4 py-3">
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100">{k.role}</span>
                </td>
                <td className="px-4 py-3">
                  {k.active
                    ? <span className="text-green-600 text-xs">Active</span>
                    : <span className="text-red-600 text-xs">Revoked</span>
                  }
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">
                  {k.expires_at ? new Date(k.expires_at).toLocaleDateString() : 'Never'}
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">
                  {k.last_used ? new Date(k.last_used).toLocaleString() : 'Never'}
                </td>
                <td className="px-4 py-3">
                  {k.active && (
                    <button
                      onClick={() => { if (confirm(`Revoke key "${k.name}"?`)) revokeMutation.mutate(k.id) }}
                      className="text-red-600 hover:text-red-800 text-xs font-medium"
                    >Revoke</button>
                  )}
                </td>
              </tr>
            ))}
            {keys.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-6 text-center text-gray-400">No scoped API keys created yet</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function APIKeyForm({ onClose, onCreated }: { onClose: () => void; onCreated: (key: string) => void }) {
  const [name, setName] = useState('')
  const [role, setRole] = useState('operator')
  const [expiresDays, setExpiresDays] = useState<number | ''>('')
  const [error, setError] = useState('')

  const mutation = useMutation({
    mutationFn: async () => {
      const body: any = { name, role }
      if (expiresDays) body.expires_in_days = expiresDays
      return api.post('/api-keys', body)
    },
    onSuccess: (res) => onCreated(res.data.key),
    onError: (err: any) => setError(err.response?.data?.detail || 'Failed'),
  })

  return (
    <div className="mb-4 bg-white rounded-lg border border-gray-200 p-4">
      {error && <p className="text-red-600 text-sm mb-3">{error}</p>}
      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" required />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
          <select value={role} onChange={e => setRole(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="admin">Admin</option>
            <option value="operator">Operator</option>
            <option value="auditor">Auditor</option>
            <option value="readonly">Read Only</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Expires (days)</label>
          <input type="number" value={expiresDays} onChange={e => setExpiresDays(e.target.value ? Number(e.target.value) : '')}
            min={1} max={365} placeholder="Never"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>
      <div className="flex gap-3 mt-3">
        <button onClick={() => mutation.mutate()} disabled={mutation.isPending || !name}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          Create Key
        </button>
        <button onClick={onClose}
          className="px-4 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-200">
          Cancel
        </button>
      </div>
    </div>
  )
}
