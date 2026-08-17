import { useState } from 'react'
import type { ConfigFile } from './types'

interface Props { configs: ConfigFile[] }

export default function ConfigViewer({ configs }: Props) {
  const [open, setOpen] = useState<string | null>(configs[0]?.id ?? null)

  if (!configs.length) return <p className="text-sm text-gray-400 py-4">No configuration files found.</p>

  return (
    <div className="space-y-3">
      {configs.map(cf => (
        <div key={cf.id} className="border border-gray-200 rounded-lg overflow-hidden">
          <button
            onClick={() => setOpen(open === cf.id ? null : cf.id)}
            className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 text-left"
          >
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm font-medium text-gray-800">{cf.filename}</span>
              <span className="text-xs text-gray-400">{cf.path_in_jar}</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              {cf.key_count != null && <span>{cf.key_count} keys</span>}
              {!!cf.encrypted_count && <span className="text-amber-600">🔒 {cf.encrypted_count} encrypted</span>}
              {!!cf.ssl_key_count && <span className="text-blue-600">🔐 {cf.ssl_key_count} SSL</span>}
              {!!cf.db_key_count && <span className="text-purple-600">🗄️ {cf.db_key_count} DB</span>}
              <span>{open === cf.id ? '▲' : '▼'}</span>
            </div>
          </button>

          {open === cf.id && (
            <div className="p-4 space-y-4">
              {cf.keys && cf.keys.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">Parsed Keys</p>
                  <div className="border border-gray-200 rounded overflow-hidden">
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-3 py-1.5 text-left font-medium text-gray-600">Key</th>
                          <th className="px-3 py-1.5 text-left font-medium text-gray-600">Value</th>
                          <th className="px-3 py-1.5 text-left font-medium text-gray-600">Category</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {cf.keys.map((k, i) => (
                          <tr key={i} className={k.is_encrypted ? 'bg-amber-50' : ''}>
                            <td className="px-3 py-1.5 font-mono text-gray-800">{k.key}</td>
                            <td className="px-3 py-1.5 font-mono text-gray-600 max-w-xs truncate">
                              {k.is_encrypted ? <span className="text-amber-600">🔒 {k.value}</span> : k.value}
                            </td>
                            <td className="px-3 py-1.5 text-gray-400">{k.category}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {cf.content && (
                <div>
                  <p className="text-xs font-medium text-gray-600 mb-2">Raw Content</p>
                  <pre className="bg-gray-900 text-gray-100 rounded p-3 text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-96 overflow-y-auto">
                    {cf.content.slice(0, 4000)}{cf.content.length > 4000 ? '\n... (truncated)' : ''}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
