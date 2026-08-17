import api from '@/lib/api'

interface Props {
  reportId: string
  subReportId?: string
  diffId?: string
}

export default function ExportControls({ reportId, subReportId, diffId }: Props) {
  const download = async (url: string, filename: string) => {
    const res = await api.get(url, { responseType: 'blob' })
    const href = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = href
    a.download = filename
    a.click()
    URL.revokeObjectURL(href)
  }

  if (diffId) {
    return (
      <div className="flex gap-2">
        <button
          onClick={() => download(`/jar-analyser/diff/${diffId}/export/markdown`, `diff-${diffId}.md`)}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-1"
        >
          ⬇ Raw Diff
        </button>
        <button
          onClick={() => download(`/jar-analyser/diff/${diffId}/export/change-report/markdown`, `change-report-${diffId.slice(0,8)}.md`)}
          className="px-3 py-1.5 border border-blue-300 bg-blue-50 rounded text-sm text-blue-700 hover:bg-blue-100"
        >
          ⬇ Change Report (MD)
        </button>
        <button
          onClick={() => download(`/jar-analyser/diff/${diffId}/export/change-report/pdf`, `change-report-${diffId.slice(0,8)}.pdf`)}
          className="px-3 py-1.5 border border-indigo-300 bg-indigo-50 rounded text-sm text-indigo-700 hover:bg-indigo-100"
        >
          ⬇ Change Report (PDF)
        </button>
      </div>
    )
  }

  if (subReportId) {
    return (
      <div className="flex gap-2">
        <button
          onClick={() => download(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/export/openapi`, `openapi.json`)}
          className="px-3 py-1.5 border border-green-300 bg-green-50 rounded text-sm text-green-700 hover:bg-green-100"
        >
          ⬇ OpenAPI
        </button>
        <button
          onClick={() => download(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/export/postman`, `postman.json`)}
          className="px-3 py-1.5 border border-orange-300 bg-orange-50 rounded text-sm text-orange-700 hover:bg-orange-100"
        >
          ⬇ Postman
        </button>
        <button
          onClick={() => download(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/export/sdk?lang=js`, `sdk.js`)}
          className="px-3 py-1.5 border border-yellow-300 bg-yellow-50 rounded text-sm text-yellow-700 hover:bg-yellow-100"
        >
          ⬇ JS SDK
        </button>
        <button
          onClick={() => download(`/jar-analyser/reports/${reportId}/sub-reports/${subReportId}/export/sdk?lang=ts`, `sdk.ts`)}
          className="px-3 py-1.5 border border-blue-300 bg-blue-50 rounded text-sm text-blue-700 hover:bg-blue-100"
        >
          ⬇ TS SDK
        </button>
      </div>
    )
  }

  return (
    <div className="flex gap-2">
      <button
        onClick={() => download(`/jar-analyser/reports/${reportId}/export/openapi`, `openapi-combined.json`)}
        className="px-3 py-1.5 border border-green-300 bg-green-50 rounded text-sm text-green-700 hover:bg-green-100"
      >
        ⬇ OpenAPI (combined)
      </button>
      <button
        onClick={() => download(`/jar-analyser/reports/${reportId}/export/sdk?lang=js`, `platform-sdk.js`)}
        className="px-3 py-1.5 border border-yellow-300 bg-yellow-50 rounded text-sm text-yellow-700 hover:bg-yellow-100"
      >
        ⬇ JS SDK
      </button>
      <button
        onClick={() => download(`/jar-analyser/reports/${reportId}/export/sdk?lang=ts`, `platform-sdk.ts`)}
        className="px-3 py-1.5 border border-blue-300 bg-blue-50 rounded text-sm text-blue-700 hover:bg-blue-100"
      >
        ⬇ TS SDK
      </button>
      <button
        onClick={() => download(`/jar-analyser/reports/${reportId}/export/reference-doc`, `reference-doc-${reportId.slice(0, 8)}.md`)}
        className="px-3 py-1.5 border border-purple-300 bg-purple-50 rounded text-sm text-purple-700 hover:bg-purple-100"
      >
        ⬇ Reference Doc
      </button>
    </div>
  )
}
