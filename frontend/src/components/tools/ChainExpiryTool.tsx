import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

export function ChainExpiryTool() {
  const [file, setFile] = useState<File | null>(null)
  const [pem, setPem] = useState('')
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/chain-expiry-check', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleCheck = () => {
    const fd = new FormData()
    if (file) fd.append('chain_file', file)
    else fd.append('chain_pem', pem)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
        <h3 className="font-semibold text-gray-900">Certificate Chain Expiry Check</h3>
        <p className="text-sm text-gray-500">Check every certificate in a chain for validity — catches expired intermediates.</p>
        <div className="flex items-center gap-3">
          <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
            {file ? file.name : 'Upload chain file...'}
            <input type="file" className="hidden" accept=".pem,.crt,.cer"
              onChange={e => { setFile(e.target.files?.[0] || null); setPem('') }} />
          </label>
          {file && <button onClick={() => setFile(null)} className="text-xs text-red-500">Clear</button>}
        </div>
        {!file && (
          <textarea value={pem} onChange={e => setPem(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono h-32"
            placeholder="Paste PEM chain..." />
        )}
        <button onClick={handleCheck} disabled={(!file && !pem.trim()) || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Checking...' : 'Check Chain Expiry'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      </div>
      {result && (
        <div className={`bg-white rounded-lg border p-5 ${result.overall === 'pass' ? 'border-green-200' : result.overall === 'warn' ? 'border-amber-200' : 'border-red-200'}`}>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xl">{result.overall === 'pass' ? '✅' : result.overall === 'warn' ? '⚠️' : '❌'}</span>
            <div>
              <h3 className="font-semibold">{result.total_certs} certificates in chain</h3>
              <p className="text-xs text-gray-500">Weakest: {result.weakest_link} ({result.weakest_days_remaining}d)</p>
            </div>
          </div>
          <div className="space-y-2">
            {result.certificates.map((c: any) => (
              <div key={c.position} className={`p-3 rounded text-sm flex justify-between ${
                c.status === 'valid' ? 'bg-green-50' : c.status === 'warning' ? 'bg-amber-50' : c.status === 'expired' ? 'bg-red-100' : 'bg-red-50'
              }`}>
                <div>
                  <span className="font-medium">{c.position}. {c.cn}</span>
                  <span className="text-xs text-gray-500 ml-2">({c.type})</span>
                </div>
                <span className={`font-bold ${c.days_remaining > 30 ? 'text-green-700' : c.days_remaining > 7 ? 'text-amber-700' : 'text-red-700'}`}>
                  {c.days_remaining > 0 ? `${c.days_remaining}d` : `EXPIRED`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
