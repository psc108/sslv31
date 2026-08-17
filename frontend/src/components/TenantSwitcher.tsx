import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface Tenant {
  id: string
  name: string
  slug: string
}

export default function TenantSwitcher() {
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [activeTenant, setActiveTenant] = useState<string>(
    localStorage.getItem('active_tenant') || 'default'
  )

  useEffect(() => {
    api.get('/tenants').then(res => {
      setTenants(res.data)
    }).catch(() => {})
  }, [])

  const handleChange = (slug: string) => {
    setActiveTenant(slug)
    localStorage.setItem('active_tenant', slug)
    // Reload to apply tenant context
    window.location.reload()
  }

  if (tenants.length <= 1) return null

  return (
    <div className="px-3 py-2 border-b border-gray-200">
      <label className="text-xs text-gray-500 block mb-1">Tenant</label>
      <select
        value={activeTenant}
        onChange={(e) => handleChange(e.target.value)}
        className="w-full text-sm border border-gray-300 rounded px-2 py-1 bg-white"
      >
        {tenants.map(t => (
          <option key={t.id} value={t.slug}>{t.name}</option>
        ))}
      </select>
    </div>
  )
}
