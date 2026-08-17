import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '@/lib/api'
import LibraryList from '@/components/docs/LibraryList'
import ShelfList from '@/components/docs/ShelfList'
import DocList from '@/components/docs/DocList'
import DocReader from '@/components/docs/DocReader'
import DocEditor from '@/components/docs/DocEditor'
import DocMap from '@/components/docs/DocMap'
import ErrorKbSearch from '@/components/docs/ErrorKbSearch'
import BugTracker from '@/components/docs/BugTracker'
import FirstSeenDocsList from '@/components/docs/FirstSeenDocsList'
import Trash from '@/components/docs/Trash'
import DocSearch from '@/components/docs/DocSearch'
import type { DocSummary, BugPrefillData } from '@/components/docs/types'

type View =
  | { type: 'libraries' }
  | { type: 'shelves'; libraryId: string; libraryName: string }
  | { type: 'docs'; libraryId: string; libraryName: string; shelfId: string; shelfName: string }
  | { type: 'reader'; libraryId: string; libraryName: string; shelfId: string; shelfName: string; docId: string; docName: string }
  | { type: 'editor'; libraryId: string; libraryName: string; shelfId: string; shelfName: string; docId: string; docName: string }
  | { type: 'map'; libraryId: string | null; libraryName: string }
  | { type: 'errorkb'; fromBugId?: string }
  | { type: 'bugs'; reportId?: string; subReportId?: string; serviceName?: string; filterReportId?: string; jobId?: string; filterJobId?: string; bugId?: string; filterAutoCreated?: boolean; prefill?: BugPrefillData }
  | { type: 'firstSeenDocs'; reportId: string; subReportId?: string }
  | { type: 'trash' }
  | { type: 'search' }

