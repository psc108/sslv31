import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import api from '@/lib/api'
import CopyButton from '@/components/CopyButton'
import { ChainExpiryTool } from '@/components/tools/ChainExpiryTool'
import { JavaDebugTool } from '@/components/tools/JavaDebugTool'
import { OpenSSLCommandsTool } from '@/components/tools/OpenSSLCommandsTool'
import { ConnectionTestTool } from '@/components/tools/ConnectionTestTool'
import { BuildKeyStoreTool, MergeTrustStoreTool, BulkImportTool } from '@/components/tools/ExtraTools'
import { TroubleshooterWizard } from '@/components/tools/TroubleshooterWizard'

type Tab = 'troubleshoot' | 'decode' | 'decodecsr' | 'remote' | 'verify' | 'keymatch' | 'convert' | 'p12' | 'compat' | 'chainexpiry' | 'javadebug' | 'opensslcmds' | 'keystore' | 'merger' | 'conntest' | 'bulkimport'

const tabs_ids: Tab[] = ['troubleshoot', 'decode', 'decodecsr', 'remote', 'verify', 'keymatch', 'convert', 'p12', 'compat', 'chainexpiry', 'javadebug', 'opensslcmds', 'keystore', 'merger', 'conntest', 'bulkimport']

export default function ToolsPage() {
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>(() => {
    const t = searchParams.get('tool') as Tab | null
    return t && tabs_ids.includes(t) ? t : 'troubleshoot'
  })

  // Re-sync if query param changes (e.g. deep-link navigation)
  useEffect(() => {
    const t = searchParams.get('tool') as Tab | null
    if (t && tabs_ids.includes(t)) setTab(t)
  }, [searchParams])

  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: 'troubleshoot', label: 'Troubleshooter', icon: '🔧' },
    { id: 'decode', label: 'Decode Cert', icon: '🔍' },
    { id: 'decodecsr', label: 'Decode CSR', icon: '📋' },
    { id: 'remote', label: 'Remote Check', icon: '🌐' },
    { id: 'compat', label: 'Compatibility', icon: '✅' },
    { id: 'chainexpiry', label: 'Chain Expiry', icon: '⏰' },
    { id: 'conntest', label: 'Connection Test', icon: '🔌' },
    { id: 'verify', label: 'Verify Chain', icon: '🔗' },
    { id: 'keymatch', label: 'Key Match', icon: '🔑' },
    { id: 'javadebug', label: 'Java Debug', icon: '☕' },
    { id: 'opensslcmds', label: 'OpenSSL Cmds', icon: '💻' },
    { id: 'keystore', label: 'Build KeyStore', icon: '📦' },
    { id: 'merger', label: 'Merge Trusts', icon: '🔀' },
    { id: 'convert', label: 'Convert', icon: '🔄' },
    { id: 'p12', label: 'Build P12', icon: '📦' },
    { id: 'bulkimport', label: 'Bulk Import', icon: '📥' },
  ]

  return (
    <div className="flex gap-6">
      {/* Tool sidebar */}
      <aside className="w-48 flex-shrink-0">
        <h2 className="text-lg font-bold text-gray-900 mb-4">Tools</h2>
        <nav className="space-y-1">
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition ${
                tab === t.id
                  ? 'bg-blue-50 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}>
              <span>{t.icon}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
      </aside>

      {/* Tool content */}
      <div className="flex-1 min-w-0">

      {tab === 'troubleshoot' && <TroubleshooterWizard />}
      {tab === 'decode' && <DecodeTool />}
      {tab === 'decodecsr' && <DecodeCSRTool />}
      {tab === 'remote' && <RemoteCheckTool />}
      {tab === 'compat' && <CompatibilityCheckTool />}
      {tab === 'chainexpiry' && <ChainExpiryTool />}
      {tab === 'conntest' && <ConnectionTestTool />}
      {tab === 'verify' && <VerifyChainTool />}
      {tab === 'keymatch' && <KeyMatchTool />}
      {tab === 'javadebug' && <JavaDebugTool />}
      {tab === 'opensslcmds' && <OpenSSLCommandsTool />}
      {tab === 'keystore' && <BuildKeyStoreTool />}
      {tab === 'merger' && <MergeTrustStoreTool />}
      {tab === 'convert' && <ConvertTool />}
      {tab === 'p12' && <BuildP12Tool />}
      {tab === 'bulkimport' && <BulkImportTool />}
      </div>
    </div>
  )
}

