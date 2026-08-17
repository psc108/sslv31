import { useState, useEffect } from 'react'
import api from '@/lib/api'

type Tab = 'overview' | 'python' | 'cli' | 'bash' | 'openapi'

export default function SDKPage() {
  const [tab, setTab] = useState<Tab>('overview')
  const [versionInfo, setVersionInfo] = useState<any>(null)
  const [changelog, setChangelog] = useState<any[]>([])
  const [pythonSdk, setPythonSdk] = useState<any>(null)
  const [cliTool, setCliTool] = useState<any>(null)
  const [bashExamples, setBashExamples] = useState<any>(null)
  const [openapiInfo, setOpenapiInfo] = useState<any>(null)

  useEffect(() => {
    api.get('/v2/version').then(r => setVersionInfo(r.data)).catch(() => {})
    api.get('/v2/changelog').then(r => setChangelog(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab === 'python' && !pythonSdk) {
      api.get('/v2/sdk/python').then(r => setPythonSdk(r.data)).catch(() => {})
    }
    if (tab === 'cli' && !cliTool) {
      api.get('/v2/sdk/cli').then(r => setCliTool(r.data)).catch(() => {})
    }
    if (tab === 'bash' && !bashExamples) {
      api.get('/v2/sdk/bash').then(r => setBashExamples(r.data)).catch(() => {})
    }
    if (tab === 'openapi' && !openapiInfo) {
      api.get('/v2/sdk/openapi-url').then(r => setOpenapiInfo(r.data)).catch(() => {})
    }
  }, [tab])

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'python', label: 'Python SDK' },
    { id: 'cli', label: 'CLI Tool' },
    { id: 'bash', label: 'Bash/curl' },
    { id: 'openapi', label: 'OpenAPI' },
  ]

  const downloadFile = (content: string, filename: string) => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">API & SDK</h1>
        <p className="text-gray-600 mt-1">API versioning, client libraries, and integration tools</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`py-2 px-1 border-b-2 text-sm font-medium ${
                tab === t.id ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>{t.label}</button>
          ))}
        </nav>
      </div>

      {/* Overview */}
      {tab === 'overview' && (
        <div className="space-y-6">
          {versionInfo && (
            <div className="bg-white border rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">API Version</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div>
                  <p className="text-sm text-gray-500">Current Version</p>
                  <p className="text-lg font-mono">{versionInfo.api_version}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">App Version</p>
                  <p className="text-lg font-mono">{versionInfo.app_version}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">v1 Status</p>
                  <p className="text-lg"><span className="px-2 py-0.5 bg-green-100 text-green-800 rounded text-sm">{versionInfo.v1_status}</span></p>
                </div>
                <div>
                  <p className="text-sm text-gray-500">v1 Sunset</p>
                  <p className="text-lg text-gray-600">{versionInfo.v1_sunset || 'None scheduled'}</p>
                </div>
              </div>
              <div className="mt-4">
                <p className="text-sm text-gray-500">Supported Versions</p>
                <div className="flex gap-2 mt-1">
                  {versionInfo.supported_versions?.map((v: string) => (
                    <span key={v} className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-sm font-mono">{v}</span>
                  ))}
                </div>
              </div>
            </div>
          )}

          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">Versioning Strategy</h2>
            <div className="space-y-3 text-sm text-gray-700">
              <p><strong>v1</strong> — Stable. All existing integrations continue to work. No breaking changes.</p>
              <p><strong>v2</strong> — Current. Envelope response format, cursor pagination, enhanced health checks.</p>
              <p>Both versions are served simultaneously. When a version is deprecated, responses include <code className="bg-gray-100 px-1 rounded">Deprecation</code> and <code className="bg-gray-100 px-1 rounded">Sunset</code> headers.</p>
            </div>
            <div className="mt-4 p-3 bg-gray-50 rounded font-mono text-xs">
              <p>X-API-Version: 2.0</p>
              <p>X-API-Status: current</p>
              <p className="text-gray-400"># When deprecated:</p>
              <p className="text-gray-400"># Deprecation: true</p>
              <p className="text-gray-400"># Sunset: Sat, 01 Jan 2028 00:00:00 GMT</p>
            </div>
          </div>

          {changelog.length > 0 && (
            <div className="bg-white border rounded-lg p-6">
              <h2 className="text-lg font-semibold mb-4">Changelog</h2>
              <div className="space-y-4">
                {changelog.map((entry: any) => (
                  <div key={entry.version} className="border-l-2 border-blue-200 pl-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-semibold">v{entry.version}</span>
                      <span className="text-sm text-gray-500">{entry.date}</span>
                    </div>
                    <ul className="mt-1 text-sm text-gray-600 list-disc list-inside">
                      {entry.changes?.map((c: string, i: number) => <li key={i}>{c}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Python SDK */}
      {tab === 'python' && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Python SDK</h2>
              {pythonSdk && (
                <button onClick={() => downloadFile(pythonSdk.source, pythonSdk.filename)}
                  className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                  Download {pythonSdk.filename}
                </button>
              )}
            </div>
            {pythonSdk && (
              <>
                <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm">
                  <strong>Requirements:</strong> <code>{pythonSdk.requires?.join(', ')}</code>
                  <br />
                  <code className="text-xs">pip install {pythonSdk.requires?.join(' ')}</code>
                </div>
                <div className="mb-4 p-3 bg-gray-50 rounded text-sm">
                  <strong>Quick start:</strong>
                  <pre className="mt-2 text-xs overflow-x-auto">{`from certmanager_sdk import CertManagerClient