export default function DocsPage() {
  const [searchParams] = useSearchParams()
  // Cross-navigated from JAR Analyser (?bugs=1&action=new|list&reportId=...
  // &subReportId=...) — a real route change, so state travels via the URL,
  // same mechanism used (then removed as unused) for the old Error Lookup
  // cross-navigation — this time with an actual caller (Stage 3).
  const [view, setView] = useState<View>(() => {
    // Cross-navigated from a bug's "Save to Docs" action (Stage 6,
    // ?openDoc=1&docId=...&shelfId=...&docName=...) — same placeholder-
    // breadcrumb approach handleNavigateToDoc already uses for wiki-links,
    // since the reader only needs library/shelf names for display, not to
    // function.
    if (searchParams.get('openDoc')) {
      return {
        type: 'reader',
        libraryId: '', libraryName: '…',
        shelfId: searchParams.get('shelfId') ?? '', shelfName: '…',
        docId: searchParams.get('docId') ?? '', docName: searchParams.get('docName') ?? '',
      }
    }
    // Cross-navigated from a report's "N docs first seen here" badge
    // (Stage 3, ?firstSeenDocs=1&reportId=...&subReportId=...).
    if (searchParams.get('firstSeenDocs')) {
      const reportId = searchParams.get('reportId') ?? ''
      const subReportId = searchParams.get('subReportId') ?? undefined
      return { type: 'firstSeenDocs', reportId, subReportId }
    }
    // A resolved bug's "Promote to KB" action (?errorkb=1&action=new&
    // fromBugId=...) — cross-navigates straight into the Error KB's New
    // Entry tab, prefilled from that bug, same "pass an id, let the
    // destination fetch its own data" shape as every other cross-nav
    // entry point here rather than stuffing free text into the URL.
    if (searchParams.get('errorkb')) {
      return { type: 'errorkb', fromBugId: searchParams.get('fromBugId') ?? undefined }
    }
    if (!searchParams.get('bugs')) return { type: 'libraries' }
    const reportId = searchParams.get('reportId') ?? undefined
    const subReportId = searchParams.get('subReportId') ?? undefined
    // Build Manager's own "Report Bug" entry point (Improvements Plan
    // Stage 20, ?bugs=1&action=new|list&jobId=...) — same mechanism as the
    // report-based cross-navigation above, just a second origin type.
    const jobId = searchParams.get('jobId') ?? undefined
    if (searchParams.get('action') === 'list') {
      const autoCreated = searchParams.get('autoCreated') === '1'
      return { type: 'bugs', filterReportId: reportId, filterJobId: jobId, filterAutoCreated: autoCreated || undefined }
    }
    // Cross-navigated from a report's "Related Bugs" panel (Improvements
    // Plan Stage 12, ?bugs=1&action=view&bugId=...) — a direct link to one
    // specific bug, not a filter or a pre-filled new-bug form.
    if (searchParams.get('action') === 'view') {
      return { type: 'bugs', bugId: searchParams.get('bugId') ?? undefined }
    }
    return { type: 'bugs', reportId, subReportId, jobId }
  })

  // Wiki-links only carry a document *name* (matching DocApp's own
  // [[Doc Name]] syntax) — resolved via a global search rather than a
  // dedicated lookup endpoint, since Stage 1 already has one and adding a
  // second name-indexed endpoint just for this isn't worth it yet.
  const handleNavigateToDoc = async (name: string) => {
    try {
      const res = await api.get('/docs/search', { params: { q: name, page_size: 50 } })
      const exact = res.data.items.find((d: DocSummary) => d.name.toLowerCase() === name.toLowerCase())
      if (!exact) {
        alert(`No document named "${name}" found.`)
        return
      }
      // Shelf/library names aren't in the search result — the reader only
      // needs them for breadcrumbs, so falling back to a placeholder is
      // harmless (a real lookup would require an extra round trip for
      // display text only).
      setView({
        type: 'reader',
        libraryId: '', libraryName: '…',
        shelfId: exact.shelf_id, shelfName: '…',
        docId: exact.id, docName: exact.name,
      })
    } catch {
      alert(`Could not resolve link to "${name}".`)
    }
  }

  return (
    <div>
      {view.type === 'libraries' && (
        <LibraryList
          onSelect={(id, name) => setView({ type: 'shelves', libraryId: id, libraryName: name })}
          onErrorKb={() => setView({ type: 'errorkb' })}
          onBugs={() => setView({ type: 'bugs' })}
          onTrash={() => setView({ type: 'trash' })}
          onSearch={() => setView({ type: 'search' })}
          onAllLibrariesMap={() => setView({ type: 'map', libraryId: null, libraryName: 'All Libraries' })}
        />
      )}

      {view.type === 'trash' && (
        <Trash onBack={() => setView({ type: 'libraries' })} />
      )}

      {view.type === 'search' && (
        <DocSearch
          onBack={() => setView({ type: 'libraries' })}
          onOpenDoc={(docId, shelfId, docName) =>
            setView({ type: 'reader', libraryId: '', libraryName: '…', shelfId, shelfName: '…', docId, docName })
          }
        />
      )}

      {view.type === 'errorkb' && (
        <ErrorKbSearch
          onBack={() => setView({ type: 'libraries' })}
          onOpenDoc={(docId, libraryId, libraryName, shelfId, shelfName, docName) =>
            setView({ type: 'reader', libraryId, libraryName, shelfId, shelfName, docId, docName })
          }
          fromBugId={view.fromBugId}
          onCreateBug={(prefill) => setView({ type: 'bugs', prefill })}
        />
      )}

      {view.type === 'bugs' && (
        <BugTracker
          onBack={() => setView({ type: 'libraries' })}
          initialReportId={view.reportId}
          initialSubReportId={view.subReportId}
          initialServiceName={view.serviceName}
          filterReportId={view.filterReportId}
          initialBmJobId={view.jobId}
          filterBmJobId={view.filterJobId}
          initialBugId={view.bugId}
          filterAutoCreated={view.filterAutoCreated}
          initialPrefill={view.prefill}
          onPromoteToKb={(bugId) => setView({ type: 'errorkb', fromBugId: bugId })}
        />
      )}

      {view.type === 'firstSeenDocs' && (
        <FirstSeenDocsList
          reportId={view.reportId}
          subReportId={view.subReportId}
          onBack={() => setView({ type: 'libraries' })}
          onOpenDoc={(docId, shelfId, docName) =>
            setView({ type: 'reader', libraryId: '', libraryName: '…', shelfId, shelfName: '…', docId, docName })
          }
        />
      )}

      {view.type === 'shelves' && (
        <ShelfList
          libraryId={view.libraryId}
          libraryName={view.libraryName}
          onSelect={(id, name) => setView({ ...view, type: 'docs', shelfId: id, shelfName: name })}
          onBack={() => setView({ type: 'libraries' })}
          onMap={() => setView({ type: 'map', libraryId: view.libraryId, libraryName: view.libraryName })}
        />
      )}

      {view.type === 'map' && (
        <DocMap
          libraryId={view.libraryId}
          libraryName={view.libraryName}
          onBack={() =>
            view.libraryId
              ? setView({ type: 'shelves', libraryId: view.libraryId, libraryName: view.libraryName })
              : setView({ type: 'libraries' })
          }
          onOpenDoc={(docId, shelfId, shelfName, docName) =>
            setView({
              type: 'reader',
              // All-libraries mode has no single library context to carry
              // forward — same placeholder-breadcrumb approach already used
              // for wiki-link/Error-KB cross-navigation elsewhere in this
              // file, since the reader only needs these for display.
              libraryId: view.libraryId ?? '', libraryName: view.libraryId ? view.libraryName : '…',
              shelfId, shelfName, docId, docName,
            })
          }
        />
      )}

      {view.type === 'docs' && (
        <DocList
          shelfId={view.shelfId}
          shelfName={view.shelfName}
          onSelect={(id, name) => setView({ ...view, type: 'reader', docId: id, docName: name })}
          onCreate={(id, name) => setView({ ...view, type: 'editor', docId: id, docName: name })}
          onBack={() => setView({ type: 'shelves', libraryId: view.libraryId, libraryName: view.libraryName })}
        />
      )}

      {view.type === 'reader' && (
        <DocReader
          docId={view.docId}
          libraryName={view.libraryName}
          shelfName={view.shelfName}
          onBackToShelf={() => setView({ type: 'docs', libraryId: view.libraryId, libraryName: view.libraryName, shelfId: view.shelfId, shelfName: view.shelfName })}
          onNavigateToDoc={handleNavigateToDoc}
          onEdit={() => setView({ ...view, type: 'editor' })}
        />
      )}

      {view.type === 'editor' && (
        <DocEditor
          docId={view.docId}
          docName={view.docName}
          onCancel={() => setView({ ...view, type: 'reader' })}
          onSaved={(newDocId) => setView({ ...view, type: 'reader', docId: newDocId })}
        />
      )}
    </div>
  )
}
