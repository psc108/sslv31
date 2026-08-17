import { useEffect, useId, useRef, useState } from 'react'
import mermaid from 'mermaid'

// Improvements Plan Stage 15 — mermaid diagrams in markdown. Initialized
// once at module load, not per-render — this is a global config call, not
// tied to any one diagram instance. securityLevel left at mermaid's own
// 'strict' default (sanitizes any HTML/links a diagram's labels contain)
// rather than 'loose' — diagram source is untrusted document content, same
// class of concern as the FTS5 search-snippet XSS fix elsewhere in Docs.
mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'strict' })

interface Props {
  source: string
}

export default function MermaidDiagram({ source }: Props) {
  // useId() gives a stable id across re-renders of the same diagram
  // instance without a module-level counter; mermaid needs a valid
  // CSS-selector id (no colons, which useId()'s default format includes).
  const baseId = useId().replace(/:/g, '')
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Guards against a stale async render landing after `source` has already
  // changed again (e.g. fast edits in the split-view preview) — only the
  // most recent render call for this instance is allowed to update state.
  const generationRef = useRef(0)

  useEffect(() => {
    const myGeneration = ++generationRef.current
    setSvg(null)
    setError(null)
    mermaid.render(`mermaid-${baseId}-${myGeneration}`, source)
      .then(({ svg: rendered }) => {
        if (myGeneration === generationRef.current) setSvg(rendered)
      })
      .catch((err: unknown) => {
        if (myGeneration === generationRef.current) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
  }, [source, baseId])

  if (error) {
    return (
      <div className="border border-red-200 bg-red-50 rounded-md p-3 my-3">
        <p className="text-red-700 font-medium text-xs mb-1.5">⚠ Couldn't render this diagram: {error}</p>
        <pre className="text-red-600 text-xs whitespace-pre-wrap font-mono">{source}</pre>
      </div>
    )
  }

  if (!svg) {
    return <div className="text-xs text-gray-400 my-3">Rendering diagram…</div>
  }

  // mermaid's own SVG output, sanitized per securityLevel above — same
  // "library-produced markup, not raw user text" trust boundary as
  // highlight.js's output elsewhere in this file.
  return <div className="my-3 flex justify-center overflow-x-auto" dangerouslySetInnerHTML={{ __html: svg }} />
}
