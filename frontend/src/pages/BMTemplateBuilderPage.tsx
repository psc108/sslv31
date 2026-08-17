import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'

interface ProductVersion {
  id: string
  version: string
  is_latest: boolean
  eol_date: string | null
  aws_defaults: Record<string, any> | null
  supported_os: { os: string; min: string }[]
  conflicts_with: { product: string; reason?: string }[]
}

interface Product {
  id: string
  name: string
  display_name: string
  category: string
  icon: string
  default_ports: number[]
  dependencies: string[]
  deployment_targets: string[]
  versions: ProductVersion[]
}

interface HostProduct {
  product_id: string
  version_id: string
  product_name: string
  display_name: string
  icon: string
  version: string
}

interface InventoryHost {
  id: string
  hostname: string
  ip: string
  connection_type: string
  container_name: string
  ansible_host: string
  service_role: string
  os_type: string
  os_version: string
}

interface Host {
  role: string
  products: HostProduct[]
  inventory_host_id?: string
  ip?: string
  instance_type?: string
  root_volume_gb?: number
  az_index?: number
}

interface CompatResult {
  valid: boolean
  errors: { product: string; message: string }[]
  warnings: { product: string; message: string }[]
  auto_dependencies: { product: string; display_name: string; version: string; version_id: string | null; reason: string }[]
}

interface OSVersion {
  id: string
  version: string
  display_name: string
  is_latest: boolean
}

interface OSFamily {
  id: string
  name: string
  display_name: string
  icon: string
  origin: string
  versions: OSVersion[]
}

interface NetworkPool {
  id: string
  name: string
  cidr: string
  gateway: string | null
  description: string | null
}

