import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import SANEditor from '@/components/SANEditor'
import { authenticatedDownload } from '@/lib/utils'
import type { CAListItem, CertCreateRequest, SANEntry, Subject } from '@/lib/types'

const RESULT_FORMAT_EXT: Record<string, string> = { pem: 'pem', der: 'cer', chain: 'pem', key: 'pem', p12: 'p12', bundle: 'zip' }

const profiles = [
  { value: 'server', label: 'Server (TLS)', desc: 'HTTPS endpoints, APIs, services', icon: '🖥️' },
  { value: 'client', label: 'Client (mTLS)', desc: 'Service accounts, mutual TLS', icon: '👤' },
  { value: 'code_sign', label: 'Code Signing', desc: 'Sign binaries and packages', icon: '✍️' },
  { value: 'email', label: 'Email (S/MIME)', desc: 'Email encryption and signing', icon: '📧' },
  { value: 'custom', label: 'Custom', desc: 'User-defined extensions', icon: '🔧' },
]

const defaultSubject: Subject = { cn: '', o: '', ou: '', c: '', st: '', l: '' }

export default function CertificateWizard() {
  const queryClient = useQueryClient()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<CertCreateRequest>({
    profile: 'server',
    signing_ca_id: '',
    subject: { ...defaultSubject },
    san: [],
    key_algo: 'RSA',
    key_size: 2048,
    validity_days: 365,
  })
  const [result, setResult] = useState<any>(null)

  const { data: cas = [] } = useQuery<CAListItem[]>({
    queryKey: ['cas'],
    queryFn: async () => (await api.get('/ca')).data,
  })

  const [constraintWarnings, setConstraintWarnings] = useState<string[]>([])

  // Check name constraints when CA selection, CN, or SANs change
  useEffect(() => {
    if (!form.signing_ca_id) { setConstraintWarnings([]); return }
    const selectedCa = cas.find(c => c.id === form.signing_ca_id)
    if (!selectedCa?.name_constraints) { setConstraintWarnings([]); return }

    const sansParam = form.san.filter(s => s.type === 'dns').map(s => `dns:${s.value}`).join(',')
    api.get(`/ca/${form.signing_ca_id}/check-constraints`, {
      params: { cn: form.subject.cn, sans: sansParam }
    }).then(res => {
      setConstraintWarnings(res.data.violations || [])
    }).catch(() => setConstraintWarnings([]))
  }, [form.signing_ca_id, form.subject.cn, form.san, cas])

  const mutation = useMutation({
    mutationFn: (data: CertCreateRequest) => api.post('/cert', data),
    onSuccess: (res) => {
      setResult(res.data)
      setStep(5)
      queryClient.invalidateQueries({ queryKey: ['certificates'] })
    },
  })

  const canAdvance = (): boolean => {
    switch (step) {
      case 0: return !!form.profile
      case 1: return !!form.subject.cn
      case 2: return form.profile !== 'server' || form.san.length > 0
      case 3: return !!form.signing_ca_id
      default: return true
    }
  }

  const steps = ['Profile', 'Subject', 'SAN', 'Key & CA', 'Review', 'Result']

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-2">Issue Certificate</h2>

      {/* Step indicator */}
      <div className="flex items-center gap-1 mb-6">
        {steps.map((label, i) => (
          <div key={label} className="flex items-center">
            <div className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-medium ${
              i === step ? 'bg-blue-600 text-white' : i < step ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'
            }`}>
              {i < step ? '✓' : i + 1}
            </div>
            <span className={`ml-1 text-xs ${i === step ? 'text-blue-700 font-medium' : 'text-gray-400'}`}>{label}</span>
            {i < steps.length - 1 && <div className="w-6 h-px bg-gray-300 mx-1" />}
          </div>
        ))}
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {/* Step 0: Profile */}
        {step === 0 && (
          <div className="space-y-3">
            <h3 className="font-semibold text-gray-900 mb-4">Select Certificate Profile</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {profiles.map(p => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setForm(prev => ({ ...prev, profile: p.value }))}
                  className={`flex items-start gap-3 p-4 rounded-lg border text-left transition ${
                    form.profile === p.value
                      ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <span className="text-2xl">{p.icon}</span>
                  <div>
                    <div className="font-medium text-sm text-gray-900">{p.label}</div>
                    <div className="text-xs text-gray-500">{p.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Step 1: Subject */}
        {step === 1 && (
          <div className="space-y-4">
            <h3 className="font-semibold text-gray-900">Subject Fields</h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Common Name *</label>
                <input type="text" value={form.subject.cn}
                  onChange={e => setForm(prev => ({ ...prev, subject: { ...prev.subject, cn: e.target.value } }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  placeholder="api.example.internal" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Organisation</label>
                <input type="text" value={form.subject.o}
                  onChange={e => setForm(prev => ({ ...prev, subject: { ...prev.subject, o: e.target.value } }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Org Unit</label>
                <input type="text" value={form.subject.ou}
                  onChange={e => setForm(prev => ({ ...prev, subject: { ...prev.subject, ou: e.target.value } }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
                <input type="text" value={form.subject.c}
                  onChange={e => setForm(prev => ({ ...prev, subject: { ...prev.subject, c: e.target.value } }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" maxLength={2} placeholder="GB" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">State / Province</label>
                <input type="text" value={form.subject.st}
                  onChange={e => setForm(prev => ({ ...prev, subject: { ...prev.subject, st: e.target.value } }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
              </div>
            </div>
          </div>
        )}

        {/* Step 2: SAN */}
        {step === 2 && (
          <div>
            <h3 className="font-semibold text-gray-900 mb-4">Subject Alternative Names</h3>
            {form.profile === 'server' && (
              <p className="text-xs text-amber-600 mb-3">⚠️ Server certificates require at least one DNS SAN for Java/JSSE compatibility.</p>
            )}
            <JarSanImport onImport={sans => setForm(prev => ({
              ...prev,
              san: [
                ...prev.san,
                ...sans.filter(s => !prev.san.some(e => e.type === s.type && e.value === s.value)),
              ],
            }))} />
            <SANEditor
              entries={form.san}
              onChange={san => setForm(prev => ({ ...prev, san }))}
              required={form.profile === 'server'}
            />
          </div>
        )}

        {/* Step 3: Key & CA */}
        {step === 3 && (
          <div className="space-y-4">
            <h3 className="font-semibold text-gray-900">Key Options & Signing CA</h3>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Algorithm</label>
                <select value={form.key_algo}
                  onChange={e => setForm(prev => ({ ...prev, key_algo: e.target.value }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
                  <option value="RSA">RSA</option>
                  <option value="ECDSA">ECDSA</option>
                  <option value="Ed25519">Ed25519</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Key Size</label>
                <select value={form.key_size}
                  onChange={e => setForm(prev => ({ ...prev, key_size: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
                  {form.key_algo === 'RSA' && <><option value={2048}>2048</option><option value={3072}>3072</option><option value={4096}>4096</option></>}
                  {form.key_algo === 'ECDSA' && <><option value={256}>P-256</option><option value={384}>P-384</option><option value={521}>P-521</option></>}
                  {form.key_algo === 'Ed25519' && <option value={256}>256</option>}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Validity (days)</label>
                <input type="number" value={form.validity_days}
                  onChange={e => setForm(prev => ({ ...prev, validity_days: Number(e.target.value) }))}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" min={1} max={398} />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Signing CA *</label>
              <select value={form.signing_ca_id}
                onChange={e => setForm(prev => ({ ...prev, signing_ca_id: e.target.value }))}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" required>
                <option value="">Select a CA...</option>
                {cas.map(ca => (
                  <option key={ca.id} value={ca.id}>
                    {ca.cn} ({ca.is_root ? 'Root' : 'Intermediate'}){ca.name_constraints ? ' ⚠️ constrained' : ''}
                  </option>
                ))}
              </select>
              {constraintWarnings.length > 0 && (
                <div className="mt-2 p-3 bg-red-50 border border-red-200 rounded-md">
                  <p className="text-sm font-medium text-red-800">⚠️ Name Constraint Violations</p>
                  <p className="text-xs text-red-600 mt-1">This CA cannot sign certificates for the requested names:</p>
                  <ul className="mt-1 text-xs text-red-700 list-disc list-inside">
                    {constraintWarnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Step 4: Review */}
        {step === 4 && (
          <div className="space-y-4">
            <h3 className="font-semibold text-gray-900">Review & Issue</h3>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-gray-500">Profile:</span> <span className="font-medium">{form.profile}</span></div>
              <div><span className="text-gray-500">CN:</span> <span className="font-medium">{form.subject.cn}</span></div>
              <div><span className="text-gray-500">Key:</span> <span className="font-medium">{form.key_algo} {form.key_size}</span></div>
              <div><span className="text-gray-500">Validity:</span> <span className="font-medium">{form.validity_days} days</span></div>
              <div className="col-span-2">
                <span className="text-gray-500">SANs:</span>{' '}
                {form.san.length === 0 ? <span className="text-gray-400">None</span> :
                  form.san.map(s => <span key={s.value} className="inline-block bg-gray-100 px-2 py-0.5 rounded text-xs mr-1">{s.type}:{s.value}</span>)
                }
              </div>
            </div>
            {constraintWarnings.length > 0 && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm font-medium text-red-800">⚠️ Name Constraint Violations — issuance will fail</p>
                <ul className="mt-1 text-xs text-red-700 list-disc list-inside">
                  {constraintWarnings.map((w, i) => <li key={i}>{w}</li>)}
                </ul>
              </div>
            )}
            {mutation.isError && (
              <div className="text-red-600 text-sm">
                {(() => {
                  const detail = (mutation.error as any)?.response?.data?.detail
                  if (detail?.name_constraint_violations) {
                    return (
                      <div className="p-3 bg-red-50 border border-red-200 rounded-md">
                        <p className="font-medium">⚠️ Rejected by CA Name Constraints:</p>
                        <ul className="mt-1 list-disc list-inside text-xs">
                          {detail.name_constraint_violations.map((v: string, i: number) => <li key={i}>{v}</li>)}
                        </ul>
                      </div>
                    )
                  }
                  return <p>{typeof detail === 'string' ? detail : JSON.stringify(detail) || 'Issuance failed'}</p>
                })()}
              </div>
            )}
          </div>
        )}

        {/* Step 5: Result */}
        {step === 5 && result && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-green-700">
              <span className="text-2xl">✅</span>
              <h3 className="font-semibold">Certificate Issued Successfully</h3>
            </div>
            <div className="text-sm space-y-1">
              <p><span className="text-gray-500">Serial:</span> {result.serial}</p>
              <p><span className="text-gray-500">Expires:</span> {new Date(result.expires_at).toLocaleDateString()}</p>
            </div>
            <div className="flex flex-wrap gap-2 pt-2">
              {['pem', 'der', 'chain', 'key', 'p12', 'bundle'].map(fmt => (
                <button
                  key={fmt}
                  onClick={() => authenticatedDownload(`/api/v1/export/${result.serial}/${fmt}`, `${result.serial}.${RESULT_FORMAT_EXT[fmt]}`)}
                  className="px-3 py-1.5 bg-gray-100 border border-gray-300 rounded-md text-xs font-medium hover:bg-gray-200"
                >
                  {fmt.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Navigation */}
        {step < 5 && (
          <div className="flex justify-between mt-6 pt-4 border-t border-gray-100">
            <button
              type="button"
              onClick={() => setStep(s => s - 1)}
              disabled={step === 0}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30"
            >
              ← Back
            </button>
            {step < 4 ? (
              <button
                type="button"
                onClick={() => setStep(s => s + 1)}
                disabled={!canAdvance()}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                Next →
              </button>
            ) : (
              <button
                type="button"
                onClick={() => mutation.mutate(form)}
                disabled={mutation.isPending}
                className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 disabled:opacity-50"
              >
                {mutation.isPending ? 'Issuing...' : 'Issue Certificate'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// JAR SAN Import widget — shown on the SAN step
// ---------------------------------------------------------------------------

interface JarSanImportProps {
  onImport: (sans: SANEntry[]) => void
}

function JarSanImport({ onImport }: JarSanImportProps) {
  const [open, setOpen] = useState(false)
  const [reportId, setReportId] = useState('')
  const [preview, setPreview] = useState<SANEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const { data: reports } = useQuery<{ items: any[] }>({
    queryKey: ['jar-reports-for-san'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 50 } }).then(r => r.data),
    enabled: open,
  })

  const fetchSans = async (id: string) => {
    if (!id) { setPreview(null); return }
    setLoading(true)
    setError('')
    try {
      const res = await api.get(`/jar-analyser/reports/${id}/ssl-requirements`)
      const sans: SANEntry[] = (res.data.suggested_sans ?? []).map((s: any) => ({
        type: s.type.toLowerCase() as 'dns' | 'ip',
        value: s.value,
      }))
      setPreview(sans)
    } catch {
      setError('Failed to load SSL requirements')
      setPreview(null)
    }
    setLoading(false)
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)}
        className="mb-3 flex items-center gap-2 px-3 py-1.5 border border-blue-300 bg-blue-50 text-blue-700 rounded-md text-xs hover:bg-blue-100">
        🔬 Import SANs from JAR Analysis
      </button>
    )
  }

  return (
    <div className="mb-4 p-3 border border-blue-200 bg-blue-50 rounded-lg space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-blue-800">Import SANs from JAR Analysis</p>
        <button type="button" onClick={() => { setOpen(false); setPreview(null) }}
          className="text-blue-400 hover:text-blue-600 text-xs">✕ Close</button>
      </div>

      <select value={reportId} onChange={e => { setReportId(e.target.value); fetchSans(e.target.value) }}
        className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white">
        <option value="">Select a JAR report...</option>
        {(reports?.items ?? []).map((r: any) => (
          <option key={r.report_id} value={r.report_id}>
            {r.filename}{r.implementation_version ? ` v${r.implementation_version}` : ''}
          </option>
        ))}
      </select>

      {loading && <p className="text-xs text-blue-600">Loading...</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}

      {preview && preview.length > 0 && (
        <div>
          <p className="text-xs text-gray-600 mb-2">{preview.length} SANs detected:</p>
          <div className="flex flex-wrap gap-1 mb-3">
            {preview.map((s, i) => (
              <span key={i} className="px-2 py-0.5 bg-white border border-gray-300 rounded text-xs font-mono">
                {s.type}:{s.value}
              </span>
            ))}
          </div>
          <button type="button"
            onClick={() => { onImport(preview); setOpen(false); setPreview(null) }}
            className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
            Add {preview.length} SANs →
          </button>
        </div>
      )}
    </div>
  )
}
