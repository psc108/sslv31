import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import api from '@/lib/api'

interface Job {
  id: string
  name: string
  job_type: string
  status: string
  playbook: string
  environment_id: string | null
  inventory_filter: string
  exit_code: number | null
  duration_seconds: number | null
  dry_run: boolean
  failed_hosts: string[]
  created_by: string
  started_at: string | null
  finished_at: string | null
  created_at: string
  // Improvements Plan Stage 21 — only present on a single-job fetch
  // (GET /build/jobs/{id}), not the list. null = not yet scanned (job
  // hasn't finished failed, or predates this feature); [] = scanned,
  // nothing found; undefined = this Job object came from the list
  // endpoint, which doesn't resolve it.
  related_bugs?: { id: string; title: string; status: string; severity: string }[] | null
}

interface LogLine {
  timestamp: string | null
  stream: string
  line: string
}

export default function JobsPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<Job | null>(null)
  const [output, setOutput] = useState<LogLine[]>([])
  const [streaming, setStreaming] = useState(false)
  // Bug Tracker cross-navigation (Improvements Plan Stage 20) — the bug-
  // filing/browsing UI lives only in Docs, same mechanism JAR Analyser's
  // "Report Bug" button already uses (JarAnalyserPage.tsx's openBugTracker).
  const [bugCount, setBugCount] = useState<number | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState<string>('all')
  const [logSearch, setLogSearch] = useState('')
  const [skippedOnly, setSkippedOnly] = useState(false)

  const terminalRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const [form, setForm] = useState({ name: '', playbook: '', inventory_filter: '', extra_vars: '{}', dry_run: false })

  const loadJobs = useCallback(async () => {
    try {
      const res = await api.get('/build/jobs')
      setJobs(res.data)
    } catch { setError('Failed to load jobs') }
  }, [])

  useEffect(() => { loadJobs() }, [loadJobs])

  // Auto-select job from URL param
  useEffect(() => {
    const jobId = searchParams.get('id')
    if (jobId && jobs.length > 0) {
      const job = jobs.find(j => j.id === jobId)
      if (job && selected?.id !== jobId) selectJob(job)
    }
  }, [searchParams, jobs])

  // Auto-select first running job if none selected
  useEffect(() => {
    if (!selected) {
      const running = jobs.find(j => j.status === 'running' || j.status === 'pending')
      if (running) selectJob(running)
    }
  }, [jobs])

  // Poll job list for status changes
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'running' || j.status === 'pending')
    if (!hasActive) return
    const interval = setInterval(loadJobs, 5000)
    return () => clearInterval(interval)
  }, [jobs, loadJobs])

  // Auto-scroll terminal
  useEffect(() => {
    if (autoScroll && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight
    }
  }, [output, autoScroll])

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { eventSourceRef.current?.close() }
  }, [])

  const selectJob = async (job: Job) => {
    // Close existing stream
    eventSourceRef.current?.close()
    setSelected(job)
    setOutput([])
    setStreaming(false)
    setBugCount(null)

    if (job.status === 'running' || job.status === 'pending') {
      startStream(job.id)
    } else {
      // Fetch full output for completed jobs
      try {
        const res = await api.get(`/build/jobs/${job.id}/output`)
        setOutput(res.data.lines)
      } catch { setOutput([]) }
    }

    try {
      const res = await api.get('/bugs', { params: { bm_job_id: job.id, page_size: 1 } })
      setBugCount(res.data.total)
    } catch { setBugCount(null) }

    // Improvements Plan Stage 21 — related_bugs is only resolved on the
    // single-job fetch, not the list this `job` param came from, so a
    // dedicated call is needed (same reasoning as the bug-count fetch
    // above already being separate from the list endpoint).
    try {
      const res = await api.get(`/build/jobs/${job.id}`)
      setSelected(prev => (prev && prev.id === job.id ? { ...prev, related_bugs: res.data.related_bugs } : prev))
    } catch { /* leave related_bugs undefined — panel just won't show */ }
  }

  const openBugTracker = (mode: 'new' | 'list', jobId: string) => {
    navigate(`/docs?${new URLSearchParams({ bugs: '1', action: mode, jobId }).toString()}`)
  }

  // Same cross-navigation mechanism, but straight to one specific bug —
  // used by the Related Bugs panel (Improvements Plan Stage 21), mirroring
  // JAR Analyser's own openBug in JarAnalyserPage.tsx.
  const openBug = (bugId: string) => {
    navigate(`/docs?${new URLSearchParams({ bugs: '1', action: 'view', bugId }).toString()}`)
  }

  const startStream = (jobId: string) => {
    setStreaming(true)
    const token = localStorage.getItem('token')
    const apiKey = localStorage.getItem('api_key')
    // Use polling-based streaming since SSE doesn't easily support auth headers
    const pollStream = async () => {
      let seen = 0
      const poll = async () => {
        try {
          const [jobRes, outRes] = await Promise.all([
            api.get(`/build/jobs/${jobId}`),
            api.get(`/build/jobs/${jobId}/output`, { params: { after: seen } }),
          ])
          const jobData = jobRes.data as Job
          setSelected(jobData)

          if (outRes.data.lines.length > 0) {
            setOutput(prev => [...prev, ...outRes.data.lines])
            seen = outRes.data.total_lines
          }

          if (jobData.status === 'running' || jobData.status === 'pending') {
            setTimeout(poll, 1000)
          } else {
            setStreaming(false)
            loadJobs()
          }
        } catch {
          setStreaming(false)
        }
      }
      poll()
    }
    pollStream()
  }

  const submitJob = async () => {
    try {
      const body = {
        name: form.name,
        playbook: form.playbook,
        inventory_filter: form.inventory_filter,
        extra_vars: JSON.parse(form.extra_vars),
        dry_run: form.dry_run,
      }
      const res = await api.post('/build/jobs', body)
      setShowCreate(false)
      setForm({ name: '', playbook: '', inventory_filter: '', extra_vars: '{}', dry_run: false })
      setSuccess('Job submitted')
      await loadJobs()
      selectJob(res.data)
    } catch (e: any) { setError(e.response?.data?.detail || 'Failed to submit job') }
  }

  const cancelJob = async (id: string) => {
    try {
      await api.post(`/build/jobs/${id}/cancel`)
      setSuccess('Job cancelled')
      loadJobs()
    } catch (e: any) { setError(e.response?.data?.detail || 'Cancel failed') }
  }

  const retryJob = async (id: string) => {
    try {
      const res = await api.post(`/build/jobs/${id}/retry`)
      setSuccess(res.data.failed_hosts?.length ? `Retrying ${res.data.failed_hosts.length} failed host(s)` : 'Retrying job (full re-run)')
      await loadJobs()
      selectJob(res.data)
    } catch (e: any) { setError(e.response?.data?.detail || 'Retry failed') }
  }

  const deleteJob = async (id: string) => {
    if (!confirm('Delete this job record?')) return
    try {
      await api.delete(`/build/jobs/${id}`)
      if (selected?.id === id) { setSelected(null); setOutput([]) }
      loadJobs()
    } catch (e: any) { setError(e.response?.data?.detail || 'Delete failed') }
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-700',
      running: 'bg-blue-100 text-blue-800',
      success: 'bg-green-100 text-green-800',
      failed: 'bg-red-100 text-red-800',
      cancelled: 'bg-yellow-100 text-yellow-800',
    }
    return (
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
        {status === 'running' && <span className="inline-block w-2 h-2 bg-blue-500 rounded-full mr-1 animate-pulse" />}
        {status}
      </span>
    )
  }

  const formatDuration = (job: Job) => {
    if (job.duration_seconds !== null) {
      const s = job.duration_seconds
      if (s < 60) return `${Math.round(s)}s`
      return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
    }
    if (job.started_at && job.status === 'running') {
      const elapsed = (Date.now() - new Date(job.started_at).getTime()) / 1000
      if (elapsed < 60) return `${Math.round(elapsed)}s`
      return `${Math.floor(elapsed / 60)}m ${Math.round(elapsed % 60)}s`
    }
    return '—'
  }

  const filteredJobs = filter === 'all' ? jobs : jobs.filter(j => j.status === filter)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Jobs & Progress Monitor</h1>
          <p className="text-sm text-gray-500 mt-1">Real-time Ansible playbook execution</p>
        </div>
        <div className="flex gap-2">
          <button onClick={loadJobs} className="px-3 py-2 bg-gray-100 text-gray-700 text-sm rounded-md hover:bg-gray-200">↻ Refresh</button>
          <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">+ Run Playbook</button>
        </div>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">{error}<button onClick={() => setError('')} className="ml-2 font-bold">✕</button></div>}
      {success && <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-700">{success}<button onClick={() => setSuccess('')} className="ml-2 font-bold">✕</button></div>}

      {/* Submit Job Form */}
      {showCreate && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          <h3 className="font-medium text-gray-900">Run Playbook</h3>
          <div className="grid grid-cols-2 gap-3">
            <input placeholder="Job Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm" />
            <input placeholder="Playbook (e.g. site.yml)" value={form.playbook} onChange={e => setForm({ ...form, playbook: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm" />
            <input placeholder="Limit (host/group filter)" value={form.inventory_filter} onChange={e => setForm({ ...form, inventory_filter: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm" />
            <input placeholder='Extra vars (JSON)' value={form.extra_vars} onChange={e => setForm({ ...form, extra_vars: e.target.value })}
              className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" />
          </div>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.dry_run} onChange={e => setForm({ ...form, dry_run: e.target.checked })} />
            Dry run (<code>--check --diff</code> — preview only, no changes applied. Note: command/shell tasks often report inaccurately under check mode.)
          </label>
          <div className="flex gap-2">
            <button onClick={submitJob} disabled={!form.name || !form.playbook}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">Submit</button>
            <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
          </div>
        </div>
      )}

      {/* Main layout: job list + terminal */}
      <div className="grid grid-cols-12 gap-4" style={{ minHeight: '600px' }}>
        {/* Job List (left panel) */}
        <div className="col-span-4 bg-white border border-gray-200 rounded-lg flex flex-col overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-200 bg-gray-50 flex items-center gap-2">
            <span className="text-xs font-medium text-gray-600">Filter:</span>
            {['all', 'running', 'pending', 'success', 'failed'].map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`text-xs px-2 py-0.5 rounded ${filter === f ? 'bg-blue-100 text-blue-700 font-medium' : 'text-gray-500 hover:text-gray-700'}`}>
                {f}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
            {filteredJobs.map(job => (
              <div key={job.id}
                onClick={() => selectJob(job)}
                className={`px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors ${selected?.id === job.id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''}`}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-900 truncate">{job.name}</span>
                  {statusBadge(job.status)}
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                  <span className="font-mono" title={job.id}>#{job.id.slice(0, 8)}</span>
                  <span>{job.playbook}</span>
                  <span>{formatDuration(job)}</span>
                  {job.dry_run && <span className="text-amber-600 font-medium">🔍 dry-run</span>}
                </div>
              </div>
            ))}
            {filteredJobs.length === 0 && (
              <div className="px-4 py-8 text-center text-gray-400 text-sm">No jobs match filter</div>
            )}
          </div>
        </div>

        {/* Terminal / Output (right panel) */}
        <div className="col-span-8 bg-gray-900 rounded-lg flex flex-col overflow-hidden border border-gray-700">
          {selected ? (
            <>
              {/* Terminal header */}
              <div className="px-4 py-2 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex gap-1.5">
                    <div className={`w-3 h-3 rounded-full ${selected.status === 'running' ? 'bg-green-500 animate-pulse' : selected.status === 'success' ? 'bg-green-500' : selected.status === 'failed' ? 'bg-red-500' : 'bg-yellow-500'}`} />
                  </div>
                  <span className="text-sm text-gray-200 font-medium">{selected.name}</span>
                  {selected.dry_run && <span className="text-xs px-1.5 py-0.5 bg-amber-900 text-amber-300 rounded">🔍 DRY RUN</span>}
                  {streaming && <span className="text-xs text-green-400 animate-pulse">● LIVE</span>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">{output.length} lines</span>
                  <button onClick={() => setAutoScroll(!autoScroll)}
                    className={`text-xs px-2 py-0.5 rounded ${autoScroll ? 'bg-green-900 text-green-300' : 'bg-gray-700 text-gray-400'}`}>
                    {autoScroll ? '⬇ Auto-scroll' : '⏸ Paused'}
                  </button>
                  {(selected.status === 'running' || selected.status === 'pending') && (
                    <button onClick={() => cancelJob(selected.id)}
                      className="text-xs px-2 py-0.5 bg-red-900 text-red-300 rounded hover:bg-red-800">⏹ Cancel</button>
                  )}
                  {selected.status === 'failed' && (
                    <button onClick={() => retryJob(selected.id)}
                      title={selected.failed_hosts?.length ? `Retry just: ${selected.failed_hosts.join(', ')}` : 'Retry (full re-run)'}
                      className="text-xs px-2 py-0.5 bg-blue-900 text-blue-300 rounded hover:bg-blue-800">
                      🔁 {selected.failed_hosts?.length ? `Retry ${selected.failed_hosts.length} Failed Host${selected.failed_hosts.length > 1 ? 's' : ''}` : 'Retry'}
                    </button>
                  )}
                  {['success', 'failed', 'cancelled'].includes(selected.status) && (
                    <button onClick={() => deleteJob(selected.id)}
                      className="text-xs px-2 py-0.5 bg-gray-700 text-gray-400 rounded hover:bg-gray-600">🗑️</button>
                  )}
                  <button onClick={() => openBugTracker('new', selected.id)}
                    className="text-xs px-2 py-0.5 bg-rose-900 text-rose-300 rounded hover:bg-rose-800">
                    🐛 Report Bug
                  </button>
                  {!!bugCount && (
                    <button onClick={() => openBugTracker('list', selected.id)}
                      className="text-xs px-2 py-0.5 bg-gray-700 text-gray-300 rounded hover:bg-gray-600">
                      🐛 {bugCount} bug{bugCount !== 1 ? 's' : ''}
                    </button>
                  )}
                </div>
              </div>

              {/* Job info bar */}
              <div className="px-4 py-1.5 bg-gray-850 border-b border-gray-700 flex items-center gap-4 text-xs text-gray-400" style={{ backgroundColor: '#1a2332' }}>
                <span className="font-mono" title={selected.id}>#{selected.id.slice(0, 8)}</span>
                <span>📋 {selected.playbook}</span>
                <span>👤 {selected.created_by}</span>
                <span>⏱ {formatDuration(selected)}</span>
                {selected.exit_code !== null && <span>Exit: <span className={selected.exit_code === 0 ? 'text-green-400' : 'text-red-400'}>{selected.exit_code}</span></span>}
                {selected.inventory_filter && <span>🎯 {selected.inventory_filter}</span>}
              </div>

              {/* Related Bugs (Improvements Plan Stage 21) — a "worth
                  checking" signal against this job's own failure output,
                  same deliberately-loose ranking as JAR Analyser's own
                  panel; only shown when the scan actually found something. */}
              {!!selected.related_bugs?.length && (
                <div className="px-4 py-2 bg-amber-950 border-b border-amber-800 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-amber-300 font-medium">🐛 Related Bugs:</span>
                  {selected.related_bugs.map(b => (
                    <button key={b.id} onClick={() => openBug(b.id)}
                      className="px-2 py-0.5 bg-amber-900 text-amber-200 rounded hover:bg-amber-800">
                      {b.title} <span className="text-amber-400">({b.status})</span>
                    </button>
                  ))}
                </div>
              )}

              {/* Log search/filter bar — Ansible's raw output doesn't say
                  *why* a task skipped (the when: condition text isn't
                  printed), just "skipping: [host]"/"skipping: [host] =>
                  (item=X)"; this at least makes those lines (or any other
                  text) findable without scrolling the whole log by hand. */}
              <div className="px-4 py-1.5 bg-gray-800 border-b border-gray-700 flex items-center gap-2">
                <input value={logSearch} onChange={e => setLogSearch(e.target.value)}
                  placeholder="Search log output..."
                  className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-500" />
                <button onClick={() => setSkippedOnly(!skippedOnly)}
                  className={`text-xs px-2 py-1 rounded whitespace-nowrap ${skippedOnly ? 'bg-amber-900 text-amber-300' : 'bg-gray-700 text-gray-400 hover:bg-gray-600'}`}>
                  Skipped only
                </button>
              </div>

              {/* Terminal output */}
              <div ref={terminalRef} className="flex-1 overflow-auto p-3 font-mono text-xs leading-5"
                onScroll={(e) => {
                  const el = e.currentTarget
                  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
                  if (!atBottom && autoScroll) setAutoScroll(false)
                  if (atBottom && !autoScroll) setAutoScroll(true)
                }}>
                {(() => {
                  const visible = output.filter(l =>
                    (!skippedOnly || /^skipping:|^skipped:/i.test(l.line.trim())) &&
                    (!logSearch || l.line.toLowerCase().includes(logSearch.toLowerCase()))
                  )
                  if (output.length > 0 && visible.length === 0) {
                    return <div className="text-gray-500 italic">No lines match{skippedOnly ? ' "Skipped only"' : ''}{logSearch ? ` + "${logSearch}"` : ''}.</div>
                  }
                  return visible.map((l, i) => (
                    <div key={i} className={`whitespace-pre-wrap ${getLineColor(l)}`}>
                      {l.line}
                    </div>
                  ))
                })()}
                {output.length === 0 && (
                  <div className="flex items-center justify-center h-full text-gray-500">
                    {selected.status === 'pending' ? (
                      <div className="text-center">
                        <div className="text-2xl mb-2">⏳</div>
                        <div>Waiting to start...</div>
                      </div>
                    ) : selected.status === 'running' ? (
                      <div className="text-center">
                        <div className="text-2xl mb-2 animate-spin">⚙️</div>
                        <div>Connecting to output stream...</div>
                      </div>
                    ) : (
                      <div className="text-center">
                        <div className="text-2xl mb-2">📭</div>
                        <div>No output captured</div>
                      </div>
                    )}
                  </div>
                )}
                {/* Completion banner */}
                {selected.status === 'success' && output.length > 0 && (
                  <div className="mt-3 px-3 py-2 bg-green-900/30 border border-green-700 rounded text-green-400 text-center">
                    ✅ Job completed successfully (exit code 0)
                  </div>
                )}
                {selected.status === 'failed' && output.length > 0 && (
                  <div className="mt-3 px-3 py-2 bg-red-900/30 border border-red-700 rounded text-red-400 text-center">
                    ❌ Job failed (exit code {selected.exit_code})
                  </div>
                )}
                {selected.status === 'cancelled' && output.length > 0 && (
                  <div className="mt-3 px-3 py-2 bg-yellow-900/30 border border-yellow-700 rounded text-yellow-400 text-center">
                    ⏹ Job cancelled
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <div className="text-4xl mb-3">📺</div>
                <div className="text-sm">Select a job to view output</div>
                <div className="text-xs mt-1 text-gray-600">Running jobs will stream output in real-time</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** Color Ansible output lines based on content */
function getLineColor(line: LogLine): string {
  if (line.stream === 'stderr') return 'text-red-400'
  const text = line.line
  if (text.startsWith('PLAY [') || text.startsWith('PLAY RECAP')) return 'text-cyan-300 font-bold'
  if (text.startsWith('TASK [')) return 'text-cyan-400'
  if (text.startsWith('ok:')) return 'text-green-400'
  if (text.startsWith('changed:')) return 'text-yellow-300'
  if (text.startsWith('skipping:') || text.startsWith('skipped:')) return 'text-gray-500'
  if (text.startsWith('fatal:') || text.startsWith('failed:')) return 'text-red-400 font-bold'
  if (text.startsWith('FAILED!') || text.includes('UNREACHABLE!')) return 'text-red-500 font-bold'
  if (text.includes('...ignoring')) return 'text-yellow-600'
  if (text.startsWith('included:') || text.startsWith('including:')) return 'text-gray-400'
  if (/^\s*(ok|changed|unreachable|failed|skipped|rescued|ignored)=/.test(text)) return 'text-white font-bold'
  return 'text-gray-300'
}