function DecodeTool() {
  const [pem, setPem] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (data: FormData) => api.post('/tools/decode', data),
    onSuccess: (res) => setResult(res.data),
  })

  const handleDecode = () => {
    const fd = new FormData()
    if (file) {
      fd.append('cert_file', file)
    } else {
      fd.append('cert_pem', pem)
    }
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="font-semibold text-gray-900 mb-3">Decode Certificate</h3>
        <p className="text-sm text-gray-500 mb-3">Paste a PEM certificate or upload a certificate file to decode and inspect it.</p>

        {/* File upload */}
        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">Upload Certificate File</label>
          <div className="flex items-center gap-3">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {file ? file.name : 'Choose file (.pem, .crt, .cer, .der)...'}
              <input type="file" className="hidden" accept=".pem,.crt,.cer,.der"
                onChange={e => { setFile(e.target.files?.[0] || null); setPem('') }} />
            </label>
            {file && (
              <>
                <span className="text-xs text-green-600">✓ {(file.size / 1024).toFixed(1)} KB</span>
                <button onClick={() => setFile(null)} className="text-xs text-red-500 hover:text-red-700">Clear</button>
              </>
            )}
          </div>
        </div>

        <div className="relative my-3">
          <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200"></div></div>
          <div className="relative flex justify-center"><span className="bg-white px-2 text-xs text-gray-400">OR paste PEM</span></div>
        </div>

        {/* PEM paste */}
        <textarea value={pem} onChange={e => { setPem(e.target.value); setFile(null) }}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono h-40"
          placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
          disabled={!!file} />

        <button onClick={handleDecode} disabled={(!pem.trim() && !file) || mutation.isPending}
          className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Decoding...' : 'Decode'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm mt-2">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
          <h3 className="font-semibold text-gray-900">Result</h3>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Subject:</span> {result.subject_rfc4514}</div>
            <div><span className="text-gray-500">Issuer:</span> {result.issuer_rfc4514}</div>
            <div><span className="text-gray-500">Serial:</span> <span className="font-mono text-xs">{result.serial}</span> <CopyButton text={result.serial} /></div>
            <div><span className="text-gray-500">Key:</span> {result.key_algo} {result.key_size}</div>
            <div><span className="text-gray-500">Valid From:</span> {new Date(result.not_valid_before).toLocaleDateString()}</div>
            <div><span className="text-gray-500">Valid To:</span> {new Date(result.not_valid_after).toLocaleDateString()}</div>
            <div><span className="text-gray-500">Days Remaining:</span> <span className={result.is_expired ? 'text-red-600 font-bold' : 'text-green-600'}>{result.days_remaining}</span></div>
            <div><span className="text-gray-500">Signature:</span> {result.signature_algorithm}</div>
          </div>
          {result.san.length > 0 && (
            <div>
              <span className="text-gray-500 text-sm">SANs:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {result.san.map((s: any, i: number) => (
                  <span key={i} className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs">{s.type}:{s.value}</span>
                ))}
              </div>
            </div>
          )}
          <div className="text-sm">
            <span className="text-gray-500">SHA-256:</span> <span className="font-mono text-xs">{result.fingerprints.sha256}</span> <CopyButton text={result.fingerprints.sha256} />
          </div>
        </div>
      )}
    </div>
  )
}

