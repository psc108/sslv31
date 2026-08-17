import { useState, useEffect } from 'react'
import api from '@/lib/api'

interface ProductVersion {
  id: string
  product_id: string
  version: string
  ansible_role: string
  default_vars: Record<string, any>
  supported_os: { os: string; min: string; max?: string }[]
  conflicts_with: { product: string; reason: string }[]
  requires: { product: string; min_version?: string; reason: string }[]
  eol_date: string | null
  is_latest: boolean
  aws_defaults: Record<string, any> | null
}

interface Product {
  id: string
  name: string
  display_name: string
  category: string
  description: string
  icon: string
  default_ports: number[]
  cert_requirements: Record<string, boolean>
  dependencies: string[]
  deployment_targets: string[]
  is_builtin: boolean
  version_count: number
  versions: ProductVersion[]
}

const DEPLOYMENT_TARGET_LABELS: Record<string, { label: string; colour: string }> = {
  ec2: { label: 'EC2', colour: 'bg-blue-100 text-blue-700' },
  rds: { label: 'RDS', colour: 'bg-orange-100 text-orange-700' },
  s3:  { label: 'S3',  colour: 'bg-green-100 text-green-700' },
}

const CATEGORIES = [
  { value: '', label: 'All' },
  { value: 'web_server', label: 'Web Servers' },
  { value: 'database', label: 'Databases' },
  { value: 'messaging', label: 'Messaging' },
  { value: 'identity', label: 'Identity' },
  { value: 'storage', label: 'Storage' },
  { value: 'runtime', label: 'Runtimes' },
  { value: 'library', label: 'Libraries' },
  { value: 'networking', label: 'Networking & Security' },
  { value: 'monitoring', label: 'Monitoring' },
  { value: 'devtools', label: 'Dev Tools' },
  { value: 'utility', label: 'Utilities' },
]

const CATEGORY_OPTIONS = CATEGORIES.slice(1)

