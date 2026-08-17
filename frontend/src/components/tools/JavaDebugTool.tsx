import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'
import CopyButton from '@/components/CopyButton'

export function JavaDebugTool() {
  const [service, setService] = useState('generic')
  const [hostname, setHostname] = useState('localhost')
  const [port, setPort] = useState('443')
  const [truststorePath, setTruststorePath] = useState('/opt/app/ssl/truststore.p12')
  const [truststorePassword, setTruststorePassword] = useState('changeit')
  const [issueType, setIssueType] = useState('connection')
  const [javaVersion, setJavaVersion] = useState('17')
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/java-debug-command', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleGenerate = () => {
    const fd = new FormData()
    fd.append('service', service)
    fd.append('hostname', hostname)
    fd.append('port', port)
    fd.append('truststore_path', truststorePath)
    fd.append('truststore_password', truststorePassword)
    fd.append('issue_type', issueType)
    fd.append('java_version', javaVersion)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Java TLS Debug Command Generator</h3>
        <p className="text-sm text-gray-500">Generate the exact JVM flags and commands for debugging Java SSL/TLS issues.</p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Service</label>
            <select value={service} onChange={e => setService(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="generic">Generic HTTPS</option>
              <option value="mysql">MySQL</option>
              <option value="rabbitmq">RabbitMQ</option>
              <option value="spring-boot">Spring Boot</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Issue Type</label>
            <select value={issueType} onChange={e => setIssueType(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="connection">Connection failure</option>
              <option value="trust">Trust / PKIX error</option>
              <option value="hostname">Hostname mismatch</option>
              <option value="client_cert">Client cert (mTLS)</option>
              <option value="session">Session issues</option>
              <option value="full">Full debug (verbose)</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Hostname</label>
            <input type="text" value={hostname} onChange={e => setHostname(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
            <input type="text" value={port} onChange={e => setPort(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">TrustStore Path</label>
            <input type="text" value={truststorePath} onChange={e => setTruststorePath(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Java Version</label>
            <select value={javaVersion} onChange={e => setJavaVersion(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="8">Java 8</option>
              <option value="11">Java 11</option>
              <option value="17">Java 17</option>
              <option value="21">Java 21</option>
            </select>
          </div>
        </div>

        <button onClick={handleGenerate} disabled={mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          Generate Commands
        </button>
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-gray-700">Java Command</h4>
              <CopyButton text={result.full_command} label="Copy" />
            </div>
            <pre className="text-xs font-mono bg-gray-900 text-green-400 p-3 rounded overflow-x-auto whitespace-pre-wrap">{result.full_command}</pre>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-gray-700">OpenSSL Equivalent</h4>
              <CopyButton text={result.openssl_equivalent} label="Copy" />
            </div>
            <pre className="text-xs font-mono bg-gray-900 text-blue-400 p-3 rounded overflow-x-auto">{result.openssl_equivalent}</pre>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-semibold text-gray-700">Verify TrustStore</h4>
              <CopyButton text={result.keytool_verify} label="Copy" />
            </div>
            <pre className="text-xs font-mono bg-gray-900 text-purple-400 p-3 rounded overflow-x-auto">{result.keytool_verify}</pre>
          </div>
          {result.service_note && <p className="text-sm text-blue-700 bg-blue-50 p-3 rounded">{result.service_note}</p>}
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2">What to look for in output:</h4>
            <ul className="text-xs text-gray-600 space-y-1">
              {result.look_for.map((l: string, i: number) => <li key={i} className="font-mono">{l}</li>)}
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-700 mb-2">Tips:</h4>
            <ul className="text-xs text-gray-600 space-y-1 list-disc list-inside">
              {result.tips.map((t: string, i: number) => <li key={i}>{t}</li>)}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
