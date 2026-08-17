import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

export function ConnectionTestTool() {
  const [hostname, setHostname] = useState('')
  const [port, setPort] = useState('443')
  const [trustFile, setTrustFile] = useState<File | null>(null)
  const [clientCert, setClientCert] = useState<File | null>(null)
  const [clientKey, setClientKey] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/connection-test', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleTest = () => {
    const fd = new FormData()
    fd.append('hostname', hostname)
    fd.append('port', port)
    if (trustFile) fd.append('truststore_file', trustFile)
    if (clientCert) fd.append('client_cert_file', clientCert)
    if (clientKey) fd.append('client_key_file', clientKey)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Full TLS Connection Tester</h3>
        <p className="text-sm text-gray-500">Simulate a complete TLS handshake with custom trust and optional client cert. Reports exactly where it fails.</p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hostname *</label>
            <input type="text" value={hostname} onChange={e => setHostname(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="api.example.com" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
            <input type="text" value={port} onChange={e => setPort(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Custom CA / TrustStore (PEM — optional)</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {trustFile ? trustFile.name : 'Choose CA file...'}
            <input type="file" className="hidden" accept=".pem,.crt,.cer" onChange={e => setTrustFile(e.target.files?.[0] || null)} />
          </label>
          <p className="text-xs text-gray-400 mt-1">If not provided, system default trust is used</p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Client Cert (mTLS — optional)</label>
            <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
              {clientCert ? clientCert.name : 'Choose client cert...'}
              <input type="file" className="hidden" accept=".pem,.crt" onChange={e => setClientCert(e.target.files?.[0] || null)} />
            </label>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Client Key (mTLS — optional)</label>
            <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
              {clientKey ? clientKey.name : 'Choose client key...'}
              <input type="file" className="hidden" accept=".pem,.key" onChange={e => setClientKey(e.target.files?.[0] || null)} />
            </label>
          </div>
        </div>

        <button onClick={handleTest} disabled={!hostname || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Testing...' : 'Test Connection'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      </div>

      {result && (
        <div className={`bg-white rounded-lg border p-5 ${result.success ? 'border-green-200' : 'border-red-200'}`}>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-2xl">{result.success ? '✅' : '❌'}</span>
            <h3 className="font-semibold">{result.success ? 'Connection Successful' : 'Connection Failed'}</h3>
          </div>

          {result.success && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div><span className="text-gray-500">TLS Version:</span> <span className="font-medium">{result.tls_version_negotiated}</span></div>
                <div><span className="text-gray-500">Cipher:</span> <span className="font-mono text-xs">{result.cipher_suite}</span></div>
                <div><span className="text-gray-500">Trust Source:</span> <span className="font-medium">{result.trust_source}</span></div>
                <div><span className="text-gray-500">Client Cert:</span> {result.client_cert_used ? 'Yes' : 'No'}</div>
              </div>
              {result.server_certificate && (
                <div className="p-3 bg-gray-50 rounded space-y-1">
                  <p className="font-medium">Server Certificate:</p>
                  <p><span className="text-gray-500">CN:</span> {result.server_certificate.cn}</p>
                  <p><span className="text-gray-500">Issuer:</span> {result.server_certificate.issuer}</p>
                  <p><span className="text-gray-500">Expires:</span> {result.server_certificate.days_remaining}d remaining</p>
                  <p><span className="text-gray-500">Hostname Match:</span> <span className={result.server_certificate.hostname_match ? 'text-green-600' : 'text-red-600'}>{result.server_certificate.hostname_match ? 'Yes ✓' : 'No ✗'}</span></p>
                  {result.server_certificate.sans?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {result.server_certificate.sans.map((s: string, i: number) => (
                        <span key={i} className={`px-1.5 py-0.5 rounded text-xs ${s === hostname ? 'bg-green-100 text-green-800' : 'bg-gray-200 text-gray-700'}`}>{s}</span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {!result.success && (
            <div className="space-y-3 text-sm">
              <p className="text-red-700">{result.error}</p>
              {result.java_equivalent_error && (
                <div className="p-3 bg-red-50 rounded">
                  <p className="text-xs text-gray-500">Java equivalent error:</p>
                  <p className="font-mono text-xs text-red-800">{result.java_equivalent_error}</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