with CertManagerClient(api_key="your-key") as client:
    # Check health
    print(client.health())

    # List CAs
    cas = client.list_cas()

    # Issue a certificate
    cert = client.issue_cert(
        signing_ca_id=cas[0]["id"],
        cn="app.internal",
        san=[{"type": "dns", "value": "app.internal"}],
    )
    print(f"Issued: {cert['serial']}")

    # Export as PKCS#12
    p12 = client.export_cert(cert["serial"], fmt="p12")
    open("app.p12", "wb").write(p12)`}</pre>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm text-blue-600 font-medium">View full source</summary>
                  <pre className="mt-2 p-4 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto max-h-96 overflow-y-auto">{pythonSdk.source}</pre>
                </details>
              </>
            )}
          </div>
        </div>
      )}

      {/* CLI Tool */}
      {tab === 'cli' && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">CLI Tool</h2>
              {cliTool && (
                <button onClick={() => downloadFile(cliTool.source, cliTool.filename)}
                  className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
                  Download {cliTool.filename}
                </button>
              )}
            </div>
            {cliTool && (
              <>
                <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm">
                  <strong>Install:</strong> <code>{cliTool.install_instructions}</code>
                </div>
                <div className="mb-4 p-3 bg-gray-50 rounded text-sm space-y-2">
                  <strong>Usage:</strong>
                  <pre className="text-xs overflow-x-auto">{`# Configure
python certmanager_cli.py configure --url https://pki.internal --api-key YOUR_KEY

# List CAs
python certmanager_cli.py cas

# Issue certificate
python certmanager_cli.py issue app.internal --ca CA_ID --profile server --san dns:app.internal

# Export
python certmanager_cli.py export SERIAL --fmt p12 -o app.p12

# Revoke
python certmanager_cli.py revoke SERIAL --reason superseded

# List certificates
python certmanager_cli.py list --profile server --status valid`}</pre>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm text-blue-600 font-medium">View full source</summary>
                  <pre className="mt-2 p-4 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto max-h-96 overflow-y-auto">{cliTool.source}</pre>
                </details>
              </>
            )}
          </div>
        </div>
      )}

      {/* Bash examples */}
      {tab === 'bash' && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">Bash / curl Examples</h2>
            <div className="mb-3 p-3 bg-yellow-50 border border-yellow-200 rounded text-sm">
              Set your API key: <code>export API_KEY="your-api-key"</code>
            </div>
            {bashExamples?.examples?.map((ex: any, i: number) => (
              <div key={i} className="mb-4">
                <p className="text-sm font-medium text-gray-700 mb-1">{ex.name}</p>
                <pre className="p-3 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto">{ex.command}</pre>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* OpenAPI */}
      {tab === 'openapi' && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">OpenAPI Specification</h2>
            <p className="text-sm text-gray-600 mb-4">
              The full OpenAPI 3.1 spec is auto-generated from the FastAPI application. Use it with any code generator.
            </p>
            {openapiInfo && (
              <>
                <div className="mb-4 space-y-2">
                  <p className="text-sm"><strong>Spec URL:</strong> <a href={openapiInfo.openapi_url} className="text-blue-600 font-mono">{openapiInfo.openapi_url}</a></p>
                  <p className="text-sm"><strong>Interactive docs:</strong> <a href={openapiInfo.docs_url} className="text-blue-600 font-mono">{openapiInfo.docs_url}</a></p>
                </div>
                <h3 className="text-sm font-semibold mt-6 mb-2">Auto-generate SDKs</h3>
                <div className="space-y-3">
                  {Object.entries(openapiInfo.generators || {}).map(([lang, cmd]) => (
                    <div key={lang}>
                      <p className="text-xs font-medium text-gray-500 uppercase">{lang}</p>
                      <pre className="p-2 bg-gray-100 rounded text-xs overflow-x-auto">{cmd as string}</pre>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