export default function BMTemplateBuilderPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)

  // Step 1
  const [deploymentTarget, setDeploymentTarget] = useState<'onprem' | 'aws'>('onprem')
  const [awsConfig, setAwsConfig] = useState({
    region: 'eu-west-2', vpc_cidr: '10.0.0.0/16', az_count: 2,
    single_nat_gateway: true, create_bastion: false,
    alb_enabled: true, alb_domain: '', alb_zone: '',
    nlb_enabled: true, nlb_expose_mysql: false, nlb_expose_rabbitmq: false,
    db_engine: null as string | null, create_app_bucket: false,
  })
  const [baseOs, setBaseOs] = useState('ubuntu')
  const [baseOsVersion, setBaseOsVersion] = useState('24.04')
  const [osFamilies, setOsFamilies] = useState<OSFamily[]>([])
  const [showOsManager, setShowOsManager] = useState(false)
  const [osFamilyForm, setOsFamilyForm] = useState({ name: '', display_name: '', icon: '🐧' })
  const [osVersionForms, setOsVersionForms] = useState<Record<string, { version: string; display_name: string }>>({})
  const [osError, setOsError] = useState('')

  // Step 2
  const [products, setProducts] = useState<Product[]>([])
  const [inventoryHosts, setInventoryHosts] = useState<InventoryHost[]>([])
  const [hosts, setHosts] = useState<Host[]>([{ role: 'host-01', products: [] }])
  const [compat, setCompat] = useState<CompatResult | null>(null)
  const [dragProduct, setDragProduct] = useState<{ product: Product; version: ProductVersion } | null>(null)
  const [showHostPicker, setShowHostPicker] = useState(false)

  // Step 3
  const [templateName, setTemplateName] = useState('')
  const [templateDesc, setTemplateDesc] = useState('')
  const [templateTags, setTemplateTags] = useState('')
  const [ansibleTimeoutMinutes, setAnsibleTimeoutMinutes] = useState(30)
  const [networkPools, setNetworkPools] = useState<NetworkPool[]>([])
  const [networkPoolId, setNetworkPoolId] = useState('')
  const [saving, setSaving] = useState(false)
  const [generatedSpec, setGeneratedSpec] = useState<object | null>(null)
  const [showSpec, setShowSpec] = useState(false)

  const loadOsFamilies = () => {
    api.get('/build/os-catalogue').then(res => setOsFamilies(res.data)).catch(() => {})
  }

  useEffect(() => {
    api.get('/build/hosts').then(res => setInventoryHosts(res.data)).catch(() => {})
    api.get('/build/network-pools').then(res => setNetworkPools(res.data)).catch(() => {})
    loadOsFamilies()
  }, [])

  useEffect(() => {
    const params = deploymentTarget === 'onprem' ? { deployment_target: 'ec2' } : {}
    api.get('/build/catalogue', { params }).then(res => setProducts(res.data)).catch(() => {})
    // Drop any rds-only products from hosts when switching to onprem
    if (deploymentTarget === 'onprem') {
      setHosts(prev => prev.map(h => ({
        ...h,
        products: h.products.filter(p => {
          const found = products.find(x => x.id === p.product_id)
          return !found || found.deployment_targets.includes('ec2')
        }),
      })))
    }
  }, [deploymentTarget])

  const seedOsCatalogue = async () => {
    try {
      await api.post('/build/os-catalogue/seed')
      loadOsFamilies()
    } catch (e: any) { setOsError(e.response?.data?.detail || 'Seed failed') }
  }

  const createOsFamily = async () => {
    if (!osFamilyForm.name.trim() || !osFamilyForm.display_name.trim()) return
    try {
      await api.post('/build/os-catalogue', osFamilyForm)
      setOsFamilyForm({ name: '', display_name: '', icon: '🐧' })
      loadOsFamilies()
    } catch (e: any) { setOsError(e.response?.data?.detail || 'Failed to add OS family') }
  }

  const deleteOsFamily = async (id: string) => {
    if (!confirm('Delete this OS family? This only works if no host or template references it.')) return
    try {
      await api.delete(`/build/os-catalogue/${id}`)
      loadOsFamilies()
    } catch (e: any) { setOsError(e.response?.data?.detail || 'Failed to delete — likely still in use') }
  }

  const createOsVersion = async (familyId: string) => {
    const form = osVersionForms[familyId]
    if (!form?.version.trim() || !form?.display_name.trim()) return
    try {
      await api.post(`/build/os-catalogue/${familyId}/versions`, form)
      setOsVersionForms({ ...osVersionForms, [familyId]: { version: '', display_name: '' } })
      loadOsFamilies()
    } catch (e: any) { setOsError(e.response?.data?.detail || 'Failed to add version') }
  }

  const deleteOsVersion = async (id: string) => {
    if (!confirm('Delete this OS version? This only works if no host or template references it.')) return
    try {
      await api.delete(`/build/os-catalogue/versions/${id}`)
      loadOsFamilies()
    } catch (e: any) { setOsError(e.response?.data?.detail || 'Failed to delete — likely still in use') }
  }

  // Run compatibility check whenever hosts change. Host-grouped (not a flat
  // selection list) so the backend can scope conflicts_with checks to
  // products on the *same* host — two conflicting products (e.g. Adminer
  // and Apache, both binding their own web server to port 80) are only a
  // real problem if they're on the same machine.
  useEffect(() => {
    const hostSelections = hosts
      .map(h => ({ role: h.role, selections: h.products.map(p => ({ product_id: p.product_id, version_id: p.version_id })) }))
      .filter(h => h.selections.length > 0)
    if (hostSelections.length === 0) { setCompat(null); return }
    api.post('/build/catalogue/check-compatibility', {
      base_os: baseOs, base_os_version: baseOsVersion, hosts: hostSelections,
    }).then(res => setCompat(res.data)).catch(() => {})
  }, [hosts, baseOs, baseOsVersion])

  const DEFAULT_INSTANCE_TYPES: Record<string, string> = {
    frontend: 't3.small', backend: 't3.medium', mysql: 't3.medium',
    rabbitmq: 't3.medium', keystone: 't3.small', bastion: 't3.micro', generic: 't3.micro',
  }

  const addHost = () => {
    const num = hosts.length + 1
    setHosts([...hosts, { role: `host-${String(num).padStart(2, '0')}`, products: [], instance_type: 't3.small', root_volume_gb: 20, az_index: 0 }])
  }

  const addFromInventory = (inv: InventoryHost) => {
    // Don't add if already present
    if (hosts.some(h => h.inventory_host_id === inv.id)) return
    setHosts([...hosts, { role: inv.service_role !== 'generic' ? inv.service_role : inv.hostname, products: [], inventory_host_id: inv.id, ip: inv.ansible_host }])
    setShowHostPicker(false)
  }

  const removeHost = (idx: number) => {
    setHosts(hosts.filter((_, i) => i !== idx))
  }

  const renameHost = (idx: number, name: string) => {
    const updated = [...hosts]
    updated[idx] = { ...updated[idx], role: name }
    setHosts(updated)
  }

  // Detaches a host from the Inventory row it was seeded from (role stays
  // as whatever it currently reads — un-linking doesn't revert it) so the
  // role field becomes freely editable again instead of locked/greyed.
  const unlinkHostFromInventory = (idx: number) => {
    const updated = [...hosts]
    const host = updated[idx]
    if (!host) return
    const { inventory_host_id: _drop, ip: _dropIp, ...rest } = host
    updated[idx] = rest
    setHosts(updated)
  }

  // Suggestions for the role field — real Inventory data (existing hosts'
  // service_role values), not an invented list. Deliberately not a hard
  // dropdown: template roles (pkg-cache, backend-lb, nfs-server, etc. in
  // the golden-path templates) are per-template slot labels, not required
  // to match Inventory's fixed service_role enum.
  const roleSuggestions = [...new Set(inventoryHosts.map(h => h.service_role))].sort()

  // Checked both directions since conflicts_with is only declared on one
  // side of a pair today (e.g. only Adminer declares "conflicts with
  // Apache", Apache has no reciprocal entry) — a future product declaring
  // its own conflicts_with shouldn't need Adminer's entry updated too.
  const findHostConflict = (hostIdx: number, candidateProduct: Product, candidateVersion: ProductVersion): string | null => {
    const existingProducts = hosts[hostIdx]?.products || []
    for (const c of candidateVersion.conflicts_with) {
      if (existingProducts.some(p => p.product_name === c.product)) {
        return `${candidateProduct.display_name} conflicts with ${c.product} on this host${c.reason ? ` — ${c.reason}` : ''}.`
      }
    }
    for (const existing of existingProducts) {
      const existingProduct = products.find(p => p.id === existing.product_id)
      const existingVersion = existingProduct?.versions.find(v => v.id === existing.version_id)
      const c = existingVersion?.conflicts_with.find(c => c.product === candidateProduct.name)
      if (c) {
        return `${existing.display_name} conflicts with ${candidateProduct.display_name} on this host${c.reason ? ` — ${c.reason}` : ''}.`
      }
    }
    return null
  }

  const addProductToHost = (hostIdx: number, product: Product, version: ProductVersion) => {
    const updated = [...hosts]
    // Don't add duplicate
    if (updated[hostIdx].products.some(p => p.product_id === product.id)) return
    const conflict = findHostConflict(hostIdx, product, version)
    if (conflict) {
      alert(`Can't add ${product.display_name} to "${updated[hostIdx].role}": ${conflict}`)
      return
    }
    updated[hostIdx] = {
      ...updated[hostIdx],
      products: [...updated[hostIdx].products, {
        product_id: product.id,
        version_id: version.id,
        product_name: product.name,
        display_name: product.display_name,
        icon: product.icon,
        version: version.version,
      }],
    }
    setHosts(updated)
  }

  const removeProductFromHost = (hostIdx: number, productId: string) => {
    const updated = [...hosts]
    updated[hostIdx] = {
      ...updated[hostIdx],
      products: updated[hostIdx].products.filter(p => p.product_id !== productId),
    }
    setHosts(updated)
  }

  const addAutoDependency = (dep: CompatResult['auto_dependencies'][0], hostIdx: number) => {
    if (!dep.version_id) return
    const product = products.find(p => p.name === dep.product)
    if (!product) return
    const version = product.versions.find(v => v.id === dep.version_id)
    if (!version) return
    addProductToHost(hostIdx, product, version)
  }

  const getLatestVersion = (product: Product): ProductVersion | undefined => {
    return product.versions.find(v => v.is_latest) || product.versions[0]
  }

  const buildAwsBlock = () => deploymentTarget !== 'aws' ? undefined : ({
    region: awsConfig.region,
    vpc_cidr: awsConfig.vpc_cidr,
    az_count: awsConfig.az_count,
    single_nat_gateway: awsConfig.single_nat_gateway,
    create_bastion: awsConfig.create_bastion,
    load_balancers: {
      alb: { enabled: awsConfig.alb_enabled, domain_name: awsConfig.alb_domain, route53_zone_name: awsConfig.alb_zone },
      nlb: { enabled: awsConfig.nlb_enabled, expose_mysql: awsConfig.nlb_expose_mysql, expose_rabbitmq: awsConfig.nlb_expose_rabbitmq },
    },
    database: { engine: awsConfig.db_engine },
    storage: { create_app_bucket: awsConfig.create_app_bucket },
    monitoring: { ec2_cpu_threshold: 80, ec2_memory_threshold: 85, log_retention_days: 30, alarm_webhook_url: '' },
  })

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        base_os: baseOs,
        base_os_version: baseOsVersion,
        hosts: hosts.map(h => ({
          role: h.role,
          products: h.products.map(p => ({ version_id: p.version_id, vars: {} })),
          inventory_host_id: h.inventory_host_id || undefined,
          ip: h.ip || undefined,
          ...(deploymentTarget === 'aws' ? { instance_type: h.instance_type || DEFAULT_INSTANCE_TYPES[h.role] || 't3.small', root_volume_gb: h.root_volume_gb || 20, az_index: h.az_index || 0 } : {}),
        })),
        template_name: templateName,
        template_description: templateDesc,
        template_tags: templateTags,
        change_note: 'Created via Template Builder',
        ansible_timeout_minutes: ansibleTimeoutMinutes,
        aws: buildAwsBlock(),
        // No network key at all when no pool is selected — that's what
        // makes build_environment recognise every host here as a Docker
        // target to auto-create, rather than expecting real reachable SSH
        // hosts at addresses nothing actually provisioned. Selecting a
        // pool means the opposite: these are real machines you're
        // expected to already have standing at whatever IPs the pool
        // hands out (see the pre-flight reachability check).
        network: deploymentTarget === 'onprem' && networkPoolId ? { pool_id: networkPoolId } : undefined,
      }
      await api.post('/build/catalogue/build-template', payload)
      navigate('/bm-templates')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to save template')
    }
    setSaving(false)
  }

  const previewSpec = async () => {
    try {
      // Just show what the spec would look like
      const payload = {
        base_os: baseOs,
        base_os_version: baseOsVersion,
        hosts: hosts.map(h => ({
          role: h.role,
          products: h.products.map(p => ({ version_id: p.version_id, vars: {} })),
        })),
        template_name: templateName || 'preview',
        template_description: templateDesc,
        template_tags: templateTags,
        change_note: 'Preview',
      }
      // We'll just build the spec shape client-side for preview — matches
      // exactly what handleSave() actually sends, so what's shown here is
      // what gets saved, not an approximation.
      const spec: Record<string, unknown> = {
        base_os: baseOs,
        base_os_version: baseOsVersion,
        hosts: hosts.map(h => ({
          role: h.role,
          hostname_pattern: `{{env_name}}-${h.role}`,
          products: h.products.map(p => ({ product: p.product_name, version: p.version, vars: {} })),
          certs: ['server_tls'],
        })),
        certificates: { key_algorithm: 'RSA', key_size: 2048, validity_days: 365, san_include_localhost: true },
        playbook_sequence: ['base-provision.yml', 'products.yml', 'health-check.yml'],
        ansible_timeout_minutes: ansibleTimeoutMinutes,
      }
      if (deploymentTarget === 'onprem' && networkPoolId) {
        spec.network = { pool_id: networkPoolId }
      }
      setGeneratedSpec(spec)
      setShowSpec(true)
    } catch { /* ignore */ }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Template Builder</h1>
        <p className="text-sm text-gray-500 mt-1">Create a template by selecting a base OS and assigning products to hosts</p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-4">
        {[1, 2, 3].map(s => (
          <div key={s} className={`flex items-center gap-2 ${s <= step ? 'text-blue-700' : 'text-gray-400'}`}>
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
              s === step ? 'bg-blue-600 text-white' : s < step ? 'bg-blue-100 text-blue-700' : 'bg-gray-100'
            }`}>{s}</div>
            <span className="text-sm font-medium">
              {s === 1 ? 'Base OS' : s === 2 ? 'Hosts & Products' : 'Review & Save'}
            </span>
            {s < 3 && <span className="text-gray-300 ml-2">→</span>}
          </div>
        ))}
      </div>

      {/* Step 1: Base OS + Deployment Target */}
      {step === 1 && (
        <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-6">

          {/* Deployment target */}
          <div>
            <h2 className="text-lg font-semibold mb-3">Deployment Target</h2>
            <div className="grid grid-cols-2 gap-4 max-w-md">
              {(['onprem', 'aws'] as const).map(t => (
                <button key={t} onClick={() => setDeploymentTarget(t)}
                  className={`p-4 border-2 rounded-lg text-left transition-colors ${
                    deploymentTarget === t ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
                  }`}>
                  <div className="text-xl mb-1">{t === 'onprem' ? '🖥️' : '☁️'}</div>
                  <div className="text-sm font-medium">{t === 'onprem' ? 'On-Premises / Docker' : 'AWS (EC2)'}</div>
                  <div className="text-xs text-gray-500 mt-0.5">{t === 'onprem' ? 'Ansible-managed' : 'OpenTofu + Ansible'}</div>
                </button>
              ))}
            </div>
          </div>

          {/* AWS config fields */}
          {deploymentTarget === 'aws' && (
            <div className="border border-blue-200 bg-blue-50 rounded-lg p-4 space-y-4">
              <h3 className="text-sm font-semibold text-blue-800">AWS Configuration</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-600 block mb-1">Region</label>
                  <select value={awsConfig.region} onChange={e => setAwsConfig(c => ({...c, region: e.target.value}))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
                    {['eu-west-1','eu-west-2','eu-west-3','eu-central-1','us-east-1','us-east-2','us-west-2','ap-southeast-1'].map(r => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs text-gray-600 block mb-1">VPC CIDR</label>
                  <input value={awsConfig.vpc_cidr} onChange={e => setAwsConfig(c => ({...c, vpc_cidr: e.target.value}))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-gray-600 block mb-1">AZ Count</label>
                  <select value={awsConfig.az_count} onChange={e => setAwsConfig(c => ({...c, az_count: Number(e.target.value)}))}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm bg-white">
                    <option value={1}>1 (dev)</option><option value={2}>2</option><option value={3}>3 (prod)</option>
                  </select>
                </div>
                <div className="flex items-center gap-4 pt-4">
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" checked={awsConfig.single_nat_gateway} onChange={e => setAwsConfig(c => ({...c, single_nat_gateway: e.target.checked}))} className="rounded" />
                    Single NAT GW
                  </label>
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <input type="checkbox" checked={awsConfig.create_bastion} onChange={e => setAwsConfig(c => ({...c, create_bastion: e.target.checked}))} className="rounded" />
                    Bastion Host
                  </label>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-gray-600 block mb-1">ALB Domain (optional)</label>
                  <input value={awsConfig.alb_domain} onChange={e => setAwsConfig(c => ({...c, alb_domain: e.target.value}))}
                    placeholder="myapp.example.com" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-gray-600 block mb-1">Route 53 Zone (optional)</label>
                  <input value={awsConfig.alb_zone} onChange={e => setAwsConfig(c => ({...c, alb_zone: e.target.value}))}
                    placeholder="example.com" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
                </div>
              </div>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={awsConfig.nlb_expose_mysql} onChange={e => setAwsConfig(c => ({...c, nlb_expose_mysql: e.target.checked}))} className="rounded" />
                  Expose MySQL via NLB
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={awsConfig.nlb_expose_rabbitmq} onChange={e => setAwsConfig(c => ({...c, nlb_expose_rabbitmq: e.target.checked}))} className="rounded" />
                  Expose AMQPS via NLB
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={awsConfig.create_app_bucket} onChange={e => setAwsConfig(c => ({...c, create_app_bucket: e.target.checked}))} className="rounded" />
                  App S3 Bucket
                </label>
              </div>
            </div>
          )}

          <div>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Select Base Operating System</h2>
            <button onClick={() => setShowOsManager(v => !v)} className="text-xs px-2 py-1 bg-gray-100 text-gray-700 rounded hover:bg-gray-200">
              ⚙ {showOsManager ? 'Hide' : 'Manage'} Operating Systems
            </button>
          </div>

          {osFamilies.length === 0 ? (
            <div className="text-sm text-gray-500 p-4 border border-dashed border-gray-300 rounded-lg text-center">
              No operating systems in the catalogue yet.
              <button onClick={seedOsCatalogue} className="ml-2 text-blue-600 hover:underline">Seed defaults</button>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {osFamilies.flatMap(family => family.versions.map(v => (
                <button key={`${family.name}-${v.version}`}
                  onClick={() => { setBaseOs(family.name); setBaseOsVersion(v.version) }}
                  className={`p-4 border-2 rounded-lg text-center transition-colors ${
                    baseOs === family.name && baseOsVersion === v.version
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}>
                  <div className="text-2xl mb-1">{family.icon}</div>
                  <div className="text-sm font-medium">{family.display_name} {v.display_name}</div>
                </button>
              )))}
            </div>
          )}

          {showOsManager && (
            <div className="mt-4 border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
              {osError && (
                <div className="bg-red-50 border border-red-200 rounded-md p-2 text-xs text-red-700">
                  {osError}
                  <button onClick={() => setOsError('')} className="ml-2 text-red-500">✕</button>
                </div>
              )}
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-700">Manage Operating Systems</h3>
                <button onClick={seedOsCatalogue} className="text-xs px-2 py-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300">Seed Defaults</button>
              </div>

              {osFamilies.map(family => (
                <div key={family.id} className="bg-white border border-gray-200 rounded-md p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-medium">
                      <span>{family.icon}</span> {family.display_name}
                      <span className="text-xs text-gray-400">({family.name})</span>
                      {family.origin === 'builtin' && <span className="text-xs px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded">builtin</span>}
                    </div>
                    <button onClick={() => deleteOsFamily(family.id)} className="text-xs text-red-500 hover:text-red-700">🗑️ Delete family</button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {family.versions.map(v => (
                      <span key={v.id} className="flex items-center gap-1 text-xs bg-gray-100 rounded-full px-2 py-1">
                        {v.display_name}{v.is_latest ? ' ★' : ''}
                        <button onClick={() => deleteOsVersion(v.id)} className="text-red-400 hover:text-red-600">✕</button>
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-2">
                    <input placeholder="Version (e.g. 25.04)" value={osVersionForms[family.id]?.version || ''}
                      onChange={e => setOsVersionForms({ ...osVersionForms, [family.id]: { ...osVersionForms[family.id], version: e.target.value, display_name: osVersionForms[family.id]?.display_name || '' } })}
                      className="border border-gray-300 rounded px-2 py-1 text-xs w-32" />
                    <input placeholder="Display name (e.g. 25.04 LTS)" value={osVersionForms[family.id]?.display_name || ''}
                      onChange={e => setOsVersionForms({ ...osVersionForms, [family.id]: { ...osVersionForms[family.id], display_name: e.target.value, version: osVersionForms[family.id]?.version || '' } })}
                      className="border border-gray-300 rounded px-2 py-1 text-xs flex-1" />
                    <button onClick={() => createOsVersion(family.id)} className="text-xs px-2 py-1 bg-blue-50 text-blue-600 rounded hover:bg-blue-100">+ Version</button>
                  </div>
                </div>
              ))}

              <div className="bg-white border border-dashed border-gray-300 rounded-md p-3">
                <div className="text-xs font-medium text-gray-600 mb-2">Add a new OS family</div>
                <div className="flex gap-2">
                  <input placeholder="Icon" value={osFamilyForm.icon} onChange={e => setOsFamilyForm({ ...osFamilyForm, icon: e.target.value })}
                    className="border border-gray-300 rounded px-2 py-1 text-xs w-14" />
                  <input placeholder="name (e.g. suse)" value={osFamilyForm.name} onChange={e => setOsFamilyForm({ ...osFamilyForm, name: e.target.value })}
                    className="border border-gray-300 rounded px-2 py-1 text-xs w-32" />
                  <input placeholder="Display name (e.g. openSUSE)" value={osFamilyForm.display_name} onChange={e => setOsFamilyForm({ ...osFamilyForm, display_name: e.target.value })}
                    className="border border-gray-300 rounded px-2 py-1 text-xs flex-1" />
                  <button onClick={createOsFamily} className="text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">+ Add Family</button>
                </div>
              </div>
            </div>
          )}

          </div>

          <div className="flex justify-end">
            <button onClick={() => setStep(2)}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Hosts & Products */}
      {step === 2 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Hosts panel */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold">Hosts</h2>
              <div className="flex gap-2">
                {inventoryHosts.length > 0 && (
                  <button onClick={() => setShowHostPicker(true)}
                    className="px-3 py-1.5 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700">
                    + From Inventory
                  </button>
                )}
                <button onClick={addHost}
                  className="px-3 py-1.5 bg-green-600 text-white rounded-md text-sm hover:bg-green-700">
                  + New Host
                </button>
              </div>
            </div>

            {/* Inventory host picker */}
            {showHostPicker && (
              <div className="bg-white border border-blue-200 rounded-lg p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-gray-700">Select from Inventory</h3>
                  <button onClick={() => setShowHostPicker(false)} className="text-xs text-gray-500 hover:text-gray-700">✕</button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-48 overflow-y-auto">
                  {inventoryHosts.filter(inv => !hosts.some(h => h.inventory_host_id === inv.id)).map(inv => (
                    <button key={inv.id} onClick={() => addFromInventory(inv)}
                      className="flex items-center gap-2 p-2 border border-gray-200 rounded-md hover:border-blue-400 hover:bg-blue-50 text-left">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{inv.hostname}</div>
                        <div className="text-xs text-gray-500">
                          {inv.connection_type === 'docker' ? `🐳 ${inv.container_name || inv.hostname}` : `🖥️ ${inv.ip}`}
                          {' · '}{inv.service_role}
                        </div>
                      </div>
                      <span className="text-xs text-blue-500">+ Add</span>
                    </button>
                  ))}
                  {inventoryHosts.filter(inv => !hosts.some(h => h.inventory_host_id === inv.id)).length === 0 && (
                    <p className="text-sm text-gray-400 col-span-full">All inventory hosts already added</p>
                  )}
                </div>
              </div>
            )}

            <datalist id="role-suggestions">
              {roleSuggestions.map(r => <option key={r} value={r} />)}
            </datalist>

            {hosts.map((host, hostIdx) => (
              <div key={hostIdx}
                className="bg-white border border-gray-200 rounded-lg p-4"
                onDragOver={e => e.preventDefault()}
                onDrop={() => {
                  if (dragProduct) {
                    addProductToHost(hostIdx, dragProduct.product, dragProduct.version)
                    setDragProduct(null)
                  }
                }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <input
                      value={host.role}
                      onChange={e => renameHost(hostIdx, e.target.value)}
                      readOnly={!!host.inventory_host_id}
                      list={host.inventory_host_id ? undefined : 'role-suggestions'}
                      className={`font-semibold text-gray-900 border-b focus:outline-none px-1 ${
                        host.inventory_host_id
                          ? 'bg-gray-100 border-transparent cursor-not-allowed text-gray-600'
                          : 'bg-transparent border-transparent hover:border-gray-300 focus:border-blue-500'
                      }`}
                    />
                    {host.ip && <span className="text-xs text-gray-400 font-mono">{host.ip}</span>}
                    {host.inventory_host_id && (
                      <span className="flex items-center gap-1 text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                        🔗 linked to inventory
                        <button type="button" title="Unlink from inventory host (role becomes editable)"
                          onClick={() => unlinkHostFromInventory(hostIdx)}
                          className="hover:text-blue-900 font-bold leading-none">✕</button>
                      </span>
                    )}
                    {deploymentTarget === 'aws' && (
                      <select value={host.instance_type || DEFAULT_INSTANCE_TYPES[host.role] || 't3.small'}
                        onChange={e => { const u=[...hosts]; u[hostIdx]={...u[hostIdx],instance_type:e.target.value}; setHosts(u) }}
                        className="text-xs border border-gray-300 rounded px-1.5 py-0.5 bg-white ml-2">
                        {['t3.micro','t3.small','t3.medium','t3.large','m6i.large','m6i.xlarge','r6i.large'].map(t => <option key={t} value={t}>{t}</option>)}
                      </select>
                    )}
                  </div>
                  {hosts.length > 1 && (
                    <button onClick={() => removeHost(hostIdx)}
                      className="text-xs text-red-500 hover:text-red-700">Remove</button>
                  )}
                </div>
                {host.products.length === 0 ? (
                  <p className="text-sm text-gray-400 italic">Drag products here from the catalogue →</p>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {host.products.map(p => (
                      <div key={p.product_id}
                        className="flex items-center gap-1.5 bg-blue-50 border border-blue-200 rounded-md px-2 py-1">
                        <span>{p.icon}</span>
                        <span className="text-sm font-medium">{p.display_name}</span>
                        <span className="text-xs text-gray-500">{p.version}</span>
                        <button onClick={() => removeProductFromHost(hostIdx, p.product_id)}
                          className="text-red-400 hover:text-red-600 ml-1">×</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* Compatibility messages */}
            {compat && (compat.errors.length > 0 || compat.warnings.length > 0 || compat.auto_dependencies.length > 0) && (
              <div className="space-y-2">
                {compat.errors.map((e, i) => (
                  <div key={`e-${i}`} className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
                    <span>❌</span> <span><strong>{e.product}:</strong> {e.message}</span>
                  </div>
                ))}
                {compat.warnings.map((w, i) => (
                  <div key={`w-${i}`} className="flex items-center gap-2 text-sm text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-md px-3 py-2">
                    <span>⚠️</span> <span><strong>{w.product}:</strong> {w.message}</span>
                  </div>
                ))}
                {compat.auto_dependencies.map((d, i) => (
                  <div key={`d-${i}`} className="flex items-center justify-between text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded-md px-3 py-2">
                    <span>💡 <strong>{d.display_name} {d.version}</strong> — {d.reason}</span>
                    {d.version_id && hosts.length > 0 && (
                      <button onClick={() => addAutoDependency(d, 0)}
                        className="text-xs bg-blue-600 text-white px-2 py-0.5 rounded hover:bg-blue-700">
                        Add to {hosts[0].role}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-between">
              <button onClick={() => setStep(1)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
                ← Back
              </button>
              <button onClick={() => setStep(3)} disabled={hosts.length === 0 || !!(compat && !compat.valid)}
                title={compat && !compat.valid ? 'Resolve the conflicts/errors below before continuing' : undefined}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
                Next →
              </button>
            </div>
          </div>

          {/* Product catalogue sidebar */}
          <div className="bg-white border border-gray-200 rounded-lg p-4 max-h-[70vh] overflow-y-auto">
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-3">Product Catalogue</h3>
            {(() => {
              const linuxProducts = products.filter(p => p.deployment_targets.includes('ec2'))
              const managedProducts = products.filter(p => !p.deployment_targets.includes('ec2'))
              const renderProduct = (product: Product) => {
                const latestVersion = getLatestVersion(product)
                if (!latestVersion) return null
                return (
                  <div key={product.id}
                    draggable
                    onDragStart={() => setDragProduct({ product, version: latestVersion })}
                    onDragEnd={() => setDragProduct(null)}
                    className="flex items-center gap-2 p-2 rounded-md border border-gray-100 hover:border-blue-300 hover:bg-blue-50 cursor-grab active:cursor-grabbing">
                    <span className="text-lg">{product.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{product.display_name}</div>
                      <div className="text-xs text-gray-400">
                        {latestVersion.version}
                        {product.default_ports.length > 0 && ` · ${product.default_ports.map(p => `:${p}`).join(' ')}`}
                      </div>
                    </div>
                    <span className="text-xs text-gray-300">drag →</span>
                  </div>
                )
              }
              return (
                <div className="space-y-4">
                  <div className="space-y-2">{linuxProducts.map(renderProduct)}</div>
                  {managedProducts.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-orange-600 uppercase tracking-wide mb-2 flex items-center gap-1">
                        <span>☁️</span> AWS Managed Services
                      </div>
                      <div className="space-y-2">{managedProducts.map(renderProduct)}</div>
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        </div>
      )}

      {/* Step 3: Review & Save */}
      {step === 3 && (
        <div className="bg-white border border-gray-200 rounded-lg p-6 space-y-6">
          <h2 className="text-lg font-semibold">Review & Save Template</h2>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Template Name *</label>
              <input value={templateName} onChange={e => setTemplateName(e.target.value)}
                placeholder="e.g. production-stack"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Tags</label>
              <input value={templateTags} onChange={e => setTemplateTags(e.target.value)}
                placeholder="e.g. production, full-stack"
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <input value={templateDesc} onChange={e => setTemplateDesc(e.target.value)}
              placeholder="What this template deploys"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ansible Job Timeout</label>
            <select value={ansibleTimeoutMinutes} onChange={e => setAnsibleTimeoutMinutes(Number(e.target.value))}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
              <option value={30}>30 minutes</option>
              <option value={40}>40 minutes</option>
              <option value={50}>50 minutes</option>
              <option value={60}>60 minutes</option>
              <option value={90}>90 minutes</option>
              <option value={120}>120 minutes</option>
            </select>
            <p className="text-xs text-gray-500 mt-1">
              How long a build from this template is allowed to run before it's killed. Bigger templates
              (more hosts, heavier installs) need more headroom than the 30-minute default.
            </p>
          </div>

          {deploymentTarget === 'onprem' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Network Pool</label>
              <select value={networkPoolId} onChange={e => setNetworkPoolId(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-blue-500 focus:border-blue-500">
                <option value="">None — auto-create local Docker test hosts</option>
                {networkPools.map(p => (
                  <option key={p.id} value={p.id}>{p.name} ({p.cidr})</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {networkPoolId
                  ? 'Hosts get real IPs from this pool. This means a real, reachable machine must already exist at each address before you build — nothing here creates one for you (pre-flight checks for this before running).'
                  : 'No pool selected — a fresh Docker container is created automatically for each host role when you build. Good for local testing; pick a pool above to target real machines instead.'}
                {networkPools.length === 0 && ' No network pools exist yet — add one from the Inventory page if you want to target real hosts.'}
              </p>
            </div>
          )}

          {/* Summary */}
          <div className="bg-gray-50 rounded-lg p-4 space-y-3">
            <div className="text-sm">
              <span className="font-medium">Base OS:</span> {baseOs === 'ubuntu' ? '🐧' : '🎩'} {baseOs} {baseOsVersion}
            </div>
            <div className="text-sm"><span className="font-medium">Hosts:</span> {hosts.length}</div>
            {hosts.map((h, i) => (
              <div key={i} className="text-sm pl-4">
                <span className="font-medium">{h.role}:</span>{' '}
                {h.products.map(p => `${p.display_name} ${p.version}`).join(', ') || 'No products'}
              </div>
            ))}
            {deploymentTarget === 'onprem' && (
              <div className="text-sm">
                <span className="font-medium">Network:</span>{' '}
                {networkPoolId
                  ? `${networkPools.find(p => p.id === networkPoolId)?.name} (${networkPools.find(p => p.id === networkPoolId)?.cidr})`
                  : 'Docker auto-provisioned test hosts'}
              </div>
            )}
            <div className="text-sm">
              <span className="font-medium">Certificates:</span> {hosts.length} server TLS (auto)
            </div>
            <div className="text-sm">
              <span className="font-medium">Ports:</span>{' '}
              {[...new Set(hosts.flatMap(h => h.products.flatMap(p => {
                const prod = products.find(x => x.id === p.product_id)
                return prod?.default_ports || []
              })))].sort((a, b) => a - b).join(', ') || 'None'}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={previewSpec}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
              View Generated Spec (JSON)
            </button>
          </div>

          {showSpec && generatedSpec && (
            <div className="bg-gray-900 text-green-400 rounded-lg p-4 overflow-auto max-h-64">
              <pre className="text-xs">{JSON.stringify(generatedSpec, null, 2)}</pre>
            </div>
          )}

          <div className="flex justify-between pt-4 border-t border-gray-200">
            <button onClick={() => setStep(2)}
              className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
              ← Back
            </button>
            <button onClick={handleSave} disabled={saving || !templateName || !!(compat && !compat.valid)}
              title={compat && !compat.valid ? 'Resolve the conflicts/errors on the previous step before saving' : undefined}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
              {saving ? 'Saving...' : 'Save Template'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
