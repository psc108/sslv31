import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import api from '@/lib/api'

export function BuildKeyStoreTool() {
  const [certFile, setCertFile] = useState<File | null>(null)
  const [keyFile, setKeyFile] = useState<File | null>(null)
  const [chainFile, setChainFile] = useState<File | null>(null)
  const [storeType, setStoreType] = useState('PKCS12')
  const [storePassword, setStorePassword] = useState('')
  const [alias, setAlias] = useState('server')

  const handleBuild = () => {
    if (!certFile || !keyFile || !storePassword) return
    const fd = new FormData()
    fd.append('cert_file', certFile)
    fd.append('key_file', keyFile)
    if (chainFile) fd.append('chain_file', chainFile)
    fd.append('store_type', storeType)
    fd.append('store_password', storePassword)
    fd.append('alias', alias)
    api.post('/tools/build-keystore', fd, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${alias}-keystore.${storeType === 'JKS' ? 'jks' : 'p12'}`
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900">Build Java KeyStore from PEM</h3>
      <p className="text-sm text-gray-500">Convert PEM cert + key + chain into a Java KeyStore (.jks or .p12).</p>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate *</label>
          <label className="cursor-pointer block px-4 py-2 bg-gray-50 border border-gray-300 rounded-md text-sm text-center hover:bg-gray-100">
            {certFile ? certFile.name : 'Choose cert...'}
            <input type="file" className="hidden" accept=".pem,.crt" onChange={e => setCertFile(e.target.files?.[0] || null)} />
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
          {chainFile ? chainFile.name : 'Choose chain...'}
          <input type="file" className="hidden" accept=".pem,.crt" onChange={e => setChainFile(e.target.files?.[0] || null)} />
        </label>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Store Type</label>
          <select value={storeType} onChange={e => setStoreType(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="PKCS12">PKCS#12 (recommended)</option>
            <option value="JKS">JKS (legacy)</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Password *</label>
          <input type="password" value={storePassword} onChange={e => setStorePassword(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Min 6 chars" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Alias</label>
          <input type="text" value={alias} onChange={e => setAlias(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>
      <button onClick={handleBuild} disabled={!certFile || !keyFile || !storePassword}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        Build & Download KeyStore
      </button>
    </div>
  )
}

export function MergeTrustStoreTool() {
  const [files, setFiles] = useState<FileList | null>(null)
  const [outputType, setOutputType] = useState('PKCS12')
  const [password, setPassword] = useState('changeit')

  const handleMerge = () => {
    if (!files || files.length === 0) return
    const fd = new FormData()
    for (let i = 0; i < files.length; i++) {
      fd.append('files', files[i])
    }
    fd.append('output_type', outputType)
    fd.append('output_password', password)
    api.post('/tools/merge-truststores', fd, { responseType: 'blob' }).then(res => {
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `merged-truststore.${outputType === 'JKS' ? 'jks' : 'p12'}`
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
      <h3 className="font-semibold text-gray-900">Merge TrustStores</h3>
      <p className="text-sm text-gray-500">
        Merge multiple PEM bundles or truststores into one. Solves the Java problem where a custom truststore replaces all default trust.
      </p>
      <p className="text-xs text-amber-600">
        💡 Tip: Upload your system cacerts (as PEM export) + your internal root-ca.pem to create a truststore that trusts both public and internal CAs.
      </p>
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Certificate / TrustStore Files (select multiple)</label>
        <input type="file" multiple accept=".pem,.crt,.cer"
          onChange={e => setFiles(e.target.files)}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        {files && <p className="text-xs text-green-600 mt-1">{files.length} file(s) selected</p>}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Output Type</label>
          <select value={outputType} onChange={e => setOutputType(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="PKCS12">PKCS#12</option>
            <option value="JKS">JKS</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
        </div>
      </div>
      <button onClick={handleMerge} disabled={!files || files.length === 0}
        className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
        Merge & Download
      </button>
    </div>
  )
}

export function BulkImportTool() {
  const [files, setFiles] = useState<FileList | null>(null)
  const [tags, setTags] = useState('')
  const [source, setSource] = useState('bulk-import')
  const [result, setResult] = useState<any>(null)

  const mutation = useMutation({
    mutationFn: (fd: FormData) => api.post('/tools/bulk-import', fd),
    onSuccess: (res) => setResult(res.data),
  })

  const handleImport = () => {
    if (!files || files.length === 0) return
    const fd = new FormData()
    for (let i = 0; i < files.length; i++) {
      fd.append('files', files[i])
    }
    fd.append('tags', tags)
    fd.append('source', source)
    mutation.mutate(fd)
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Bulk Certificate Import</h3>
        <p className="text-sm text-gray-500">Import multiple existing certificates into the inventory for tracking and monitoring.</p>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate Files (select multiple)</label>
          <input type="file" multiple accept=".pem,.crt,.cer,.der"
            onChange={e => setFiles(e.target.files)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" />
          {files && <p className="text-xs text-green-600 mt-1">{files.length} file(s) selected</p>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tags (comma-separated)</label>
            <input type="text" value={tags} onChange={e => setTags(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="production, aws, migrated" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Source</label>
            <input type="text" value={source} onChange={e => setSource(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="bulk-import" />
          </div>
        </div>
        <button onClick={handleImport} disabled={!files || files.length === 0 || mutation.isPending}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
          {mutation.isPending ? 'Importing...' : 'Import Certificates'}
        </button>
        {mutation.isError && <p className="text-red-600 text-sm">{(mutation.error as any)?.response?.data?.detail || 'Import failed'}</p>}
      </div>

      {result && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="font-semibold text-gray-900 mb-3">Import Results</h3>
          <div className="flex gap-4 text-sm mb-4">
            <span className="text-green-700">✓ {result.summary.imported} imported</span>
            <span className="text-amber-700">⊘ {result.summary.skipped} skipped</span>
            <span className="text-red-700">✗ {result.summary.failed} failed</span>
          </div>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {result.results.map((r: any, i: number) => (
              <div key={i} className={`text-xs p-2 rounded flex justify-between ${
                r.status === 'imported' ? 'bg-green-50' : r.status === 'skipped' ? 'bg-amber-50' : 'bg-red-50'
              }`}>
                <span>{r.file} {r.cn && `— ${r.cn}`}</span>
                <span className="text-gray-500">{r.status}{r.reason ? `: ${r.reason}` : ''}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
