interface Props {
  form: any
  setForm: (fn: (prev: any) => any) => void
}

const OPTIONS = [
  { key: 'include_nopass', label: 'Include unencrypted keys (.key.nopass)', desc: 'Plain PKCS#8 keys for services that cannot use encrypted keys' },
  { key: 'include_snippets', label: 'Include config snippets', desc: 'MySQL, RabbitMQ, Keystone, Spring Boot SSL configuration' },
  { key: 'include_scripts', label: 'Include deployment scripts', desc: 'distribute-certs.sh and verify-certs.sh' },
  { key: 'include_readmes', label: 'Include per-machine READMEs', desc: 'Instructions for each machine role' },
  { key: 'include_quicksetup', label: 'Include quicksetup properties', desc: 'quicksetup-ssl.properties with ENC(...) values' },
]

export default function WizardStep3({ form, setForm }: Props) {
  return (
    <div className="space-y-5">
      <h3 className="font-semibold text-gray-900">Output Options</h3>

      <div className="space-y-3">
        {OPTIONS.map(opt => (
          <label key={opt.key} className="flex items-start gap-3 p-3 border border-gray-200 rounded-lg cursor-pointer hover:bg-gray-50">
            <input type="checkbox" checked={form[opt.key]}
              onChange={e => setForm(p => ({ ...p, [opt.key]: e.target.checked }))}
              className="mt-0.5" />
            <div>
              <div className="text-sm font-medium text-gray-900">{opt.label}</div>
              <div className="text-xs text-gray-500">{opt.desc}</div>
            </div>
          </label>
        ))}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Base Path</label>
        <input type="text" value={form.base_path}
          onChange={e => setForm(p => ({ ...p, base_path: e.target.value }))}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="/opt/scripts/ssl" />
        <p className="text-xs text-gray-400 mt-1">Target directory on remote machines (used in config snippets and scripts)</p>
      </div>
    </div>
  )
}
