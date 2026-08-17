import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { formatDate, daysUntil, parseSubject, parseSAN, authenticatedDownload } from '@/lib/utils'
import type { CertListItem, PaginatedResponse } from '@/lib/types'

function statusBadge(status: string, expiresAt: string) {
  const days = daysUntil(expiresAt)
  if (status === 'revoked') return <span className="px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800">❌ Revoked</span>
  if (days <= 0) return <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">⏰ Expired</span>
  if (days <= 30) return <span className="px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">⚠️ {days}d</span>
  return <span className="px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">✅ Valid</span>
}

export default function CertificateList() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [profileFilter, setProfileFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')

  const { data, isLoading } = useQuery<PaginatedResponse<CertListItem>>({
    queryKey: ['certificates', page, search, profileFilter, statusFilter, tagFilter],
    queryFn: async () => {
      const params = new URLSearchParams({ page: String(page), page_size: '25' })
      if (search) params.set('search', search)
      if (profileFilter) params.set('profile', profileFilter)
      if (statusFilter) params.set('status', statusFilter)
      if (tagFilter) params.set('tag', tagFilter)
      return (await api.get(`/cert?${params}`)).data
    },
  })

  const revokeMutation = useMutation({
    mutationFn: (serial: string) => api.delete(`/cert/${serial}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['certificates'] }),
  })

  const certs = data?.items || []
  const total = data?.total || 0
  const totalPages = Math.ceil(total / 25)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Certificates</h2>
          <p className="text-sm text-gray-500 mt-1">{total} certificate{total !== 1 ? 's' : ''} issued</p>
        </div>
        <button
          onClick={() => navigate('/certificates/new')}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700"
        >
          + Issue Certificate
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <input
          type="text"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(1) }}
          placeholder="Search by CN or SAN..."
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
        />
        <select value={profileFilter} onChange={e => { setProfileFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">All Profiles</option>
          <option value="server">Server</option>
          <option value="client">Client</option>
          <option value="code_sign">Code Signing</option>
          <option value="email">Email</option>
          <option value="custom">Custom</option>
        </select>
        <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1) }}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm">
          <option value="">All Status</option>
          <option value="valid">Valid</option>
          <option value="revoked">Revoked</option>
          <option value="expired">Expired</option>
        </select>
        <input
          type="text"
          value={tagFilter}
          onChange={e => { setTagFilter(e.target.value); setPage(1) }}
          placeholder="Filter by tag..."
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-36"
        />
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">CN</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Profile</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Key</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Issued</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Expires</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Tags</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>
            )}
            {!isLoading && certs.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-400">No certificates found</td></tr>
            )}
            {certs.map(cert => {
              const subject = parseSubject(cert.subject_json)
              return (
                <tr key={cert.id} className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/certificates/${cert.serial}`)}>
                  <td className="px-4 py-3 font-medium text-gray-900">{subject.cn}</td>
                  <td className="px-4 py-3 text-gray-600 capitalize">{cert.profile.replace('_', ' ')}</td>
                  <td className="px-4 py-3 text-gray-600">{cert.key_algo} {cert.key_size}</td>
                  <td className="px-4 py-3 text-gray-600">{formatDate(cert.created_at)}</td>
                  <td className="px-4 py-3 text-gray-600">{formatDate(cert.expires_at)}</td>
                  <td className="px-4 py-3">{statusBadge(cert.status, cert.expires_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {cert.tags?.map(tag => (
                        <span key={tag}
                          onClick={e => { e.stopPropagation(); setTagFilter(tag); setPage(1) }}
                          className="px-1.5 py-0.5 bg-gray-100 text-gray-700 rounded text-[10px] font-medium cursor-pointer hover:bg-blue-100 hover:text-blue-800">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => authenticatedDownload(`/api/v1/export/${cert.serial}/bundle`, `${parseSubject(cert.subject_json).cn || cert.serial}-bundle.zip`)}
                        className="text-blue-600 hover:text-blue-800 text-xs font-medium">
                        Download
                      </button>
                      {cert.status === 'valid' && (
                        <button
                          onClick={() => {
                            if (confirm(`Revoke certificate ${subject.cn}?`)) {
                              revokeMutation.mutate(cert.serial)
                            }
                          }}
                          className="text-red-600 hover:text-red-800 text-xs font-medium"
                        >
                          Revoke
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-500">
            Page {page} of {totalPages} ({total} total)
          </p>
          <div className="flex gap-2">
            <button onClick={() => setPage(p => p - 1)} disabled={page <= 1}
              className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-30">
              ← Prev
            </button>
            <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages}
              className="px-3 py-1 border border-gray-300 rounded text-sm disabled:opacity-30">
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
