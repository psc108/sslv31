import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { daysUntil, parseSubject } from '@/lib/utils'
import type { CAListItem, CertListItem, PaginatedResponse } from '@/lib/types'

export default function Dashboard() {
  const navigate = useNavigate()

  const { data: cas = [] } = useQuery<CAListItem[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  const { data: certData } = useQuery<PaginatedResponse<CertListItem>>({
    queryKey: ['certificates', 1, '', '', ''],
    queryFn: async () => (await api.get('/cert?page=1&page_size=200')).data,
  })

  const certs = certData?.items || []
  const validCerts = certs.filter(c => c.status === 'valid')
  const expiringCerts = validCerts.filter(c => daysUntil(c.expires_at) <= 30 && daysUntil(c.expires_at) > 0)
  const criticalCerts = validCerts.filter(c => daysUntil(c.expires_at) <= 7 && daysUntil(c.expires_at) > 0)
  const expiredCerts = certs.filter(c => c.status === 'expired' || (c.status === 'valid' && daysUntil(c.expires_at) <= 0))

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">Dashboard</h2>

      {/* Stats grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Certificate Authorities" value={cas.length} color="blue" onClick={() => navigate('/ca')} />
        <StatCard label="Active Certificates" value={validCerts.length} color="green" onClick={() => navigate('/certificates')} />
        <StatCard label="Expiring (30d)" value={expiringCerts.length} color={expiringCerts.length > 0 ? 'amber' : 'green'} onClick={() => navigate('/certificates')} />
        <StatCard label="Expired / Revoked" value={expiredCerts.length + certs.filter(c => c.status === 'revoked').length} color={expiredCerts.length > 0 ? 'red' : 'gray'} />
      </div>

      {/* Expiry warnings */}
      {(expiringCerts.length > 0 || criticalCerts.length > 0) && (
        <div className="mb-8">
          <h3 className="text-lg font-semibold text-gray-900 mb-3">⚠️ Certificates Expiring Soon</h3>
          <div className="bg-white rounded-lg border border-amber-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-amber-50 border-b border-amber-200">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">CN</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Days Left</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Profile</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Serial</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {[...criticalCerts, ...expiringCerts.filter(c => daysUntil(c.expires_at) > 7)]
                  .sort((a, b) => daysUntil(a.expires_at) - daysUntil(b.expires_at))
                  .map(cert => {
                    const days = daysUntil(cert.expires_at)
                    const subject = parseSubject(cert.subject_json)
                    return (
                      <tr key={cert.id} className="hover:bg-amber-50">
                        <td className="px-4 py-2 font-medium">{subject.cn}</td>
                        <td className="px-4 py-2">
                          <span className={`font-bold ${days <= 7 ? 'text-red-600' : 'text-amber-600'}`}>
                            {days} days
                          </span>
                        </td>
                        <td className="px-4 py-2 text-gray-600 capitalize">{cert.profile}</td>
                        <td className="px-4 py-2 font-mono text-xs text-gray-500">{cert.serial.slice(0, 16)}...</td>
                      </tr>
                    )
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Quick actions */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <QuickAction icon="📜" label="Issue Certificate" desc="Create a new signed certificate" onClick={() => navigate('/certificates/new')} />
        <QuickAction icon="🏛️" label="Create CA" desc="Set up a new Certificate Authority" onClick={() => navigate('/ca')} />
        <QuickAction icon="📋" label="Generate CSR" desc="Create a CSR for an external CA" onClick={() => navigate('/csr')} />
        <QuickAction icon="🔐" label="Build TrustStore" desc="Generate JKS/PKCS#12 for Java" onClick={() => navigate('/truststores')} />
      </div>
    </div>
  )
}

function StatCard({ label, value, color, onClick }: { label: string; value: number; color: string; onClick?: () => void }) {
  const colorClasses: Record<string, string> = {
    blue: 'bg-blue-50 border-blue-200',
    green: 'bg-green-50 border-green-200',
    amber: 'bg-amber-50 border-amber-200',
    red: 'bg-red-50 border-red-200',
    gray: 'bg-gray-50 border-gray-200',
  }
  return (
    <div onClick={onClick}
      className={`p-4 rounded-lg border ${colorClasses[color]} cursor-pointer hover:shadow-sm transition`}>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-sm text-gray-600 mt-1">{label}</p>
    </div>
  )
}

function QuickAction({ icon, label, desc, onClick }: { icon: string; label: string; desc: string; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className="flex items-start gap-3 p-4 bg-white rounded-lg border border-gray-200 hover:border-gray-300 hover:shadow-sm transition text-left">
      <span className="text-2xl">{icon}</span>
      <div>
        <p className="font-medium text-sm text-gray-900">{label}</p>
        <p className="text-xs text-gray-500">{desc}</p>
      </div>
    </button>
  )
}
