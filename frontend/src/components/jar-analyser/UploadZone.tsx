import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

interface Props {
  onUploaded: (reportId: string) => void
  pollUploadId?: string  // skip upload, go straight to polling
}

export default function UploadZone({ onUploaded, pollUploadId }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [label, setLabel] = useState('')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<string | null>(pollUploadId ? 'Analysing...' : null)
  const [duplicate, setDuplicate] = useState<{ existing_report_id: string; filename: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // If a re-run upload ID was passed in, start polling immediately
  const startPolling = (uploadId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const r = await api.get(`/jar-analyser/uploads/${uploadId}/status`)
        const s = r.data
        if (s.status === 'completed' && s.report_id) {
          clearInterval(pollRef.current!)
          onUploaded(s.report_id)
        } else if (s.status === 'failed') {
          clearInterval(pollRef.current!)
          setProgress('Analysis failed.')
        } else {
          setProgress(`Analysing... (${s.status})`)
        }
      } catch {
        clearInterval(pollRef.current!)
        setProgress('Error polling status.')
      }
    }, 2000)
  }

  // Kick off polling for re-run on mount
  useEffect(() => {
    if (pollUploadId) startPolling(pollUploadId)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const mutation = useMutation({
    mutationFn: async (f: File) => {
      const fd = new FormData()
      fd.append('file', f)
      if (label) fd.append('label', label)
      const res = await api.post('/jar-analyser/upload', fd, {
        params: { skip_if_duplicate: false },
      })
      return res.data
    },
    onSuccess: (data) => {
      if (data.status === 'duplicate_skipped') {
        setDuplicate({ existing_report_id: data.existing_report_id, filename: data.filename })
        return
      }
      if (data.duplicate && data.existing_report_id) {
        setDuplicate({ existing_report_id: data.existing_report_id, filename: data.filename })
      }
      const uploadId: string = data.upload_id
      setProgress('Analysing...')
      startPolling(uploadId)
    },
  })

  const handleFile = (f: File) => {
    if (!f.name.match(/\.(jar|war|zip)$/i)) return
    setFile(f)
    setDuplicate(null)
    setProgress(null)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const handleUpload = () => {
    if (!file) return
    mutation.mutate(file)
  }

  const isPending = mutation.isPending || (progress !== null && progress.startsWith('Analysing'))

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <h1 className="text-2xl font-bold text-gray-900">JAR Analyser</h1>
      <p className="text-sm text-gray-500">Upload a JAR or WAR file to generate a full technical analysis report.</p>

      {duplicate && (
        <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800 flex items-center justify-between">
          <span>This JAR was previously uploaded.</span>
          <button
            onClick={() => onUploaded(duplicate.existing_report_id)}
            className="ml-3 px-3 py-1 bg-amber-600 text-white rounded text-xs hover:bg-amber-700"
          >
            View existing report
          </button>
        </div>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => !isPending && inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
          dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400 bg-white'
        } ${isPending ? 'pointer-events-none opacity-60' : ''}`}
      >
        <input ref={inputRef} type="file" accept=".jar,.war,.zip" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }} />
        <div className="text-4xl mb-3">📦</div>
        {file ? (
          <div>
            <p className="font-medium text-gray-900">{file.name}</p>
            <p className="text-sm text-gray-500 mt-1">
              {(file.size / 1024 / 1024).toFixed(1)} MB
              {file.name.endsWith('.zip') && ' · ZIP bundle'}
            </p>
          </div>
        ) : (
          <div>
            <p className="text-gray-600 font-medium">Drag & drop a JAR, WAR, or ZIP bundle here, or click to browse</p>
            <p className="text-sm text-gray-400 mt-1">Supported: .jar, .war, .zip (bundle of JARs) — Max 5 GB</p>
          </div>
        )}
      </div>

      <div className="flex gap-3 items-end">
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">Label (optional)</label>
          <input
            type="text"
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="e.g. CPI Services v2.6.9"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            disabled={isPending}
          />
        </div>
        <button
          onClick={handleUpload}
          disabled={!file || isPending}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {isPending ? 'Uploading...' : 'Upload & Analyse'}
        </button>
      </div>

      {progress && (
        <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-700 flex items-center gap-2">
          {progress.startsWith('Analysing') && (
            <svg className="animate-spin h-4 w-4 text-blue-600" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
          )}
          {progress}
        </div>
      )}

      {mutation.isError && (
        <p className="text-red-600 text-sm">
          {(mutation.error as any)?.response?.data?.detail || 'Upload failed'}
        </p>
      )}
    </div>
  )
}
