import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'

export default function RecentErrors() {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<any>({
    queryKey: ['recent-errors'],
    queryFn: async () => (await api.get('/diagnostics/recent-errors?limit=30')).data,
    refetchInterval: 15000,
  })

  const clearMutation = useMutation({
    mutationFn: () => api.post('/diagnostics/clear-errors'),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['recent-errors'] }),
  })

  const errors = data?.errors || []

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-700">Recent Errors & Warnings</h3>
          {errors.length > 0 && (
            <span className="px-1.5 py-0.5 bg-red-100 text-red-700 rounded-full text-xs font-bold">
              {data.total}
            </span>
          )}
        </div>
        {errors.length > 0 && (
          <button onClick={() => clearMutation.mutate()}
            className="text-xs text-gray-500 hover:text-red-600">
            Clear all
          </button>
        )}
      </div>

      {isLoading && <p className="text-xs text-gray-400">Loading...</p>}

      {!isLoading && errors.length === 0 && (
        <p className="text-xs text-gray-400 py-4 text-center">No errors or warnings recorded ✓</p>
      )}

      {errors.length > 0 && (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {errors.map((err: any, i: number) => (
            <div key={i} className={`p-2 rounded text-xs ${
              err.level === 'ERROR' ? 'bg-red-50 border-l-3 border-red-400' : 'bg-amber-50 border-l-3 border-amber-400'
            }`}>
              <div className="flex items-center justify-between">
                <span className={`font-bold ${err.level === 'ERROR' ? 'text-red-700' : 'text-amber-700'}`}>
                  {err.level}
                </span>
                <span className="text-gray-400">
                  {new Date(err.timestamp).toLocaleTimeString()}
                </span>
              </div>
              <p className="text-gray-700 mt-1">{err.message}</p>
              {err.source && (
                <p className="text-gray-400 font-mono mt-0.5">{err.source}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400 mt-2">
        Buffer: {data?.buffer_size || 0} / {data?.buffer_max || 200} entries. Auto-refreshes every 15s.
      </p>
    </div>
  )
}
