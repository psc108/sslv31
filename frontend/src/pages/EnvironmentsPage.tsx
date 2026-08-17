import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import AwsCredentialBanner from '@/components/jar-analyser/AwsCredentialBanner'

interface Environment {
  id: string
  name: string
  template_id: string
  template_name: string | null
  template_version: number
  status: string
  ip_allocations: Record<string, string>
  variables: Record<string, any>
  created_by: string
  created_at: string
  destroyed_at: string | null
  expires_at: string | null
  certs?: { id: string; cert_serial: string; role: string; cert_type: string; issued_at: string; revoked_at: string | null }[]
}

interface TlsResult {
  product: string
  port: number
  status: string
  host?: string
  subject?: string
  issuer?: string
  expiry?: string
  verify?: string
  protocol?: string
  cipher?: string
  error?: string
  detail?: string
  require_secure_transport?: string
  session_cipher?: string
}

interface VerifyResults {
  available: boolean
  job_id?: string
  job_status?: string
  ran_at?: string
  message?: string
  status?: string
  summary?: { total: number; passed: number; failed: number; warnings: number }
  results?: TlsResult[]
}

interface TemplateOption {
  id: string
  name: string
  current_version: number
  current_spec: any
}

interface SchemaField {
  key: string
  label: string
  type: 'text' | 'password' | 'number' | 'list' | 'checkbox' | 'textarea' | 'select'
  required?: boolean
  default?: any
  placeholder?: string
  options?: string[]
  item_schema?: SchemaField[]
}

interface ProductCatalogue {
  name: string
  default_ports: number[]
  versions: { version: string; config_schema: SchemaField[] }[]
}

