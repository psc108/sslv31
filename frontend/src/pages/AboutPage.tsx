import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import MarkdownPreview from '@/components/docs/MarkdownPreview'

interface AboutData {
  content: string
  updated_by: string | null
  updated_at: string | null
}

interface AboutVersionSummary {
  id: string
  updated_by: string | null
  updated_at: string | null
  archived_at: string | null
  source: 'manual_edit' | 'regenerate' | 'restore'
  content_length: number
}

interface AboutVersionChange {
  id: string
  package_key: string
  display_name: string
  old_version: string | null
  new_version: string
  detected_at: string | null
}

interface AboutDiffRow {
  tag: 'equal' | 'insert' | 'delete'
  a_line: number | null
  b_line: number | null
  text: string
}

interface AboutDiffResult {
  added: number
  removed: number
  rows: AboutDiffRow[]
}

const SOURCE_LABEL: Record<string, string> = {
  manual_edit: '✏️ Manual edit', regenerate: '🔄 Regenerate', restore: '⏪ Restore',
}

export default function AboutPage() {
  const { isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [exportingFormat, setExportingFormat] = useState<'pdf' | 'markdown' | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateError, setRegenerateError] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [showChangelog, setShowChangelog] = useState(false)
  const [restoringId, setRestoringId] = useState<string | null>(null)
  const [historyError, setHistoryError] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data, isLoading } = useQuery<AboutData>({
    queryKey: ['about-page'],
    queryFn: () => api.get('/about').then(r => r.data),
  })

  // Seed the edit draft from the fetched content once, matching this
  // codebase's usual "fetch once, prefill via useEffect + a guard"
  // pattern — re-running on every refetch would clobber in-progress edits.
  const [prefilled, setPrefilled] = useState(false)
  useEffect(() => {
    if (data && !prefilled) {
      setDraft(data.content)
      setPrefilled(true)
    }
  }, [data, prefilled])

  const startEditing = () => {
    if (data) setDraft(data.content)
    setError('')
    setShowHistory(false)
    setShowChangelog(false)
    setExpandedId(null)
    setEditing(true)
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await api.put('/about', { content: draft })
      setEditing(false)
      await queryClient.invalidateQueries({ queryKey: ['about-page'] })
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save changes')
    } finally {
      setSaving(false)
    }
  }

  const regenerate = async () => {
    if (!confirm('Regenerate this page from detected package versions? This overwrites the current content (including any hand-written notes).')) return
    setRegenerating(true)
    setRegenerateError('')
    try {
      await api.post('/about/regenerate')
      setEditing(false)
      await queryClient.invalidateQueries({ queryKey: ['about-page'] })
    } catch (err: any) {
      setRegenerateError(err.response?.data?.detail || 'Failed to regenerate')
    } finally {
      setRegenerating(false)
    }
  }

  const { data: history } = useQuery<AboutVersionSummary[]>({
    queryKey: ['about-history'],
    queryFn: () => api.get('/about/history').then(r => r.data),
    enabled: showHistory,
  })

  const { data: changelog } = useQuery<AboutVersionChange[]>({
    queryKey: ['about-changelog'],
    queryFn: () => api.get('/about/changelog').then(r => r.data),
    enabled: showChangelog,
  })

  const { data: diff, isFetching: diffLoading, error: diffError } = useQuery<AboutDiffResult>({
    queryKey: ['about-history-diff', expandedId],
    queryFn: () => api.get(`/about/history/${expandedId}/diff`).then(r => r.data),
    enabled: !!expandedId,
  })

  const restoreVersion = async (id: string, archivedAt: string | null) => {
    const when = archivedAt ? new Date(archivedAt).toLocaleString() : 'this snapshot'
    if (!confirm(`Restore the About page to the version from ${when}? The current content is backed up first, so this can itself be undone.`)) return
    setRestoringId(id)
    setHistoryError('')
    try {
      await api.post(`/about/history/${id}/restore`)
      setExpandedId(null)
      await queryClient.invalidateQueries({ queryKey: ['about-page'] })
      await queryClient.invalidateQueries({ queryKey: ['about-history'] })
      await queryClient.invalidateQueries({ queryKey: ['about-history-diff'] })
    } catch (err: any) {
      setHistoryError(err.response?.data?.detail || 'Failed to restore')
    } finally {
      setRestoringId(null)
    }
  }

  const exportAbout = async (format: 'pdf' | 'markdown') => {
    setExportingFormat(format)
    try {
      const res = await api.get(`/about/export/${format}`, { responseType: 'blob' })
      const href = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = href
      a.download = format === 'pdf' ? 'about.pdf' : 'about.md'
      a.click()
      URL.revokeObjectURL(href)
    } finally {
      setExportingFormat(null)
    }
  }

  if (isLoading || !data) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-gray-900">ℹ️ About</h1>
        {!editing && (
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => exportAbout('markdown')} disabled={exportingFormat !== null}
              className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded-md disabled:opacity-40">
              {exportingFormat === 'markdown' ? 'Exporting…' : '⬇ Markdown'}
            </button>
            <button onClick={() => exportAbout('pdf')} disabled={exportingFormat !== null}
              className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded-md disabled:opacity-40">
              {exportingFormat === 'pdf' ? 'Exporting…' : '⬇ PDF'}
            </button>
            <button onClick={() => { setShowHistory(v => !v); setShowChangelog(false); setEditing(false); setExpandedId(null) }}
              className={`px-3 py-1.5 text-xs border rounded-md ${showHistory ? 'text-blue-700 border-blue-200 bg-blue-50' : 'text-gray-600 hover:text-gray-800 border-gray-300'}`}>
              🕐 History
            </button>
            <button onClick={() => { setShowChangelog(v => !v); setShowHistory(false); setEditing(false) }}
              className={`px-3 py-1.5 text-xs border rounded-md ${showChangelog ? 'text-blue-700 border-blue-200 bg-blue-50' : 'text-gray-600 hover:text-gray-800 border-gray-300'}`}>
              📋 Changelog
            </button>
            {isAdmin && (
              <>
                <button onClick={regenerate} disabled={regenerating}
                  title="Rebuild this page from live-detected package versions (pip metadata, package-lock.json, java/nginx/tofu --version) — overwrites current content"
                  className="px-3 py-1.5 text-xs text-blue-700 hover:text-blue-900 border border-blue-200 bg-blue-50 rounded-md disabled:opacity-40">
                  {regenerating ? 'Regenerating…' : '🔄 Regenerate'}
                </button>
                <button onClick={startEditing}
                  className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 border border-gray-300 rounded-md">
                  ✏️ Edit
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {regenerateError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{regenerateError}</p>
      )}
      {historyError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{historyError}</p>
      )}

      {showHistory ? (
        <div className="bg-white border border-gray-200 rounded-lg p-6">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
            Content Snapshots (backed up automatically before every edit, regenerate, or restore)
          </p>
          {!history && <p className="text-sm text-gray-400">Loading…</p>}
          {history?.length === 0 && <p className="text-sm text-gray-400">No snapshots yet — nothing has overwritten the page since it was first seeded.</p>}
          <div className="space-y-2">
            {history?.map(v => {
              const isExpanded = expandedId === v.id
              return (
                <div key={v.id} className="border border-gray-100 rounded-md">
                  <div className="flex items-center gap-3 text-sm px-3 py-2 cursor-pointer hover:bg-gray-50"
                    onClick={() => setExpandedId(isExpanded ? null : v.id)}>
                    <span className="text-gray-400 text-xs w-3 shrink-0">{isExpanded ? '▾' : '▸'}</span>
                    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded shrink-0">{SOURCE_LABEL[v.source] ?? v.source}</span>
                    <span className="text-gray-700">
                      {v.updated_by ?? 'unknown'} · {v.updated_at ? new Date(v.updated_at).toLocaleString() : '?'}
                    </span>
                    <span className="text-xs text-gray-400">({v.content_length.toLocaleString()} chars)</span>
                    {isAdmin && (
                      <button onClick={e => { e.stopPropagation(); restoreVersion(v.id, v.archived_at) }} disabled={restoringId === v.id}
                        className="ml-auto text-xs text-blue-600 hover:underline disabled:opacity-40">
                        {restoringId === v.id ? 'Restoring…' : '⏪ Restore'}
                      </button>
                    )}
                  </div>
                  {isExpanded && (
                    <div className="border-t border-gray-100 px-3 py-2">
                      {diffLoading && <p className="text-xs text-gray-400 py-2">Comparing…</p>}
                      {diffError && <p className="text-xs text-red-600 py-2">Failed to load diff.</p>}
                      {diff && !diffLoading && (
                        <div className="space-y-1.5">
                          <div className="text-xs text-gray-500 flex items-center gap-3">
                            <span>What this change did:</span>
                            <span className="text-green-700">+{diff.added}</span>
                            <span className="text-red-700">−{diff.removed}</span>
                          </div>
                          {diff.added === 0 && diff.removed === 0 && (
                            <p className="text-xs text-gray-400">No textual changes (content is identical).</p>
                          )}
                          <div className="border border-gray-200 rounded-md overflow-hidden font-mono text-xs max-h-80 overflow-y-auto">
                            {diff.rows.filter(r => r.tag !== 'equal').map((row, idx) => (
                              <div key={idx}
                                className={`flex ${row.tag === 'insert' ? 'bg-green-50' : 'bg-red-50'}`}>
                                <span className="w-9 shrink-0 text-right pr-2 text-gray-400 select-none border-r border-gray-100">
                                  {row.a_line ?? ''}
                                </span>
                                <span className="w-9 shrink-0 text-right pr-2 text-gray-400 select-none border-r border-gray-100">
                                  {row.b_line ?? ''}
                                </span>
                                <span className={`px-2 select-none ${row.tag === 'insert' ? 'text-green-700' : 'text-red-700'}`}>
                                  {row.tag === 'insert' ? '+' : '−'}
                                </span>
                                <span className={`flex-1 whitespace-pre-wrap break-all pr-3 ${row.tag === 'insert' ? 'text-green-900' : 'text-red-900'}`}>
                                  {row.text || ' '}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ) : showChangelog ? (
        <div className="bg-white border border-gray-200 rounded-lg p-6">
          <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-3">
            Version Changelog (recorded automatically on every Regenerate)
          </p>
          {!changelog && <p className="text-sm text-gray-400">Loading…</p>}
          {changelog?.length === 0 && <p className="text-sm text-gray-400">No version changes recorded yet — run Regenerate at least twice to start building history.</p>}
          <div className="space-y-1.5">
            {changelog?.map(c => (
              <div key={c.id} className={`rounded p-2 text-xs flex items-center gap-2 ${c.old_version ? 'bg-amber-50 border-l-4 border-amber-400' : 'bg-green-50 border-l-4 border-green-400'}`}>
                <span className={`px-1.5 py-0.5 rounded font-bold ${c.old_version ? 'bg-amber-100 text-amber-800' : 'bg-green-100 text-green-800'}`}>
                  {c.old_version ? '~' : '+'}
                </span>
                <span className="font-medium text-gray-800">{c.display_name}</span>
                {c.old_version ? (
                  <span className="text-gray-500">{c.old_version} → <span className="font-medium text-gray-800">{c.new_version}</span></span>
                ) : (
                  <span className="text-gray-500">{c.new_version} (first detected)</span>
                )}
                <span className="ml-auto text-gray-400">{c.detected_at ? new Date(c.detected_at).toLocaleString() : ''}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg p-6">
          {editing ? (
            <div className="space-y-2">
              {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">{error}</p>}
              <textarea
                value={draft} onChange={e => setDraft(e.target.value)}
                rows={24} className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
              />
              <div className="flex gap-2">
                <button onClick={save} disabled={saving || !draft.trim()}
                  className="px-4 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-40">
                  {saving ? 'Saving…' : 'Save Changes'}
                </button>
                <button onClick={() => setEditing(false)} className="px-4 py-1.5 border border-gray-300 text-sm rounded-md hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <MarkdownPreview content={data.content} onNavigateToDoc={() => {}} />
          )}
        </div>
      )}

      {data.updated_by && data.updated_at && !editing && !showHistory && !showChangelog && (
        <p className="text-xs text-gray-400">
          Last updated by {data.updated_by} on {new Date(data.updated_at).toLocaleString()}
        </p>
      )}
    </div>
  )
}