export default function BMCataloguePage() {
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [seeding, setSeeding] = useState(false)

  // Product modal
  const [showProductModal, setShowProductModal] = useState(false)
  const [editingProduct, setEditingProduct] = useState<Product | null>(null)
  const [productForm, setProductForm] = useState({ name: '', display_name: '', category: 'utility', description: '', icon: '📦', default_ports: '', cert_server_tls: true, cert_client_mtls: false, dependencies: '', deployment_target_ec2: true, deployment_target_rds: false })

  // Version modal
  const [showVersionModal, setShowVersionModal] = useState(false)
  const [editingVersion, setEditingVersion] = useState<ProductVersion | null>(null)
  const [versionProductId, setVersionProductId] = useState('')
  const [versionForm, setVersionForm] = useState({ version: '', ansible_role: '', supported_os_ubuntu: '22.04', supported_os_rhel: '8', eol_date: '', is_latest: false, default_vars: '{}', conflicts_with: '[]', requires: '[]', aws_defaults: '' })

  useEffect(() => { loadProducts() }, [filter])

  const loadProducts = async () => {
    setLoading(true)
    try {
      const params = filter ? { category: filter } : {}
      const res = await api.get('/build/catalogue', { params })
      setProducts(res.data)
    } catch { /* ignore */ }
    setLoading(false)
  }

  const seedCatalogue = async () => {
    setSeeding(true)
    try {
      const res = await api.post('/build/catalogue/seed')
      alert(`Added ${res.data.products_added} new product(s), synced ${res.data.products_updated} existing product(s) to the current catalogue`)
      loadProducts()
    } catch { /* ignore */ }
    setSeeding(false)
  }

  // --- Product CRUD ---
  const openAddProduct = () => {
    setEditingProduct(null)
    setProductForm({ name: '', display_name: '', category: 'utility', description: '', icon: '📦', default_ports: '', cert_server_tls: true, cert_client_mtls: false, dependencies: '' })
    setShowProductModal(true)
  }

  const openEditProduct = (p: Product) => {
    setEditingProduct(p)
    const targets = p.deployment_targets ?? ['ec2']
    setProductForm({
      name: p.name,
      display_name: p.display_name,
      category: p.category,
      description: p.description,
      icon: p.icon,
      default_ports: p.default_ports.join(', '),
      cert_server_tls: p.cert_requirements?.server_tls ?? false,
      cert_client_mtls: p.cert_requirements?.client_mtls ?? false,
      dependencies: p.dependencies.join(', '),
      deployment_target_ec2: targets.includes('ec2'),
      deployment_target_rds: targets.includes('rds'),
    })
    setShowProductModal(true)
  }

  const saveProduct = async () => {
    const ports = productForm.default_ports ? productForm.default_ports.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n)) : []
    const deps = productForm.dependencies ? productForm.dependencies.split(',').map(s => s.trim()).filter(Boolean) : []
    const certReqs: Record<string, boolean> = {}
    if (productForm.cert_server_tls) certReqs.server_tls = true
    if (productForm.cert_client_mtls) certReqs.client_mtls = true

    const deploymentTargets: string[] = []
    if (productForm.deployment_target_ec2) deploymentTargets.push('ec2')
    if (productForm.deployment_target_rds) deploymentTargets.push('rds')
    if (deploymentTargets.length === 0) deploymentTargets.push('ec2')

    try {
      if (editingProduct) {
        await api.put(`/build/catalogue/${editingProduct.id}`, {
          display_name: productForm.display_name,
          category: productForm.category,
          description: productForm.description,
          icon: productForm.icon,
          default_ports: ports,
          cert_requirements: certReqs,
          dependencies: deps,
          deployment_targets: deploymentTargets,
        })
      } else {
        await api.post('/build/catalogue', {
          name: productForm.name,
          display_name: productForm.display_name,
          category: productForm.category,
          description: productForm.description,
          icon: productForm.icon,
          default_ports: ports,
          cert_requirements: certReqs,
          dependencies: deps,
          deployment_targets: deploymentTargets,
        })
      }
      setShowProductModal(false)
      loadProducts()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to save product')
    }
  }

  const deleteProduct = async (p: Product) => {
    if (!confirm(`Delete "${p.display_name}"? This cannot be undone.`)) return
    try {
      await api.delete(`/build/catalogue/${p.id}`)
      loadProducts()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to delete')
    }
  }

  // --- Version CRUD ---
  const openAddVersion = (productId: string) => {
    setEditingVersion(null)
    setVersionProductId(productId)
    setVersionForm({ version: '', ansible_role: '', supported_os_ubuntu: '22.04', supported_os_rhel: '8', eol_date: '', is_latest: false, default_vars: '{}', conflicts_with: '[]', requires: '[]' })
    setShowVersionModal(true)
  }

  const openEditVersion = (v: ProductVersion) => {
    setEditingVersion(v)
    setVersionProductId(v.product_id)
    const ubuntuMin = v.supported_os.find(o => o.os === 'ubuntu')?.min || ''
    const rhelMin = v.supported_os.find(o => o.os === 'rhel')?.min || ''
    setVersionForm({
      version: v.version,
      ansible_role: v.ansible_role,
      supported_os_ubuntu: ubuntuMin,
      supported_os_rhel: rhelMin,
      eol_date: v.eol_date || '',
      is_latest: v.is_latest,
      default_vars: JSON.stringify(v.default_vars || {}, null, 2),
      conflicts_with: JSON.stringify(v.conflicts_with || [], null, 2),
      requires: JSON.stringify(v.requires || [], null, 2),
      aws_defaults: v.aws_defaults ? JSON.stringify(v.aws_defaults, null, 2) : '',
    })
    setShowVersionModal(true)
  }

  const saveVersion = async () => {
    const supported_os: { os: string; min: string }[] = []
    if (versionForm.supported_os_ubuntu) supported_os.push({ os: 'ubuntu', min: versionForm.supported_os_ubuntu })
    if (versionForm.supported_os_rhel) supported_os.push({ os: 'rhel', min: versionForm.supported_os_rhel })

    let default_vars = {}
    let conflicts_with: any[] = []
    let requires: any[] = []
    try { default_vars = JSON.parse(versionForm.default_vars) } catch { /* ignore */ }
    try { conflicts_with = JSON.parse(versionForm.conflicts_with) } catch { /* ignore */ }
    try { requires = JSON.parse(versionForm.requires) } catch { /* ignore */ }

    let aws_defaults: Record<string, any> | null = null
    if (versionForm.aws_defaults.trim()) {
      try { aws_defaults = JSON.parse(versionForm.aws_defaults) } catch { /* ignore */ }
    }

    try {
      if (editingVersion) {
        await api.put(`/build/catalogue/versions/${editingVersion.id}`, {
          ansible_role: versionForm.ansible_role,
          supported_os,
          eol_date: versionForm.eol_date || null,
          is_latest: versionForm.is_latest,
          default_vars,
          conflicts_with,
          requires,
          aws_defaults,
        })
      } else {
        await api.post(`/build/catalogue/${versionProductId}/versions`, {
          version: versionForm.version,
          ansible_role: versionForm.ansible_role,
          supported_os,
          eol_date: versionForm.eol_date || null,
          is_latest: versionForm.is_latest,
          default_vars,
          conflicts_with,
          requires,
          aws_defaults,
        })
      }
      setShowVersionModal(false)
      loadProducts()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to save version')
    }
  }

  const deleteVersion = async (v: ProductVersion) => {
    if (!confirm(`Delete version ${v.version}?`)) return
    try {
      await api.delete(`/build/catalogue/versions/${v.id}`)
      loadProducts()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Failed to delete')
    }
  }

  const grouped = CATEGORIES.slice(1).map(cat => ({
    ...cat,
    products: products.filter(p => p.category === cat.value),
  })).filter(g => g.products.length > 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Product Catalogue</h1>
          <p className="text-sm text-gray-500 mt-1">Deployable software packages with version and compatibility tracking</p>
        </div>
        <div className="flex gap-2">
          <button onClick={openAddProduct}
            className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700">
            + Add Product
          </button>
          <button onClick={seedCatalogue} disabled={seeding}
            title="Adds any new built-in products and syncs existing ones (e.g. new config fields) to the current catalogue code"
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
            {seeding ? 'Syncing...' : '🌱 Seed / Sync Built-ins'}
          </button>
        </div>
      </div>

      {/* Filter */}
      <div className="flex gap-2 flex-wrap">
        {CATEGORIES.map(cat => (
          <button key={cat.value} onClick={() => setFilter(cat.value)}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              filter === cat.value ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}>
            {cat.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading catalogue...</div>
      ) : products.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-gray-500 mb-4">No products in catalogue yet.</p>
          <button onClick={seedCatalogue} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm">
            Seed Built-in Products
          </button>
        </div>
      ) : (
        <div className="space-y-8">
          {grouped.map(group => (
            <div key={group.value}>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">{group.label}</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {group.products.map(product => (
                  <div key={product.id} className="bg-white border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
                    <div className="flex items-start justify-between">
                      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setExpanded(expanded === product.id ? null : product.id)}>
                        <span className="text-2xl">{product.icon}</span>
                        <div>
                          <h3 className="font-semibold text-gray-900">{product.display_name}</h3>
                          <p className="text-xs text-gray-500">{product.version_count} version{product.version_count !== 1 ? 's' : ''}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 flex-wrap">
                        {(product.deployment_targets ?? ['ec2']).map(t => {
                          const meta = DEPLOYMENT_TARGET_LABELS[t]
                          return meta ? (
                            <span key={t} className={`text-xs px-1.5 py-0.5 rounded font-medium ${meta.colour}`}>{meta.label}</span>
                          ) : null
                        })}
                        {product.is_builtin && (
                          <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">built-in</span>
                        )}
                        <button onClick={(e) => { e.stopPropagation(); openEditProduct(product) }}
                          className="text-xs text-blue-600 hover:text-blue-800 px-1">✏️</button>
                        <button onClick={(e) => { e.stopPropagation(); deleteProduct(product) }}
                          className="text-xs text-red-500 hover:text-red-700 px-1">🗑️</button>
                      </div>
                    </div>
                    <p className="text-sm text-gray-600 mt-2">{product.description}</p>
                    {product.default_ports.length > 0 && (
                      <div className="mt-2 flex gap-1 flex-wrap">
                        {product.default_ports.map(port => (
                          <span key={port} className="text-xs bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">:{port}</span>
                        ))}
                      </div>
                    )}
                    {product.dependencies.length > 0 && (
                      <p className="text-xs text-gray-400 mt-2">Depends on: {product.dependencies.join(', ')}</p>
                    )}

                    {/* Expanded version list */}
                    {expanded === product.id && (
                      <div className="mt-4 pt-3 border-t border-gray-100 space-y-2" onClick={e => e.stopPropagation()}>
                        <div className="flex items-center justify-between">
                          <h4 className="text-xs font-semibold text-gray-500 uppercase">Versions</h4>
                          <button onClick={() => openAddVersion(product.id)}
                            className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded hover:bg-green-200">
                            + Add Version
                          </button>
                        </div>
                        {product.versions.map(v => (
                          <div key={v.id} className="flex items-center justify-between text-sm py-1">
                            <div className="flex items-center gap-2">
                              <span className="font-mono">{v.version}</span>
                              {v.is_latest && <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">latest</span>}
                              {v.eol_date && <span className="text-xs bg-yellow-100 text-yellow-700 px-1.5 py-0.5 rounded">EOL: {v.eol_date}</span>}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-xs text-gray-400">
                                {v.supported_os.map(o => `${o.os} ${o.min}+`).join(', ')}
                              </span>
                              <button onClick={() => openEditVersion(v)}
                                className="text-xs text-blue-600 hover:text-blue-800">✏️</button>
                              <button onClick={() => deleteVersion(v)}
                                className="text-xs text-red-500 hover:text-red-700">🗑️</button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Product Modal */}
      {showProductModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg space-y-4">
            <h2 className="text-lg font-semibold">{editingProduct ? 'Edit Product' : 'Add Product'}</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Name (slug)</label>
                <input value={productForm.name} onChange={e => setProductForm({ ...productForm, name: e.target.value })}
                  disabled={!!editingProduct} placeholder="e.g. nginx"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm disabled:bg-gray-100" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Display Name</label>
                <input value={productForm.display_name} onChange={e => setProductForm({ ...productForm, display_name: e.target.value })}
                  placeholder="e.g. Nginx"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Category</label>
                <select value={productForm.category} onChange={e => setProductForm({ ...productForm, category: e.target.value })}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm">
                  {CATEGORY_OPTIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Icon (emoji)</label>
                <input value={productForm.icon} onChange={e => setProductForm({ ...productForm, icon: e.target.value })}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" maxLength={4} />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
              <input value={productForm.description} onChange={e => setProductForm({ ...productForm, description: e.target.value })}
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Default Ports (comma-separated)</label>
                <input value={productForm.default_ports} onChange={e => setProductForm({ ...productForm, default_ports: e.target.value })}
                  placeholder="e.g. 80, 443" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Dependencies (comma-separated)</label>
                <input value={productForm.dependencies} onChange={e => setProductForm({ ...productForm, dependencies: e.target.value })}
                  placeholder="e.g. erlang, python" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
            </div>
            <div className="flex gap-4 flex-wrap">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={productForm.cert_server_tls}
                  onChange={e => setProductForm({ ...productForm, cert_server_tls: e.target.checked })} />
                Requires Server TLS
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={productForm.cert_client_mtls}
                  onChange={e => setProductForm({ ...productForm, cert_client_mtls: e.target.checked })} />
                Requires Client mTLS
              </label>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Deployment Targets</label>
              <div className="flex gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={productForm.deployment_target_ec2}
                    onChange={e => setProductForm({ ...productForm, deployment_target_ec2: e.target.checked })} />
                  <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded text-xs font-medium">EC2</span> EC2 / Docker / On-premises
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={productForm.deployment_target_rds}
                    onChange={e => setProductForm({ ...productForm, deployment_target_rds: e.target.checked })} />
                  <span className="bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded text-xs font-medium">RDS</span> RDS / Aurora (AWS managed)
                </label>
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t">
              <button onClick={() => setShowProductModal(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">Cancel</button>
              <button onClick={saveProduct} disabled={!productForm.display_name || (!editingProduct && !productForm.name)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
                {editingProduct ? 'Save Changes' : 'Add Product'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Version Modal */}
      {showVersionModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-lg space-y-4">
            <h2 className="text-lg font-semibold">{editingVersion ? `Edit Version ${editingVersion.version}` : 'Add Version'}</h2>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Version</label>
                <input value={versionForm.version} onChange={e => setVersionForm({ ...versionForm, version: e.target.value })}
                  disabled={!!editingVersion} placeholder="e.g. 1.26"
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm disabled:bg-gray-100" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Ansible Role</label>
                <input value={versionForm.ansible_role} onChange={e => setVersionForm({ ...versionForm, ansible_role: e.target.value })}
                  placeholder="e.g. nginx" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Min Ubuntu Version</label>
                <input value={versionForm.supported_os_ubuntu} onChange={e => setVersionForm({ ...versionForm, supported_os_ubuntu: e.target.value })}
                  placeholder="e.g. 22.04" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Min RHEL Version</label>
                <input value={versionForm.supported_os_rhel} onChange={e => setVersionForm({ ...versionForm, supported_os_rhel: e.target.value })}
                  placeholder="e.g. 8" className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">EOL Date (optional)</label>
                <input type="date" value={versionForm.eol_date} onChange={e => setVersionForm({ ...versionForm, eol_date: e.target.value })}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm" />
              </div>
              <div className="flex items-end pb-1">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={versionForm.is_latest}
                    onChange={e => setVersionForm({ ...versionForm, is_latest: e.target.checked })} />
                  Mark as Latest
                </label>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Default Variables (JSON)</label>
              <textarea value={versionForm.default_vars} onChange={e => setVersionForm({ ...versionForm, default_vars: e.target.value })}
                rows={3} className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Requires (JSON array)</label>
              <textarea value={versionForm.requires} onChange={e => setVersionForm({ ...versionForm, requires: e.target.value })}
                rows={2} placeholder='[{"product": "erlang", "min_version": "26", "reason": "..."}]'
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Conflicts With (JSON array)</label>
              <textarea value={versionForm.conflicts_with} onChange={e => setVersionForm({ ...versionForm, conflicts_with: e.target.value })}
                rows={2} placeholder='[{"product": "mariadb", "reason": "Port conflict"}]'
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                AWS Defaults (JSON — optional, used by Template Builder)
              </label>
              <textarea value={versionForm.aws_defaults} onChange={e => setVersionForm({ ...versionForm, aws_defaults: e.target.value })}
                rows={3} placeholder='{"instance_type": "t3.medium", "db_instance_class": "db.t3.medium"}'
                className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono" />
            </div>
            <div className="flex justify-end gap-2 pt-2 border-t">
              <button onClick={() => setShowVersionModal(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">Cancel</button>
              <button onClick={saveVersion} disabled={!editingVersion && !versionForm.version}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50">
                {editingVersion ? 'Save Changes' : 'Add Version'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
