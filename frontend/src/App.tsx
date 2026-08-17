import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from '@/lib/auth'
import Layout from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import CAPage from '@/pages/CAPage'
import CertificateList from '@/pages/CertificateList'
import CertificateWizard from '@/pages/CertificateWizard'
import CertificateDetail from '@/pages/CertificateDetail'
import TrustStoreBuilder from '@/pages/TrustStoreBuilder'
import AuditLogViewer from '@/pages/AuditLogViewer'
import CSRPage from '@/pages/CSRPage'
import SettingsPage from '@/pages/SettingsPage'
import ToolsPage from '@/pages/ToolsPage'
import TemplatesPage from '@/pages/TemplatesPage'
import UsersPage from '@/pages/UsersPage'
import LoginPage from '@/pages/LoginPage'
import HelpPage from '@/pages/HelpPage'
import AboutPage from '@/pages/AboutPage'
import DiagnosticsPage from '@/pages/DiagnosticsPage'
import ReportsPage from '@/pages/ReportsPage'
import ApprovalsPage from '@/pages/ApprovalsPage'
import EnvironmentProvisioning from '@/pages/EnvironmentProvisioning'
import TenantsPage from '@/pages/TenantsPage'
import CTLogPage from '@/pages/CTLogPage'
import NotificationsPage from '@/pages/NotificationsPage'
import CrossCertPage from '@/pages/CrossCertPage'
import KubernetesPage from '@/pages/KubernetesPage'
import CompliancePage from '@/pages/CompliancePage'
import KeyEscrowPage from '@/pages/KeyEscrowPage'
import SDKPage from '@/pages/SDKPage'
import SCEPPage from '@/pages/SCEPPage'
import InventoryPage from '@/pages/InventoryPage'
import BMTemplatesPage from '@/pages/BMTemplatesPage'
import EnvironmentsPage from '@/pages/EnvironmentsPage'
import JobsPage from '@/pages/JobsPage'
import BMDashboardPage from '@/pages/BMDashboardPage'
import BMHelpPage from '@/pages/BMHelpPage'
import BMCataloguePage from '@/pages/BMCataloguePage'
import BMTemplateBuilderPage from '@/pages/BMTemplateBuilderPage'
import BMCertBindingsPage from '@/pages/BMCertBindingsPage'
import BMSecretsPage from '@/pages/BMSecretsPage'
import BMPkiPosturePage from '@/pages/BMPkiPosturePage'
import BMHealthPage from '@/pages/BMHealthPage'
import BMEditorPage from '@/pages/BMEditorPage'
import BMPkgCachePage from '@/pages/BMPkgCachePage'
import JarAnalyserPage from '@/pages/JarAnalyserPage'
import JarAnalyserHelpPage from '@/pages/JarAnalyserHelpPage'
import DocsPage from '@/pages/DocsPage'
import DocsHelpPage from '@/pages/DocsHelpPage'

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ca" element={<CAPage />} />
          <Route path="/certificates" element={<CertificateList />} />
          <Route path="/certificates/new" element={<CertificateWizard />} />
          <Route path="/certificates/:serial" element={<CertificateDetail />} />
          <Route path="/truststores" element={<TrustStoreBuilder />} />
          <Route path="/csr" element={<CSRPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/audit" element={<AuditLogViewer />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/help" element={<HelpPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/provisioning" element={<EnvironmentProvisioning />} />
          <Route path="/tenants" element={<TenantsPage />} />
          <Route path="/ct-log" element={<CTLogPage />} />
          <Route path="/notifications" element={<NotificationsPage />} />
          <Route path="/cross-certs" element={<CrossCertPage />} />
          <Route path="/kubernetes" element={<KubernetesPage />} />
          <Route path="/compliance" element={<CompliancePage />} />
          <Route path="/key-escrow" element={<KeyEscrowPage />} />
          <Route path="/sdk" element={<SDKPage />} />
          <Route path="/scep" element={<SCEPPage />} />
          <Route path="/bm" element={<BMDashboardPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/bm-templates" element={<BMTemplatesPage />} />
          <Route path="/environments" element={<EnvironmentsPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/bm-help" element={<BMHelpPage />} />
          <Route path="/bm-catalogue" element={<BMCataloguePage />} />
          <Route path="/bm-builder" element={<BMTemplateBuilderPage />} />
          <Route path="/bm-certs" element={<BMCertBindingsPage />} />
          <Route path="/bm-secrets" element={<BMSecretsPage />} />
          <Route path="/bm-pki-posture" element={<BMPkiPosturePage />} />
          <Route path="/bm-health" element={<BMHealthPage />} />
          <Route path="/bm-editor" element={<BMEditorPage />} />
          <Route path="/bm-pkg-cache" element={<BMPkgCachePage />} />
          <Route path="/diagnostics" element={<DiagnosticsPage />} />
          <Route path="/jar-analyser" element={<JarAnalyserPage />} />
          <Route path="/jar-help" element={<JarAnalyserHelpPage />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/docs-help" element={<DocsHelpPage />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