function DecodeCSRTool() {
  const [pem, setPem] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (data: FormData) => api.post('/tools/decode-csr', data),
    onSuccess: (res) => setResult(res.data),
  })

  const handleDecode = () => {
    const fd = new FormData()
    if (file) fd.append('csr_file', file)
    else fd.append('csr_pem', pem)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="font-semibold text-gray-900 mb-1">Decode CSR</h3>
        <p className="text-sm text-gray-500 mb-3">Paste a PEM CSR or upload a .csr / .der file to inspect subject, SANs, key, and validate it before submission.</p>

        <div className="mb-3">
          <label className="block text-sm font-medium text-gray-700 mb-1">Upload CSR File</label>
          <div className="flex items-center gap-3">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {file ? file.name : 'Choose file (.csr, .pem, .der)...'}
              <input type="file" className="hidden" accept=".csr,.pem,.der"
                onChange={e => { setFile(e.target.files?.[0] || null); setPem(''); setResult(null) }} />
            </label>
            {file && (
              <>
                <span className="text-xs text-green-600">✓ {(file.size / 1024).toFixed(1)} KB</span>
                <button onClick={() => setFile(null)} className="text-xs text-red-500 hover:text-red-700">Clear</button>
              </>
            )}
          </div>
        </div>

        <div className="relative my-3">
          <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200"></div></div>
          <div className="relative flex justify-center"><span className="bg-white px-2 text-xs text-gray-400">OR paste PEM</span></div>
        </div>

        <textarea value={pem} onChange={e => { setPem(e.target.value); setFile(null); setResult(null) }}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono h-40"
          placeholder="-----BEGIN CERTIFICATE REQUEST-----&#10;...&#10;-----END CERTIFICATE REQUEST-----"
          disabled={!!file} />

        <button onClick={handleDecode} disabled={(!pem.trim() && !file) || mutation.isPending}
          className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Decoding...' : 'Decode CSR'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm mt-2">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          <h3 className="font-semibold text-gray-900">CSR Details</h3>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="col-span-2"><span className="text-gray-500">Subject:</span> <span className="font-mono text-xs">{result.subject_rfc4514}</span></div>
            <div><span className="text-gray-500">Key:</span> {result.key_algo} {result.key_size}-bit</div>
            <div><span className="text-gray-500">Signature:</span> <span className={result.signature_valid ? 'text-green-600' : 'text-red-600'}>{result.signature_valid ? '✓ Valid' : '✗ Invalid'}</span></div>
          </div>

          {result.san.length > 0 && (
            <div>
              <p className="text-sm text-gray-500 mb-1">SANs ({result.san.length})</p>
              <div className="flex flex-wrap gap-1">
                {result.san.map((s: any, i: number) => (
                  <span key={i} className="px-2 py-0.5 bg-blue-100 text-blue-800 rounded text-xs">{s.type}:{s.value}</span>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <p className="text-sm font-medium text-gray-700">Checks</p>
            {result.checks.map((c: any, i: number) => (
              <div key={i} className={`flex items-start gap-2 p-2 rounded text-sm ${
                c.pass ? 'bg-green-50' : 'bg-amber-50'
              }`}>
                <span className={c.pass ? 'text-green-600' : 'text-amber-600'}>{c.pass ? '✓' : '⚠'}</span>
                <div>
                  <span className="font-medium">{c.check}</span>
                  <p className="text-xs text-gray-600 mt-0.5">{c.detail}</p>
                </div>
              </div>
            ))}
          </div>

          <details className="text-xs">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-700">Show PEM</summary>
            <pre className="mt-2 p-3 bg-gray-50 rounded font-mono overflow-x-auto whitespace-pre-wrap break-all">{result.pem}</pre>
          </details>
        </div>
      )}
    </div>
  )
}

function RemoteCheckTool() {
  const [searchParams] = useSearchParams()
  const [hostname, setHostname] = useState(() => searchParams.get('host') || '')
  const [port, setPort] = useState(() => searchParams.get('port') || '443')
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (data: FormData) => api.post('/tools/remote-check', data),
    onSuccess: (res) => setResult(res.data),
  })

  const handleCheck = () => {
    const fd = new FormData()
    fd.append('hostname', hostname)
    fd.append('port', port)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="font-semibold text-gray-900 mb-3">Remote Server Certificate Check</h3>
        <p className="text-sm text-gray-500 mb-3">Connect to a server and inspect its TLS certificate.</p>
        <div className="flex gap-3">
          <input type="text" value={hostname} onChange={e => setHostname(e.target.value)}
            className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="example.com" />
          <input type="number" value={port} onChange={e => setPort(e.target.value)}
            className="w-20 border border-gray-300 rounded-md px-3 py-2 text-sm" />
          <button onClick={handleCheck} disabled={!hostname || mutation.isPending}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
            {mutation.isPending ? 'Checking...' : 'Check'}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          This check runs from the server, not your browser — "localhost" here means this app's own container.
          For a cert on a Docker-published port (e.g. a Build Manager environment's RabbitMQ management UI),
          localhost/127.0.0.1 is automatically retried via host.docker.internal.
        </p>
        {mutation.isError && <p className="text-red-600 text-sm mt-2">{(mutation.error as any)?.response?.data?.detail || 'Connection failed'}</p>}
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-3">
          <div className="flex items-center gap-2">
            <span className={result.hostname_match ? 'text-green-600' : 'text-red-600'}>{result.hostname_match ? '✓' : '✗'}</span>
            <h3 className="font-semibold text-gray-900">{result.hostname}:{result.port}</h3>
          </div>
          {result.resolved_via && (
            <p className="text-xs text-amber-600">
              Connected via {result.resolved_via} — {result.hostname} wasn't reachable directly from the server (expected for a Docker-published port).
            </p>
          )}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Subject:</span> {result.subject.commonName}</div>
            <div><span className="text-gray-500">Issuer:</span> {result.issuer.commonName || result.issuer.organizationName}</div>
            <div><span className="text-gray-500">Expires:</span> {new Date(result.not_valid_after).toLocaleDateString()}</div>
            <div><span className="text-gray-500">Days Left:</span> <span className={result.is_expired ? 'text-red-600' : 'text-green-600'}>{result.days_remaining}</span></div>
            <div><span className="text-gray-500">Hostname Match:</span> <span className={result.hostname_match ? 'text-green-600' : 'text-red-600'}>{result.hostname_match ? 'Yes ✓' : 'No ✗'}</span></div>
            <div><span className="text-gray-500">Serial:</span> <span className="font-mono text-xs">{result.serial?.slice(0, 20)}...</span></div>
          </div>
          {result.san.length > 0 && (
            <div>
              <span className="text-gray-500 text-sm">SANs:</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {result.san.map((s: any, i: number) => (
                  <span key={i} className={`px-2 py-0.5 rounded text-xs ${s.value === hostname ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}`}>{s.value}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function VerifyChainTool() {
  const [certPem, setCertPem] = useState('')
  const [chainPem, setChainPem] = useState('')
  const [certFile, setCertFile] = useState<File | null>(null)
  const [chainFile, setChainFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: async (fd: FormData) => {
      // If files were selected, read them into the form data as text
      let certText = certPem
      let chainText = chainPem
      if (certFile) {
        certText = await certFile.text()
      }
      if (chainFile) {
        chainText = await chainFile.text()
      }
      const formData = new FormData()
      formData.append('cert_pem', certText)
      formData.append('chain_pem', chainText)
      return api.post('/tools/verify-chain', formData)
    },
    onSuccess: (res) => setResult(res.data),
  })

  const canVerify = (!!certPem.trim() || !!certFile) && (!!chainPem.trim() || !!chainFile)

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Verify Certificate Chain</h3>
        <p className="text-sm text-gray-500">Provide the leaf certificate and the CA chain to verify the chain is complete and signatures are valid.</p>

        {/* Leaf certificate */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Leaf Certificate</label>
          <div className="flex items-center gap-3 mb-2">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {certFile ? certFile.name : 'Upload cert file...'}
              <input type="file" className="hidden" accept=".pem,.crt,.cer"
                onChange={e => { setCertFile(e.target.files?.[0] || null); setCertPem('') }} />
            </label>
            {certFile && (
              <>
                <span className="text-xs text-green-600">✓ {(certFile.size / 1024).toFixed(1)} KB</span>
                <button onClick={() => setCertFile(null)} className="text-xs text-red-500 hover:text-red-700">Clear</button>
              </>
            )}
          </div>
          {!certFile && (
            <textarea value={certPem} onChange={e => setCertPem(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono h-28" placeholder="-----BEGIN CERTIFICATE-----" />
          )}
        </div>

        {/* Chain */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">CA Chain (intermediate + root PEM bundle)</label>
          <div className="flex items-center gap-3 mb-2">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {chainFile ? chainFile.name : 'Upload chain file...'}
              <input type="file" className="hidden" accept=".pem,.crt,.cer"
                onChange={e => { setChainFile(e.target.files?.[0] || null); setChainPem('') }} />
            </label>
            {chainFile && (
              <>
                <span className="text-xs text-green-600">✓ {(chainFile.size / 1024).toFixed(1)} KB</span>
                <button onClick={() => setChainFile(null)} className="text-xs text-red-500 hover:text-red-700">Clear</button>
              </>
            )}
          </div>
          {!chainFile && (
            <textarea value={chainPem} onChange={e => setChainPem(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-xs font-mono h-28" placeholder="-----BEGIN CERTIFICATE-----" />
          )}
        </div>

        <button onClick={() => mutation.mutate(new FormData())} disabled={!canVerify || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Verifying...' : 'Verify Chain'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      </div>

      {result && (
        <div className={`bg-white rounded-lg border p-5 ${result.valid ? 'border-green-200' : 'border-red-200'}`}>
          <h3 className={`font-semibold ${result.valid ? 'text-green-700' : 'text-red-700'}`}>
            {result.valid ? '✓ Chain Valid' : '✗ Chain Invalid'}
          </h3>
          <p className="text-sm text-gray-600 mt-1">Chain length: {result.chain_length} certificates</p>
          <div className="mt-3 space-y-2">
            {result.results.map((r: any, i: number) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <span className={r.valid ? 'text-green-600' : 'text-red-600'}>{r.valid ? '✓' : '✗'}</span>
                <span>{r.child}</span> → <span>{r.parent}</span>
              </div>
            ))}
          </div>
          {result.root_is_self_signed && <p className="text-xs text-gray-500 mt-2">Root ({result.root_cn}) is self-signed ✓</p>}
        </div>
      )}
    </div>
  )
}

function KeyMatchTool() {
  const [certFile, setCertFile] = useState<File | null>(null)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [keyPassword, setKeyPassword] = useState('')
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (data: FormData) => api.post('/tools/key-match', data),
    onSuccess: (res) => setResult(res.data),
  })

  const handleCheck = () => {
    if (!certFile || !keyFile) return
    const fd = new FormData()
    fd.append('cert_file', certFile)
    fd.append('key_file', keyFile)
    if (keyPassword) fd.append('key_password', keyPassword)
    mutation.mutate(fd)
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900">Key / Certificate Match Checker</h3>
      <p className="text-sm text-gray-500">Upload a certificate and private key to confirm they're a matching pair.</p>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {certFile ? certFile.name : 'Choose cert...'}
            <input type="file" className="hidden" accept=".pem,.crt,.cer,.der" onChange={e => setCertFile(e.target.files?.[0] || null)} />
          </label>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Private Key</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {keyFile ? keyFile.name : 'Choose key...'}
            <input type="file" className="hidden" accept=".pem,.key,.der" onChange={e => setKeyFile(e.target.files?.[0] || null)} />
          </label>
        </div>
      </div>
      <input type="password" value={keyPassword} onChange={e => setKeyPassword(e.target.value)}
        className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Key passphrase (if encrypted)" />
      <button onClick={handleCheck} disabled={!certFile || !keyFile || mutation.isPending}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        {mutation.isPending ? 'Checking...' : 'Check Match'}
      </button>
      {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Failed'}</p>}
      {result && (
        <div className={`p-3 rounded ${result.match ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
          <p className={`font-medium ${result.match ? 'text-green-700' : 'text-red-700'}`}>{result.message}</p>
          <p className="text-xs text-gray-600 mt-1">Certificate: {result.certificate_cn} (serial: {result.certificate_serial?.slice(0, 16)}...)</p>
        </div>
      )}
    </div>
  )
}

function ConvertTool() {
  const [file, setFile] = useState<File | null>(null)
  const [outputFormat, setOutputFormat] = useState('pem')

  const handleConvert = () => {
    if (!file) return
    const fd = new FormData()
    fd.append('cert_file', file)
    fd.append('output_format', outputFormat)
    // Direct download via form submission
    api.post('/tools/convert', fd, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `converted.${outputFormat}`
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900">Format Converter (PEM ↔ DER)</h3>
      <p className="text-sm text-gray-500">Convert a certificate between PEM and DER formats.</p>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Certificate File</label>
        <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
          {file ? file.name : 'Choose file (.pem or .der)...'}
          <input type="file" className="hidden" accept=".pem,.crt,.cer,.der" onChange={e => setFile(e.target.files?.[0] || null)} />
        </label>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Output Format</label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" checked={outputFormat === 'pem'} onChange={() => setOutputFormat('pem')} /> PEM (Base64)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" checked={outputFormat === 'der'} onChange={() => setOutputFormat('der')} /> DER (Binary)
          </label>
        </div>
      </div>
      <button onClick={handleConvert} disabled={!file}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        Convert & Download
      </button>
    </div>
  )
}

function BuildP12Tool() {
  const [certFile, setCertFile] = useState<File | null>(null)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [chainFile, setChainFile] = useState<File | null>(null)
  const [keyPassword, setKeyPassword] = useState('')
  const [p12Password, setP12Password] = useState('')
  const [friendlyName, setFriendlyName] = useState('certificate')

  const handleBuild = () => {
    if (!certFile || !keyFile) return
    const fd = new FormData()
    fd.append('cert_file', certFile)
    fd.append('key_file', keyFile)
    if (chainFile) fd.append('chain_file', chainFile)
    if (keyPassword) fd.append('key_password', keyPassword)
    fd.append('p12_password', p12Password)
    fd.append('friendly_name', friendlyName)

    api.post('/tools/build-p12', fd, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${friendlyName}.p12`
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900">Build PKCS#12 (.p12) Bundle</h3>
      <p className="text-sm text-gray-500">Combine a certificate, private key, and optional chain into a .p12 file.</p>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate *</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {certFile ? certFile.name : 'Choose cert...'}
            <input type="file" className="hidden" accept=".pem,.crt,.cer" onChange={e => setCertFile(e.target.files?.[0] || null)} />
          </label>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Private Key *</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {keyFile ? keyFile.name : 'Choose key...'}
            <input type="file" className="hidden" accept=".pem,.key" onChange={e => setKeyFile(e.target.files?.[0] || null)} />
          </label>
        </div>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">CA Chain (optional)</label>
        <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
          {chainFile ? chainFile.name : 'Choose chain file...'}
          <input type="file" className="hidden" accept=".pem,.crt" onChange={e => setChainFile(e.target.files?.[0] || null)} />
        </label>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Key Passphrase</label>
          <input type="password" value={keyPassword} onChange={e => setKeyPassword(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="If key is encrypted" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">P12 Password</label>
          <input type="password" value={p12Password} onChange={e => setP12Password(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Set export password" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Friendly Name</label>
          <input type="text" value={friendlyName} onChange={e => setFriendlyName(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>
      <button onClick={handleBuild} disabled={!certFile || !keyFile}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        Build & Download .p12
      </button>
    </div>
  )
}


function CompatibilityCheckTool() {
  const [certFile, setCertFile] = useState<File | null>(null)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [service, setService] = useState('nginx')
  const [hostname, setHostname] = useState('')
  const [result, setResult] = useState<any>(null)

  const services = [
    { id: 'nginx', label: 'Nginx', icon: '🌐' },
    { id: 'mysql', label: 'MySQL / MariaDB', icon: '🗄️' },
    { id: 'rabbitmq', label: 'RabbitMQ', icon: '🐰' },
    { id: 'java', label: 'Java / Spring Boot', icon: '☕' },
    { id: 'keycloak', label: 'Keycloak', icon: '🔐' },
    { id: 'keystone', label: 'OpenStack Keystone', icon: '🏗️' },
  ]

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/compatibility-check', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleCheck = () => {
    if (!certFile) return
    const fd = new FormData()
    fd.append('cert_file', certFile)
    if (keyFile) fd.append('key_file', keyFile)
    fd.append('service', service)
    fd.append('expected_hostname', hostname)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Service Compatibility Check</h3>
        <p className="text-sm text-gray-500">
          Upload a certificate and select a target service to check if the cert meets all requirements for that service.
        </p>

        {/* Service selector */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">Target Service</label>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {services.map(s => (
              <button key={s.id} onClick={() => setService(s.id)}
                className={`flex items-center gap-2 p-3 rounded-lg border text-left text-sm transition ${
                  service === s.id
                    ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
                    : 'border-gray-200 hover:border-gray-300'
                }`}>
                <span>{s.icon}</span>
                <span className="font-medium">{s.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Certificate upload */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate File *</label>
          <div className="flex items-center gap-3">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {certFile ? certFile.name : 'Choose certificate...'}
              <input type="file" className="hidden" accept=".pem,.crt,.cer,.der"
                onChange={e => setCertFile(e.target.files?.[0] || null)} />
            </label>
            {certFile && <span className="text-xs text-green-600">✓ {(certFile.size / 1024).toFixed(1)} KB</span>}
          </div>
        </div>

        {/* Key upload (optional) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Private Key File (optional — enables key checks)</label>
          <div className="flex items-center gap-3">
            <label className="cursor-pointer px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm font-medium hover:bg-gray-100">
              {keyFile ? keyFile.name : 'Choose key file...'}
              <input type="file" className="hidden" accept=".pem,.key,.der"
                onChange={e => setKeyFile(e.target.files?.[0] || null)} />
            </label>
            {keyFile && <span className="text-xs text-green-600">✓</span>}
          </div>
        </div>

        {/* Expected hostname */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Expected Hostname (optional — enables hostname match check)</label>
          <input type="text" value={hostname} onChange={e => setHostname(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="e.g. db.example.internal" />
        </div>

        <button onClick={handleCheck} disabled={!certFile || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Checking...' : 'Check Compatibility'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Check failed'}</p>}
      </div>

      {/* Results */}
      {result && (
        <div className={`bg-white rounded-lg border p-5 ${
          result.overall === 'pass' ? 'border-green-200' :
          result.overall === 'warn' ? 'border-amber-200' : 'border-red-200'
        }`}>
          {/* Summary */}
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">
              {result.overall === 'pass' ? '✅' : result.overall === 'warn' ? '⚠️' : '❌'}
            </span>
            <div>
              <h3 className="font-semibold text-gray-900">{result.summary}</h3>
              <p className="text-xs text-gray-500 mt-1">
                {result.certificate.cn} — {result.certificate.key_algo} {result.certificate.key_size} —
                {result.certificate.san_count} SANs — {result.certificate.days_remaining}d remaining
              </p>
            </div>
          </div>

          {/* Service note */}
          <div className="p-3 bg-gray-50 rounded text-xs text-gray-600 mb-4">
            <strong>{result.service_label}:</strong> {result.notes}
          </div>

          {/* Checklist */}
          <div className="space-y-2">
            {result.checks.map((check: any, i: number) => (
              <div key={i} className={`flex items-start gap-2 p-2 rounded text-sm ${
                check.status === 'pass' ? 'bg-green-50' :
                check.status === 'warn' ? 'bg-amber-50' : 'bg-red-50'
              }`}>
                <span className="mt-0.5">
                  {check.status === 'pass' ? '✓' : check.status === 'warn' ? '⚠' : '✗'}
                </span>
                <div>
                  <span className="font-medium">{check.check}</span>
                  <p className="text-xs text-gray-600 mt-0.5">{check.detail}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Score */}
          <div className="mt-4 pt-3 border-t border-gray-100 flex gap-4 text-xs">
            <span className="text-green-700">{result.pass_count} passed</span>
            <span className="text-amber-700">{result.warn_count} warnings</span>
            <span className="text-red-700">{result.fail_count} failed</span>
          </div>
        </div>
      )}
    </div>
  )
}
