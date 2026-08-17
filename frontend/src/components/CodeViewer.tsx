import { useEffect, useRef, useState } from 'react'
import { EditorView, lineNumbers, highlightActiveLine, keymap } from '@codemirror/view'
import { EditorState, Extension } from '@codemirror/state'
import { foldGutter, indentOnInput, syntaxHighlighting, defaultHighlightStyle, bracketMatching } from '@codemirror/language'
import { searchKeymap, highlightSelectionMatches, openSearchPanel } from '@codemirror/search'
import { defaultKeymap } from '@codemirror/commands'
import { oneDark } from '@codemirror/theme-one-dark'
import { yaml } from '@codemirror/lang-yaml'
import { json } from '@codemirror/lang-json'
import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { java } from '@codemirror/lang-java'

function getLanguageExtension(format: string): Extension[] {
  switch (format) {
    case 'yaml': return [yaml()]
    case 'json': return [json()]
    case 'python': return [python()]
    case 'shell': return [javascript()]
    case 'jinja2': return [yaml()]
    case 'java': return [java()]
    default: return []
  }
}

interface CodeViewerProps {
  content: string
  format: string
  readOnly?: boolean
  onChange?: (value: string) => void
  onSave?: () => void
}

export default function CodeViewer({ content, format, readOnly = true, onChange, onSave }: CodeViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const [wordWrap, setWordWrap] = useState(true)

  useEffect(() => {
    if (!containerRef.current) return

    const extensions: Extension[] = [
      lineNumbers(),
      foldGutter(),
      indentOnInput(),
      bracketMatching(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      oneDark,
      EditorState.readOnly.of(readOnly),
      keymap.of([...defaultKeymap, ...searchKeymap]),
      ...getLanguageExtension(format),
    ]

    if (wordWrap) {
      extensions.push(EditorView.lineWrapping)
    }

    if (!readOnly && onChange) {
      extensions.push(EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChange(update.state.doc.toString())
        }
      }))
    }

    if (!readOnly && onSave) {
      extensions.push(keymap.of([{ key: 'Mod-s', run: () => { onSave(); return true } }]))
    }

    const state = EditorState.create({ doc: content, extensions })

    if (viewRef.current) {
      viewRef.current.destroy()
    }

    viewRef.current = new EditorView({ state, parent: containerRef.current })

    return () => {
      viewRef.current?.destroy()
      viewRef.current = null
    }
  }, [content, format, wordWrap, readOnly])

  const handleSearch = () => {
    if (viewRef.current) {
      openSearchPanel(viewRef.current)
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 border-b border-gray-700">
        <button
          onClick={handleSearch}
          className="text-xs px-2 py-0.5 rounded bg-gray-700 text-gray-300 hover:bg-gray-600"
          title="Search (Ctrl+F)"
        >🔍 Search</button>
        <button
          onClick={() => setWordWrap(w => !w)}
          className={`text-xs px-2 py-0.5 rounded ${wordWrap ? 'bg-blue-700 text-blue-100' : 'bg-gray-700 text-gray-300'} hover:opacity-80`}
          title="Toggle word wrap"
        >↩ Wrap</button>
        {!readOnly && (
          <span className="text-xs text-yellow-400 ml-auto">● Editing</span>
        )}
      </div>
      <div ref={containerRef} className="flex-1 overflow-auto" />
    </div>
  )
}
