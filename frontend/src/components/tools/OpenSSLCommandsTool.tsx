import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import CopyButton from '@/components/CopyButton'

export function OpenSSLCommandsTool() {
  const [hostname, setHostname] = useState('')
  const [port, setPort] = useState('443')
  const [certCn, setCertCn] = useState('certificate')
  const [service, setService] = useState('generic')
  const [mtls, setMtls] = useState(false)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/openssl-commands', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleGenerate = () => {
    const fd = new FormData()
    fd.append('hostname', hostname)
    fd.append('port', port)
    fd.append('cert_cn', certCn)
    fd.append('service', service)
    fd.append('mtls', String(mtls))
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">OpenSSL Command Generator</h3>
        <p className="text-sm text-gray-500">Generate ready-to-use openssl commands for inspecting, verifying, and testing certificates.</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hostname</label>
            <input type="text" value={hostname} onChange={e => setHostname(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="api.example.com" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
            <input type="text" value={port} onChange={e => setPort(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Certificate CN (for filenames)</label>
            <input type="text" value={certCn} onChange={e => setCertCn(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="api.example.com" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Service</label>
            <select value={service} onChange={e => setService(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="generic">Generic</option>
              <option value="nginx">Nginx</option>
              <option value="mysql">MySQL</option>
              <option value="rabbitmq">RabbitMQ</option>
              <option value="java">Java</option>
              <option value="keystone">Keystone</option>
            </select>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={mtls} onChange={e => setMtls(e.target.checked)} />
          Include mTLS (client certificate) commands
        </label>
        <button onClick={handleGenerate} disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          Generate Commands
        </button>
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          {Object.entries(result.commands as Record<string, any>).map(([key, section]) => (
            <div key={key}>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">{(section as any).label}</h4>
              <div className="space-y-2">
                {(section as any).commands.map((cmd: any, i: number) => (
                  <div key={i} className="flex items-start gap-2">
                    <div className="flex-1">
                      <p className="text-xs text-gray-500">{cmd.desc}</p>
                      <pre className="text-xs font-mono bg-gray-900 text-green-400 p-2 rounded mt-1 overflow-x-auto">{cmd.cmd}</pre>
                    </div>
                    <CopyButton text={cmd.cmd} className="mt-4" />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