export default function EnvironmentsPage() {
  const navigate = useNavigate()
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [catalogue, setCatalogue] = useState<ProductCatalogue[]>([])
  const [selected, setSelected] = useState<Environment | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState<string | null>(null)
  const [verifyResults, setVerifyResults] = useState<VerifyResults | null>(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [platform, setPlatform] = useState<{ platform: string; expose_ports_applicable: boolean }>({ platform: 'on-prem', expose_ports_applicable: false })
  const [envDetailTab, setEnvDetailTab] = useState<'overview' | 'aws' | 'certs'>('overview')
  const [awsOutputs, setAwsOutputs] = useState<Record<string, any> | null>(null)
  const [awsLoading, setAwsLoading] = useState<string | null>(null)
  const [envCerts, setEnvCerts] = useState<any[]>([])

  const [form, setForm] = useState({ name: '', template_id: '', template_version: null as number | null, signing_ca_id: '', ttl_hours: '', extra_trusted_ca_pem: '' })
  const [editingEnvId, setEditingEnvId] = useState<string | null>(null)
  const [editTimeoutMinutes, setEditTimeoutMinutes] = useState<number | ''>('')
  const [editExtraTrustedCaPem, setEditExtraTrustedCaPem] = useState('')
  const [jarImportOpen, setJarImportOpen] = useState(false)
  const [jarReportId, setJarReportId] = useState('')
  const [jarFeed, setJarFeed] = useState<any>(null)
  const [jarFeedLoading, setJarFeedLoading] = useState(false)
  const [hostMap, setHostMap] = useState<Record<string, string>>({})
  const [templateRoles, setTemplateRoles] = useState<{ role: string; products: { product: string; version: string; vars: Record<string, any> }[] }[]>([])
  // productConfig: { "host-01": { "mysql": { mysql_root_password: "...", ... } } }
  const [productConfig, setProductConfig] = useState<Record<string, Record<string, any>>>({})
  const [exposePorts, setExposePorts] = useState<Record<string, boolean>>({})
  // nfsVolumeNames: a named Docker volume to bind-mount into a role's
  // container (e.g. the NFS Server reference template's export dir) — a
  // Docker-level mount, not an Ansible var, so it's kept separate from
  // productConfig. A named volume, not a raw host path, since only a real
  // Docker-managed filesystem is reliably NFS-exportable (a host-path bind
  // can land on a passthrough filesystem — e.g. Docker Desktop for Windows
  // shares host drives via 9p — that the kernel NFS server can't export).
  const [nfsVolumeNames, setNfsVolumeNames] = useState<Record<string, string>>({})
  const [signingCas, setSigningCas] = useState<any[]>([])
  const [preflightModal, setPreflightModal] = useState<{ id: string; report: { ready: boolean; hosts: { role: string; checked: boolean; ready: boolean; blockers: string[] }[] } } | null>(null)
  const [inventoryHosts, setInventoryHosts] = useState<{id: string; hostname: string; ip: string; service_role: string; connection_type: string; container_name: string; ansible_host: string}[]>([])

  const { data: jarReports } = useQuery<{ items: any[] }>({
    queryKey: ['jar-reports-for-bm'],
    queryFn: () => api.get('/jar-analyser/reports', { params: { page_size: 50 } }).then(r => r.data),
    enabled: jarImportOpen,
  })

  const fetchJarFeed = async (id: string) => {
    if (!id) { setJarFeed(null); return }
    setJarFeedLoading(true)
    try {
      const res = await api.get(`/jar-analyser/reports/${id}/build-manager-feed`)
      setJarFeed(res.data)
    } catch { setJarFeed(null) }
    setJarFeedLoading(false)
  }

  const applyJarFeed = () => {
    if (!jarFeed) return
    // Pre-populate host map from service names
    const newHostMap: Record<string, string> = { ...hostMap }
    for (const svc of jarFeed.services ?? []) {
      if (svc.name && !newHostMap[svc.name]) {
        newHostMap[svc.name] = svc.name
      }
    }
    setHostMap(newHostMap)
    setJarImportOpen(false)
    setJarFeed(null)
    setSuccess(`Imported ${jarFeed.services?.length ?? 0} services from JAR analysis`)
  }

  const loadInventoryHosts = useCallback(async () => {
    try {
      const res = await api.get('/build/hosts')
      setInventoryHosts(res.data)
    } catch {}
  }, [])

  const loadEnvironments = useCallback(async () => {
    try {
      const res = await api.get('/build/environments')
      setEnvironments(res.data)
    } catch { setError('Failed to load environments') }
  }, [])

  const loadTemplates = useCallback(async () => {
    try {
      const res = await api.get('/build/templates')
      setTemplates(res.data)
    } catch {}
  }, [])

  const loadCatalogue = useCallback(async () => {
    try {
      const res = await api.get('/build/catalogue')
      setCatalogue(res.data)
    } catch {}
  }, [])

  const loadPlatform = useCallback(async () => {
    try {
      const res = await api.get('/build/platform')
      setPlatform(res.data)
    } catch {}
  }, [])

  const loadSigningCas = useCallback(async () => {
    try {
      const res = await api.get('/build/signing-cas')
      setSigningCas(res.data)
      // Auto-select recommended
      const rec = res.data.find((c: any) => c.recommended)
      if (rec) setForm(f => ({ ...f, signing_ca_id: rec.id }))
    } catch {}
  }, [])

  useEffect(() => { loadEnvironments(); loadTemplates(); loadCatalogue(); loadPlatform(); loadSigningCas(); loadInventoryHosts() }, [loadEnvironments, loadTemplates, loadCatalogue, loadPlatform, loadSigningCas, loadInventoryHosts])

  const getSchema = (productName: string, version: string): SchemaField[] => {
    const product = catalogue.find(p => p.name === productName)
    if (!product) return []
    const ver = product.versions.find(v => v.version === version) || product.versions.find(v => (v as any).is_latest)
    return ver?.config_schema || []
  }

  const onTemplateChange = (templateId: string) => {
    setForm({ ...form, template_id: templateId })
    const tmpl = templates.find(t => t.id === templateId)
    if (tmpl?.current_spec?.hosts) {
      const roles = tmpl.current_spec.hosts.map((h: any) => ({
        role: h.role,
        products: (h.products || []).map((p: any) => ({ product: p.product, version: p.version || '', vars: p.vars || {} })),
      }))
      setTemplateRoles(roles)

      // Compute default IPs: prefer spec ip, then match inventory by host_id/hostname/role, then network range
      const network = tmpl.current_spec.network || {}
      const pool = network.pool || network.subnet || ''
      let rangeStart = network.range_start ?? 10
      if (typeof rangeStart === 'string') rangeStart = parseInt(rangeStart.split('.').pop() || '10')
      const map: Record<string, string> = {}
      const prefix = pool ? pool.replace(/\d+\/\d+$/, '') : ''
      let rangeIdx = 0
      for (const h of tmpl.current_spec.hosts) {
        if (h.ip) {
          map[h.role] = h.ip
        } else {
          // Try to resolve from inventory
          const inv = h.inventory_host_id
            ? inventoryHosts.find(i => i.id === h.inventory_host_id)
            : inventoryHosts.find(i => i.hostname === h.role || i.service_role === h.role)
          if (inv) {
            map[h.role] = inv.ansible_host
          } else if (prefix) {
            map[h.role] = `${prefix}${(rangeStart as number) + rangeIdx}`
          }
        }
        rangeIdx++
      }
      setHostMap(map)

      // Initialize expose ports (default on for Docker)
      const ep: Record<string, boolean> = {}
      for (const r of roles) {
        if (r.products.some((p: any) => {
          const cat = catalogue.find(c => c.name === p.product)
          return cat?.default_ports?.length
        })) {
          ep[r.role] = true
        }
      }
      setExposePorts(ep)

      // Initialize product config with defaults from schema, overlaid with
      // whatever the template itself already bakes in for this product
      // (e.g. the NFS Server reference template's nfs_exports). Template
      // vars must win over schema defaults here — otherwise a config_schema
      // field's own default (even an empty list) silently overwrites a
      // real value the template author already supplied, since this is
      // what actually gets submitted as variables.product_config and that
      // takes precedence over the template's vars server-side (found via
      // a real build failure: nfs_exports came through empty because the
      // schema default for that field is `[]`).
      const cfg: Record<string, Record<string, any>> = {}
      for (const r of roles) {
        cfg[r.role] = {}
        for (const p of r.products) {
          const schema = getSchema(p.product, p.version)
          const defaults: Record<string, any> = {}
          for (const field of schema) {
            if (field.default !== undefined && field.default !== '') defaults[field.key] = field.default
          }
          if (schema.length > 0) cfg[r.role][p.product] = { ...defaults, ...p.vars }
        }
      }
      setProductConfig(cfg)
      setNfsVolumeNames({})
    } else {
      setTemplateRoles([])
      setHostMap({})
      setProductConfig({})
      setExposePorts({})
      setNfsVolumeNames({})
    }
  }

  const updateProductVar = (role: string, product: string, key: string, value: any) => {
    setProductConfig(prev => ({
      ...prev,
      [role]: { ...prev[role], [product]: { ...(prev[role]?.[product] || {}), [key]: value } }
    }))
  }

  const updateListItem = (role: string, product: string, key: string, index: number, itemKey: string, value: string) => {
    setProductConfig(prev => {
      const list = [...(prev[role]?.[product]?.[key] || [])]
      list[index] = { ...list[index], [itemKey]: value }
      return { ...prev, [role]: { ...prev[role], [product]: { ...(prev[role]?.[product] || {}), [key]: list } } }
    })
  }

  const addListItem = (role: string, product: string, key: string, itemSchema: SchemaField[]) => {
    setProductConfig(prev => {
      const list = [...(prev[role]?.[product]?.[key] || [])]
      const newItem: Record<string, string> = {}
      for (const f of itemSchema) newItem[f.key] = f.default || ''
      list.push(newItem)
      return { ...prev, [role]: { ...prev[role], [product]: { ...(prev[role]?.[product] || {}), [key]: list } } }
    })
  }

  const removeListItem = (role: string, product: string, key: string, index: number) => {
    setProductConfig(prev => {
      const list = [...(prev[role]?.[product]?.[key] || [])]
      list.splice(index, 1)
      return { ...prev, [role]: { ...prev[role], [product]: { ...(prev[role]?.[product] || {}), [key]: list } } }
    })
  }

  const selectEnv = async (env: Environment) => {
    try {
      const res = await api.get(`/build/environments/${env.id}`)
      setSelected(res.data)
      setVerifyResults(null)
      setAwsOutputs(null)
      setEnvCerts([])
      setEnvDetailTab('overview')
      if (['active', 'degraded', 'failed'].includes(env.status)) {
        loadVerifyResults(env.id)
      }
      // Load AWS outputs if this is an AWS environment
      const tmpl = templates.find(t => t.id === env.template_id)
      if (tmpl?.current_spec?.aws) {
        api.get(`/build/environments/${env.id}/outputs`).then(r => setAwsOutputs(r.data)).catch(() => {})
      }
      // Always load certs
      api.get(`/build/environments/${env.id}/certs`).then(r => setEnvCerts(r.data)).catch(() => {})
    } catch { setError('Failed to load environment details') }
  }

  const getProductPorts = (role: string): number[] => {
    const r = templateRoles.find(tr => tr.role === role)
    if (!r) return []
    const ports: number[] = []
    for (const p of r.products) {
      const cat = catalogue.find(c => c.name === p.product)
      if (cat?.default_ports) ports.push(...cat.default_ports)
    }
    // Ports 80 and 8000 are always owned by the ssl-cert-manager container's
    // own -p flags, so neither can ever actually be published for another
    // host — exclude both here so the checkbox never offers a port that
    // would just fail at container creation.
    return ports.filter(p => p !== 80 && p !== 8000)
  }

  const createEnv = async () => {
    const selectedTemplate = templates.find(t => t.id === form.template_id)
    const isAwsTemplate = !!selectedTemplate?.current_spec?.aws
    if (!isAwsTemplate) {
      const emptyRoles = Object.entries(hostMap).filter(([, v]) => !v.trim())
      if (emptyRoles.length > 0) {
        setError(`Please specify a hostname/IP for: ${emptyRoles.map(([k]) => k).join(', ')}`)
        return
      }
    }
    const volumeNameRe = /^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/
    const badVolumeNames = Object.entries(nfsVolumeNames).filter(([, v]) => v.trim() && !volumeNameRe.test(v.trim()))
    if (badVolumeNames.length > 0) {
      setError(`Storage Volume Name '${badVolumeNames[0][1]}' isn't a valid Docker volume name — it looks like a filesystem path. Use a short name like 'my-nfs-data' instead; Docker creates the volume automatically.`)
      return
    }
    try {
      const body: any = {
        name: form.name,
        template_id: form.template_id,
        ip_overrides: hostMap,
        variables: {
          product_config: productConfig, expose_ports: exposePorts, signing_ca_id: form.signing_ca_id || undefined,
          nfs_volumes: nfsVolumeNames, extra_trusted_ca_pem: form.extra_trusted_ca_pem.trim() || undefined,
        },
      }
      if (form.template_version) body.template_version = form.template_version
      if (form.ttl_hours.trim()) body.ttl_hours = parseFloat(form.ttl_hours)
      await api.post('/build/environments', body)
      setShowCreate(false)
      setForm({ name: '', template_id: '', template_version: null, signing_ca_id: signingCas.find(c => c.recommended)?.id || '', ttl_hours: '', extra_trusted_ca_pem: '' })
      setHostMap({})
      setTemplateRoles([])
      setProductConfig({})
      setExposePorts({})
      setNfsVolumeNames({})
      setSuccess('Environment created')
      loadEnvironments()
    } catch (e: any) { setError(e.response?.data?.detail || 'Failed to create environment') }
  }

  const verifyTls = async (id: string) => {
    setVerifyLoading(true)
    setVerifyResults(null)
    try {
      const res = await api.post(`/build/environments/${id}/verify`)
      setSuccess('TLS verification started')
      // Poll for results
      const jobId = res.data.job_id
      const poll = async () => {
        const r = await api.get(`/build/environments/${id}/verify-results`)
        if (r.data.available) {
          setVerifyResults(r.data)
          setVerifyLoading(false)
        } else if (r.data.status === 'running' || r.data.status === 'pending') {
          setTimeout(poll, 2000)
        } else {
          setVerifyResults(r.data)
          setVerifyLoading(false)
        }
      }
      setTimeout(poll, 3000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Verify failed')
      setVerifyLoading(false)
    }
  }

  const loadVerifyResults = async (id: string) => {
    try {
      const r = await api.get(`/build/environments/${id}/verify-results`)
      if (r.data.available) setVerifyResults(r.data)
    } catch {}
  }

  const planEnv = async (id: string) => {
    setAwsLoading('plan')
    try {
      const res = await api.post(`/build/environments/${id}/plan`)
      setSuccess('Plan job started')
      navigate(`/jobs?id=${res.data.job_id}`)
    } catch (e: any) { setError(e.response?.data?.detail || 'Plan failed') }
    setAwsLoading(null)
  }

  const applyEnv = async (id: string) => {
    if (!confirm('Apply the saved plan? This will create/modify AWS infrastructure.')) return
    setAwsLoading('apply')
    try {
      const res = await api.post(`/build/environments/${id}/apply`)
      setSuccess('Apply job started')
      navigate(`/jobs?id=${res.data.job_id}`)
    } catch (e: any) { setError(e.response?.data?.detail || 'Apply failed') }
    setAwsLoading(null)
  }

  const destroyEnvAws = async (id: string) => {
    if (!confirm('Destroy all AWS infrastructure for this environment? This cannot be undone.')) return
    setAwsLoading('destroy')
    try {
      const res = await api.post(`/build/environments/${id}/tofu-destroy`)
      setSuccess('Destroy job started')
      navigate(`/jobs?id=${res.data.job_id}`)
    } catch (e: any) { setError(e.response?.data?.detail || 'Destroy failed') }
    setAwsLoading(null)
  }

  const downloadEnvFile = async (url: string, filename: string) => {
    // Plain <a href> anchors don't carry the app's auth (a Bearer token /
    // X-API-Key header injected by the api client from localStorage, not a
    // cookie) — a direct browser navigation to an API endpoint always came
    // back "Missing or invalid authentication". Fetch through the
    // authenticated client instead and trigger the download from the blob.
    try {
      const res = await api.get(url, { responseType: 'blob' })
      const blobUrl = URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      a.click()
      URL.revokeObjectURL(blobUrl)
    } catch (e: any) {
      // With responseType: 'blob', an error response body comes back as a
      // Blob too (not parsed JSON), so e.response.data.detail is always
      // undefined here — read it out explicitly or every failure just says
      // the generic fallback message, masking the real reason.
      let detail = 'Download failed'
      if (e.response?.data instanceof Blob) {
        try { detail = JSON.parse(await e.response.data.text())?.detail || detail } catch { /* not JSON */ }
      } else if (e.response?.data?.detail) {
        detail = e.response.data.detail
      }
      setError(detail)
    }
  }

  const renewCerts = async (id: string) => {
    if (!confirm('Re-issue all certificates for this environment? Existing certs will be revoked.')) return
    try {
      const res = await api.post(`/build/environments/${id}/certs/renew`)
      setSuccess(`Renewed ${res.data.renewed} certificate(s)`)
      api.get(`/build/environments/${id}/certs`).then(r => setEnvCerts(r.data)).catch(() => {})
    } catch (e: any) { setError(e.response?.data?.detail || 'Renewal failed') }
  }

  const buildEnv = async (id: string, force = false, dryRun = false) => {
    setLoading(id)
    try {
      const params = new URLSearchParams()
      if (force) params.set('force', 'true')
      if (dryRun) params.set('dry_run', 'true')
      const qs = params.toString()
      const res = await api.post(`/build/environments/${id}/build${qs ? `?${qs}` : ''}`)
      setSuccess(dryRun ? 'Dry-run build started (no changes will be applied)' : 'Build started')
      setPreflightModal(null)
      loadEnvironments()
      navigate(`/jobs?id=${res.data.job_id}`)
    } catch (e: any) {
      const preflight = e.response?.status === 422 && e.response?.data?.detail?.preflight
      if (preflight) {
        setPreflightModal({ id, report: preflight })
      } else {
        setError(e.response?.data?.detail || 'Build failed')
      }
    }
    setLoading(null)
  }

  const destroyEnv = async (id: string) => {
    if (!confirm('Destroy this environment? All certificates will be revoked.')) return
    setLoading(id)
    try {
      await api.post(`/build/environments/${id}/destroy`)
      setSuccess('Environment destroyed')
      setSelected(null)
      loadEnvironments()
    } catch (e: any) { setError(e.response?.data?.detail || 'Destroy failed') }
    setLoading(null)
  }

  const openEditConfig = (env: Environment) => {
    const tmpl = templates.find(t => t.id === env.template_id)
    if (!tmpl?.current_spec?.hosts) {
      setError('Could not load this template\'s spec to edit configuration')
      return
    }
    const roles = tmpl.current_spec.hosts.map((h: any) => ({
      role: h.role,
      products: (h.products || []).map((p: any) => ({ product: p.product, version: p.version || '', vars: p.vars || {} })),
    }))
    setTemplateRoles(roles)

    // Seed from schema defaults + template vars same as environment creation,
    // then overlay this environment's actually-stored product_config on top
    // (the values a rebuild would apply) so the form shows what's really
    // there — not just an empty box for whatever was left unset originally
    // (e.g. RabbitMQ's admin password, whose schema default is '').
    const existingPC = env.variables?.product_config || {}
    const cfg: Record<string, Record<string, any>> = {}
    for (const r of roles) {
      cfg[r.role] = {}
      for (const p of r.products) {
        const schema = getSchema(p.product, p.version)
        const defaults: Record<string, any> = {}
        for (const field of schema) {
          if (field.default !== undefined && field.default !== '') defaults[field.key] = field.default
        }
        if (schema.length > 0) cfg[r.role][p.product] = { ...defaults, ...p.vars, ...(existingPC[r.role]?.[p.product] || {}) }
      }
    }
    setProductConfig(cfg)
    setExposePorts(env.variables?.expose_ports || {})
    setNfsVolumeNames(env.variables?.nfs_volumes || {})
    // '' means "no override — inherit whatever the template resolves to";
    // only set state when this environment already has one stored.
    setEditTimeoutMinutes(env.variables?.ansible_timeout_minutes ?? '')
    setEditExtraTrustedCaPem(env.variables?.extra_trusted_ca_pem || '')
    setEditingEnvId(env.id)
  }

  const saveEnvConfig = async () => {
    if (!editingEnvId) return
    const env = environments.find(e => e.id === editingEnvId)
    try {
      const variables: Record<string, any> = { ...(env?.variables || {}), product_config: productConfig, expose_ports: exposePorts, nfs_volumes: nfsVolumeNames }
      if (editTimeoutMinutes === '') delete variables.ansible_timeout_minutes
      else variables.ansible_timeout_minutes = editTimeoutMinutes
      if (editExtraTrustedCaPem.trim() === '') delete variables.extra_trusted_ca_pem
      else variables.extra_trusted_ca_pem = editExtraTrustedCaPem.trim()
      await api.patch(`/build/environments/${editingEnvId}/variables`, { variables })
      setEditingEnvId(null)
      setTemplateRoles([])
      setProductConfig({})
      setExposePorts({})
      setNfsVolumeNames({})
      setEditTimeoutMinutes('')
      setEditExtraTrustedCaPem('')
      setSuccess('Configuration updated — Rebuild (or Build) the environment to apply it')
      loadEnvironments()
    } catch (e: any) { setError(e.response?.data?.detail || 'Failed to update configuration') }
  }

  const rebuildEnv = async (id: string) => {
    if (!confirm('Rebuild this environment? Existing certs will be revoked and re-issued.')) return
    setLoading(id)
    try {
      const res = await api.post(`/build/environments/${id}/rebuild`)
      setSuccess('Rebuild started')
      loadEnvironments()
      navigate(`/jobs?id=${res.data.job_id}`)
    } catch (e: any) { setError(e.response?.data?.detail || 'Rebuild failed') }
    setLoading(null)
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-700',
      provisioning: 'bg-yellow-100 text-yellow-800',
      active: 'bg-green-100 text-green-800',
      degraded: 'bg-orange-100 text-orange-800',
      failed: 'bg-red-100 text-red-700',
      destroyed: 'bg-red-50 text-red-500',
    }
    return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-gray-100 text-gray-600'}`}>{status}</span>
  }

  const ttlBadge = (expiresAt: string | null) => {
    if (!expiresAt) return null
    const msLeft = new Date(expiresAt).getTime() - Date.now()
    if (msLeft <= 0) return <span className="ml-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">⏱ expiring</span>
    const hoursLeft = msLeft / 3_600_000
    const label = hoursLeft < 1 ? `${Math.round(msLeft / 60_000)}m left` : hoursLeft < 48 ? `${Math.round(hoursLeft)}h left` : `${Math.round(hoursLeft / 24)}d left`
    return <span className="ml-1 px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700" title={`Auto-destroys at ${new Date(expiresAt).toLocaleString()}`}>⏱ {label}</span>
  }

  const renderField = (field: SchemaField, role: string, product: string) => {
    const value = productConfig[role]?.[product]?.[field.key]

    if (field.type === 'list') {
      const items: any[] = value || []
      // Plain lists (e.g. pkg_cache_seed_packages: ["nginx", "python3-pip"])
      // have no item_schema — each entry is a bare string, not an object of
      // sub-fields. Render one text input per entry directly, instead of the
      // object-list case below (which would otherwise render zero inputs
      // per row: nothing to type into, just a remove button).
      if (!field.item_schema || field.item_schema.length === 0) {
        return (
          <div key={field.key} className="mt-2">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-gray-600">{field.label}</label>
              <button type="button"
                onClick={() => updateProductVar(role, product, field.key, [...items, ''])}
                className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100">+ Add</button>
            </div>
            {items.map((item, idx) => (
              <div key={idx} className="flex gap-2 items-center mb-1">
                <input type="text" value={item || ''} placeholder={field.placeholder || field.label}
                  onChange={e => {
                    const next = [...items]
                    next[idx] = e.target.value
                    updateProductVar(role, product, field.key, next)
                  }}
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs" />
                <button type="button"
                  onClick={() => updateProductVar(role, product, field.key, items.filter((_, i) => i !== idx))}
                  className="text-red-400 hover:text-red-600 text-xs px-1">✕</button>
              </div>
            ))}
          </div>
        )
      }
      return (
        <div key={field.key} className="mt-2">
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium text-gray-600">{field.label}</label>
            <button type="button" onClick={() => addListItem(role, product, field.key, field.item_schema || [])}
              className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100">+ Add</button>
          </div>
          {items.map((item, idx) => (
            <div key={idx} className="flex gap-2 items-center mb-1">
              {(field.item_schema || []).map(sf => (
                <input key={sf.key} type={sf.type === 'password' ? 'password' : 'text'}
                  value={item[sf.key] || ''} placeholder={sf.placeholder || sf.label}
                  onChange={e => updateListItem(role, product, field.key, idx, sf.key, e.target.value)}
                  className="flex-1 border border-gray-300 rounded px-2 py-1 text-xs" />
              ))}
              <button type="button" onClick={() => removeListItem(role, product, field.key, idx)}
                className="text-red-400 hover:text-red-600 text-xs px-1">✕</button>
            </div>
          ))}
        </div>
      )
    }

    if (field.type === 'checkbox') {
      const checked = value ?? field.default ?? false
      return (
        <div key={field.key} className="mt-2 flex items-center gap-2">
          <input type="checkbox" checked={!!checked}
            onChange={e => updateProductVar(role, product, field.key, e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600" />
          <label className="text-xs text-gray-700">{field.label}</label>
        </div>
      )
    }

    if (field.type === 'textarea') {
      return (
        <div key={field.key} className="mt-2">
          <label className="text-xs text-gray-500">{field.label}{field.required && <span className="text-red-400"> *</span>}</label>
          <textarea
            value={value ?? field.default ?? ''}
            placeholder={field.placeholder || ''}
            onChange={e => updateProductVar(role, product, field.key, e.target.value)}
            rows={8}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5 font-mono"
          />
        </div>
      )
    }

    if (field.type === 'select') {
      return (
        <div key={field.key} className="mt-1">
          <label className="text-xs text-gray-500">{field.label}{field.required && <span className="text-red-400"> *</span>}</label>
          <select
            value={value ?? field.default ?? ''}
            onChange={e => updateProductVar(role, product, field.key, e.target.value)}
            className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5"
          >
            {(field.options || []).map(opt => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      )
    }

    return (
      <div key={field.key} className="mt-1">
        <label className="text-xs text-gray-500">{field.label}{field.required && <span className="text-red-400"> *</span>}</label>
        <input
          type={field.type === 'password' ? 'password' : field.type === 'number' ? 'number' : 'text'}
          value={value ?? field.default ?? ''}
          placeholder={field.placeholder || ''}
          onChange={e => updateProductVar(role, product, field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
          className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5"
        />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Build Manager — Environments</h1>
          <p className="text-sm text-gray-500 mt-1">Deploy and manage environments from templates</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="px-4 py-2 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700">
          + New Environment
        </button>
      </div>

      {error && <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm text-red-700">{error}<button onClick={() => setError('')} className="ml-2 font-bold">✕</button></div>}
      {success && <div className="bg-green-50 border border-green-200 rounded-md p-3 text-sm text-green-700">{success}<button onClick={() => setSuccess('')} className="ml-2 font-bold">✕</button></div>}

      {templates.some(t => t.current_spec?.aws) && <AwsCredentialBanner />}

      {/* Create Form */}
      {showCreate && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
          <h3 className="font-medium text-gray-900">Create Environment</h3>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">Environment Name</label>
              <input placeholder="e.g. dev-01, staging, qa-sprint-42" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs text-gray-500 block mb-1">Template</label>
              <select value={form.template_id} onChange={e => onTemplateChange(e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
                <option value="">Select Template...</option>
                {templates.map(t => <option key={t.id} value={t.id}>{t.name} (v{t.current_version}){t.current_spec?.aws ? ' ☁️ AWS' : ''}</option>)}
              </select>
            </div>
          </div>

          {/* Signing CA Selection */}
          {signingCas.length > 0 && (
            <div>
              <label className="text-xs text-gray-500 block mb-1">Signing CA</label>
              <select value={form.signing_ca_id} onChange={e => setForm({ ...form, signing_ca_id: e.target.value })}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm">
                <option value="">Select CA...</option>
                {signingCas.map(ca => (
                  <option key={ca.id} value={ca.id}
                    style={ca.recommended ? { fontWeight: 'bold' } : ca.warnings?.length ? { color: '#b45309' } : {}}>
                    {ca.recommended ? '★ ' : ''}{ca.cn} ({ca.key_algo} {ca.key_size}{ca.is_root ? ', Root' : ', Intermediate'})
                    {ca.warnings?.length ? ` ⚠ ${ca.warnings[0]}` : ''}
                    {ca.recommended ? ' — Recommended' : ''}
                  </option>
                ))}
              </select>
              {form.signing_ca_id && (() => {
                const sel = signingCas.find(c => c.id === form.signing_ca_id)
                if (!sel) return null
                if (sel.recommended) return <p className="text-xs text-green-600 mt-1">✓ This CA can sign for any hostname including localhost. Best choice for build environments.</p>
                if (sel.warnings?.length) return <p className="text-xs text-amber-600 mt-1">⚠ {sel.warnings[0]}. Certificates for hostnames outside this scope will be rejected by browsers.</p>
                return null
              })()}
            </div>
          )}

          {/* Optional extra trusted CA — a corporate proxy's own CA (Zscaler,
              Netskope, etc.), not this app's internal CA. Needed whenever
              outbound HTTPS from the target hosts is intercepted/re-signed,
              which otherwise breaks any product installing packages from an
              external (non-OS-mirror) repo. Per-environment since not every
              deployment sits behind the same proxy, or any proxy at all. */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">Extra Trusted CA (PEM) — optional</label>
            <textarea value={form.extra_trusted_ca_pem} onChange={e => setForm({ ...form, extra_trusted_ca_pem: e.target.value })}
              placeholder="Paste a corporate proxy's CA cert here if outbound HTTPS on this network is intercepted (e.g. Zscaler) — needed for products that fetch packages from external repos"
              rows={4}
              className="w-full border border-gray-300 rounded px-3 py-2 text-xs font-mono" />
          </div>

          {/* Optional auto-destroy TTL */}
          <div>
            <label className="text-xs text-gray-500 block mb-1">Auto-destroy after (hours) — optional</label>
            <input type="number" min="0.1" step="0.5" placeholder="e.g. 4 for a throwaway test environment"
              value={form.ttl_hours} onChange={e => setForm({ ...form, ttl_hours: e.target.value })}
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm" />
            <p className="text-xs text-gray-400 mt-1">Leave blank for no expiry. A background check runs every few minutes and destroys the environment once its TTL passes.</p>
          </div>

          {/* JAR Import */}
          <div>
            {!jarImportOpen ? (
              <button type="button" onClick={() => setJarImportOpen(true)}
                className="flex items-center gap-2 px-3 py-1.5 border border-blue-300 bg-blue-50 text-blue-700 rounded-md text-xs hover:bg-blue-100">
                🔬 Import Services from JAR Analysis
              </button>
            ) : (
              <div className="p-3 border border-blue-200 bg-blue-50 rounded-lg space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-blue-800">Import Services from JAR Analysis</p>
                  <button type="button" onClick={() => { setJarImportOpen(false); setJarFeed(null) }}
                    className="text-blue-400 hover:text-blue-600 text-xs">✕ Close</button>
                </div>
                <select value={jarReportId} onChange={e => { setJarReportId(e.target.value); fetchJarFeed(e.target.value) }}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm bg-white">
                  <option value="">Select a JAR report...</option>
                  {(jarReports?.items ?? []).map((r: any) => (
                    <option key={r.report_id} value={r.report_id}>
                      {r.filename}{r.implementation_version ? ` v${r.implementation_version}` : ''}
                    </option>
                  ))}
                </select>
                {jarFeedLoading && <p className="text-xs text-blue-600">Loading...</p>}
                {jarFeed && (
                  <div>
                    <p className="text-xs text-gray-600 mb-2">{jarFeed.services?.length ?? 0} services detected:</p>
                    <div className="border border-gray-200 rounded overflow-hidden mb-3">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="px-3 py-1.5 text-left font-medium text-gray-600">Service</th>
                            <th className="px-3 py-1.5 text-left font-medium text-gray-600">Port</th>
                            <th className="px-3 py-1.5 text-left font-medium text-gray-600">Group</th>
                            <th className="px-3 py-1.5 text-left font-medium text-gray-600">Needs</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {(jarFeed.services ?? []).map((svc: any, i: number) => (
                            <tr key={i}>
                              <td className="px-3 py-1.5 font-mono text-gray-800">{svc.name}</td>
                              <td className="px-3 py-1.5 text-gray-600">{svc.port ?? '—'}</td>
                              <td className="px-3 py-1.5 text-gray-500">{svc.group ?? '—'}</td>
                              <td className="px-3 py-1.5 text-gray-500">
                                {[svc.requires_database && 'DB', svc.requires_rabbitmq && 'MQ', svc.requires_config_server && 'Config'].filter(Boolean).join(', ') || '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <button type="button" onClick={applyJarFeed}
                      className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700">
                      Apply Service Names to Host Map →
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Host Mapping — on-prem/Docker only */}
          {templateRoles.length > 0 && (() => {
            const selTmpl = templates.find(t => t.id === form.template_id)
            const isAws = !!selTmpl?.current_spec?.aws
            if (isAws) {
              const aws = selTmpl!.current_spec.aws
              return (
                <div className="border border-orange-200 bg-orange-50 rounded-lg p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-orange-600 text-lg">☁️</span>
                    <span className="font-medium text-orange-900">AWS Environment</span>
                    <span className="text-xs px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full">OpenTofu + Ansible</span>
                  </div>
                  <div className="grid grid-cols-3 gap-3 text-sm">
                    <div><span className="text-gray-500 text-xs">Region</span><div className="font-mono font-medium">{aws.region || '—'}</div></div>
                    <div><span className="text-gray-500 text-xs">VPC CIDR</span><div className="font-mono font-medium">{aws.vpc_cidr || '10.0.0.0/16'}</div></div>
                    <div><span className="text-gray-500 text-xs">AZ Count</span><div className="font-mono font-medium">{aws.az_count ?? 2}</div></div>
                  </div>
                  <div>
                    <p className="text-xs text-gray-600 font-medium mb-1">EC2 Instances ({templateRoles.length})</p>
                    <div className="border border-orange-200 rounded overflow-hidden">
                      <table className="w-full text-xs">
                        <thead className="bg-orange-100">
                          <tr>
                            <th className="text-left px-3 py-1.5 font-medium text-orange-800">Role</th>
                            <th className="text-left px-3 py-1.5 font-medium text-orange-800">Products</th>
                            <th className="text-left px-3 py-1.5 font-medium text-orange-800">Instance Type</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-orange-100 bg-white">
                          {templateRoles.map(r => {
                            const hostSpec = selTmpl!.current_spec.hosts?.find((h: any) => h.role === r.role)
                            return (
                              <tr key={r.role}>
                                <td className="px-3 py-1.5 font-mono text-gray-900">{r.role}</td>
                                <td className="px-3 py-1.5 text-gray-500">{r.products.map(p => p.product).join(', ')}</td>
                                <td className="px-3 py-1.5 font-mono text-gray-700">{hostSpec?.instance_type || 't3.small'}</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                  {aws.load_balancers?.alb?.enabled && (
                    <div className="text-xs text-gray-600">🔀 External ALB: <span className="font-mono">{aws.load_balancers.alb.domain_name || 'no domain set'}</span></div>
                  )}
                  {aws.load_balancers?.internal_alb?.enabled && (
                    <div className="text-xs text-gray-600">🔀 Internal ALB: <span className="font-mono">backend service-to-service HTTPS (ports 8090–8106)</span></div>
                  )}
                  {(aws.database?.product || aws.database?.engine) && (
                    <div className="text-xs text-gray-600">🗄️ Database: <span className="font-mono">{aws.database.product || aws.database.engine}</span></div>
                  )}
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
                    ⚠️ Infrastructure will be created in AWS. A <strong>tofu plan</strong> runs first — review it before applying.
                  </p>
                </div>
              )
            }
            return (
              <div>
                <label className="text-xs text-gray-500 block mb-2">Host Mapping</label>
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="text-left px-3 py-2 font-medium text-gray-600">Role</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-600">Products</th>
                        <th className="text-left px-3 py-2 font-medium text-gray-600">Hostname / IP</th>
                        {platform.expose_ports_applicable && (
                          <th className="text-left px-3 py-2 font-medium text-gray-600">Expose Ports</th>
                        )}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {templateRoles.map(r => {
                        const ports = getProductPorts(r.role)
                        return (
                          <tr key={r.role}>
                            <td className="px-3 py-2 font-mono text-gray-900">{r.role}</td>
                            <td className="px-3 py-2 text-gray-500 text-xs">{r.products.map(p => p.product).join(', ')}</td>
                            <td className="px-3 py-2">
                              <input value={hostMap[r.role] || ''} onChange={e => setHostMap({ ...hostMap, [r.role]: e.target.value })}
                                placeholder="e.g. target-mysql" className="w-full border border-gray-300 rounded px-2 py-1 text-sm" />
                            </td>
                            {platform.expose_ports_applicable && (
                              <td className="px-3 py-2">
                                <div className="flex items-center gap-2">
                                  <input type="checkbox" checked={!!exposePorts[r.role]}
                                    onChange={e => setExposePorts({ ...exposePorts, [r.role]: e.target.checked })}
                                    className="h-4 w-4 rounded border-gray-300 text-blue-600" />
                                  <span className="text-xs text-gray-500">{ports.length > 0 ? ports.join(', ') : 'no default ports'}</span>
                                </div>
                              </td>
                            )}
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-gray-400 mt-1">Use Docker container names (e.g. target-frontend) or IPs.{platform.expose_ports_applicable && ' Exposed ports are mapped to localhost.'}</p>
              </div>
            )
          })()}

          {/* Product Configuration */}
          {templateRoles.some(r => r.products.some(p => getSchema(p.product, p.version).length > 0)) && (
            <div>
              <label className="text-xs text-gray-500 block mb-2">Product Configuration</label>
              <div className="space-y-3">
                {templateRoles.map(r => {
                  const configurable = r.products.filter(p => getSchema(p.product, p.version).length > 0)
                  if (configurable.length === 0) return null
                  return (
                    <div key={r.role} className="border border-gray-200 rounded-lg p-3">
                      <div className="text-xs font-medium text-gray-700 mb-2 uppercase tracking-wide">{r.role}</div>
                      {configurable.map(p => {
                        const schema = getSchema(p.product, p.version)
                        return (
                          <div key={p.product} className="mb-3 last:mb-0">
                            <div className="text-sm font-medium text-gray-800 border-b border-gray-100 pb-1 mb-1">{p.product} {p.version}</div>
                            {schema.map(field => renderField(field, r.role, p.product))}
                          </div>
                        )
                      })}
                      {r.products.some(p => p.product === 'nfs_server') && (
                        <div className="mt-2 pt-2 border-t border-gray-100">
                          <label className="text-xs text-gray-500">
                            Storage Volume Name <span className="text-gray-400">(a short name, NOT a file path — Docker creates the volume automatically and mounts it at /srv/nfs-export; persists across rebuilds as long as you reuse the same name; leave blank to use non-persistent container storage)</span>
                          </label>
                          <input value={nfsVolumeNames[r.role] || ''}
                            onChange={e => setNfsVolumeNames({ ...nfsVolumeNames, [r.role]: e.target.value })}
                            placeholder="e.g. nfs-shared-storage"
                            className="w-full border border-gray-300 rounded px-2 py-1 text-xs mt-0.5" />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <button onClick={createEnv} disabled={!form.name || !form.template_id}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">Create</button>
            <button onClick={() => { setShowCreate(false); setTemplateRoles([]); setHostMap({}); setProductConfig({}); setNfsVolumeNames({}) }}
              className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
          </div>
        </div>
      )}

      {/* Edit Config modal — host mapping/TTL are still creation-time only;
          Rebuild or Build afterwards to apply anything changed here. */}
      {editingEnvId && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
          <h3 className="font-medium text-gray-900">Edit Configuration</h3>
          <p className="text-xs text-gray-500">Changes are saved immediately but only take effect on the target hosts after you Rebuild (or Build) this environment.</p>

          <div className="border border-gray-200 rounded-lg p-3">
            <label className="text-xs text-gray-500 block mb-1">Ansible Job Timeout</label>
            <select value={editTimeoutMinutes} onChange={e => setEditTimeoutMinutes(e.target.value === '' ? '' : Number(e.target.value))}
              className="w-full border border-gray-300 rounded px-2 py-1 text-sm">
              <option value="">Use template default</option>
              <option value={30}>30 minutes</option>
              <option value={40}>40 minutes</option>
              <option value={50}>50 minutes</option>
              <option value={60}>60 minutes</option>
              <option value={90}>90 minutes</option>
              <option value={120}>120 minutes</option>
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Overrides the template's timeout for just this environment, without affecting other environments built from the same template.
            </p>
          </div>

          <div className="border border-gray-200 rounded-lg p-3">
            <label className="text-xs text-gray-500 block mb-1">Extra Trusted CA (PEM) — optional</label>
            <textarea value={editExtraTrustedCaPem} onChange={e => setEditExtraTrustedCaPem(e.target.value)}
              placeholder="Paste a corporate proxy's CA cert here if outbound HTTPS on this network is intercepted (e.g. Zscaler) — needed for products that fetch packages from external repos"
              rows={4}
              className="w-full border border-gray-300 rounded px-2 py-1 text-xs font-mono" />
            <p className="text-xs text-gray-400 mt-1">
              Trusted by every host in this environment alongside the internal CA — clear the box and save to remove it.
            </p>
          </div>

          {platform.expose_ports_applicable && templateRoles.length > 0 && (() => {
            // Live client-side mirror of the server's own host-port collision
            // check (build_manager.py's _ensure_docker_hosts_ready) — two
            // roles both publishing the same host port always fails one of
            // them (only one container can bind a given port), previously
            // discovered only ~20 minutes into a build via a baffling
            // "Could not resolve hostname" on whichever host lost the race.
            const portOwners: Record<number, string[]> = {}
            for (const r of templateRoles) {
              if (!exposePorts[r.role]) continue
              for (const p of getProductPorts(r.role)) {
                (portOwners[p] ||= []).push(r.role)
              }
            }
            const conflicts = Object.entries(portOwners).filter(([, roles]) => roles.length > 1)
            return (
              <div className="border border-gray-200 rounded-lg p-3">
                <label className="text-xs text-gray-500 block mb-2">Expose Ports</label>
                <div className="space-y-1">
                  {templateRoles.map(r => {
                    const ports = getProductPorts(r.role)
                    return (
                      <div key={r.role} className="flex items-center gap-2">
                        <input type="checkbox" checked={!!exposePorts[r.role]}
                          onChange={e => setExposePorts({ ...exposePorts, [r.role]: e.target.checked })}
                          className="h-4 w-4 rounded border-gray-300 text-blue-600" />
                        <span className="text-xs font-mono text-gray-700 w-28">{r.role}</span>
                        <span className="text-xs text-gray-500">{ports.length > 0 ? ports.join(', ') : 'no default ports'}</span>
                      </div>
                    )
                  })}
                </div>
                {conflicts.length > 0 && (
                  <p className="text-xs text-red-600 mt-2">
                    ⚠ Port conflict: {conflicts.map(([port, roles]) => `${port} (${roles.join(', ')})`).join('; ')} —
                    only one host can publish a given port. Uncheck all but one before saving.
                  </p>
                )}
              </div>
            )
          })()}

          {templateRoles.some(r => r.products.some(p => getSchema(p.product, p.version).length > 0)) && (
            <div>
              <div className="space-y-3">
                {templateRoles.map(r => {
                  const configurable = r.products.filter(p => getSchema(p.product, p.version).length > 0)
                  if (configurable.length === 0) return null
                  return (
                    <div key={r.role} className="border border-gray-200 rounded-lg p-3">
                      <div className="text-xs font-medium text-gray-700 mb-2 uppercase tracking-wide">{r.role}</div>
                      {configurable.map(p => {
                        const schema = getSchema(p.product, p.version)
                        return (
                          <div key={p.product} className="mb-3 last:mb-0">
                            <div className="text-sm font-medium text-gray-800 border-b border-gray-100 pb-1 mb-1">{p.product} {p.version}</div>
                            {schema.map(field => renderField(field, r.role, p.product))}
                          </div>
                        )
                      })}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <button onClick={saveEnvConfig}
              className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Save</button>
            <button onClick={() => { setEditingEnvId(null); setTemplateRoles([]); setProductConfig({}); setExposePorts({}); setNfsVolumeNames({}); setEditTimeoutMinutes(''); setEditExtraTrustedCaPem('') }}
              className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">Cancel</button>
          </div>
        </div>
      )}

      {/* Environment Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Template</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Hosts</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
              <th className="text-left px-4 py-3 font-medium text-gray-600">Created</th>
              <th className="text-right px-4 py-3 font-medium text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {environments.map(env => (
              <tr key={env.id} className={`hover:bg-gray-50 cursor-pointer ${selected?.id === env.id ? 'bg-blue-50' : ''}`} onClick={() => selectEnv(env)}>
                <td className="px-4 py-3 font-medium text-gray-900">{env.name}</td>
                <td className="px-4 py-3 text-gray-600">{env.template_name || '—'} <span className="text-xs text-gray-400">v{env.template_version}</span></td>
                <td className="px-4 py-3 text-xs text-gray-500">{Object.keys(env.ip_allocations).length} hosts</td>
                <td className="px-4 py-3">{statusBadge(env.status)}{ttlBadge(env.expires_at)}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{env.created_at ? new Date(env.created_at).toLocaleDateString() : ''}</td>
                <td className="px-4 py-3 text-right space-x-1" onClick={e => e.stopPropagation()}>
                  {['pending', 'failed'].includes(env.status) && (
                    <>
                      <button onClick={() => buildEnv(env.id)} disabled={loading === env.id}
                        className="text-xs px-2 py-1 bg-green-50 text-green-700 rounded hover:bg-green-100 disabled:opacity-50">▶ Build</button>
                      <button onClick={() => buildEnv(env.id, false, true)} disabled={loading === env.id}
                        title="Preview with --check --diff — no changes applied"
                        className="text-xs px-2 py-1 bg-amber-50 text-amber-700 rounded hover:bg-amber-100 disabled:opacity-50">🔍 Dry Run</button>
                    </>
                  )}
                  {env.status === 'provisioning' && (
                    <button onClick={() => navigate('/jobs')}
                      className="text-xs px-2 py-1 bg-yellow-50 text-yellow-700 rounded hover:bg-yellow-100">📺 Monitor</button>
                  )}
                  {['active', 'degraded', 'failed'].includes(env.status) && (
                    <button onClick={() => rebuildEnv(env.id)} disabled={loading === env.id}
                      className="text-xs px-2 py-1 bg-yellow-50 text-yellow-700 rounded hover:bg-yellow-100 disabled:opacity-50">🔄 Rebuild</button>
                  )}
                  {!['destroyed', 'provisioning'].includes(env.status) && (
                    <button onClick={() => openEditConfig(env)}
                      title="Edit product config (e.g. passwords) — rebuild afterwards to apply"
                      className="text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded hover:bg-blue-100">⚙️ Config</button>
                  )}
                  {!['destroyed'].includes(env.status) && (
                    <button onClick={() => destroyEnv(env.id)} disabled={loading === env.id}
                      className="text-xs px-2 py-1 bg-red-50 text-red-700 rounded hover:bg-red-100 disabled:opacity-50">💥 Destroy</button>
                  )}
                </td>
              </tr>
            ))}
            {environments.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-400">No environments. Create one from a template.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Selected Environment Detail */}
      {selected && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-900">{selected.name}</h2>
              {statusBadge(selected.status)}
              {ttlBadge(selected.expires_at)}
            </div>
            {['active', 'degraded', 'failed'].includes(selected.status) && (
              <button onClick={() => verifyTls(selected.id)} disabled={verifyLoading}
                className="px-3 py-1.5 bg-indigo-50 text-indigo-700 text-sm rounded hover:bg-indigo-100 disabled:opacity-50">
                {verifyLoading ? '⏳ Verifying...' : '🔒 Verify TLS'}
              </button>
            )}
          </div>

          {/* Tab switcher — show AWS tab only for AWS environments; Certs tab always */}
          {(() => {
            const tmpl = templates.find(t => t.id === selected.template_id)
            const isAws = !!tmpl?.current_spec?.aws
            const tabs: { key: 'overview' | 'aws' | 'certs'; label: string }[] = [
              { key: 'overview', label: 'Overview' },
              ...(isAws ? [{ key: 'aws' as const, label: '☁️ AWS Infrastructure' }] : []),
              { key: 'certs', label: `🔐 Certificates${envCerts.length ? ` (${envCerts.length})` : ''}` },
            ]
            return tabs.length > 1 ? (
              <div className="flex gap-1 border-b border-gray-200">
                {tabs.map(tab => (
                  <button key={tab.key} onClick={() => setEnvDetailTab(tab.key)}
                    className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                      envDetailTab === tab.key ? 'border-blue-500 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'
                    }`}>
                    {tab.label}
                  </button>
                ))}
              </div>
            ) : null
          })()}

          {/* AWS Infrastructure tab */}
          {envDetailTab === 'aws' && (() => {
            const tmpl = templates.find(t => t.id === selected.template_id)
            const aws = tmpl?.current_spec?.aws
            if (!aws) return null
            return (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div><span className="text-gray-500">Region:</span> <span className="font-mono">{aws.region}</span></div>
                  <div><span className="text-gray-500">VPC CIDR:</span> <span className="font-mono">{aws.vpc_cidr}</span></div>
                  {awsOutputs?.vpc_id && <div><span className="text-gray-500">VPC ID:</span> <span className="font-mono">{awsOutputs.vpc_id}</span></div>}
                  {awsOutputs?.bastion_public_ip && <div><span className="text-gray-500">Bastion IP:</span> <span className="font-mono">{awsOutputs.bastion_public_ip}</span></div>}
                  {awsOutputs?.alb_dns_name && <div><span className="text-gray-500">ALB DNS:</span> <span className="font-mono text-xs">{awsOutputs.alb_dns_name}</span></div>}
                  {awsOutputs?.route53_alb_fqdn && <div><span className="text-gray-500">ALB Domain:</span> <span className="font-mono">{awsOutputs.route53_alb_fqdn}</span></div>}
                  {awsOutputs?.internal_alb_dns_name && <div><span className="text-gray-500">Internal ALB DNS:</span> <span className="font-mono text-xs">{awsOutputs.internal_alb_dns_name}</span></div>}
                  {awsOutputs?.nlb_dns_name && <div><span className="text-gray-500">NLB DNS:</span> <span className="font-mono text-xs">{awsOutputs.nlb_dns_name}</span></div>}
                  {awsOutputs?.route53_nlb_fqdn && <div><span className="text-gray-500">NLB Domain:</span> <span className="font-mono">{awsOutputs.route53_nlb_fqdn}</span></div>}
                  {awsOutputs?.acm_certificate_arn && <div><span className="text-gray-500">ACM Cert:</span> <span className="font-mono text-xs">{awsOutputs.acm_certificate_arn}</span></div>}
                  {awsOutputs?.db_endpoint && <div><span className="text-gray-500">DB Endpoint:</span> <span className="font-mono text-xs">{awsOutputs.db_endpoint}</span></div>}
                  {awsOutputs?.db_reader_endpoint && <div><span className="text-gray-500">DB Reader:</span> <span className="font-mono text-xs">{awsOutputs.db_reader_endpoint}</span></div>}
                  {awsOutputs?.app_bucket_name && <div><span className="text-gray-500">App Bucket:</span> <span className="font-mono">{awsOutputs.app_bucket_name}</span></div>}
                </div>

                {awsOutputs?.private_ips && Object.keys(awsOutputs.private_ips).length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-gray-700 mb-2">EC2 Instances</h4>
                    <div className="border border-gray-200 rounded overflow-hidden">
                      <table className="w-full text-xs">
                        <thead className="bg-gray-50">
                          <tr>
                            <th className="text-left px-3 py-1.5 font-medium text-gray-600">Host</th>
                            <th className="text-left px-3 py-1.5 font-medium text-gray-600">Instance ID</th>
                            <th className="text-left px-3 py-1.5 font-medium text-gray-600">Private IP</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {Object.entries(awsOutputs.private_ips as Record<string,string>).map(([host, ip]) => (
                            <tr key={host}>
                              <td className="px-3 py-1.5 font-mono">{host}</td>
                              <td className="px-3 py-1.5 font-mono text-gray-500">{awsOutputs?.instance_ids?.[host] || '—'}</td>
                              <td className="px-3 py-1.5 font-mono">{ip}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {awsOutputs?.dashboard_url && (
                  <div className="flex items-center gap-3 pt-1">
                    <a href={awsOutputs.dashboard_url} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-orange-50 text-orange-700 text-sm rounded hover:bg-orange-100">
                      📊 CloudWatch Dashboard ↗
                    </a>
                    {awsOutputs?.sns_topic_arn && (
                      <span className="text-xs text-gray-400 font-mono truncate max-w-xs" title={awsOutputs.sns_topic_arn}>
                        SNS: {awsOutputs.sns_topic_arn.split(':').pop()}
                      </span>
                    )}
                  </div>
                )}

                {selected.status === 'degraded' && (
                  <div className="flex items-center gap-2 px-3 py-2 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
                    <span>⚠️</span>
                    <span>One or more CloudWatch alarms are firing — environment is degraded. Check the dashboard for details.</span>
                  </div>
                )}

                <div className="flex gap-2 pt-2">
                  <button onClick={() => planEnv(selected.id)} disabled={!!awsLoading}
                    className="px-3 py-1.5 bg-blue-50 text-blue-700 text-sm rounded hover:bg-blue-100 disabled:opacity-50">
                    {awsLoading === 'plan' ? '⏳ Planning...' : '📋 Plan'}
                  </button>
                  <button onClick={() => applyEnv(selected.id)} disabled={!!awsLoading}
                    className="px-3 py-1.5 bg-green-50 text-green-700 text-sm rounded hover:bg-green-100 disabled:opacity-50">
                    {awsLoading === 'apply' ? '⏳ Applying...' : '▶ Apply'}
                  </button>
                  <button onClick={() => destroyEnvAws(selected.id)} disabled={!!awsLoading}
                    className="px-3 py-1.5 bg-red-50 text-red-700 text-sm rounded hover:bg-red-100 disabled:opacity-50">
                    {awsLoading === 'destroy' ? '⏳ Destroying...' : '💥 Destroy AWS'}
                  </button>
                </div>
              </div>
            )
          })()}

          {/* Certificates tab */}
          {envDetailTab === 'certs' && (
            <div className="space-y-4">
              {envCerts.length === 0 ? (
                <p className="text-sm text-gray-400">No certificates issued yet. Build the environment to issue certificates automatically.</p>
              ) : (
                <div className="border border-gray-200 rounded overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="text-left px-3 py-1.5 font-medium text-gray-600">Host</th>
                        <th className="text-left px-3 py-1.5 font-medium text-gray-600">Type</th>
                        <th className="text-left px-3 py-1.5 font-medium text-gray-600">Expires</th>
                        <th className="text-left px-3 py-1.5 font-medium text-gray-600">Status</th>
                        <th className="text-left px-3 py-1.5 font-medium text-gray-600">Serial</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {envCerts.map((c: any) => (
                        <tr key={c.id}>
                          <td className="px-3 py-1.5 font-mono text-gray-900">{c.role}</td>
                          <td className="px-3 py-1.5 text-gray-500">{c.cert_type}</td>
                          <td className="px-3 py-1.5 text-gray-500">
                            {c.expires_at ? new Date(c.expires_at).toLocaleDateString() : '—'}
                            {c.days_remaining != null && c.days_remaining <= 30 && c.days_remaining > 0 && (
                              <span className="ml-1 text-amber-600">({c.days_remaining}d)</span>
                            )}
                          </td>
                          <td className="px-3 py-1.5">
                            {c.status === 'valid' && <span className="text-green-600">✓ Valid</span>}
                            {c.status === 'expiring_soon' && <span className="text-amber-600">⚠ Expiring</span>}
                            {c.status === 'expired' && <span className="text-red-600">✗ Expired</span>}
                            {c.status === 'revoked' && <span className="text-gray-400">🚫 Revoked</span>}
                            {c.status === 'unknown' && <span className="text-gray-400">—</span>}
                          </td>
                          <td className="px-3 py-1.5 font-mono text-blue-600 hover:underline cursor-pointer"
                            onClick={() => navigate(`/certificates/${c.cert_serial}`)}>
                            {c.cert_serial.slice(0, 16)}…
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="flex gap-2 flex-wrap">
                <button onClick={() => renewCerts(selected.id)}
                  className="px-3 py-1.5 bg-blue-50 text-blue-700 text-sm rounded hover:bg-blue-100">
                  🔄 Renew All
                </button>
                <button onClick={() => downloadEnvFile(`/build/environments/${selected.id}/certs/trust-bundle`, `${selected.name}-ca-chain.pem`)}
                  className="px-3 py-1.5 bg-gray-50 text-gray-700 text-sm rounded hover:bg-gray-100">
                  ⬇ CA Chain PEM
                </button>
                <button onClick={() => downloadEnvFile(`/build/environments/${selected.id}/certs/truststore.jks`, `${selected.name}-truststore.jks`)}
                  className="px-3 py-1.5 bg-gray-50 text-gray-700 text-sm rounded hover:bg-gray-100">
                  ⬇ Trust Store (JKS)
                </button>
              </div>
            </div>
          )}

          {/* Overview tab (default) */}
          {envDetailTab === 'overview' && (
          <div className="space-y-4">
            <div>
            <h4 className="font-medium text-gray-700 mb-2 text-sm">Host Allocations</h4>
            <div className="border border-gray-200 rounded overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-3 py-1.5 text-xs font-medium text-gray-600">Role</th>
                    <th className="text-left px-3 py-1.5 text-xs font-medium text-gray-600">Host</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {Object.entries(selected.ip_allocations).map(([role, host]) => (
                    <tr key={role}>
                      <td className="px-3 py-1.5 font-mono text-gray-900">{role}</td>
                      <td className="px-3 py-1.5 font-mono text-gray-600">{host}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </div>
          {/* TLS Verification Results */}
          {verifyResults?.available && verifyResults.results && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-medium text-gray-700 text-sm">TLS Verification</h4>
                <span className="text-xs text-gray-400">{verifyResults.ran_at ? new Date(verifyResults.ran_at).toLocaleString() : ''}</span>
              </div>
              {verifyResults.summary && (() => {
                const real = verifyResults.results!.filter(r => r.port !== 0)
                const passed = real.filter(r => r.status === 'ok').length
                const failed = real.filter(r => r.status === 'failed').length
                const warns = real.filter(r => r.status === 'warning').length
                return (
                  <div className="flex gap-3 mb-2 text-xs">
                    <span className="px-2 py-0.5 bg-green-50 text-green-700 rounded">{passed} passed</span>
                    {failed > 0 && <span className="px-2 py-0.5 bg-red-50 text-red-700 rounded">{failed} failed</span>}
                    {warns > 0 && <span className="px-2 py-0.5 bg-yellow-50 text-yellow-700 rounded">{warns} warnings</span>}
                  </div>
                )
              })()}
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="text-left px-3 py-1.5 font-medium text-gray-600">Host</th>
                      <th className="text-left px-3 py-1.5 font-medium text-gray-600">Product</th>
                      <th className="text-left px-3 py-1.5 font-medium text-gray-600">Port</th>
                      <th className="text-left px-3 py-1.5 font-medium text-gray-600">Status</th>
                      <th className="text-left px-3 py-1.5 font-medium text-gray-600">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {verifyResults.results.filter(r => r.port !== 0).map((r, i) => (
                      <tr key={i} className={r.status === 'ok' ? '' : r.status === 'failed' ? 'bg-red-50' : 'bg-yellow-50'}>
                        <td className="px-3 py-1.5 font-mono text-gray-700">{r.host || '—'}</td>
                        <td className="px-3 py-1.5 text-gray-900">{r.product}</td>
                        <td className="px-3 py-1.5 text-gray-600">{r.port || '—'}</td>
                        <td className="px-3 py-1.5">
                          {r.status === 'ok' && <span className="text-green-600 font-medium">✓ OK</span>}
                          {r.status === 'failed' && <span className="text-red-600 font-medium">✗ Failed</span>}
                          {r.status === 'warning' && <span className="text-yellow-600 font-medium">⚠ Warning</span>}
                        </td>
                        <td className="px-3 py-1.5 text-gray-500">
                          {r.error || r.detail || (
                            [r.protocol && r.cipher ? `${r.protocol} / ${r.cipher}` : r.protocol || r.cipher || '', r.session_cipher ? `Session: ${r.session_cipher}` : '', r.subject && !r.session_cipher ? r.subject : ''].filter(Boolean).join(' · ') || '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {selected.certs && selected.certs.length > 0 && (
            <div>
              <h4 className="font-medium text-gray-700 mb-2 text-sm">Certificates</h4>
              <div className="space-y-1">
                {selected.certs.map(c => (
                  <div key={c.id} className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded text-xs">
                    <span><span className="font-medium">{c.role}</span> ({c.cert_type})</span>
                    <span className="font-mono text-blue-600 hover:text-blue-800 cursor-pointer hover:underline" onClick={() => navigate(`/certificates/${c.cert_serial}`)}>{c.cert_serial}</span>
                    {c.revoked_at && <span className="text-red-500">revoked</span>}
                  </div>
                ))}
              </div>
            </div>
          )}
          </div>
          )}
        </div>
      )}

      {preflightModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setPreflightModal(null)}>
          <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="font-medium text-gray-900">Pre-flight Check Failed</h3>
            <p className="text-xs text-gray-500">One or more hosts aren't ready for a build. Review below, then build anyway if you understand the risk.</p>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {preflightModal.report.hosts.map((h, i) => (
                <div key={i} className={`p-2 rounded-md border text-sm ${h.ready ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
                  <div className="font-medium">{h.ready ? '✓' : '✗'} {h.role} {!h.checked && <span className="text-xs text-gray-400">(not checked — Docker/unregistered host)</span>}</div>
                  {h.blockers.length > 0 && (
                    <ul className="list-disc list-inside text-xs text-red-700 mt-1">
                      {h.blockers.map((b, bi) => <li key={bi}>{b}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={() => buildEnv(preflightModal.id, true)} disabled={loading === preflightModal.id}
                className="px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50">
                Build Anyway
              </button>
              <button type="button" onClick={() => setPreflightModal(null)} className="px-3 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
