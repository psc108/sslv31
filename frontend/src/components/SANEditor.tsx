import { useState } from 'react'
import type { SANEntry } from '@/lib/types'

interface SANEditorProps {
  entries: SANEntry[]
  onChange: (entries: SANEntry[]) => void
  required?: boolean
}

const typeLabels: Record<string, string> = {
  dns: 'DNS',
  ip: 'IP',
  email: 'Email',
  uri: 'URI',
}

const typeBadgeColors: Record<string, string> = {
  dns: 'bg-blue-100 text-blue-800',
  ip: 'bg-purple-100 text-purple-800',
  email: 'bg-amber-100 text-amber-800',
  uri: 'bg-emerald-100 text-emerald-800',
}

function validateEntry(type: string, value: string): string | null {
  if (!value.trim()) return 'Value is required'

  if (type === 'dns') {
    // Allow wildcards like *.example.com but not *.*.example.com
    const dnsPattern = /^(\*\.)?([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)*[a-zA-Z]{2,}$/
    if (!dnsPattern.test(value)) return 'Invalid DNS name'
    if ((value.match(/\*/g) || []).length > 1) return 'Only one wildcard level allowed'
  }

  if (type === 'ip') {
    // IPv4
    const ipv4 = /^(\d{1,3}\.){3}\d{1,3}$/
    // IPv6 (simplified check)
    const ipv6 = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/
    if (!ipv4.test(value) && !ipv6.test(value)) return 'Invalid IP address'
    if (ipv4.test(value)) {
      const parts = value.split('.').map(Number)
      if (parts.some(p => p > 255)) return 'Invalid IPv4 address'
    }
  }

  if (type === 'email') {
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
    if (!emailPattern.test(value)) return 'Invalid email address'
  }

  return null
}

export default function SANEditor({ entries, onChange, required = false }: SANEditorProps) {
  const [type, setType] = useState<string>('dns')
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)

  const addEntry = () => {
    const trimmed = value.trim()
    if (!trimmed) return

    const validationError = validateEntry(type, trimmed)
    if (validationError) {
      setError(validationError)
      return
    }

    // Duplicate check
    if (entries.some(e => e.type === type && e.value === trimmed)) {
      setError('Duplicate entry')
      return
    }

    onChange([...entries, { type: type as SANEntry['type'], value: trimmed }])
    setValue('')
    setError(null)
  }

  const removeEntry = (index: number) => {
    onChange(entries.filter((_, i) => i !== index))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      addEntry()
    }
  }

  const handlePaste = (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData('text')
    if (text.includes(',') || text.includes('\n')) {
      e.preventDefault()
      const values = text.split(/[,\n]/).map(v => v.trim()).filter(Boolean)
      const newEntries: SANEntry[] = []
      for (const v of values) {
        if (!entries.some(e => e.type === type && e.value === v)) {
          const err = validateEntry(type, v)
          if (!err) {
            newEntries.push({ type: type as SANEntry['type'], value: v })
          }
        }
      }
      if (newEntries.length > 0) {
        onChange([...entries, ...newEntries])
      }
    }
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium text-gray-700">
        Subject Alternative Names {required && <span className="text-red-500">*</span>}
      </label>

      {/* Tags */}
      {entries.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {entries.map((entry, i) => (
            <span
              key={`${entry.type}-${entry.value}`}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${typeBadgeColors[entry.type]}`}
            >
              <span className="font-semibold">{typeLabels[entry.type]}</span>
              {entry.value}
              <button
                type="button"
                onClick={() => removeEntry(i)}
                className="ml-1 hover:opacity-70"
                aria-label={`Remove ${entry.value}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input row */}
      <div className="flex gap-2">
        <select
          value={type}
          onChange={e => setType(e.target.value)}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm w-24"
          aria-label="SAN type"
        >
          <option value="dns">DNS</option>
          <option value="ip">IP</option>
          <option value="email">Email</option>
          <option value="uri">URI</option>
        </select>
        <input
          type="text"
          value={value}
          onChange={e => { setValue(e.target.value); setError(null) }}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder={type === 'dns' ? 'api.example.com' : type === 'ip' ? '10.0.1.50' : ''}
          aria-label="SAN value"
        />
        <button
          type="button"
          onClick={addEntry}
          className="px-3 py-2 bg-gray-100 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-200"
        >
          Add
        </button>
      </div>

      {error && <p className="text-red-600 text-xs">{error}</p>}
      <p className="text-xs text-gray-400">Paste comma or newline-separated values to add multiple entries.</p>
    </div>
  )
}
