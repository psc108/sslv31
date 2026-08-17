import { useEffect, useState, useCallback } from 'react'
import api from '@/lib/api'
import CodeViewer from '@/components/CodeViewer'

interface ConfigFile {
  id: string
  path: string
  display_name: string
  category: string
  format: string
  purpose: string
  editable: boolean
  exists: boolean
  size: number
  last_modified_by: string | null
  last_modified_at: string | null
  content?: string
}

interface ValidationError {
  line: number
  message: string
}

interface VersionEntry {
  version: number
  edited_by: string
  edited_at: string | null
  comment: string
  has_diff: boolean
}

interface FileHelp {
  summary: string
  directives: { key: string; purpose: string; default?: string }[]
  examples: { title: string; code: string }[]
  related_docs: string[]
}

interface ScaffoldVariable {
  name: string
  label: string
  placeholder: string
  required: boolean
}

interface Scaffold {
  id: string
  name: string
  description: string
  icon: string
  variables: ScaffoldVariable[]
}

interface FileAction {
  id: string
  label: string
  icon: string
  type: string
  description: string
}

const CATEGORIES = [
  { key: 'system', label: 'System', icon: '⚙️' },
  { key: 'playbooks', label: 'Playbooks', icon: '📋' },
  { key: 'roles', label: 'Roles', icon: '🎭' },
  { key: 'templates', label: 'Templates', icon: '📄' },
  { key: 'docker', label: 'Docker', icon: '🐳' },
  { key: 'generated', label: 'Generated', icon: '🔒' },
]

const FORMAT_COLORS: Record<string, string> = {
  yaml: 'bg-green-50 text-green-700',
  json: 'bg-blue-50 text-blue-700',
  ini: 'bg-yellow-50 text-yellow-700',
  jinja2: 'bg-purple-50 text-purple-700',
  nginx: 'bg-orange-50 text-orange-700',
  python: 'bg-indigo-50 text-indigo-700',
  shell: 'bg-gray-50 text-gray-700',
  text: 'bg-gray-50 text-gray-500',
}

