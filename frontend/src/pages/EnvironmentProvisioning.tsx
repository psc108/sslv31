import { useState, useEffect } from 'react'
import api from '@/lib/api'
import WizardStep1 from '@/components/provisioning/WizardStep1'
import WizardStep2 from '@/components/provisioning/WizardStep2'
import WizardStep3 from '@/components/provisioning/WizardStep3'
import WizardStep4 from '@/components/provisioning/WizardStep4'

interface Host {
  role: string
  fqdn: string
  ip: string
}

interface FormState {
  env_name: string
  key_algo: string
  key_size: number
  ca_validity_days: number
  cert_validity_days: number
  ssl_passphrase: string
  encryption_key: string
  cipher_profile: string
  base_path: string
  include_nopass: boolean
  include_snippets: boolean
  include_scripts: boolean
  include_readmes: boolean
  include_quicksetup: boolean
}

interface Template {
  id: string
  name: string
  description: string
  config: any
}

const DEFAULT_HOSTS: Host[] = [
  { role: 'mysql', fqdn: '', ip: '' },
  { role: 'rabbitmq', fqdn: '', ip: '' },
  { role: 'keystone', fqdn: '', ip: '' },
  { role: 'backend', fqdn: '', ip: '' },
  { role: 'frontend', fqdn: '', ip: '' },
]

const DEFAULT_FORM: FormState = {
  env_name: '',
  key_algo: 'RSA',
  key_size: 2048,
  ca_validity_days: 3650,
  cert_validity_days: 365,
  ssl_passphrase: '',
  encryption_key: '',
  cipher_profile: 'intermediate',
  base_path: '/opt/scripts/ssl',
  include_nopass: true,
  include_snippets: true,
  include_scripts: true,
  include_readmes: true,
  include_quicksetup: true,
}

const STEPS = ['Environment', 'Hosts', 'Options', 'Review']

