import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import SANEditor from '@/components/SANEditor'
import { formatDate, parseSubject, authenticatedDownload } from '@/lib/utils'
import type { SANEntry, Subject } from '@/lib/types'

interface CSRRecord {
  id: string
  mode: string
  subject_json: string
  san_json: string
  key_algo: string
  key_size: number
  status: string
  signed_cert_id: string | null
  has_stored_key: boolean
  created_at: string
}

export default function CSRPage() {
  const queryClient = useQueryClient()
  const [showWizard, setShowWizard] = useState(false)
  const [importingCsrId, setImportingCsrId] = useState<string | null>(null)
  const [signingCsrId, setSigningCsrId] = useState<string | null>(null)

  const { data: csrs = [], isLoading } = useQuery<CSRRecord[]>({
    queryKey: ['csrs'],
    queryFn: async () => (await api.get('/csr')).data,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.delete(`/csr/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['csrs'] }),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">CSR Manager</h2>
          <p className="text-sm text-gray-500 mt-1">Generate and manage Certificate Signing Requests</p>
        </div>
        <button onClick={() => setShowWizard(!showWizard)}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700">
          {showWizard ? 'Cancel' : '+ New CSR'}
        </button>
      </div>

      {showWizard && <CSRWizard onSuccess={() => setShowWizard(false)} />}

      {importingCsrId && (
        <ImportCertForm
          csrId={importingCsrId}
          onSuccess={() => setImportingCsrId(null)}
          onCancel={() => setImportingCsrId(null)}
        />
      )}

      {signingCsrId && (
        <SignCSRForm
          csrId={signingCsrId}
          onSuccess={() => setSigningCsrId(null)}
          onCancel={() => setSigningCsrId(null)}
        />
      )}

      {/* CSR List */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">CN</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Mode</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Key</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Created</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Status</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading && <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">Loading...</td></tr>}
            {!isLoading && csrs.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No CSRs generated yet</td></tr>}
            {csrs.map(csr => {
              const subject = parseSubject(csr.subject_json)
              return (
                <tr key={csr.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-900">{subject.cn}</td>
                  <td className="px-4 py-3 text-gray-600 capitalize">{csr.mode.replace('_', ' ')}</td>
                  <td className="px-4 py-3 text-gray-600">{csr.key_algo} {csr.key_size}</td>
                  <td className="px-4 py-3 text-gray-600">{formatDate(csr.created_at)}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      csr.status === 'signed' ? 'bg-green-100 text-green-800' :
                      csr.status === 'pending' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-gray-100 text-gray-600'
                    }`}>
                      {csr.status}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <button
                        onClick={() => authenticatedDownload(`/api/v1/csr/${csr.id}/export/pem`, `${parseSubject(csr.subject_json).cn || 'csr'}.csr`)}
                        className="text-blue-600 hover:text-blue-800 text-xs font-medium">Download</button>
                      {csr.status === 'pending' && csr.has_stored_key && (
                        <button onClick={() => setSigningCsrId(csr.id)}
                          className="text-purple-600 hover:text-purple-800 text-xs font-medium">Sign</button>
                      )}
                      {csr.status === 'pending' && (
                        <button onClick={() => setImportingCsrId(csr.id)}
                          className="text-green-600 hover:text-green-800 text-xs font-medium">Import Cert</button>
                      )}
                      {csr.status === 'pending' && (
                        <button onClick={() => { if (confirm('Delete this CSR?')) deleteMutation.mutate(csr.id) }}
                          className="text-red-600 hover:text-red-800 text-xs font-medium">Delete</button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CSRWizard({ onSuccess }: { onSuccess: () => void }) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'new_key' | 'existing_key' | 'renew'>('new_key')
  const [subject, setSubject] = useState<Subject>({ cn: '', o: '', ou: '', c: '', st: '', l: '' })
  const [san, setSan] = useState<SANEntry[]>([])
  const [keyAlgo, setKeyAlgo] = useState('RSA')
  const [keySize, setKeySize] = useState(2048)
  const [storeKey, setStoreKey] = useState(true)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [keyPassword, setKeyPassword] = useState('')
  const [certFile, setCertFile] = useState<File | null>(null)
  const [p12File, setP12File] = useState<File | null>(null)
  const [p12Password, setP12Password] = useState('')
  const [renewUploadMode, setRenewUploadMode] = useState<'p12' | 'separate'>('p12')
  const [result, setResult] = useState<any>(null)

  const newKeyMutation = useMutation({
    mutationFn: (data: any) => api.post('/csr', data),
    onSuccess: (res) => {
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['csrs'] })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (formData: FormData) => api.post('/csr/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
    onSuccess: (res) => {
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['csrs'] })
    },
  })

  const renewMutation = useMutation({
    mutationFn: (formData: FormData) => api.post('/csr/renew', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
    onSuccess: (res) => {
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['csrs'] })
    },
  })

  const mutation = mode === 'new_key' ? newKeyMutation : mode === 'existing_key' ? uploadMutation : renewMutation

  const handleGenerate = () => {
    if (mode === 'new_key') {
      newKeyMutation.mutate({
        mode,
        subject,
        san,
        key_algo: keyAlgo,
        key_size: keySize,
        store_key: storeKey,
        digest: 'sha256',
      })
    } else if (mode === 'existing_key') {
      if (!keyFile) return
      const formData = new FormData()
      formData.append('key_file', keyFile)
      formData.append('subject_json', JSON.stringify(subject))
      formData.append('san_json', JSON.stringify(san))
      formData.append('store_key', String(storeKey))
      formData.append('digest', 'sha256')
      if (keyPassword) formData.append('key_password', keyPassword)
      uploadMutation.mutate(formData)
    } else if (mode === 'renew') {
      const formData = new FormData()
      if (renewUploadMode === 'p12' && p12File) {
        formData.append('p12_file', p12File)
        if (p12Password) formData.append('p12_password', p12Password)
      } else if (renewUploadMode === 'separate' && certFile && keyFile) {
        formData.append('cert_file', certFile)
        formData.append('key_file', keyFile)
        if (keyPassword) formData.append('key_password', keyPassword)
      } else {
        return
      }
      formData.append('store_key', String(storeKey))
      formData.append('digest', 'sha256')
      renewMutation.mutate(formData)
    }
  }

  const canGenerate = (): boolean => {
    if (mode === 'new_key') return !!subject.cn
    if (mode === 'existing_key') return !!subject.cn && !!keyFile
    if (mode === 'renew') {
      if (renewUploadMode === 'p12') return !!p12File
      return !!certFile && !!keyFile
    }
    return false
  }

  if (result) {
    return (
      <div className="mb-6 p-5 bg-white rounded-lg border border-green-200 space-y-3">
        <div className="flex items-center gap-2 text-green-700">
          <span className="text-xl">✅</span>
          <h3 className="font-semibold">CSR Generated Successfully</h3>
        </div>
        {result.extracted && (
          <div className="p-3 bg-green-50 rounded text-sm space-y-1">
            <p className="font-medium text-green-800">Extracted from existing certificate:</p>
            <p><span className="text-gray-500">CN:</span> {result.extracted.cn}</p>
            <p><span className="text-gray-500">SANs:</span> {result.extracted.san?.map((s: any) => `${s.type}:${s.value}`).join(', ') || 'None'}</p>
            <p><span className="text-gray-500">Original Issuer:</span> {result.extracted.original_issuer}</p>
            <p><span className="text-gray-500">Original Expiry:</span> {new Date(result.extracted.original_expires).toLocaleDateString()}</p>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2 text-sm">
          {Object.entries(result.verification || {}).map(([k, v]) => (
            <div key={k}>
              <span className={`${v === 'pass' ? 'text-green-600' : v === 'warn' ? 'text-amber-600' : 'text-red-600'}`}>
                {v === 'pass' ? '✓' : v === 'warn' ? '⚠' : '✗'}
              </span>{' '}
              <span className="text-gray-600">{k.replace('_', ' ')}</span>
            </div>
          ))}
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={() => authenticatedDownload(`/api/v1/csr/${result.id}/export/pem`, `${result.id}.csr`)}
            className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded text-xs font-medium hover:bg-gray-200">PEM</button>
          <button onClick={() => authenticatedDownload(`/api/v1/csr/${result.id}/export/der`, `${result.id}.der`)}
            className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded text-xs font-medium hover:bg-gray-200">DER</button>
          <button onClick={() => authenticatedDownload(`/api/v1/csr/${result.id}/export/zip`, `${result.id}-bundle.zip`)}
            className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded text-xs font-medium hover:bg-gray-200">Bundle ZIP</button>
        </div>
        <button onClick={onSuccess} className="text-sm text-blue-600 hover:text-blue-800">Done</button>
      </div>
    )
  }

  return (
    <div className="mb-6 p-5 bg-white rounded-lg border border-gray-200 space-y-4">
      <h3 className="font-semibold text-gray-900">Generate CSR</h3>

      {/* Mode selector */}
      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={mode === 'new_key'} onChange={() => setMode('new_key')} />
          Generate New Key + CSR
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={mode === 'existing_key'} onChange={() => setMode('existing_key')} />
          Upload Existing Key + CSR
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" checked={mode === 'renew'} onChange={() => setMode('renew')} />
          Renew from Existing Certificate <span className="text-xs text-gray-400">(auto-extracts subject &amp; SANs)</span>
        </label>
      </div>

      {/* Renew mode */}
      {mode === 'renew' && (
        <div className="p-4 bg-blue-50 rounded-lg border border-blue-200 space-y-3">
          <p className="text-sm text-blue-800">Upload your existing certificate (or .p12) and the tool will extract subject, SANs, and key automatically — no manual input needed.</p>

          <div className="flex gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" checked={renewUploadMode === 'p12'} onChange={() => setRenewUploadMode('p12')} />
              PKCS#12 / .p12 / .pfx (cert + key in one file)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="radio" checked={renewUploadMode === 'separate'} onChange={() => setRenewUploadMode('separate')} />
              Separate cert + key files
            </label>
          </div>

          {renewUploadMode === 'p12' && (
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">PKCS#12 File (.p12 / .pfx) *</label>
                <div className="flex items-center gap-3">
                  <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
                    {p12File ? p12File.name : 'Choose .p12 file...'}
                    <input type="file" className="hidden" accept=".p12,.pfx"
                      onChange={e => setP12File(e.target.files?.[0] || null)} />
                  </label>
                  {p12File && <span className="text-xs text-green-600">✓ {(p12File.size / 1024).toFixed(1)} KB</span>}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">P12 Password</label>
                <input type="password" value={p12Password} onChange={e => setP12Password(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  placeholder="Password for the .p12 file" />
              </div>
            </div>
          )}

          {renewUploadMode === 'separate' && (
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Certificate File *</label>
                <div className="flex items-center gap-3">
                  <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
                    {certFile ? certFile.name : 'Choose certificate...'}
                    <input type="file" className="hidden" accept=".pem,.crt,.cer,.der"
                      onChange={e => setCertFile(e.target.files?.[0] || null)} />
                  </label>
                  {certFile && <span className="text-xs text-green-600">✓ {(certFile.size / 1024).toFixed(1)} KB</span>}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Private Key File *</label>
                <div className="flex items-center gap-3">
                  <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
                    {keyFile ? keyFile.name : 'Choose key file...'}
                    <input type="file" className="hidden" accept=".pem,.key,.der"
                      onChange={e => setKeyFile(e.target.files?.[0] || null)} />
                  </label>
                  {keyFile && <span className="text-xs text-green-600">✓ {(keyFile.size / 1024).toFixed(1)} KB</span>}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Key Passphrase (if encrypted)</label>
                <input type="password" value={keyPassword} onChange={e => setKeyPassword(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Leave blank if unencrypted" />
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={storeKey} onChange={e => setStoreKey(e.target.checked)} />
            Store key in database (encrypted) for importing signed cert later
          </label>
        </div>
      )}

      {/* Key upload (Path B) */}
      {mode === 'existing_key' && (
        <div className="p-4 bg-gray-50 rounded-lg border border-gray-200 space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Private Key File *</label>
            <div className="flex items-center gap-3">
              <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
                {keyFile ? keyFile.name : 'Choose key file...'}
                <input
                  type="file"
                  className="hidden"
                  accept=".pem,.key,.der,.p12,.pfx"
                  onChange={e => setKeyFile(e.target.files?.[0] || null)}
                />
              </label>
              {keyFile && (
                <span className="text-xs text-green-600">✓ {(keyFile.size / 1024).toFixed(1)} KB</span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-1">Supported: PEM (PKCS#1, PKCS#8, EC), DER, PKCS#12 (.p12/.pfx)</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Key Passphrase (if encrypted)</label>
            <input
              type="password"
              value={keyPassword}
              onChange={e => setKeyPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="Leave blank if key is not encrypted"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={storeKey} onChange={e => setStoreKey(e.target.checked)} />
            Store key in database (encrypted) for later signing
          </label>
          <p className="text-xs text-amber-600">⚠️ If unchecked, the key is used only for CSR generation and then discarded.</p>
        </div>
      )}

      {/* Subject (not shown in renew mode — auto-extracted) */}
      {mode !== 'renew' && (
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">Common Name *</label>
            <input type="text" value={subject.cn}
              onChange={e => setSubject(prev => ({ ...prev, cn: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="api.example.internal" required />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Organisation</label>
            <input type="text" value={subject.o} onChange={e => setSubject(prev => ({ ...prev, o: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
            <input type="text" value={subject.c} onChange={e => setSubject(prev => ({ ...prev, c: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" maxLength={2} placeholder="GB" />
          </div>
        </div>
      )}

      {/* SAN (not shown in renew mode) */}
      {mode !== 'renew' && <SANEditor entries={san} onChange={setSan} />}

      {/* Key options (Path A only) */}
      {mode === 'new_key' && (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Algorithm</label>
            <select value={keyAlgo} onChange={e => setKeyAlgo(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              <option value="RSA">RSA</option>
              <option value="ECDSA">ECDSA</option>
              <option value="Ed25519">Ed25519</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Key Size</label>
            <select value={keySize} onChange={e => setKeySize(Number(e.target.value))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
              {keyAlgo === 'RSA' && <><option value={2048}>2048</option><option value={3072}>3072</option><option value={4096}>4096</option></>}
              {keyAlgo === 'ECDSA' && <><option value={256}>P-256</option><option value={384}>P-384</option><option value={521}>P-521</option></>}
              {keyAlgo === 'Ed25519' && <option value={256}>256</option>}
            </select>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-2 text-sm pb-2">
              <input type="checkbox" checked={storeKey} onChange={e => setStoreKey(e.target.checked)} />
              Store key (for signing later)
            </label>
          </div>
        </div>
      )}

      <div className="flex justify-end gap-3">
        {mutation.isError && (
          <p className="text-red-600 text-sm self-center">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>
        )}
        <button onClick={handleGenerate}
          disabled={!canGenerate() || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Generating...' : mode === 'renew' ? 'Generate Renewal CSR' : 'Generate CSR'}
        </button>
      </div>
    </div>
  )
}


function SignCSRForm({ csrId, onSuccess, onCancel }: { csrId: string; onSuccess: () => void; onCancel: () => void }) {
  const queryClient = useQueryClient()
  const [caId, setCaId] = useState('')
  const [validityDays, setValidityDays] = useState(365)
  const [result, setResult] = useState<any>(null)

  const { data: csrDetail } = useQuery<{ san_json: string }>({ 
    queryKey: ['csr', csrId],
    queryFn: async () => (await api.get(`/csr/${csrId}`)).data,
  })

  const hasSans = csrDetail ? (() => { try { return JSON.parse(csrDetail.san_json).length > 0 } catch { return false } })() : true
  const [profile, setProfile] = useState('server')

  // Auto-switch away from server if no SANs
  const effectiveProfile = profile === 'server' && !hasSans ? 'client' : profile

  const { data: cas = [] } = useQuery<{ id: string; cn: string }[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  const mutation = useMutation({
    mutationFn: () => api.post(`/csr/${csrId}/sign`, { signing_ca_id: caId, validity_days: validityDays, profile: effectiveProfile }),
    onSuccess: (res) => {
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['csrs'] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
    },
  })

  if (result) {
    return (
      <div className="mb-6 p-5 bg-white rounded-lg border border-green-200 space-y-3">
        <div className="flex items-center gap-2 text-green-700">
          <span className="text-xl">✅</span>
          <h3 className="font-semibold">CSR Signed Successfully</h3>
        </div>
        <div className="text-sm space-y-1">
          <p><span className="text-gray-500">Serial:</span> <span className="font-mono">{result.certificate_serial}</span></p>
        </div>
        <p className="text-xs text-gray-500">The certificate is now in the Certificates inventory.</p>
        <button onClick={onSuccess} className="text-sm text-blue-600 hover:text-blue-800">Done</button>
      </div>
    )
  }

  return (
    <div className="mb-6 p-5 bg-white rounded-lg border border-purple-200 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">Sign CSR with Internal CA</h3>
        <button onClick={onCancel} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="col-span-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">Signing CA *</label>
          <select value={caId} onChange={e => setCaId(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="">Select CA...</option>
            {cas.map(ca => <option key={ca.id} value={ca.id}>{ca.cn}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Profile</label>
          <select value={profile} onChange={e => setProfile(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="server">Server TLS</option>
            <option value="client">Client mTLS</option>
            <option value="code_sign">Code Signing</option>
            <option value="email">Email</option>
            <option value="custom">Custom</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Validity (days)</label>
          <input type="number" value={validityDays} onChange={e => setValidityDays(Number(e.target.value))}
            min={1} max={3650}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>

      {profile === 'server' && !hasSans && (
        <p className="text-sm text-amber-600">⚠️ This CSR has no SANs — Server TLS requires at least one SAN (RFC 2818). Will sign as <strong>Client mTLS</strong> instead, or regenerate the CSR with SANs.</p>
      )}

      {!cas.length && (
        <p className="text-sm text-amber-600">⚠️ No CAs found. A CA is only needed here to sign — you can still generate and download the CSR without one.</p>
      )}

      <div className="flex justify-end gap-3 pt-2">
        {mutation.isError && (
          <p className="text-red-600 text-sm self-center">
            {(mutation.error as any)?.response?.data?.detail || 'Signing failed'}
          </p>
        )}
        <button onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button onClick={() => mutation.mutate()}
          disabled={!caId || mutation.isPending}
          className="px-4 py-2 bg-purple-600 text-white text-sm font-medium rounded-md hover:bg-purple-700 disabled:opacity-50">
          {mutation.isPending ? 'Signing...' : 'Sign Certificate'}
        </button>
      </div>
    </div>
  )
}


function ImportCertForm({ csrId, onSuccess, onCancel }: { csrId: string; onSuccess: () => void; onCancel: () => void }) {
  const queryClient = useQueryClient()
  const [certFile, setCertFile] = useState<File | null>(null)
  const [chainFile, setChainFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (formData: FormData) => api.post(`/csr/${csrId}/import-cert`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
    onSuccess: (res) => {
      setResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['csrs'] })
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
    },
  })

  const handleImport = () => {
    if (!certFile) return
    const formData = new FormData()
    formData.append('cert_file', certFile)
    if (chainFile) formData.append('chain_file', chainFile)
    mutation.mutate(formData)
  }

  if (result) {
    return (
      <div className="mb-6 p-5 bg-white rounded-lg border border-green-200 space-y-3">
        <div className="flex items-center gap-2 text-green-700">
          <span className="text-xl">✅</span>
          <h3 className="font-semibold">Certificate Imported Successfully</h3>
        </div>
        <div className="text-sm space-y-1">
          <p><span className="text-gray-500">Serial:</span> <span className="font-mono">{result.certificate_serial}</span></p>
          <p><span className="text-gray-500">Issuer:</span> {result.issuer}</p>
          <p><span className="text-gray-500">Expires:</span> {new Date(result.expires_at).toLocaleDateString()}</p>
        </div>
        <p className="text-xs text-gray-500">
          The certificate is now stored in the inventory alongside its private key (if stored during CSR generation).
        </p>
        <button onClick={onSuccess} className="text-sm text-blue-600 hover:text-blue-800">Done</button>
      </div>
    )
  }

  return (
    <div className="mb-6 p-5 bg-white rounded-lg border border-blue-200 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-900">Import Signed Certificate</h3>
        <button onClick={onCancel} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
      </div>
      <p className="text-sm text-gray-500">
        Upload the signed certificate received from your external CA (DigiCert, Sectigo, Let's Encrypt, etc.).
        It will be paired with the private key stored during CSR generation.
      </p>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Signed Certificate *</label>
        <div className="flex items-center gap-3">
          <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
            {certFile ? certFile.name : 'Choose certificate file...'}
            <input
              type="file"
              className="hidden"
              accept=".pem,.crt,.cer,.der"
              onChange={e => setCertFile(e.target.files?.[0] || null)}
            />
          </label>
          {certFile && <span className="text-xs text-green-600">✓ {(certFile.size / 1024).toFixed(1)} KB</span>}
        </div>
        <p className="text-xs text-gray-400 mt-1">PEM or DER format (.pem, .crt, .cer, .der)</p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">CA Chain / Intermediate Certificates (optional)</label>
        <div className="flex items-center gap-3">
          <label className="cursor-pointer px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-50">
            {chainFile ? chainFile.name : 'Choose chain file...'}
            <input
              type="file"
              className="hidden"
              accept=".pem,.crt,.cer"
              onChange={e => setChainFile(e.target.files?.[0] || null)}
            />
          </label>
          {chainFile && <span className="text-xs text-green-600">✓ {(chainFile.size / 1024).toFixed(1)} KB</span>}
        </div>
        <p className="text-xs text-gray-400 mt-1">PEM bundle containing intermediate CA certificates (ca-bundle.crt)</p>
      </div>

      <div className="flex justify-end gap-3 pt-2">
        {mutation.isError && (
          <p className="text-red-600 text-sm self-center">
            {(mutation.error as any)?.response?.data?.detail || 'Import failed'}
          </p>
        )}
        <button onClick={onCancel}
          className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
          Cancel
        </button>
        <button onClick={handleImport}
          disabled={!certFile || mutation.isPending}
          className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 disabled:opacity-50">
          {mutation.isPending ? 'Importing...' : 'Import Certificate'}
        </button>
      </div>
    </div>
  )
}
