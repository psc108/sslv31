import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props { reportId: string }

type Flavour = 'on_prem_standard' | 'on_prem_ha' | 'aws' | 'docker'
type LbKey = 'frontend' | 'backend'

const FLAVOURS: { key: Flavour; label: string; icon: string }[] = [
  { key: 'on_prem_standard', label: 'On-Prem (Standard)', icon: '🖥️' },
  { key: 'on_prem_ha',       label: 'On-Prem (HA)',       icon: '🔁' },
  { key: 'aws',              label: 'AWS (ALB)',           icon: '☁️' },
  { key: 'docker',           label: 'Docker / K8s',       icon: '🐳' },
]

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button onClick={copy}
      className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 text-gray-600 transition">
      {copied ? '✓ Copied' : '📋 Copy'}
    </button>
  )
}

function DownloadButton({ text, filename }: { text: string; filename: string }) {
  const dl = () => {
    const blob = new Blob([text], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }
  return (
    <button onClick={dl}
      className="px-2 py-1 text-xs border border-gray-300 rounded hover:bg-gray-100 text-gray-600 transition">
      ⬇ Download
    </button>
  )
}

export default function NginxConfigTab({ reportId }: Props) {
  const [flavour, setFlavour] = useState<Flavour>('on_prem_standard')
  const [lb, setLb] = useState<LbKey>('frontend')

  const { data, isLoading, error } = useQuery({
    queryKey: ['nginx-configs', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}/nginx-configs`).then(r => r.data),
  })

  if (isLoading) return <div className="text-sm text-gray-400 py-8 text-center">Loading nginx configs…</div>
  if (error || !data) return <div className="text-sm text-red-500 py-4">Failed to load nginx configs.</div>

  const flavourData = data[flavour] as Record<LbKey, string> | undefined
  const configText = flavourData?.[lb] ?? ''
  const note = (data.notes as Record<Flavour, string>)?.[flavour] ?? ''
  const services: { name: string; port: number }[] = data.services ?? []
  const filename = `${lb}-lb-${flavour.replace(/_/g, '-')}.conf`

  const availableLbs = flavourData ? (Object.keys(flavourData) as LbKey[]) : []

  return (
    <div className="space-y-4">
      {/* Stats bar */}
      <div className="flex flex-wrap gap-3 text-sm text-gray-600">
        <span className="font-medium">🔧 Nginx Config Generator</span>
        <span className="text-gray-400">|</span>
        <span>{services.length} services</span>
        <span className="text-gray-400">|</span>
        <span>4 deployment variants</span>
        <span className="text-gray-400">|</span>
        <span>2 load balancers</span>
      </div>

      {/* Flavour tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1">
          {FLAVOURS.map(f => (
            <button key={f.key} onClick={() => setFlavour(f.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                flavour === f.key
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}>
              {f.icon} {f.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Note */}
      {note && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-800">
          ℹ️ {note}
        </div>
      )}

      {/* LB selector + actions */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex gap-2">
          {availableLbs.map(k => (
            <button key={k} onClick={() => setLb(k)}
              className={`px-3 py-1.5 text-sm rounded border transition ${
                lb === k
                  ? 'bg-gray-800 text-white border-gray-800'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-50'
              }`}>
              {k === 'frontend' ? '🌐 frontend-lb' : '⚙️ backend-lb'}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <CopyButton text={configText} />
          <DownloadButton text={configText} filename={filename} />
        </div>
      </div>

      {/* Config viewer */}
      <div className="relative">
        <pre className="bg-gray-900 text-gray-100 text-xs font-mono p-4 rounded-lg overflow-auto max-h-[600px] leading-relaxed whitespace-pre">
          {configText || '# No config available for this combination'}
        </pre>
      </div>

      {/* Service port reference */}
      {services.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          <div className="px-4 py-2 bg-gray-50 border-b border-gray-200">
            <span className="text-xs font-semibold text-gray-600">Service Port Reference</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-0 divide-x divide-y divide-gray-100">
            {services.map(s => (
              <div key={s.name} className="px-3 py-2 flex justify-between items-center">
                <span className="text-xs text-gray-700 font-medium">{s.name}</span>
                <span className="text-xs font-mono text-blue-600">{s.port}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