export default function EnvironmentProvisioning() {
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<FormState>({ ...DEFAULT_FORM })
  const [hosts, setHosts] = useState<Host[]>(DEFAULT_HOSTS.map(h => ({ ...h })))
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [profiles, setProfiles] = useState<any>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [saveTemplateName, setSaveTemplateName] = useState('')
  const [showSave, setShowSave] = useState(false)

  useEffect(() => {
    api.get('/provisioning/cipher-profiles').then(r => setProfiles(r.data.profiles)).catch(() => {})
    api.get('/provisioning/templates').then(r => setTemplates(r.data)).catch(() => {})
  }, [])

  const IP_REGEX = /^(\d{1,3}\.){3}\d{1,3}$/
  const FQDN_REGEX = /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/

  const canAdvance = (): boolean => {
    switch (step) {
      case 0: return !!(form.env_name && form.ssl_passphrase.length >= 6 && form.encryption_key.length >= 6)
      case 1: {
        if (!hosts.every(h => h.fqdn && h.ip)) return false
        if (!hosts.every(h => FQDN_REGEX.test(h.fqdn))) return false
        if (!hosts.every(h => IP_REGEX.test(h.ip) && h.ip.split('.').every(o => parseInt(o) <= 255))) return false
        const fqdns = hosts.map(h => h.fqdn)
        const ips = hosts.map(h => h.ip)
        if (new Set(fqdns).size !== fqdns.length) return false
        if (new Set(ips).size !== ips.length) return false
        return true
      }
      case 2: return true
      default: return true
    }
  }

  const handleGenerate = async () => {
    setGenerating(true)
    setError(null)
    try {
      const payload = { ...form, hosts: hosts.filter(h => h.fqdn && h.ip) }
      const res = await api.post('/provisioning/generate', payload, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `${form.env_name}-ssl.zip`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      const text = e.response?.data instanceof Blob
        ? JSON.parse(await e.response.data.text()).detail
        : e.response?.data?.detail || 'Generation failed'
      setError(text)
    } finally {
      setGenerating(false)
    }
  }

  const loadTemplate = (id: string) => {
    const t = templates.find(t => t.id === id)
    if (!t) return
    setSelectedTemplate(id)
    const c = t.config
    setForm({
      env_name: c.env_name || '',
      key_algo: c.key_algo || 'RSA',
      key_size: c.key_size || 2048,
      ca_validity_days: c.ca_validity_days || 3650,
      cert_validity_days: c.cert_validity_days || 365,
      ssl_passphrase: c.ssl_passphrase || '',
      encryption_key: c.encryption_key || '',
      cipher_profile: c.cipher_profile || 'intermediate',
      base_path: c.base_path || '/opt/scripts/ssl',
      include_nopass: c.include_nopass ?? true,
      include_snippets: c.include_snippets ?? true,
      include_scripts: c.include_scripts ?? true,
      include_readmes: c.include_readmes ?? true,
      include_quicksetup: c.include_quicksetup ?? true,
    })
    if (c.hosts?.length) {
      setHosts(DEFAULT_HOSTS.map(dh => {
        const match = c.hosts.find((h: any) => h.role === dh.role)
        return match ? { ...match } : { ...dh }
      }))
    }
  }

  const saveTemplate = async () => {
    if (!saveTemplateName) return
    try {
      const payload = {
        name: saveTemplateName,
        description: `Saved from wizard — ${form.env_name}`,
        config: { ...form, hosts },
      }
      const res = await api.post('/provisioning/templates', payload)
      setTemplates(prev => [...prev, res.data])
      setShowSave(false)
      setSaveTemplateName('')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Save failed')
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold text-gray-900">Environment Provisioning</h2>
          <p className="text-sm text-gray-500">Generate a complete SSL bundle for an SSP deployment</p>
        </div>

        {/* Template controls */}
        <div className="flex items-center gap-2">
          <select value={selectedTemplate}
            onChange={e => loadTemplate(e.target.value)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm">
            <option value="">Load template...</option>
            {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button type="button" onClick={() => setShowSave(!showSave)}
            className="px-3 py-1.5 border border-gray-300 rounded-md text-sm hover:bg-gray-50">
            💾 Save
          </button>
        </div>
      </div>

      {/* Save template inline */}
      {showSave && (
        <div className="mb-4 flex items-center gap-2 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
          <input type="text" value={saveTemplateName}
            onChange={e => setSaveTemplateName(e.target.value)}
            className="flex-1 border border-gray-300 rounded-md px-3 py-1.5 text-sm"
            placeholder="Template name" />
          <button type="button" onClick={saveTemplate} disabled={!saveTemplateName}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50">
            Save
          </button>
          <button type="button" onClick={() => setShowSave(false)}
            className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">Cancel</button>
        </div>
      )}

      {/* Step indicator */}
      <div className="flex items-center gap-1 mb-6">
        {STEPS.map((label, i) => (
          <div key={label} className="flex items-center">
            <div className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-medium ${
              i === step ? 'bg-blue-600 text-white' : i < step ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-500'
            }`}>
              {i < step ? '✓' : i + 1}
            </div>
            <span className={`ml-1 text-xs ${i === step ? 'text-blue-700 font-medium' : 'text-gray-400'}`}>{label}</span>
            {i < STEPS.length - 1 && <div className="w-8 h-px bg-gray-300 mx-1" />}
          </div>
        ))}
      </div>

      {/* Wizard content */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {step === 0 && <WizardStep1 form={form} setForm={setForm} profiles={profiles} />}
        {step === 1 && <WizardStep2 hosts={hosts} setHosts={setHosts} />}
        {step === 2 && <WizardStep3 form={form} setForm={setForm} />}
        {step === 3 && <WizardStep4 form={form} hosts={hosts} generating={generating} error={error} onGenerate={handleGenerate} />}

        {/* Navigation */}
        <div className="flex justify-between mt-6 pt-4 border-t border-gray-100">
          <button type="button" onClick={() => setStep(s => s - 1)} disabled={step === 0}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30">
            ← Back
          </button>
          {step < 3 && (
            <button type="button" onClick={() => setStep(s => s + 1)} disabled={!canAdvance()}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
              Next →
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
