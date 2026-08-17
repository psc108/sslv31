import { isValidElement } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import rehypeSlug from 'rehype-slug'
import 'highlight.js/styles/github.css'
import MermaidDiagram from './MermaidDiagram'

// [[Doc Name]] or [[Doc Name|Display Text]] -> a normal markdown link using
// a custom scheme, intercepted by the `a` component override below rather
// than actually navigating the browser. Shared between DocReader and the
// editor's split-view preview (Stage 3) so both render identically.
const WIKILINK_RE = /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g

export function preprocessWikiLinks(text: string): string {
  return text.replace(WIKILINK_RE, (_match, target: string, label?: string) => {
    const display = (label || target).trim()
    const href = `wikilink://${encodeURIComponent(target.trim())}`
    return `[${display}](${href})`
  })
}

// GFM blockquote callouts (> [!NOTE] ...). Handled as plain text
// substitution before parsing (turns the marker line into a bold label)
// rather than AST manipulation — avoids rehype-raw / dangerouslySetInnerHTML
// entirely, so there's no HTML-injection surface from document content.
const CALLOUT_LABELS: Record<string, string> = {
  NOTE: 'ℹ️ Note', TIP: '💡 Tip', WARNING: '⚠️ Warning',
  IMPORTANT: '❗ Important', CAUTION: '🔶 Caution', DANGER: '🚨 Danger',
}

export function preprocessCallouts(text: string): string {
  return text.replace(/^> ?\[!(\w+)\]\s*$/gim, (match, type: string) => {
    const label = CALLOUT_LABELS[type.toUpperCase()]
    return label ? `> **${label}**` : match
  })
}

// Fenced code blocks must never go through wikilink/callout text
// substitution — mermaid's own `[[Subroutine]]` node-shape syntax
// (Improvements Plan Stage 15) is otherwise indistinguishable, at the
// plain-text level this preprocessing operates on, from a real
// `[[Doc Name]]` wiki-link, and substituting inside it would corrupt the
// diagram before mermaid ever sees it. General fix, not mermaid-specific —
// any fenced example content containing literal `[[...]]` or a line
// starting `> [!` had the same latent risk before this.
const FENCE_RE = /(^|\n)([ \t]*(?:```|~~~)[^\n]*\n[\s\S]*?\n[ \t]*(?:```|~~~)[ \t]*(?=\n|$))/g

function transformOutsideCodeFences(text: string, transform: (segment: string) => string): string {
  let result = ''
  let lastIndex = 0
  FENCE_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = FENCE_RE.exec(text)) !== null) {
    const fenceStart = m.index + m[1]!.length
    result += transform(text.slice(lastIndex, fenceStart))
    result += m[2]!
    lastIndex = fenceStart + m[2]!.length
  }
  result += transform(text.slice(lastIndex))
  return result
}

export function preprocessMarkdown(text: string): string {
  return transformOutsideCodeFences(text, segment => preprocessWikiLinks(preprocessCallouts(segment)))
}

interface Props {
  content: string
  onNavigateToDoc: (name: string) => void
  className?: string
}

// Footnotes ([^1] references / [^1]: definitions) need no extra plugin or
// component override at all — remark-gfm already parses GFM footnote
// syntax into real footnoteReference/footnoteDefinition AST nodes (verified
// directly against remark-gfm's own output before writing this comment,
// since the plan that named this stage assumed otherwise), and
// remark-rehype converts those into a standard <sup>/backlink structure
// that Tailwind Typography's `prose` class already styles sensibly.
// Improvements Plan Stage 15's only real remaining gap was Mermaid diagrams.

export default function MarkdownPreview({ content, onNavigateToDoc, className }: Props) {
  return (
    <div className={className ?? 'prose prose-sm max-w-none'}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSlug, rehypeHighlight]}
        components={{
          a: ({ href, children, ...props }) => {
            if (href?.startsWith('wikilink://')) {
              const target = decodeURIComponent(href.replace('wikilink://', ''))
              return (
                <button
                  onClick={() => onNavigateToDoc(target)}
                  className="text-blue-600 underline decoration-dotted hover:decoration-solid"
                >
                  {children}
                </button>
              )
            }
            return <a href={href} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
          },
          blockquote: ({ children, ...props }) => (
            <blockquote className="border-l-4 border-gray-300 bg-gray-50 pl-4 py-1 my-3" {...props}>
              {children}
            </blockquote>
          ),
          // Mermaid (Improvements Plan Stage 15) — a ```mermaid fenced block
          // gets a "language-mermaid" class from rehype-highlight, same as
          // any other fenced language; highlight.js doesn't recognise
          // "mermaid" as a real language though, so it leaves the code
          // block's content as a single plain-text child instead of
          // splitting it into highlighted spans (confirmed directly against
          // rehype-highlight's own output before writing this) — that's
          // what makes String(children) a safe way to recover the raw
          // diagram source here.
          code: ({ className: codeClassName, children, ...props }) => {
            if (codeClassName?.includes('language-mermaid')) {
              return <MermaidDiagram source={String(children).replace(/\n$/, '')} />
            }
            return <code className={codeClassName} {...props}>{children}</code>
          },
          // A rendered diagram shouldn't sit inside a code-block-styled
          // <pre> (monospace background/border/scroll) — unwrap it for
          // exactly that one case, leave every other fenced/inline code
          // block's <pre> wrapper untouched.
          pre: ({ children, ...props }) => {
            if (isValidElement(children) && children.type === MermaidDiagram) {
              return <>{children}</>
            }
            return <pre {...props}>{children}</pre>
          },
        }}
      >
        {preprocessMarkdown(content)}
      </ReactMarkdown>
    </div>
  )
}