export default function BMEditorPage() {
  const [files, setFiles] = useState<ConfigFile[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedFile, setSelectedFile] = useState<ConfigFile | null>(null)
  const [fileContent, setFileContent] = useState('')
  const [editedContent, setEditedContent] = useState('')
  const [loadingContent, setLoadingContent] = useState(false)
  const [filterCategory, setFilterCategory] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [seeding, setSeeding] = useState(false)
  const [editing, setEditing] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validationErrors, setValidationErrors] = useState<ValidationError[]>([])
  const [validationOk, setValidationOk] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  // History state
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<VersionEntry[]>([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [viewingVersion, setViewingVersion] = useState<number | null>(null)
  const [versionContent, setVersionContent] = useState('')
  const [diffContent, setDiffContent] = useState('')
  const [showDiff, setShowDiff] = useState(false)
  const [restoring, setRestoring] = useState(false)
  // Help state
  const [showHelp, setShowHelp] = useState(false)
  const [helpData, setHelpData] = useState<FileHelp | null>(null)
  const [loadingHelp, setLoadingHelp] = useState(false)
  // Scaffold state
  const [showScaffold, setShowScaffold] = useState(false)
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([])
  const [selectedScaffold, setSelectedScaffold] = useState<Scaffold | null>(null)
  const [scaffoldVars, setScaffoldVars] = useState<Record<string, string>>({})
  const [creatingScaffold, setCreatingScaffold] = useState(false)
  // Actions state
  const [postSaveActions, setPostSaveActions] = useState<FileAction[]>([])
  const [showActions, setShowActions] = useState(false)
  const [runningAction, setRunningAction] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<{ success: boolean; output: string; error: string } | null>(null)

  const load = () => {
    setLoading(true)
    api.get('/build/editor/files').then(r => {
      setFiles(r.data)
      setLoading(false)
    }).catch(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const handleSeed = async () => {
    setSeeding(true)
    try {
      const r = await api.post('/build/editor/seed')
      if (r.data.files_added > 0) load()
      else alert('Registry already up to date')
    } catch { alert('Failed to seed registry') }
    setSeeding(false)
  }

  const openFile = async (file: ConfigFile) => {
    if (dirty && !confirm('You have unsaved changes. Discard?')) return
    setSelectedFile(file)
    setEditing(false)
    setDirty(false)
    setValidationErrors([])
    setValidationOk(false)
    setShowHistory(false)
    setViewingVersion(null)
    setShowDiff(false)
    setShowHelp(false)
    setHelpData(null)
    setShowActions(false)
    setActionResult(null)
    setLoadingContent(true)
    try {
      const r = await api.get(`/build/editor/files/${file.id}`)
      setFileContent(r.data.content || '')
      setEditedContent(r.data.content || '')
    } catch { setFileContent('// Failed to load file content'); setEditedContent('') }
    setLoadingContent(false)
  }

  const handleEdit = () => {
    setEditing(true)
    setEditedContent(fileContent)
    setDirty(false)
    setValidationErrors([])
    setValidationOk(false)
    setShowHistory(false)
    setViewingVersion(null)
    setShowDiff(false)
    setShowHelp(false)
    setShowActions(false)
    setActionResult(null)
  }

  const handleCancel = () => {
    if (dirty && !confirm('Discard unsaved changes?')) return
    setEditing(false)
    setDirty(false)
    setEditedContent(fileContent)
    setValidationErrors([])
    setValidationOk(false)
  }

  const handleChange = useCallback((value: string) => {
    setEditedContent(value)
    setDirty(true)
    setValidationOk(false)
  }, [])

  const handleValidate = async () => {
    if (!selectedFile) return
    setValidating(true)
    setValidationErrors([])
    setValidationOk(false)
    try {
      const r = await api.post(`/build/editor/files/${selectedFile.id}/validate`, { content: editedContent })
      if (r.data.valid) {
        setValidationOk(true)
      } else {
        setValidationErrors(r.data.errors)
      }
    } catch (e: any) {
      setValidationErrors([{ line: 1, message: e.response?.data?.detail || 'Validation failed' }])
    }
    setValidating(false)
  }

  const handleSave = () => {
    setShowConfirm(true)
  }

  const confirmSave = async () => {
    if (!selectedFile) return
    setShowConfirm(false)
    setSaving(true)
    try {
      await api.put(`/build/editor/files/${selectedFile.id}`, { content: editedContent })
      setFileContent(editedContent)
      setDirty(false)
      setEditing(false)
      setValidationErrors([])
      setValidationOk(false)
      load()
      // Fetch post-save actions
      try {
        const ar = await api.get(`/build/editor/files/${selectedFile.id}/actions`)
        if (ar.data.length > 0) {
          setPostSaveActions(ar.data)
          setShowActions(true)
          setActionResult(null)
        }
      } catch { /* no actions available */ }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      if (detail?.errors) {
        setValidationErrors(detail.errors)
      } else {
        alert(typeof detail === 'string' ? detail : 'Save failed')
      }
    }
    setSaving(false)
  }

  const executeAction = async (actionId: string) => {
    if (!selectedFile) return
    setRunningAction(actionId)
    setActionResult(null)
    try {
      const r = await api.post(`/build/editor/files/${selectedFile.id}/actions/${actionId}`)
      setActionResult(r.data)
    } catch (e: any) {
      setActionResult({ success: false, output: '', error: e.response?.data?.detail || 'Action failed' })
    }
    setRunningAction(null)
  }

  const handleSaveShortcut = useCallback(() => {
    if (editing && dirty) handleSave()
  }, [editing, dirty])

  // History functions
  const loadHistory = async () => {
    if (!selectedFile) return
    setLoadingHistory(true)
    try {
      const r = await api.get(`/build/editor/files/${selectedFile.id}/history`)
      setHistory(r.data)
    } catch { setHistory([]) }
    setLoadingHistory(false)
  }

  const toggleHistory = () => {
    if (!showHistory) {
      loadHistory()
      setViewingVersion(null)
      setShowDiff(false)
      setShowHelp(false)
    }
    setShowHistory(!showHistory)
  }

  const viewVersion = async (version: number) => {
    if (!selectedFile) return
    setViewingVersion(version)
    setShowDiff(false)
    try {
      const r = await api.get(`/build/editor/files/${selectedFile.id}/history/${version}`)
      setVersionContent(r.data.content)
      setDiffContent(r.data.diff_patch || '')
    } catch { setVersionContent('// Failed to load version') }
  }

  const toggleDiff = () => setShowDiff(!showDiff)

  const handleRestore = async () => {
    if (!selectedFile || viewingVersion === null) return
    if (!confirm(`Restore ${selectedFile.display_name} to version ${viewingVersion}?`)) return
    setRestoring(true)
    try {
      await api.post(`/build/editor/files/${selectedFile.id}/restore/${viewingVersion}`)
      const r = await api.get(`/build/editor/files/${selectedFile.id}`)
      setFileContent(r.data.content || '')
      setEditedContent(r.data.content || '')
      setViewingVersion(null)
      setShowDiff(false)
      loadHistory()
      load()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Restore failed')
    }
    setRestoring(false)
  }

  // Scaffold functions
  const openScaffoldModal = async () => {
    setShowScaffold(true)
    setSelectedScaffold(null)
    setScaffoldVars({})
    try {
      const r = await api.get('/build/editor/scaffolds')
      setScaffolds(r.data)
    } catch { setScaffolds([]) }
  }

  const handleCreateScaffold = async () => {
    if (!selectedScaffold) return
    setCreatingScaffold(true)
    try {
      const r = await api.post(`/build/editor/scaffolds/${selectedScaffold.id}/create`, { variables: scaffoldVars })
      setShowScaffold(false)
      load()
      // Open the first created file
      if (r.data.files?.length > 0) {
        const created = r.data.files[0]
        openFile({ ...created, editable: true, exists: true, size: 0, purpose: '', last_modified_by: null, last_modified_at: null } as ConfigFile)
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to create from scaffold')
    }
    setCreatingScaffold(false)
  }

  // Help functions
  const toggleHelp = async () => {
    if (!showHelp && selectedFile) {
      setShowHistory(false)
      setLoadingHelp(true)
      try {
        const r = await api.get(`/build/editor/files/${selectedFile.id}/help`)
        setHelpData(r.data)
      } catch { setHelpData(null) }
      setLoadingHelp(false)
    }
    setShowHelp(!showHelp)
  }

  const filteredFiles = files.filter(f => {
    if (filterCategory && f.category !== filterCategory) return false
    if (search) {
      const q = search.toLowerCase()
      return f.display_name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q) || f.purpose.toLowerCase().includes(q)
    }
    return true
  })

  const grouped = CATEGORIES.map(cat => ({
    ...cat,
    files: filteredFiles.filter(f => f.category === cat.key),
  })).filter(g => g.files.length > 0)

  // Determine what to show in the editor
  const displayContent = viewingVersion !== null
    ? (showDiff ? diffContent : versionContent)
    : (editing ? editedContent : fileContent)
  const displayFormat = viewingVersion !== null && showDiff ? 'text' : (selectedFile?.format || 'text')

  return (
    <div className="flex h-[calc(100vh-4rem)] -m-6">
      {/* Sidebar — file browser */}
      <div className="w-80 border-r border-gray-200 bg-gray-50 flex flex-col overflow-hidden">
        <div className="p-3 border-b border-gray-200 space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700">Config Files</h2>
            <div className="flex gap-1">
              <button onClick={openScaffoldModal} className="text-xs px-2 py-1 rounded border border-blue-200 text-blue-600 hover:bg-blue-50" title="Create new file from template">
                + New
              </button>
              <button onClick={handleSeed} disabled={seeding} className="text-xs px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-white disabled:opacity-50">
                {seeding ? '...' : 'Seed'}
              </button>
            </div>
          </div>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search files..."
            className="w-full text-xs border border-gray-200 rounded px-2 py-1.5"
          />
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setFilterCategory(null)}
              className={`text-xs px-2 py-0.5 rounded ${!filterCategory ? 'bg-blue-100 text-blue-700' : 'bg-white text-gray-500 border border-gray-200'}`}
            >All</button>
            {CATEGORIES.map(c => (
              <button
                key={c.key}
                onClick={() => setFilterCategory(filterCategory === c.key ? null : c.key)}
                className={`text-xs px-2 py-0.5 rounded ${filterCategory === c.key ? 'bg-blue-100 text-blue-700' : 'bg-white text-gray-500 border border-gray-200'}`}
              >{c.icon}</button>
            ))}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="p-4 text-xs text-gray-400">Loading...</p>
          ) : files.length === 0 ? (
            <div className="p-4 text-center">
              <p className="text-sm text-gray-500">No files registered.</p>
              <button onClick={handleSeed} className="mt-2 text-xs text-blue-600 hover:underline">Seed file registry</button>
            </div>
          ) : (
            grouped.map(group => (
              <div key={group.key}>
                <div className="px-3 py-1.5 bg-gray-100 border-b border-gray-200 sticky top-0">
                  <span className="text-xs font-medium text-gray-600">{group.icon} {group.label}</span>
                  <span className="text-xs text-gray-400 ml-1">({group.files.length})</span>
                </div>
                {group.files.map(f => (
                  <button
                    key={f.id}
                    onClick={() => openFile(f)}
                    className={`w-full text-left px-3 py-2 border-b border-gray-100 hover:bg-white transition-colors ${selectedFile?.id === f.id ? 'bg-white border-l-2 border-l-blue-500' : ''}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-gray-800 truncate">{f.display_name}</span>
                      <span className={`text-[10px] px-1 py-0 rounded ${FORMAT_COLORS[f.format] || 'bg-gray-50 text-gray-500'}`}>{f.format}</span>
                      {!f.exists && <span className="text-[10px] text-red-500">✗</span>}
                      {!f.editable && <span className="text-[10px] text-gray-400">🔒</span>}
                    </div>
                    <p className="text-[11px] text-gray-400 truncate mt-0.5">{f.purpose}</p>
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Main panel — file content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {selectedFile ? (
          <>
            {/* File header */}
            <div className={`px-4 py-3 border-b bg-white ${dirty ? 'border-yellow-400' : 'border-gray-200'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-800">
                    {selectedFile.display_name}
                    {dirty && <span className="ml-1 text-yellow-500">●</span>}
                    {viewingVersion !== null && (
                      <span className="ml-2 text-xs text-purple-600 font-normal">viewing v{viewingVersion}</span>
                    )}
                  </h3>
                  <p className="text-xs text-gray-400 font-mono mt-0.5">{selectedFile.path}</p>
                </div>
                <div className="flex items-center gap-2">
                  {editing ? (
                    <>
                      <button onClick={handleValidate} disabled={validating} className="text-xs px-2.5 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50">
                        {validating ? '...' : '✓ Validate'}
                      </button>
                      <button onClick={handleSave} disabled={saving || !dirty} className="text-xs px-2.5 py-1 rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
                        {saving ? '...' : '💾 Save'}
                      </button>
                      <button onClick={handleCancel} className="text-xs px-2.5 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200">
                        Cancel
                      </button>
                    </>
                  ) : viewingVersion !== null ? (
                    <>
                      <button onClick={toggleDiff} className={`text-xs px-2.5 py-1 rounded ${showDiff ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'} hover:opacity-80`}>
                        {showDiff ? '📄 Content' : '± Diff'}
                      </button>
                      <button onClick={handleRestore} disabled={restoring} className="text-xs px-2.5 py-1 rounded bg-orange-50 text-orange-700 hover:bg-orange-100 disabled:opacity-50">
                        {restoring ? '...' : '↺ Restore'}
                      </button>
                      <button onClick={() => { setViewingVersion(null); setShowDiff(false) }} className="text-xs px-2.5 py-1 rounded bg-gray-100 text-gray-600 hover:bg-gray-200">
                        ← Back
                      </button>
                    </>
                  ) : (
                    <>
                      <span className={`text-xs px-2 py-0.5 rounded ${FORMAT_COLORS[selectedFile.format] || 'bg-gray-50 text-gray-500'}`}>
                        {selectedFile.format}
                      </span>
                      <button onClick={toggleHistory} className={`text-xs px-2.5 py-1 rounded ${showHistory ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'} hover:opacity-80`}>
                        🕒 History
                      </button>
                      <button onClick={toggleHelp} className={`text-xs px-2.5 py-1 rounded ${showHelp ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600'} hover:opacity-80`}>
                        ? Help
                      </button>
                      {selectedFile.editable && selectedFile.exists ? (
                        <button onClick={handleEdit} className="text-xs px-2.5 py-1 rounded bg-blue-50 text-blue-700 hover:bg-blue-100">
                          ✏️ Edit
                        </button>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-500">read-only</span>
                      )}
                      {!selectedFile.exists && (
                        <span className="text-xs px-2 py-0.5 rounded bg-red-50 text-red-600">file missing</span>
                      )}
                    </>
                  )}
                </div>
              </div>
              {selectedFile.last_modified_by && !editing && viewingVersion === null && (
                <p className="text-[11px] text-gray-400 mt-1">
                  Last modified by {selectedFile.last_modified_by} on {selectedFile.last_modified_at ? new Date(selectedFile.last_modified_at).toLocaleString() : 'unknown'}
                </p>
              )}
            </div>

            {/* Post-save actions bar */}
            {showActions && postSaveActions.length > 0 && (
              <div className="px-4 py-2 bg-blue-50 border-b border-blue-200">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-blue-700 font-medium">✓ Saved —</span>
                    {postSaveActions.map(a => (
                      <button
                        key={a.id}
                        onClick={() => executeAction(a.id)}
                        disabled={runningAction !== null}
                        title={a.description}
                        className="text-xs px-2 py-0.5 rounded bg-white border border-blue-200 text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                      >
                        {runningAction === a.id ? '...' : `${a.icon} ${a.label}`}
                      </button>
                    ))}
                  </div>
                  <button onClick={() => { setShowActions(false); setActionResult(null) }} className="text-xs text-blue-400 hover:text-blue-600">✕</button>
                </div>
                {actionResult && (
                  <p className={`text-xs mt-1 ${actionResult.success ? 'text-green-700' : 'text-red-600'}`}>
                    {actionResult.success ? `✓ ${actionResult.output}` : `✗ ${actionResult.error || actionResult.output}`}
                  </p>
                )}
              </div>
            )}

            {/* Validation feedback */}
            {validationErrors.length > 0 && (
              <div className="px-4 py-2 bg-red-50 border-b border-red-200">
                <p className="text-xs font-medium text-red-700 mb-1">Validation errors:</p>
                {validationErrors.map((err, i) => (
                  <p key={i} className="text-xs text-red-600">Line {err.line}: {err.message}</p>
                ))}
              </div>
            )}
            {validationOk && (
              <div className="px-4 py-2 bg-green-50 border-b border-green-200">
                <p className="text-xs text-green-700">✓ Syntax valid</p>
              </div>
            )}

            {/* Content area */}
            <div className="flex-1 overflow-hidden bg-gray-900">
              {loadingContent ? (
                <p className="p-4 text-sm text-gray-400">Loading...</p>
              ) : (
                <CodeViewer
                  content={displayContent || '(empty file)'}
                  format={displayFormat}
                  readOnly={!editing || viewingVersion !== null}
                  onChange={editing && viewingVersion === null ? handleChange : undefined}
                  onSave={editing ? handleSaveShortcut : undefined}
                />
              )}
            </div>

            {/* Footer */}
            <div className="px-4 py-2 border-t border-gray-200 bg-gray-50 flex items-center justify-between">
              <span className="text-xs text-gray-400">
                {selectedFile.size > 0 ? `${selectedFile.size.toLocaleString()} bytes` : ''}
              </span>
              <span className="text-xs text-gray-400">
                {displayContent.split('\n').length} lines
                {editing && ' • Ctrl+S to save'}
              </span>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center bg-gray-50">
            <div className="text-center">
              <p className="text-lg text-gray-300">📝</p>
              <p className="text-sm text-gray-400 mt-2">Select a file to view</p>
              <p className="text-xs text-gray-300 mt-1">{files.length} files registered</p>
            </div>
          </div>
        )}
      </div>

      {/* History panel (slide-out) */}
      {showHistory && selectedFile && (
        <div className="w-72 border-l border-gray-200 bg-white flex flex-col overflow-hidden">
          <div className="px-3 py-2.5 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-700">🕒 Version History</h3>
            <button onClick={() => setShowHistory(false)} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {loadingHistory ? (
              <p className="p-3 text-xs text-gray-400">Loading...</p>
            ) : history.length === 0 ? (
              <p className="p-3 text-xs text-gray-400">No versions recorded yet. Versions are created when you save edits.</p>
            ) : (
              history.map(v => (
                <button
                  key={v.version}
                  onClick={() => viewVersion(v.version)}
                  className={`w-full text-left px-3 py-2.5 border-b border-gray-100 hover:bg-gray-50 transition-colors ${viewingVersion === v.version ? 'bg-purple-50 border-l-2 border-l-purple-500' : ''}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-700">v{v.version}</span>
                    <span className="text-[10px] text-gray-400">{v.edited_by}</span>
                  </div>
                  <p className="text-[10px] text-gray-400 mt-0.5">
                    {v.edited_at ? new Date(v.edited_at).toLocaleString() : ''}
                  </p>
                  {v.comment && (
                    <p className="text-[10px] text-gray-500 mt-0.5 italic">{v.comment}</p>
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Help panel (slide-out) */}
      {showHelp && selectedFile && (
        <div className="w-80 border-l border-gray-200 bg-white flex flex-col overflow-hidden">
          <div className="px-3 py-2.5 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-gray-700">? Help — {selectedFile.display_name}</h3>
            <button onClick={() => setShowHelp(false)} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {loadingHelp ? (
              <p className="text-xs text-gray-400">Loading...</p>
            ) : !helpData || (!helpData.summary && helpData.directives.length === 0) ? (
              <div className="space-y-2">
                <p className="text-xs text-gray-500 italic">No detailed help available for this file.</p>
                <p className="text-xs text-gray-400">{selectedFile.purpose}</p>
              </div>
            ) : (
              <>
                {helpData.summary && (
                  <div>
                    <p className="text-xs text-gray-600 leading-relaxed">{helpData.summary}</p>
                  </div>
                )}
                {helpData.directives.length > 0 && (
                  <div>
                    <h4 className="text-[11px] font-semibold text-gray-700 mb-1.5">Key Directives</h4>
                    <div className="space-y-1.5">
                      {helpData.directives.map((d, i) => (
                        <div key={i} className="bg-gray-50 rounded px-2 py-1.5">
                          <code className="text-[10px] font-mono text-blue-700">{d.key}</code>
                          <p className="text-[10px] text-gray-500 mt-0.5">{d.purpose}</p>
                          {d.default && <p className="text-[10px] text-gray-400">Default: <code className="text-gray-500">{d.default}</code></p>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {helpData.examples.length > 0 && (
                  <div>
                    <h4 className="text-[11px] font-semibold text-gray-700 mb-1.5">Examples</h4>
                    {helpData.examples.map((ex, i) => (
                      <div key={i} className="mb-2">
                        <p className="text-[10px] text-gray-500 mb-0.5">{ex.title}</p>
                        <pre className="text-[10px] font-mono bg-gray-900 text-gray-200 rounded p-2 overflow-x-auto">{ex.code}</pre>
                      </div>
                    ))}
                  </div>
                )}
                {helpData.related_docs.length > 0 && (
                  <div>
                    <h4 className="text-[11px] font-semibold text-gray-700 mb-1">Related Documentation</h4>
                    <ul className="space-y-0.5">
                      {helpData.related_docs.map((doc, i) => (
                        <li key={i} className="text-[10px] text-blue-600">📖 {doc}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}
          </div>
          <div className="px-3 py-2 border-t border-gray-200 bg-gray-50">
            <p className="text-[10px] text-gray-400">Ctrl+F search • Ctrl+S save</p>
          </div>
        </div>
      )}

      {/* Scaffold modal */}
      {showScaffold && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-gray-800">Create New File</h3>
              <button onClick={() => setShowScaffold(false)} className="text-gray-400 hover:text-gray-600">✕</button>
            </div>

            {!selectedScaffold ? (
              <div className="grid grid-cols-2 gap-3">
                {scaffolds.map(s => (
                  <button
                    key={s.id}
                    onClick={() => { setSelectedScaffold(s); setScaffoldVars({}) }}
                    className="text-left p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-colors"
                  >
                    <span className="text-lg">{s.icon}</span>
                    <p className="text-xs font-medium text-gray-800 mt-1">{s.name}</p>
                    <p className="text-[10px] text-gray-500 mt-0.5">{s.description}</p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-2 pb-2 border-b border-gray-100">
                  <span className="text-lg">{selectedScaffold.icon}</span>
                  <div>
                    <p className="text-xs font-medium text-gray-800">{selectedScaffold.name}</p>
                    <p className="text-[10px] text-gray-500">{selectedScaffold.description}</p>
                  </div>
                </div>

                {selectedScaffold.variables.map(v => (
                  <div key={v.name}>
                    <label className="text-xs text-gray-600 block mb-0.5">
                      {v.label}{v.required && <span className="text-red-500"> *</span>}
                    </label>
                    <input
                      type="text"
                      value={scaffoldVars[v.name] || ''}
                      onChange={e => setScaffoldVars({ ...scaffoldVars, [v.name]: e.target.value })}
                      placeholder={v.placeholder}
                      className="w-full text-xs border border-gray-200 rounded px-2.5 py-1.5 focus:border-blue-300 focus:outline-none"
                    />
                  </div>
                ))}

                <div className="flex justify-between pt-2">
                  <button onClick={() => setSelectedScaffold(null)} className="text-xs px-3 py-1.5 rounded bg-gray-100 text-gray-600 hover:bg-gray-200">
                    ← Back
                  </button>
                  <button
                    onClick={handleCreateScaffold}
                    disabled={creatingScaffold}
                    className="text-xs px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {creatingScaffold ? 'Creating...' : 'Create'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Save confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-sm font-semibold text-gray-800 mb-2">Confirm Save</h3>
            <p className="text-xs text-gray-600 mb-4">
              You are about to modify <span className="font-mono font-medium">{selectedFile?.display_name}</span>.
              A backup will be created before overwriting.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowConfirm(false)} className="text-xs px-3 py-1.5 rounded bg-gray-100 text-gray-600 hover:bg-gray-200">
                Cancel
              </button>
              <button onClick={confirmSave} className="text-xs px-3 py-1.5 rounded bg-green-600 text-white hover:bg-green-700">
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
