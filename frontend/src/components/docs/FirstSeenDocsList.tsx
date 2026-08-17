import { useQuery } from '@tanstack/react-query'
import api from '@/lib/api'
import type { DocSummary } from './types'

// Reverse lookup for the "N docs first seen here" badge on a report/sub-
// report view (Stage 3 of doc_first_seen_plan.md) — Docs has no other flat,
// cross-shelf filtered doc list, so this is a small dedicated view rather
// than a generalisation of DocList (which is shelf-scoped) or the search
// results rendering in ErrorKbSearch (which is KB-specific).
interface Props {
  reportId: string
  subReportId?: string
  onBack: () => void
  onOpenDoc: (docId: string, shelfId: string, docName: string) => void
}

export default function FirstSeenDocsList({ reportId, subReportId, onBack, onOpenDoc }: Props) {
  const { data: report } = useQuery({
    queryKey: ['jar-report-brief', reportId],
    queryFn: () => api.get(`/jar-analyser/reports/${reportId}`).then(r => r.data),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['docs-first-seen', reportId, subReportId],
    queryFn: () => api.get('/docs/search', {
      params: subReportId ? { first_seen_sub_report_id: subReportId } : { first_seen_report_id: reportId },
    }).then(r => r.data),
  })
  const docs: DocSummary[] = data?.items ?? []

  const fmtDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

  return (
    <div className="space-y-4">
      <div>
        <button onClick={onBack} className="text-sm text-gray-500 hover:text-gray-700 mb-2">← Docs</button>
        <h1 className="text-2xl font-bold text-gray-900">📄 First Seen Here</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          {report ? (report.implementation_title || report.filename) : `report #${reportId.slice(0, 8)}`}
          {subReportId ? ' (specific service)' : ''}
        </p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
        {isLoading && <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading...</div>}
        {!isLoading && docs.length === 0 && (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No documents first seen here.</div>
        )}
        {docs.map(doc => (
          <div key={doc.id}
            className="px-4 py-3 flex items-center justify-between hover:bg-gray-50 cursor-pointer"
            onClick={() => onOpenDoc(doc.id, doc.shelf_id, doc.name)}>
            <div className="flex items-center gap-2">
              <span>📄</span>
              <span className="font-medium text-gray-900">{doc.name}</span>
              <span className="text-xs text-gray-400 font-mono">v{doc.version}</span>
            </div>
            <span className="text-xs text-gray-400">{fmtDate(doc.updated_at)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
