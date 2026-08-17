import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

export default function ApprovalsPage() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState('pending')
  const [reviewNote, setReviewNote] = useState('')
  const [reviewingId, setReviewingId] = useState<string | null>(null)

  const { data: requests = [], isLoading } = useQuery({
    queryKey: ['approvals', filter],
    queryFn: async () => (await api.get(`/approvals?status_filter=${filter}`)).data,
  })

  const reviewMutation = useMutation({
    mutationFn: async ({ id, action, note }: { id: string; action: string; note: string }) =>
      (await api.post(`/approvals/${id}/review`, { action, note })).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      setReviewingId(null)
      setReviewNote('')
    },
  })

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">Approval Queue</h2>
        <p className="text-sm text-gray-500 mt-1">Certificate requests requiring admin review</p>
      </div>

      <div className="flex gap-2 mb-4">
        {['pending', 'approved', 'rejected', 'all'].map(s => (
          <button key={s} onClick={() => setFilter(s)}
            className={`px-3 py-1.5 text-sm rounded-md border ${
              filter === s ? 'bg-blue-50 border-blue-300 text-blue-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
            }`}>
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {isLoading && <p className="text-gray-400">Loading...</p>}

      {!isLoading && requests.length === 0 && (
        <div className="bg-gray-50 border rounded-lg p-8 text-center text-gray-500">
          No {filter === 'all' ? '' : filter} requests.
        </div>
      )}

      <div className="space-y-3">
        {requests.map((r: any) => (
          <div key={r.id} className="bg-white rounded-lg border p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{r.cn || 'Unknown'}</span>
                  <StatusBadge status={r.status} />
                  {r.template_name && (
                    <span className="px-2 py-0.5 rounded text-xs bg-purple-100 text-purple-700">{r.template_name}</span>
                  )}
                </div>
                <div className="text-xs text-gray-500 mt-1 space-x-3">
                  <span>Profile: {r.profile}</span>
                  <span>Key: {r.key_algo} {r.key_size || ''}</span>
                  <span>Validity: {r.validity_days} days</span>
                  <span>By: {r.requested_by}</span>
                  <span>{new Date(r.created_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })}</span>
                </div>
                {r.reviewed_by && (
                  <p className="text-xs text-gray-500 mt-1">
                    Reviewed by {r.reviewed_by}{r.review_note ? `: ${r.review_note}` : ''}
                  </p>
                )}
              </div>

              {r.status === 'pending' && isAdmin && (
                <div className="flex items-center gap-2">
                  {reviewingId === r.id ? (
                    <div className="flex items-center gap-2">
                      <input type="text" value={reviewNote} onChange={e => setReviewNote(e.target.value)}
                        placeholder="Note (optional)" className="border rounded px-2 py-1 text-sm w-40" />
                      <button onClick={() => reviewMutation.mutate({ id: r.id, action: 'approve', note: reviewNote })}
                        disabled={reviewMutation.isPending}
                        className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50">
                        Approve
                      </button>
                      <button onClick={() => reviewMutation.mutate({ id: r.id, action: 'reject', note: reviewNote })}
                        disabled={reviewMutation.isPending}
                        className="px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50">
                        Reject
                      </button>
                      <button onClick={() => setReviewingId(null)}
                        className="px-2 py-1 text-sm text-gray-500 hover:text-gray-700">✕</button>
                    </div>
                  ) : (
                    <button onClick={() => setReviewingId(r.id)}
                      className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
                      Review
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-100 text-amber-800',
    approved: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-800'}`}>
      {status}
    </span>
  )
}
