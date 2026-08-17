import { useState, useEffect } from 'react'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'

const EVENT_TYPES = [
  { value: 'expiry_warning', label: 'Certificate Expiry Warning', icon: '⚠️' },
  { value: 'cert_issued', label: 'Certificate Issued', icon: '✅' },
  { value: 'approval_required', label: 'Approval Required', icon: '🔔' },
  { value: 'approval_decision', label: 'Approval Decision', icon: '📋' },
  { value: 'security_event', label: 'Security Event', icon: '🚨' },
  { value: 'auto_renewal', label: 'Auto-Renewal Completed', icon: '🔄' },
  { value: 'bug_assigned', label: 'Bug Assigned to You', icon: '🐛' },
  { value: 'bug_status_changed', label: 'Bug Status Changed', icon: '🐛' },
  { value: 'bug_occurrence_linked', label: 'Bug Seen on Another Report', icon: '🐛' },
]

export default function NotificationsPage() {
  const { user } = useAuth()
  const [prefs, setPrefs] = useState<any[]>([])
  const [smtp, setSmtp] = useState<any>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [tab, setTab] = useState<'preferences' | 'smtp'>('preferences')
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [emailInfo, setEmailInfo] = useState<any>({})
  const [emailInput, setEmailInput] = useState('')
  const [smtpForm, setSmtpForm] = useState({
    enabled: false, host: '', port: 587, user: '', password: '',
    from_address: 'PKI Alerts <pki@corp.internal>', tls: 'starttls',
  })

  useEffect(() => { loadData() }, [])

  async function loadData() {
    setLoading(true)
    try {
      const [prefRes, emailRes, smtpRes] = await Promise.all([
        api.get('/notifications/preferences'),
        api.get('/notifications/my-email'),
        api.get('/notifications/smtp').catch(() => null),
      ])
      setPrefs(prefRes.data.preferences || [])
      setEmailInfo(emailRes.data)
      setEmailInput(emailRes.data.notification_email || '')

      if (smtpRes?.data) {
        setIsAdmin(true)
        setSmtp(smtpRes.data)
        setSmtpForm({
          enabled: smtpRes.data.enabled,
          host: smtpRes.data.host,
          port: smtpRes.data.port,
          user: smtpRes.data.user,
          password: '',
          from_address: smtpRes.data.from_address,
          tls: smtpRes.data.tls,
        })
      }
    } catch { /* ignore */ }
    setLoading(false)
  }

  async function saveEmail() {
    try {
      await api.put('/notifications/my-email', { email: emailInput })
      setMsg('Notification email updated')
      loadData()
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Failed to save email')
    }
  }

  async function subscribe(eventType: string) {
    // Bug events are tagged per-recipient by bug_tracker.py (e.g. the
    // assignee's username) rather than broadcast tenant-wide like the
    // cert/BM events above — subscribing only makes sense scoped to
    // yourself, so auto-fill filter_tag with your own username rather
    // than exposing a manual tag field just for these three.
    const filterTag = eventType.startsWith('bug_') ? user?.username : undefined
    await api.post('/notifications/preferences', { event_type: eventType, filter_tag: filterTag })
    setMsg(`Subscribed to ${eventType}`)
    loadData()
  }

  async function togglePref(id: string, enabled: boolean) {
    await api.put(`/notifications/preferences/${id}`, { enabled: !enabled })
    loadData()
  }

  async function toggleDigest(id: string, digest: boolean) {
    await api.put(`/notifications/preferences/${id}`, { digest_mode: !digest })
    loadData()
  }

  async function deletePref(id: string) {
    await api.delete(`/notifications/preferences/${id}`)
    loadData()
  }

  async function saveSmtp() {
    try {
      await api.put('/notifications/smtp', smtpForm)
      setMsg('SMTP settings saved')
      loadData()
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Failed to save')
    }
  }

  async function testSmtp() {
    try {
      const res = await api.post('/notifications/smtp/test')
      setMsg(`SMTP test: ${res.data.status} — ${res.data.message}`)
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Test failed')
    }
  }

  async function sendTestEmail() {
    try {
      const res = await api.post('/notifications/smtp/test-email')
      setMsg(`Test email: ${res.data.status} → ${res.data.to}`)
    } catch (e: any) {
      setMsg(e.response?.data?.detail || 'Send failed')
    }
  }

  const subscribedTypes = prefs.map(p => p.event_type)
  const unsubscribed = EVENT_TYPES.filter(e => !subscribedTypes.includes(e.value))

  if (loading) return <div className="p-6">Loading...</div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">📧 Notifications</h1>
        <div className="flex gap-2">
          <button onClick={() => setTab('preferences')}
            className={`px-3 py-1.5 rounded text-sm font-medium ${tab === 'preferences' ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'}`}>
            My Preferences
          </button>
          {isAdmin && (
            <button onClick={() => setTab('smtp')}
              className={`px-3 py-1.5 rounded text-sm font-medium ${tab === 'smtp' ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'}`}>
              SMTP Settings
            </button>
          )}
        </div>
      </div>

      {msg && (
        <div className="bg-blue-50 border border-blue-200 text-blue-800 px-4 py-2 rounded text-sm">
          {msg}
          <button onClick={() => setMsg('')} className="ml-2 text-blue-600">✕</button>
        </div>
      )}

      {tab === 'preferences' && (
        <div className="space-y-4">
          {/* Email address */}
          <div className="bg-white rounded-lg border p-4">
            <h2 className="text-lg font-semibold mb-2">Notification Email</h2>
            <p className="text-sm text-gray-500 mb-3">
              Notifications will be sent to this address. Leave blank to use your account email
              {emailInfo.account_email ? ` (${emailInfo.account_email})` : ''}.
            </p>
            <div className="flex gap-2">
              <input type="email" value={emailInput}
                onChange={e => setEmailInput(e.target.value)}
                placeholder={emailInfo.account_email || 'you@example.com'}
                className="flex-1 rounded border-gray-300 shadow-sm text-sm p-2 border" />
              <button onClick={saveEmail}
                className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">
                Save
              </button>
            </div>
            {emailInfo.effective_email && (
              <p className="text-xs text-gray-400 mt-1">Delivering to: {emailInfo.effective_email}</p>
            )}
          </div>

          {/* Current subscriptions */}
          <div className="bg-white rounded-lg border p-4">
            <h2 className="text-lg font-semibold mb-3">Active Subscriptions</h2>
            {prefs.length === 0 ? (
              <p className="text-gray-500 text-sm">No subscriptions yet. Add one below.</p>
            ) : (
              <div className="space-y-2">
                {prefs.map(p => {
                  const evt = EVENT_TYPES.find(e => e.value === p.event_type)
                  return (
                    <div key={p.id} className="flex items-center justify-between p-3 bg-gray-50 rounded">
                      <div className="flex items-center gap-2">
                        <span>{evt?.icon || '📨'}</span>
                        <span className="font-medium text-sm">{evt?.label || p.event_type}</span>
                        {p.mandatory && <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded">mandatory</span>}
                        {p.digest_mode && <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">digest</span>}
                        {p.filter_ca_id && <span className="text-xs bg-gray-200 px-1.5 py-0.5 rounded">CA filter</span>}
                        {p.filter_tag && <span className="text-xs bg-gray-200 px-1.5 py-0.5 rounded">scoped to "{p.filter_tag}"</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        <button onClick={() => toggleDigest(p.id, p.digest_mode)}
                          className="text-xs text-purple-600 hover:underline" title="Toggle digest mode">
                          {p.digest_mode ? 'Immediate' : 'Digest'}
                        </button>
                        <button onClick={() => togglePref(p.id, p.enabled)}
                          className={`text-xs px-2 py-1 rounded ${p.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'}`}>
                          {p.enabled ? 'On' : 'Off'}
                        </button>
                        {!p.mandatory && (
                          <button onClick={() => deletePref(p.id)} className="text-xs text-red-500 hover:text-red-700">✕</button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Subscribe to new events */}
          {unsubscribed.length > 0 && (
            <div className="bg-white rounded-lg border p-4">
              <h2 className="text-lg font-semibold mb-3">Available Events</h2>
              <div className="grid grid-cols-2 gap-2">
                {unsubscribed.map(evt => (
                  <button key={evt.value} onClick={() => subscribe(evt.value)}
                    className="flex items-center gap-2 p-3 border rounded hover:bg-blue-50 text-left text-sm">
                    <span>{evt.icon}</span>
                    <span>{evt.label}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === 'smtp' && isAdmin && (
        <div className="bg-white rounded-lg border p-6 space-y-4">
          <h2 className="text-lg font-semibold">SMTP Configuration</h2>
          <p className="text-sm text-gray-500">System-wide email delivery settings. Only admins can modify this.</p>

          <div className="grid grid-cols-2 gap-4">
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Enabled</span>
              <select value={smtpForm.enabled ? 'true' : 'false'}
                onChange={e => setSmtpForm({ ...smtpForm, enabled: e.target.value === 'true' })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border">
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">TLS Mode</span>
              <select value={smtpForm.tls}
                onChange={e => setSmtpForm({ ...smtpForm, tls: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border">
                <option value="starttls">STARTTLS</option>
                <option value="ssl">SSL/TLS</option>
                <option value="none">None</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">SMTP Host</span>
              <input type="text" value={smtpForm.host}
                onChange={e => setSmtpForm({ ...smtpForm, host: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border"
                placeholder="smtp.corp.internal" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Port</span>
              <input type="number" value={smtpForm.port}
                onChange={e => setSmtpForm({ ...smtpForm, port: parseInt(e.target.value) || 587 })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Username</span>
              <input type="text" value={smtpForm.user}
                onChange={e => setSmtpForm({ ...smtpForm, user: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border" />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-gray-700">Password</span>
              <input type="password" value={smtpForm.password}
                onChange={e => setSmtpForm({ ...smtpForm, password: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border"
                placeholder="Leave blank to keep current" />
            </label>
            <label className="block col-span-2">
              <span className="text-sm font-medium text-gray-700">From Address</span>
              <input type="text" value={smtpForm.from_address}
                onChange={e => setSmtpForm({ ...smtpForm, from_address: e.target.value })}
                className="mt-1 block w-full rounded border-gray-300 shadow-sm text-sm p-2 border" />
            </label>
          </div>

          <div className="flex gap-3 pt-2">
            <button onClick={saveSmtp}
              className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">
              Save Settings
            </button>
            <button onClick={testSmtp}
              className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200 border">
              Test Connection
            </button>
            <button onClick={sendTestEmail}
              className="px-4 py-2 bg-green-100 text-green-700 rounded text-sm font-medium hover:bg-green-200 border border-green-200">
              Send Test Email
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
