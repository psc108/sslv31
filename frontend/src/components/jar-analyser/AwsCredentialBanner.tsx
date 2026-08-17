import { useState, useEffect } from 'react'
import api from '../../lib/api'

interface CredentialStatus {
  configured: boolean
  valid: boolean
  account_id: string
  arn: string
  region: string
  validated_at: string | null
}

export default function AwsCredentialBanner() {
  const [status, setStatus] = useState<CredentialStatus | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ access_key_id: '', secret_access_key: '', session_token: '', region: 'eu-west-2' })
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadStatus = async () => {
    try {
      const res = await api.get('/aws/credential-status')
      setStatus(res.data)
    } catch {
      setStatus(null)
    }
  }

  useEffect(() => { loadStatus() }, [])

  const handleSaveAndValidate = async () => {
    setError(null)
    setSaving(true)
    try {
      await api.post('/aws/credentials', form)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to store credentials')
      setSaving(false)
      return
    }
    setSaving(false)
    setValidating(true)
    try {
      await api.post('/aws/validate-credentials')
      setShowForm(false)
      setForm({ access_key_id: '', secret_access_key: '', session_token: '', region: 'eu-west-2' })
      await loadStatus()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Credential validation failed')
    }
    setValidating(false)
  }

  const handleClear = async () => {
    await api.delete('/aws/credentials')
    await loadStatus()
  }

  const busy = saving || validating

  if (showForm) {
    return (
      <div className="border border-yellow-400 bg-yellow-50 rounded-lg p-4 mb-4">
        <h3 className="font-semibold text-yellow-800 mb-3">Enter AWS Credentials</h3>
        <p className="text-sm text-yellow-700 mb-3">
          Paste your STS temporary credentials (from <code>aws-env-vars.ps1</code> or equivalent).
          These are held in memory only and cleared on container restart.
        </p>
        <div className="grid grid-cols-1 gap-2">
          {[
            { key: 'access_key_id', label: 'Access Key ID', placeholder: 'ASIA...' },
            { key: 'secret_access_key', label: 'Secret Access Key', placeholder: '' },
            { key: 'session_token', label: 'Session Token', placeholder: 'IQoJ...' },
            { key: 'region', label: 'Region', placeholder: 'eu-west-2' },
          ].map(({ key, label, placeholder }) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
              <input
                type={key === 'secret_access_key' || key === 'session_token' ? 'password' : 'text'}
                className="w-full border border-gray-300 rounded px-2 py-1 text-sm font-mono"
                placeholder={placeholder}
                value={(form as any)[key]}
                onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                disabled={busy}
              />
            </div>
          ))}
        </div>
        {error && <p className="text-red-600 text-sm mt-2">{error}</p>}
        <div className="flex gap-2 mt-3">
          <button
            onClick={handleSaveAndValidate}
            disabled={busy || !form.access_key_id || !form.secret_access_key}
            className="px-3 py-1.5 bg-yellow-600 text-white rounded text-sm hover:bg-yellow-700 disabled:opacity-50"
          >
            {saving ? 'Saving…' : validating ? 'Validating…' : 'Save & Validate'}
          </button>
          <button
            onClick={() => { setShowForm(false); setError(null) }}
            disabled={busy}
            className="px-3 py-1.5 border border-gray-300 rounded text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

  if (!status) return null

  if (!status.configured || !status.valid) {
    return (
      <div className="border border-orange-300 bg-orange-50 rounded-lg p-3 mb-4 flex items-center justify-between">
        <div>
          <span className="text-orange-700 font-medium text-sm">⚠ AWS credentials not configured</span>
          <p className="text-orange-600 text-xs mt-0.5">Required for AWS environment provisioning</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          className="px-3 py-1.5 bg-orange-600 text-white rounded text-sm hover:bg-orange-700"
        >
          Configure
        </button>
      </div>
    )
  }

  return (
    <div className="border border-green-300 bg-green-50 rounded-lg p-3 mb-4 flex items-center justify-between">
      <div>
        <span className="text-green-700 font-medium text-sm">✓ AWS credentials active</span>
        <p className="text-green-600 text-xs mt-0.5">
          Account: {status.account_id} · Region: {status.region}
          {status.validated_at && ` · Validated ${new Date(status.validated_at).toLocaleTimeString()}`}
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => setShowForm(true)}
          className="px-2 py-1 border border-green-400 text-green-700 rounded text-xs hover:bg-green-100"
        >
          Update
        </button>
        <button
          onClick={handleClear}
          className="px-2 py-1 border border-gray-300 text-gray-600 rounded text-xs hover:bg-gray-100"
        >
          Clear
        </button>
      </div>
    </div>
  )
}
