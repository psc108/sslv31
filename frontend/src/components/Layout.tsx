import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import TenantSwitcher from '@/components/TenantSwitcher'

type Mode = 'cert' | 'bm' | 'jar' | 'docs'

const certNavItems = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/ca', label: 'Certificate Authorities', icon: '🏛️' },
  { to: '/certificates', label: 'Certificates', icon: '📜' },
  { to: '/csr', label: 'CSR Manager', icon: '📝' },
  { to: '/truststores', label: 'Trust Stores', icon: '🔐' },
  { to: '/tools', label: 'Tools', icon: '🛠️' },
  { to: '/templates', label: 'Templates', icon: '📋' },
  { to: '/provisioning', label: 'Provisioning', icon: '🏗️' },
  { to: '/approvals', label: 'Approvals', icon: '✅' },
  { to: '/users', label: 'Users & Keys', icon: '👥', adminOnly: true },
  { to: '/tenants', label: 'Tenants', icon: '🏢', adminOnly: true },
  { to: '/ct-log', label: 'CT Log', icon: '🌲' },
  { to: '/cross-certs', label: 'Cross-Certification', icon: '🔗' },
  { to: '/kubernetes', label: 'Kubernetes', icon: '☸️' },
  { to: '/compliance', label: 'Compliance', icon: '🛡️' },
  { to: '/key-escrow', label: 'Key Escrow', icon: '🔑', adminOnly: true },
  { to: '/sdk', label: 'API & SDK', icon: '📦' },
  { to: '/scep', label: 'SCEP', icon: '📱' },
  { to: '/notifications', label: 'Notifications', icon: '📧' },
  { to: '/audit', label: 'Audit Log', icon: '📋' },
  { to: '/reports', label: 'Reports', icon: '📊' },
  { to: '/help', label: 'Help', icon: '❓' },
  { to: '/diagnostics', label: 'Diagnostics', icon: '🩺' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
]

const bmNavItems = [
  { to: '/bm', label: 'Dashboard', icon: '📊' },
  { to: '/inventory', label: 'Inventory', icon: '🖥️' },
  { to: '/bm-catalogue', label: 'Catalogue', icon: '📦' },
  { to: '/bm-builder', label: 'Template Builder', icon: '🏗️' },
  { to: '/bm-templates', label: 'Templates', icon: '📐' },
  { to: '/environments', label: 'Environments', icon: '🌍' },
  { to: '/jobs', label: 'Jobs', icon: '⚡' },
  { to: '/bm-certs', label: 'Cert Lifecycle', icon: '🔐' },
  { to: '/bm-secrets', label: 'Secrets', icon: '🗄️' },
  { to: '/bm-pki-posture', label: 'PKI Posture', icon: '🛡️' },
  { to: '/bm-health', label: 'Health', icon: '📊' },
  { to: '/bm-editor', label: 'Editor', icon: '✏️' },
  { to: '/bm-pkg-cache', label: 'Pkg Cache', icon: '📥' },
  { to: '/bm-help', label: 'Help', icon: '❓' },
]

const jarNavItems = [
  { to: '/jar-analyser', label: 'JAR Analyser', icon: '🔬' },
  { to: '/jar-help', label: 'Help', icon: '❓' },
]

const docsNavItems = [
  { to: '/docs', label: 'Libraries', icon: '📚' },
  { to: '/docs-help', label: 'Help', icon: '❓' },
]

const bmRoutes = ['/bm', '/inventory', '/bm-templates', '/environments', '/jobs', '/bm-help', '/bm-catalogue', '/bm-builder', '/bm-certs', '/bm-secrets', '/bm-pki-posture', '/bm-health', '/bm-editor', '/bm-pkg-cache']
const jarRoutes = ['/jar-analyser', '/jar-help']
const docsRoutes = ['/docs', '/docs-help']

