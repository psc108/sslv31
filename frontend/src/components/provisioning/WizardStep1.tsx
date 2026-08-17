import { useEffect, useState } from 'react'

interface CipherProfile {
  name: string
  description: string
  min_tls: string
  ciphers: string[]
}

interface Props {
  form: any
  setForm: (fn: (prev: any) => any) => void
  profiles: Record<string, CipherProfile> | null
}

function generatePassword(len = 24): string {
  const chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*'
  return Array.from(crypto.getRandomValues(new Uint8Array(len)))
    .map(b => chars[b % chars.length]).join('')
}

function passwordStrength(pw: string): { label: string; color: string; width: string } {
  if (!pw) return { label: '', color: 'bg-gray-200', width: 'w-0' }
  let score = 0
  if (pw.length >= 8) score++
  if (pw.length >= 12) score++
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++
  if (/\d/.test(pw)) score++
  if (/[^a-zA-Z0-9]/.test(pw)) score++
  if (score <= 1) return { label: 'Weak', color: 'bg-red-500', width: 'w-1/5' }
  if (score <= 2) return { label: 'Fair', color: 'bg-orange-400', width: 'w-2/5' }
  if (score <= 3) return { label: 'Good', color: 'bg-yellow-400', width: 'w-3/5' }
  if (score <= 4) return { label: 'Strong', color: 'bg-green-400', width: 'w-4/5' }
  return { label: 'Excellent', color: 'bg-green-600', width: 'w-full' }
}

export default function WizardStep1({ form, setForm, profiles }: Props) {
  const [showPass, setShowPass] = useState(false)
  const [showEnc, setShowEnc] = useState(false)

  return (
    <div className="space-y-5">
      <h3 className="font-semibold text-gray-900">Environment & Security</h3>

      {/* Environment Name */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Environment Name *</label>
        <input type="text" value={form.env_name}
          onChange={e => setForm(p => ({ ...p, env_name: e.target.value }))}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="dev-01" maxLength={64} />
        <p className="text-xs text-gray-400 mt-1">Used as ZIP filename and CA CN prefix</p>
      </div>

      {/* Key Algorithm & Size */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Key Algorithm</label>
          <select value={form.key_algo}
            onChange={e => setForm(p => ({ ...p, key_algo: e.target.value, key_size: e.target.value === 'ECDSA' ? 256 : 2048 }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            <option value="RSA">RSA</option>
            <option value="ECDSA">ECDSA</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Key Size</label>
          <select value={form.key_size}
            onChange={e => setForm(p => ({ ...p, key_size: Number(e.target.value) }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm">
            {form.key_algo === 'RSA'
              ? <><option value={2048}>2048</option><option value={3072}>3072</option><option value={4096}>4096</option></>
              : <><option value={256}>P-256</option><option value={384}>P-384</option></>}
          </select>
        </div>
      </div>

      {/* Validity */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">CA Validity (days)</label>
          <input type="number" value={form.ca_validity_days}
            onChange={e => setForm(p => ({ ...p, ca_validity_days: Number(e.target.value) }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" min={365} max={7300} />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cert Validity (days)</label>
          <input type="number" value={form.cert_validity_days}
            onChange={e => setForm(p => ({ ...p, cert_validity_days: Number(e.target.value) }))}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" min={30} max={3650} />
        </div>
      </div>

      {/* SSL Passphrase */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">SSL Passphrase *</label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input type={showPass ? 'text' : 'password'} value={form.ssl_passphrase}
              onChange={e => setForm(p => ({ ...p, ssl_passphrase: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm pr-10"
              placeholder="Keystore/truststore password" />
            <button type="button" onClick={() => setShowPass(!showPass)}
              className="absolute right-2 top-2 text-gray-400 hover:text-gray-600 text-sm">
              {showPass ? '🙈' : '👁️'}
            </button>
          </div>
          <button type="button"
            onClick={() => setForm(p => ({ ...p, ssl_passphrase: generatePassword() }))}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm hover:bg-gray-50" title="Generate random">
            🎲
          </button>
        </div>
        {form.ssl_passphrase && (
          <div className="mt-1 flex items-center gap-2">
            <div className="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div className={`h-full ${passwordStrength(form.ssl_passphrase).color} ${passwordStrength(form.ssl_passphrase).width} transition-all`} />
            </div>
            <span className="text-xs text-gray-500">{passwordStrength(form.ssl_passphrase).label}</span>
          </div>
        )}
        <p className="text-xs text-gray-400 mt-1">Used for all keystores and truststores (min 6 chars)</p>
      </div>

      {/* Encryption Key */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Jasypt Encryption Key *</label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <input type={showEnc ? 'text' : 'password'} value={form.encryption_key}
              onChange={e => setForm(p => ({ ...p, encryption_key: e.target.value }))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm pr-10"
              placeholder="propertiesEncryptionKey value" />
            <button type="button" onClick={() => setShowEnc(!showEnc)}
              className="absolute right-2 top-2 text-gray-400 hover:text-gray-600 text-sm">
              {showEnc ? '🙈' : '👁️'}
            </button>
          </div>
          <button type="button"
            onClick={() => setForm(p => ({ ...p, encryption_key: generatePassword(16) }))}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm hover:bg-gray-50" title="Generate random">
            🎲
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-1">Used to produce ENC(...) values in quicksetup properties</p>
      </div>

      {/* Cipher Profile */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Cipher Profile</label>
        <div className="space-y-2">
          {(['modern', 'intermediate', 'legacy'] as const).map(key => {
            const p = profiles?.[key]
            return (
              <label key={key}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition ${
                  form.cipher_profile === key ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500' : 'border-gray-200 hover:border-gray-300'
                }`}>
                <input type="radio" name="cipher_profile" value={key} checked={form.cipher_profile === key}
                  onChange={() => setForm(prev => ({ ...prev, cipher_profile: key }))}
                  className="mt-1" />
                <div>
                  <div className="font-medium text-sm text-gray-900 capitalize">{key}</div>
                  <div className="text-xs text-gray-500">
                    {p ? `${p.description} — Min TLS: ${p.min_tls}` : key === 'modern' ? 'TLS 1.3 only — best security' : key === 'intermediate' ? 'TLS 1.2 + 1.3 — recommended' : 'TLS 1.1+ — legacy support'}
                  </div>
                </div>
              </label>
            )
          })}
        </div>
      </div>
    </div>
  )
}
