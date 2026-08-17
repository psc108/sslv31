import { useState, useEffect } from 'react'
import api from '@/lib/api'

type Tab = 'config' | 'guide' | 'log'

export default function SCEPPage() {
  const [tab, setTab] = useState<Tab>('config')
  const [config, setConfig] = useState<any>(null)
  const [guide, setGuide] = useState<any>(null)
  const [log, setLog] = useState<any[]>([])

  useEffect(() => {
    api.get('/scep/config').then(r => setConfig(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    if (tab === 'guide' && !guide) {
      api.get('/scep/guide').then(r => setGuide(r.data)).catch(() => {})
    }
    if (tab === 'log') {
      api.get('/audit', { params: { page_size: 50, event_type: 'SCEP' } })
        .then(r => setLog(r.data?.items || []))
        .catch(() => {})
    }
  }, [tab])

  const tabs: { id: Tab; label: string }[] = [
    { id: 'config', label: 'Configuration' },
    { id: 'guide', label: 'Device Guides' },
    { id: 'log', label: 'Enrollment Log' },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">SCEP Protocol</h1>
        <p className="text-gray-600 mt-1">Simple Certificate Enrollment Protocol for legacy network devices</p>
      </div>

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

      {/* Configuration */}
      {tab === 'config' && config && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">SCEP Status</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <p className="text-sm text-gray-500">Status</p>
                <span className={`px-2 py-0.5 rounded text-sm ${config.enabled ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                  {config.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div>
                <p className="text-sm text-gray-500">Signing CA</p>
                <p className="text-sm font-mono">{config.ca_name || config.ca_id || 'Auto-select'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Profile</p>
                <p className="text-sm font-mono">{config.profile}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Max Validity</p>
                <p className="text-sm">{config.max_validity_days} days</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">Challenge Password</p>
                <span className={`px-2 py-0.5 rounded text-sm ${config.challenge_configured ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                  {config.challenge_configured ? 'Configured' : 'Open enrollment'}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">Endpoints</h2>
            <div className="space-y-2 font-mono text-sm">
              {config.endpoints && Object.entries(config.endpoints).map(([key, url]) => (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-gray-500 w-32">{key}:</span>
                  <code className="bg-gray-100 px-2 py-0.5 rounded">{url as string}</code>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-white border rounded-lg p-6">
            <h2 className="text-lg font-semibold mb-4">Configuration</h2>
            <p className="text-sm text-gray-600 mb-3">Set these environment variables to enable SCEP:</p>
            <pre className="p-3 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto">{`# Enable SCEP
SCEP_ENABLED=true

# CA to use for signing (leave empty for auto-select)
SCEP_CA_ID=

# Challenge password (shared secret for enrollment)
# Leave empty for open enrollment (NOT recommended for production)
SCEP_CHALLENGE_PASSWORD=MySecretChallenge123

# Certificate profile (server, client, or custom template name)
SCEP_PROFILE=server

# Maximum validity for SCEP-enrolled certificates
SCEP_MAX_VALIDITY_DAYS=365`}</pre>
          </div>

          {!config.enabled && (
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <p className="text-sm text-yellow-800">
                SCEP is currently disabled. Set <code className="bg-yellow-100 px-1 rounded">SCEP_ENABLED=true</code> in your environment to enable it.
              </p>
            </div>
          )}

          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <p className="text-sm text-blue-800 font-medium mb-1">Security Note</p>
            <p className="text-sm text-blue-700">
              SCEP uses shared challenge passwords which are less secure than EST or ACME.
              Use SCEP only for legacy devices that don't support modern enrollment protocols.
              Always configure a strong challenge password and consider network-level access controls.
            </p>
          </div>
        </div>
      )}

      {/* Device Guides */}
      {tab === 'guide' && (
        <div className="space-y-4">
          {guide && Object.entries(guide).map(([key, device]: [string, any]) => (
            <div key={key} className="bg-white border rounded-lg p-6">
              <h3 className="text-md font-semibold mb-3">{device.title}</h3>
              <pre className="p-3 bg-gray-900 text-green-300 rounded text-xs overflow-x-auto whitespace-pre-wrap">{device.commands}</pre>
            </div>
          ))}
          {!guide && <p className="text-gray-500">Loading device guides...</p>}
        </div>
      )}

      {/* Enrollment Log */}
      {tab === 'log' && (
        <div className="bg-white border rounded-lg overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Event</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Subject</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Description</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {log.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-gray-500">No SCEP enrollment events yet</td></tr>
              )}
              {log.map((entry: any, i: number) => (
                <tr key={i}>
                  <td className="px-4 py-2 text-xs text-gray-500">{new Date(entry.timestamp).toLocaleString()}</td>
                  <td className="px-4 py-2 text-xs font-mono">{entry.event_type}</td>
                  <td className="px-4 py-2 text-xs font-mono">{entry.subject_id?.slice(0, 16)}</td>
                  <td className="px-4 py-2 text-xs text-gray-700">{entry.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
