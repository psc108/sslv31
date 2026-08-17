interface Host {
  role: string
  fqdn: string
  ip: string
}

interface Props {
  hosts: Host[]
  setHosts: (hosts: Host[]) => void
}

const ROLES = [
  { role: 'mysql', label: 'MySQL', icon: '🗄️', desc: 'Database server' },
  { role: 'rabbitmq', label: 'RabbitMQ', icon: '🐰', desc: 'Message broker' },
  { role: 'keystone', label: 'Keystone', icon: '🔑', desc: 'Identity service' },
  { role: 'backend', label: 'Backend', icon: '⚙️', desc: 'Application server' },
  { role: 'frontend', label: 'Frontend', icon: '🌐', desc: 'Web server' },
]

const IP_REGEX = /^(\d{1,3}\.){3}\d{1,3}$/
const FQDN_REGEX = /^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$/

function validateIp(ip: string): boolean {
  if (!ip) return true
  if (!IP_REGEX.test(ip)) return false
  return ip.split('.').every(o => { const n = parseInt(o); return n >= 0 && n <= 255 })
}

export default function WizardStep2({ hosts, setHosts }: Props) {
  const update = (idx: number, field: 'fqdn' | 'ip', value: string) => {
    const next = [...hosts]
    next[idx] = { ...next[idx], [field]: value }
    setHosts(next)
  }

  const duplicateFqdns = hosts.map((h, i) =>
    h.fqdn && hosts.some((o, j) => j !== i && o.fqdn === h.fqdn)
  )
  const duplicateIps = hosts.map((h, i) =>
    h.ip && hosts.some((o, j) => j !== i && o.ip === h.ip)
  )

  return (
    <div className="space-y-4">
      <h3 className="font-semibold text-gray-900">Host Configuration</h3>
      <p className="text-xs text-gray-500">Enter the FQDN and IP address for each machine in the environment.</p>

      <div className="space-y-3">
        {ROLES.map((r, idx) => {
          const host = hosts[idx]
          const ipValid = validateIp(host.ip)
          const fqdnValid = !host.fqdn || FQDN_REGEX.test(host.fqdn)
          const fqdnDup = duplicateFqdns[idx]
          const ipDup = duplicateIps[idx]
          return (
            <div key={r.role} className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 p-3 border border-gray-200 rounded-lg">
              <div className="w-28 flex items-center gap-2 shrink-0">
                <span>{r.icon}</span>
                <div>
                  <div className="text-sm font-medium text-gray-900">{r.label}</div>
                  <div className="text-xs text-gray-400">{r.desc}</div>
                </div>
              </div>
              <div className="flex-1">
                <input type="text" value={host.fqdn}
                  onChange={e => update(idx, 'fqdn', e.target.value)}
                  className={`w-full border rounded-md px-3 py-1.5 text-sm ${!fqdnValid || fqdnDup ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
                  placeholder={`${r.role}.example.internal`} />
                {!fqdnValid && <p className="text-xs text-red-500 mt-0.5">Invalid hostname format</p>}
                {fqdnDup && <p className="text-xs text-red-500 mt-0.5">Duplicate FQDN</p>}
              </div>
              <div className="w-full sm:w-40">
                <input type="text" value={host.ip}
                  onChange={e => update(idx, 'ip', e.target.value)}
                  className={`w-full border rounded-md px-3 py-1.5 text-sm ${!ipValid || ipDup ? 'border-red-400 bg-red-50' : 'border-gray-300'}`}
                  placeholder="10.0.0.x" />
                {!ipValid && <p className="text-xs text-red-500 mt-0.5">Invalid IP (0-255)</p>}
                {ipDup && <p className="text-xs text-red-500 mt-0.5">Duplicate IP</p>}
              </div>
            </div>
          )
        })}
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-xs text-blue-700">
        💡 Each certificate will include the FQDN, IP, <code>localhost</code>, and <code>127.0.0.1</code> as SANs automatically.
      </div>
    </div>
  )
}
