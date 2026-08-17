import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import RecentErrors from '@/components/RecentErrors'

export default function DiagnosticsPage() {
  const { data, isLoading, error } = useQuery<any>({
    queryKey: ['diagnostics'],
    queryFn: async () => (await api.get('/diagnostics')).data,
    refetchInterval: 30000,
  })

  if (isLoading) return <div className="p-6 text-gray-400">Loading diagnostics...</div>
  if (error) return <div className="p-6 text-red-600">Failed to load diagnostics</div>
  if (!data) return null

  return (
    <div>
      <h2 className="text-2xl font-bold text-gray-900 mb-6">System Diagnostics</h2>

      {/* Recent Errors */}
      <div className="mb-4">
        <RecentErrors />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System Info */}
        <Panel title="System">
          <Row label="OS" value={data.system.os_pretty || data.system.os} />
          <Row label="Hostname" value={data.system.hostname} />
          <Row label="Python" value={data.system.python_version} />
          <Row label="Uptime" value={formatUptime(data.system.uptime_seconds)} />
        </Panel>

        {/* Dependencies */}
        <Panel title="Dependencies">
          <Row label="OpenSSL" value={data.dependencies.openssl_version} />
          <Row label="Java" value={data.dependencies.java_version} />
          <StatusRow label="Keytool" ok={data.dependencies.keytool_available} detail={data.dependencies.keytool_path} />
        </Panel>

        {/* Health */}
        <Panel title="Health Checks">
          <StatusRow label="Database" ok={data.health.database === 'ok'} />
          <StatusRow label="Keytool" ok={data.health.keytool === 'ok'} detail={data.health.keytool !== 'ok' ? 'Not installed' : undefined} />
          <StatusRow label="Data dir writable" ok={data.health.data_dir_writable} />
          <StatusRow label="Backup dir writable" ok={data.health.backup_dir_writable} />
        </Panel>

        {/* Storage */}
        <Panel title="Storage">
          <Row label="Data directory" value={`${data.storage.data_dir_size_mb} MB used`} />
          <Row label="Free disk space" value={`${data.storage.data_dir_free_mb} MB`} />
          <Row label="Database size" value={`${data.storage.db_size_mb} MB`} />
          <Row label="Backups" value={`${data.storage.backup_count} archives`} />
          <Row label="Last backup" value={data.storage.last_backup ? new Date(data.storage.last_backup).toLocaleString() : 'Never'} />
        </Panel>

        {/* Certificates */}
        <Panel title="Certificate Inventory">
          <Row label="Total" value={data.certificates.total} />
          <Row label="Valid" value={data.certificates.valid} color="green" />
          <Row label="Expiring soon" value={data.certificates.expiring_soon} color={data.certificates.expiring_soon > 0 ? 'amber' : 'green'} />
          <Row label="Expired" value={data.certificates.expired} color={data.certificates.expired > 0 ? 'red' : 'gray'} />
          <Row label="Revoked" value={data.certificates.revoked} color="gray" />
          <Row label="CAs" value={data.certificates.cas_total} />
        </Panel>

        {/* Configuration */}
        <Panel title="Configuration">
          <Row label="Data dir" value={data.configuration.data_dir} mono />
          <Row label="Backup dir" value={data.configuration.backup_dir} mono />
          <Row label="Log level" value={data.configuration.log_level} />
          <Row label="Max cert days" value={data.configuration.max_cert_days} />
          <Row label="Backup enabled" value={data.configuration.backup_enabled ? 'Yes' : 'No'} />
          <Row label="Backup interval" value={`${data.configuration.backup_interval_hours}h`} />
          <Row label="Expiry scan interval" value={`${data.configuration.expiry_scan_interval_hours}h`} />
          <Row label="Base URL" value={data.configuration.base_url} mono />
        </Panel>
      </div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function Row({ label, value, mono, color }: { label: string; value: any; mono?: boolean; color?: string }) {
  const colorClass = color === 'green' ? 'text-green-700' :
    color === 'amber' ? 'text-amber-700' :
    color === 'red' ? 'text-red-700' :
    color === 'gray' ? 'text-gray-500' : 'text-gray-900'

  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`${mono ? 'font-mono text-xs' : ''} ${colorClass}`}>{String(value)}</span>
    </div>
  )
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-gray-500">{label}</span>
      <span className={`flex items-center gap-1 ${ok ? 'text-green-700' : 'text-red-700'}`}>
        {ok ? '✓' : '✗'} {ok ? 'OK' : 'Issue'}
        {detail && <span className="text-xs text-gray-400 ml-1">({detail})</span>}
      </span>
    </div>
  )
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h ${mins}m`
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}
