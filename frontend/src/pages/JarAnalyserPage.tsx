import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import UploadZone from '@/components/jar-analyser/UploadZone'
import ReportBrowser from '@/components/jar-analyser/ReportBrowser'
import TopLevelReport from '@/components/jar-analyser/TopLevelReport'
import SubReportView from '@/components/jar-analyser/SubReportView'
import DiffView from '@/components/jar-analyser/DiffView'
import DiagnosticsRunPage from '@/components/jar-analyser/DiagnosticsRunPage'
import ManualDiagnosticsPage from '@/components/jar-analyser/ManualDiagnosticsPage'
import InfraDiagnosticsLandingPage from '@/components/jar-analyser/InfraDiagnosticsLandingPage'
import InfraWizardPage from '@/components/jar-analyser/InfraWizardPage'
import InfraRunPage from '@/components/jar-analyser/InfraRunPage'

type View =
  | { type: 'browser' }
  | { type: 'upload' }
  | { type: 'polling'; uploadId: string }
  | { type: 'report'; reportId: string }
  | { type: 'sub'; reportId: string; subId: string; initialTab?: string }
  | { type: 'diff'; reportAId?: string; reportBId?: string; diffId?: string }
  | { type: 'diagnostics'; reportId: string }
  | { type: 'manual-diagnostics'; reportId: string }
  | { type: 'infra-diagnostics'; reportId?: string }
  | { type: 'infra-wizard'; service: string; reportId?: string }
  | { type: 'infra-run'; runId: string; service: string }

export default function JarAnalyserPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Deep link from a bug's "back to report" link in Docs (?report=...&sub=...)
  // — a real route change landing here, so state travels via the URL like
  // any other cross-page entry into this app.
  const [view, setView] = useState<View>(() => {
    const reportId = searchParams.get('report')
    if (!reportId) return { type: 'browser' }
    const subId = searchParams.get('sub')
    if (!subId) return { type: 'report', reportId }
    return { type: 'sub', reportId, subId, initialTab: searchParams.get('tab') ?? undefined }
  })

  const handleNavigate = (reportId: string, subReportId: string, tab: string) => {
    setView({ type: 'sub', reportId, subId: subReportId, initialTab: tab })
  }

  // The bug-filing/browsing UI lives only in Docs — this just cross-navigates
  // there with enough context to land pre-filled (new bug) or pre-filtered
  // (existing bugs for this report), same mechanism as the old Error Lookup
  // cross-navigation, this time with an actual caller.
  const openBugTracker = (mode: 'new' | 'list', reportId: string, subReportId?: string) => {
    const params = new URLSearchParams({ bugs: '1', action: mode, reportId })
    if (subReportId) params.set('subReportId', subReportId)
    navigate(`/docs?${params.toString()}`)
  }

  // Same cross-navigation mechanism, but straight to one specific bug — used
  // by the "Related Bugs" panel (Improvements Plan Stage 12), where the
  // destination is a known bug id rather than a mode/filter to apply.
  const openBug = (bugId: string) => {
    navigate(`/docs?${new URLSearchParams({ bugs: '1', action: 'view', bugId }).toString()}`)
  }

  // Same cross-navigation mechanism as openBugTracker — the "N docs first
  // seen here" badge (Stage 3 of doc_first_seen_plan.md) needs its own
  // filtered results view in Docs since DocList is shelf-scoped only.
  const openFirstSeenDocs = (reportId: string, subReportId?: string) => {
    const params = new URLSearchParams({ firstSeenDocs: '1', reportId })
    if (subReportId) params.set('subReportId', subReportId)
    navigate(`/docs?${params.toString()}`)
  }

  return (
    <div>
      {view.type === 'browser' && (
        <ReportBrowser
          onSelect={id => setView({ type: 'report', reportId: id })}
          onUpload={() => setView({ type: 'upload' })}
          onCompare={(a, b) => setView({ type: 'diff', reportAId: a, reportBId: b })}
          onNavigate={handleNavigate}
          onInfraDiagnostics={() => setView({ type: 'infra-diagnostics' })}
        />
      )}

      {(view.type === 'upload' || view.type === 'polling') && (
        <UploadZone
          onUploaded={id => setView({ type: 'report', reportId: id })}
          pollUploadId={view.type === 'polling' ? view.uploadId : undefined}
        />
      )}

      {view.type === 'report' && (
        <TopLevelReport
          reportId={view.reportId}
          onSelectSub={subId => setView({ type: 'sub', reportId: view.reportId, subId })}
          onBack={() => setView({ type: 'browser' })}
          onCompare={() => setView({ type: 'diff' })}
          onRerun={uploadId => setView({ type: 'polling', uploadId })}
          onNavigate={handleNavigate}
          onDiagnostics={() => setView({ type: 'diagnostics', reportId: view.reportId })}
          onInfraDiagnostics={id => setView({ type: 'infra-diagnostics', reportId: id })}
          onBugTracker={mode => openBugTracker(mode, view.reportId)}
          onViewBug={openBug}
          onFirstSeenDocs={() => openFirstSeenDocs(view.reportId)}
        />
      )}

      {view.type === 'sub' && (
        <SubReportView
          reportId={view.reportId}
          subReportId={view.subId}
          initialTab={view.initialTab}
          onBack={() => setView({ type: 'report', reportId: view.reportId })}
          onBugTracker={mode => openBugTracker(mode, view.reportId, view.subId)}
          onFirstSeenDocs={() => openFirstSeenDocs(view.reportId, view.subId)}
        />
      )}

      {view.type === 'diff' && (
        <DiffView
          reportAId={view.reportAId}
          reportBId={view.reportBId}
          diffId={view.diffId}
          onBack={() => setView({ type: 'browser' })}
        />
      )}

      {view.type === 'diagnostics' && (
        <DiagnosticsRunPage
          reportId={view.reportId}
          onBack={() => setView({ type: 'report', reportId: view.reportId })}
          onManualCollection={() => setView({ type: 'manual-diagnostics', reportId: view.reportId })}
        />
      )}

      {view.type === 'manual-diagnostics' && (
        <ManualDiagnosticsPage
          reportId={view.reportId}
          onBack={() => setView({ type: 'diagnostics', reportId: view.reportId })}
          onRunCreated={runId => setView({ type: 'diagnostics', reportId: view.reportId })}
        />
      )}

      {view.type === 'infra-diagnostics' && (
        <InfraDiagnosticsLandingPage
          reportId={view.reportId}
          onSelectService={(service, reportId) => setView({ type: 'infra-wizard', service, reportId })}
          onViewRun={(runId, service) => setView({ type: 'infra-run', runId, service })}
          onBack={() => setView({ type: 'browser' })}
        />
      )}

      {view.type === 'infra-wizard' && (
        <InfraWizardPage
          service={view.service}
          reportId={view.reportId}
          onBack={() => setView({ type: 'infra-diagnostics', reportId: view.reportId })}
          onRunCreated={(runId, service) => setView({ type: 'infra-run', runId, service })}
        />
      )}

      {view.type === 'infra-run' && (
        <InfraRunPage
          runId={view.runId}
          service={view.service}
          onBack={() => setView({ type: 'infra-diagnostics' })}
        />
      )}
    </div>
  )
}