export default function Layout() {
  const { user, logout, isAdmin } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState<Mode>(() => {
    const saved = localStorage.getItem('nav-mode') as Mode | null
    if (saved) return saved
    if (jarRoutes.some(r => location.pathname.startsWith(r))) return 'jar'
    if (docsRoutes.some(r => location.pathname.startsWith(r))) return 'docs'
    return bmRoutes.some(r => location.pathname.startsWith(r)) ? 'bm' : 'cert'
  })

  // Auto-switch mode based on current route
  useEffect(() => {
    const isBmRoute = bmRoutes.some(r => location.pathname === r || location.pathname.startsWith(r + '/'))
    const isJarRoute = jarRoutes.some(r => location.pathname === r || location.pathname.startsWith(r + '/'))
    const isDocsRoute = docsRoutes.some(r => location.pathname === r || location.pathname.startsWith(r + '/'))
    if (isJarRoute && mode !== 'jar') {
      setMode('jar')
      localStorage.setItem('nav-mode', 'jar')
    } else if (isDocsRoute && mode !== 'docs') {
      setMode('docs')
      localStorage.setItem('nav-mode', 'docs')
    } else if (isBmRoute && mode !== 'bm') {
      setMode('bm')
      localStorage.setItem('nav-mode', 'bm')
    } else if (!isBmRoute && !isJarRoute && !isDocsRoute && mode !== 'cert' && location.pathname !== '/login') {
      setMode('cert')
      localStorage.setItem('nav-mode', 'cert')
    }
  }, [location.pathname])

  const switchMode = (newMode: Mode) => {
    setMode(newMode)
    localStorage.setItem('nav-mode', newMode)
    navigate(newMode === 'cert' ? '/' : newMode === 'bm' ? '/bm' : newMode === 'jar' ? '/jar-analyser' : '/docs')
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navItems = mode === 'cert' ? certNavItems : mode === 'bm' ? bmNavItems : mode === 'jar' ? jarNavItems : docsNavItems
  const visibleItems = navItems.filter(item => !('adminOnly' in item && item.adminOnly) || isAdmin)

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">
            {mode === 'cert' ? 'SSL Cert Manager' : mode === 'bm' ? 'Build Manager' : mode === 'jar' ? 'JAR Analyser' : 'Docs'}
          </h1>
          <p className="text-xs text-gray-500 mt-1">
            {mode === 'cert' ? 'Self-Signed CA & Trust Tool' : mode === 'bm' ? 'Infrastructure Deployment' : mode === 'jar' ? 'Bytecode & Dependency Analysis' : 'Libraries & Documents'}
          </p>
        </div>

        {/* Mode switcher */}
        <div className="px-3 pt-3">
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            <button
              onClick={() => switchMode('cert')}
              className={cn(
                'flex-1 text-xs font-medium py-1.5 rounded-md transition-colors',
                mode === 'cert'
                  ? 'bg-white text-blue-700 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              🔒 Certificates
            </button>
            <button
              onClick={() => switchMode('bm')}
              className={cn(
                'flex-1 text-xs font-medium py-1.5 rounded-md transition-colors',
                mode === 'bm'
                  ? 'bg-white text-blue-700 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              🚀 Build Mgr
            </button>
            <button
              onClick={() => switchMode('jar')}
              className={cn(
                'flex-1 text-xs font-medium py-1.5 rounded-md transition-colors',
                mode === 'jar'
                  ? 'bg-white text-blue-700 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              🔬 JAR
            </button>
            <button
              onClick={() => switchMode('docs')}
              className={cn(
                'flex-1 text-xs font-medium py-1.5 rounded-md transition-colors',
                mode === 'docs'
                  ? 'bg-white text-blue-700 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              📚 Docs
            </button>
          </div>
        </div>

        {mode === 'cert' && <TenantSwitcher />}


        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {visibleItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/' || item.to === '/bm'}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-gray-700 hover:bg-gray-100'
                )
              }
            >
              <span>{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* About link — a global utility link (open-source attributions),
            not mode-specific, so it lives outside the per-mode navItems
            arrays rather than being duplicated into all four. */}
        <div className="px-3 pt-2">
          <NavLink to="/about"
            className={({ isActive }) =>
              cn('flex items-center gap-2 px-3 py-1.5 rounded-md text-xs',
                isActive ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700')
            }>
            <span>ℹ️</span> About
          </NavLink>
        </div>

        {/* User info footer */}
        <div className="p-3 border-t border-gray-200">
          {user ? (
            <div className="flex items-center justify-between">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{user.username}</p>
                <p className="text-xs text-gray-500">{user.role}</p>
              </div>
              <button onClick={handleLogout}
                className="text-xs text-gray-500 hover:text-red-600 px-2 py-1 rounded">
                Logout
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500">API Key mode</p>
              <button onClick={handleLogout}
                className="text-xs text-gray-500 hover:text-red-600 px-2 py-1 rounded">
                Switch
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
