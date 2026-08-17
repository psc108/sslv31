import { useState } from 'react'
import type { Dependency } from './types'

interface Props {
  dependencies: Dependency[]
  loading?: boolean
  total?: number
  page?: number
  pages?: number
  onPageChange?: (p: number) => void
  onCategoryChange?: (cat: string) => void
}

const CATEGORIES = ['', 'spring_boot', 'spring_framework', 'spring_security', 'database', 'messaging', 'cryptography', 'serialisation', 'http_client', 'observability', 'logging', 'cloud_sdk', 'testing', 'npm', 'dev', 'other']

const CATEGORY_LABELS: Record<string, string> = {
  '': 'All', spring_boot: 'Spring Boot', spring_framework: 'Spring', spring_security: 'Security',
  database: 'Database', messaging: 'Messaging', cryptography: 'Crypto', serialisation: 'Serialisation',
  http_client: 'HTTP Client', observability: 'Observability', logging: 'Logging',
  cloud_sdk: 'Cloud SDK', testing: 'Testing', npm: 'Runtime', dev: 'Dev', other: 'Other',
}

function fmtBytes(b: number | null) {
  if (!b) return '—'
  if (b > 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`
  return `${(b / 1024).toFixed(0)} KB`
}

export default function DependencyTable({ dependencies, loading, total, page = 1, pages = 1, onPageChange, onCategoryChange }: Props) {
  const [cat, setCat] = useState('')

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1">
        {CATEGORIES.map(c => (
          <button key={c} onClick={() => { setCat(c); onCategoryChange?.(c) }}
            className={`px-2 py-1 rounded text-xs border transition ${
              cat === c ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
            }`}>
            {CATEGORY_LABELS[c] ?? c}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 py-4 text-center">Loading...</p>}

      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Group ID</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Artifact ID</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Version</th>
              <th className="px-4 py-2 text-left font-medium text-gray-600">Category</th>
              <th className="px-4 py-2 text-right font-medium text-gray-600">Size</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {!loading && dependencies.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400">No dependencies found.</td></tr>
            )}
            {dependencies.map(d => {
              const isNpm = d.category === 'npm' || d.category === 'dev'
              return (
              <tr key={d.id} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-xs font-mono text-gray-600">{isNpm ? '—' : (d.group_id ?? '—')}</td>
                <td className="px-4 py-2 text-xs font-mono text-gray-800">{d.artifact_id ?? d.filename}</td>
                <td className="px-4 py-2 text-xs text-gray-600">{d.version ?? '—'}</td>
                <td className="px-4 py-2">
                  <span className={`px-2 py-0.5 rounded text-xs ${
                    isNpm ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'
                  }`}>
                    {CATEGORY_LABELS[d.category ?? ''] ?? d.category ?? '—'}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-right text-gray-400">{fmtBytes(d.size_bytes)}</td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>{total} dependencies</span>
          <div className="flex gap-2">
            <button disabled={page === 1} onClick={() => onPageChange?.(page - 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">← Prev</button>
            <span className="px-2">{page} / {pages}</span>
            <button disabled={page >= pages} onClick={() => onPageChange?.(page + 1)}
              className="px-3 py-1 border rounded disabled:opacity-40 hover:bg-gray-50">Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
