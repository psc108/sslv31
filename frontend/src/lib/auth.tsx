import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import api from '@/lib/api'

interface AuthUser {
  user_id: string
  username: string
  role: string
  auth_method: string
}

interface AuthContextType {
  user: AuthUser | null
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
  isAdmin: boolean
  isOperator: boolean
  canWrite: boolean
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  login: async () => {},
  logout: () => {},
  isAuthenticated: false,
  isAdmin: false,
  isOperator: false,
  canWrite: false,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(localStorage.getItem('auth_token'))

  useEffect(() => {
    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`
      // Fetch current user
      api.get('/auth/me').then(res => {
        setUser(res.data)
      }).catch(() => {
        // Token expired or invalid
        logout()
      })
    }
  }, [token])

  const login = async (username: string, password: string) => {
    const res = await api.post('/auth/login', { username, password })
    const { token: newToken, user_id, username: uname, role } = res.data
    localStorage.setItem('auth_token', newToken)
    setToken(newToken)
    setUser({ user_id, username: uname, role, auth_method: 'jwt' })
    api.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
  }

  const logout = () => {
    localStorage.removeItem('auth_token')
    setToken(null)
    setUser(null)
    delete api.defaults.headers.common['Authorization']
  }

  const isAuthenticated = !!user || !!localStorage.getItem('api_key')
  const isAdmin = user?.role === 'admin' || !!localStorage.getItem('api_key')
  const isOperator = isAdmin || user?.role === 'operator'
  const canWrite = isAdmin || isOperator

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAuthenticated, isAdmin, isOperator, canWrite }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
