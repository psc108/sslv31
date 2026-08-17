interface Props {
  form: any
  hosts: { role: string; fqdn: string; ip: string }[]
  generating: boolean
  error: string | null
  onGenerate: () => void
}

const CONNECTIONS = [
  { from: 'Backend', to: 'MySQL', type: 'mTLS client' },
  { from: 'Backend', to: 'RabbitMQ', type: 'mTLS client' },
  { from: 'Backend', to: 'Keystone', type: 'TLS client' },
  { from: 'Frontend', to: 'Backend', type: 'mTLS client' },
  { from: 'Frontend', to: 'RabbitMQ', type: 'mTLS client' },
]

export default function WizardStep4({ form, hosts, generating, error, onGenerate }: Props) {
  const certCount = 7 // 5 server + 2 client
  const keystoreCount = 12 // mysql(1s+1t) + rabbitmq(1s+1t) + keystone(1s+1t) + backend(2s+1c+1t) + frontend(2s+1c+1t) = 12 stores

  return (
    <div className="space-y-5">
      <h3 className="font-semibold text-gray-900">Review & Generate</h3>

      {/* Summary */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">Environment:</span>
          <span className="ml-2 font-medium">{form.env_name || '—'}</span>
        </div>
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">Key:</span>
          <span className="ml-2 font-medium">{form.key_algo} {form.key_size}</span>
        </div>
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">CA Validity:</span>
          <span className="ml-2 font-medium">{form.ca_validity_days} days</span>
        </div>
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">Cert Validity:</span>
          <span className="ml-2 font-medium">{form.cert_validity_days} days</span>
        </div>
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">Cipher Profile:</span>
          <span className="ml-2 font-medium capitalize">{form.cipher_profile}</span>
        </div>
        <div className="p-3 bg-gray-50 rounded-md">
          <span className="text-gray-500">Base Path:</span>
          <span className="ml-2 font-medium font-mono text-xs">{form.base_path}</span>
        </div>
      </div>

      {/* Hosts */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">Hosts ({hosts.filter(h => h.fqdn).length}/5)</h4>
        <div className="border border-gray-200 rounded-md overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Role</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">FQDN</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {hosts.map(h => (
                <tr key={h.role}>
                  <td className="px-3 py-2 font-medium capitalize">{h.role}</td>
                  <td className="px-3 py-2 font-mono text-xs">{h.fqdn || <span className="text-red-400">missing</span>}</td>
                  <td className="px-3 py-2 font-mono text-xs">{h.ip || <span className="text-red-400">missing</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* What will be generated */}
      <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
        <h4 className="text-sm font-medium text-blue-800 mb-1">Bundle Contents</h4>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs text-blue-700">
          <div>📜 {certCount} certificates</div>
          <div>🔐 {keystoreCount} keystores/truststores</div>
          <div>🏛️ 1 dedicated CA</div>
          {form.include_snippets && <div>📄 5 config snippets</div>}
          {form.include_scripts && <div>📜 2 deploy scripts</div>}
          {form.include_readmes && <div>📖 6 READMEs</div>}
        </div>
      </div>

      {/* Connection Matrix */}
      <div>
        <h4 className="text-sm font-medium text-gray-700 mb-2">mTLS Connection Matrix</h4>
        <div className="border border-gray-200 rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">From</th>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">To</th>
                <th className="px-3 py-1.5 text-left font-medium text-gray-500">Connection</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {CONNECTIONS.map((c, i) => (
                <tr key={i}>
                  <td className="px-3 py-1.5">{c.from}</td>
                  <td className="px-3 py-1.5">{c.to}</td>
                  <td className="px-3 py-1.5"><span className="bg-green-100 text-green-700 px-1.5 py-0.5 rounded">{c.type}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">
          ❌ {error}
        </div>
      )}

      {/* Generate Button */}
      <button type="button" onClick={onGenerate} disabled={generating}
        className="w-full py-3 bg-green-600 text-white font-medium rounded-md hover:bg-green-700 disabled:opacity-50 transition">
        {generating ? (
          <span className="flex items-center justify-center gap-2">
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            Generating bundle...
          </span>
        ) : '🚀 Generate & Download ZIP'}
      </button>
    </div>
  )
}
