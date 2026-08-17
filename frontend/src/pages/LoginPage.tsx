import { useState, useEffect } from 'react'
import { useAuth } from '@/lib/auth'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { APP_NAME, APP_VERSION } from '@/lib/version'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [mode, setMode] = useState<'login' | 'apikey'>('login')
  const [apiKey, setApiKey] = useState(localStorage.getItem('api_key') || '')
  const [ldapEnabled, setLdapEnabled] = useState(false)

  useEffect(() => {
    api.get('/auth/auth-info').then(res => {
      if (res.data?.ldap_enabled) setLdapEnabled(true)
    }).catch(() => {})
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const handleApiKey = (e: React.FormEvent) => {
    e.preventDefault()
    if (apiKey.length < 16) {
      setError('API key must be at least 16 characters')
      return
    }
    localStorage.setItem('api_key', apiKey)
    navigate('/')
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm">
        <div className="bg-white rounded-lg border border-gray-200 p-6 shadow-sm">
          <div className="flex items-baseline gap-2 mb-1">
            <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{APP_NAME}</h1>
            <span className="text-xs font-semibold text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
              v{APP_VERSION}
            </span>
          </div>
          <p className="text-sm text-gray-500 mb-6">Sign in to continue</p>

          {/* Mode tabs */}
          <div className="flex border-b border-gray-200 mb-4">
            <button
              onClick={() => { setMode('login'); setError('') }}
              className={`px-3 py-2 text-sm font-medium ${mode === 'login' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
            >
              User Login
            </button>
            <button
              onClick={() => { setMode('apikey'); setError('') }}
              className={`px-3 py-2 text-sm font-medium ${mode === 'apikey' ? 'border-b-2 border-blue-600 text-blue-600' : 'text-gray-500'}`}
            >
              API Key
            </button>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error}
            </div>
          )}

          {mode === 'login' ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text" value={username} onChange={e => setUsername(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  autoFocus required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  required
                />
              </div>
              <button
                type="submit" disabled={loading}
                className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? 'Signing in...' : 'Sign In'}
              </button>
              <p className="text-xs text-gray-400 text-center">
                {ldapEnabled ? 'Supports local & LDAP accounts' : 'Default: admin / admin'}
              </p>
            </form>
          ) : (
            <form onSubmit={handleApiKey} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
                <input
                  type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                  placeholder="Paste API key from backend/.env"
                  required
                />
              </div>
              <button
                type="submit"
                className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
              >
                Connect
              </button>
              <p className="text-xs text-gray-400 text-center">Legacy API key auth (admin access)</p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
