import { useEffect, useRef, useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { EditorView, lineNumbers, highlightActiveLine, keymap } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { foldGutter, indentOnInput, syntaxHighlighting, defaultHighlightStyle, bracketMatching } from '@codemirror/language'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { searchKeymap, highlightSelectionMatches, openSearchPanel } from '@codemirror/search'
import { defaultKeymap, history, historyKeymap, undo, redo, indentWithTab } from '@codemirror/commands'
import { markdown } from '@codemirror/lang-markdown'
import api from '@/lib/api'
import MarkdownPreview from './MarkdownPreview'
import EditorMinimap from './EditorMinimap'
import type { DocFull } from './types'

interface Props {
  docId: string
  docName: string
  onSaved: (newDocId: string) => void
  onCancel: () => void
}

// Wraps (or, if nothing is selected, inserts placeholder + wraps) the
// current selection with the given prefix/suffix — the shared primitive
// behind the Bold/Italic/Code toolbar buttons.
function wrapSelection(view: EditorView, prefix: string, suffix: string, placeholder = '') {
  const { from, to } = view.state.selection.main
  const selected = view.state.sliceDoc(from, to) || placeholder
  view.dispatch({
    changes: { from, to, insert: `${prefix}${selected}${suffix}` },
    selection: { anchor: from + prefix.length, head: from + prefix.length + selected.length },
  })
  view.focus()
}

// Prefixes each selected line — the shared primitive behind Heading/List.
function prefixLines(view: EditorView, prefix: string) {
  const { from, to } = view.state.selection.main
  const startLine = view.state.doc.lineAt(from)
  const endLine = view.state.doc.lineAt(to)
  const changes = []
  for (let n = startLine.number; n <= endLine.number; n++) {
    const line = view.state.doc.line(n)
    changes.push({ from: line.from, insert: prefix })
  }
  view.dispatch({ changes })
  view.focus()
}

function insertAtCursor(view: EditorView, text: string) {
  const { from } = view.state.selection.main
  view.dispatch({ changes: { from, insert: text }, selection: { anchor: from + text.length } })
  view.focus()
}

export default function DocEditor({ docId, docName, onSaved, onCancel }: Props) {
  const editorContainerRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<EditorView | null>(null)
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [splitView, setSplitView] = useState(false)
  const [visibleLines, setVisibleLines] = useState({ start: 1, end: 30 })

  const { data: doc, isLoading } = useQuery<DocFull>({
    queryKey: ['doc', docId],
    queryFn: () => api.get(`/docs/${docId}`).then(r => r.data),
  })

  const handleSave = useCallback(async () => {
    if (!viewRef.current) return
    setSaving(true)
    setError('')
    try {
      const res = await api.post(`/docs/${docId}/save`, { content: viewRef.current.state.doc.toString() })
      setDirty(false)
      onSaved(res.data.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }, [docId, onSaved])

  // Initialise CodeMirror once the doc has loaded.
  useEffect(() => {
    if (!doc || !editorContainerRef.current) return

    const updateVisibleLines = (view: EditorView) => {
      const { from, to } = view.viewport
      setVisibleLines({
        start: view.state.doc.lineAt(from).number,
        end: view.state.doc.lineAt(to).number,
      })
    }

    const state = EditorState.create({
      doc: doc.content,
      extensions: [
        lineNumbers(),
        foldGutter(),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        history(),
        markdown(),
        EditorView.lineWrapping,
        keymap.of([
          ...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap,
          indentWithTab,
          { key: 'Mod-s', run: () => { handleSave(); return true } },
        ]),
        EditorView.updateListener.of(update => {
          if (update.docChanged) {
            setContent(update.state.doc.toString())
            setDirty(true)
          }
          if (update.docChanged || update.viewportChanged) {
            updateVisibleLines(update.view)
          }
        }),
      ],
    })

    if (viewRef.current) viewRef.current.destroy()
    viewRef.current = new EditorView({ state, parent: editorContainerRef.current })
    setContent(doc.content)
    updateVisibleLines(viewRef.current)

    return () => {
      viewRef.current?.destroy()
      viewRef.current = null
    }
    // Only re-init when switching to a different document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id])

  // Autosave every 30s if dirty — matches DocApp's own editor.js behaviour.
  useEffect(() => {
    const interval = setInterval(() => {
      if (dirty && !saving) handleSave()
    }, 30000)
    return () => clearInterval(interval)
  }, [dirty, saving, handleSave])

  // Warn on navigating away with unsaved changes.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty) { e.preventDefault() }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const scrollToLine = (line: number) => {
    const view = viewRef.current
    if (!view) return
    const pos = view.state.doc.line(Math.min(line, view.state.doc.lines)).from
    view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
    view.focus()
  }

  if (isLoading || !doc) {
    return <div className="text-sm text-gray-400 py-8 text-center">Loading...</div>
  }

  const view = viewRef.current

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">
          Editing: {docName}
          {dirty && <span className="text-sm text-yellow-600 font-normal ml-2">● Unsaved changes</span>}
        </h1>
        <div className="flex items-center gap-2">
          <button onClick={onCancel}
            className="px-3 py-1.5 border border-gray-300 text-gray-600 text-sm rounded-md hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving || !dirty}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-1 p-1.5 bg-gray-50 border border-gray-200 rounded-md flex-wrap">
        {view && (
          <>
            <button onClick={() => wrapSelection(view, '**', '**', 'bold text')} title="Bold"
              className="px-2 py-1 text-sm font-bold rounded hover:bg-gray-200">B</button>
            <button onClick={() => wrapSelection(view, '*', '*', 'italic text')} title="Italic"
              className="px-2 py-1 text-sm italic rounded hover:bg-gray-200">I</button>
            <button onClick={() => prefixLines(view, '## ')} title="Heading"
              className="px-2 py-1 text-sm font-semibold rounded hover:bg-gray-200">H</button>
            <button onClick={() => wrapSelection(view, '[', '](url)', 'link text')} title="Link"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">🔗</button>
            <button onClick={() => prefixLines(view, '- ')} title="Bulleted list"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">• List</button>
            <button onClick={() => wrapSelection(view, '`', '`', 'code')} title="Inline code"
              className="px-2 py-1 text-sm font-mono rounded hover:bg-gray-200">{'</>'}</button>
            <button onClick={() => wrapSelection(view, '```\n', '\n```', 'code block')} title="Code block"
              className="px-2 py-1 text-xs font-mono rounded hover:bg-gray-200">{'{ }'}</button>
            <button onClick={() => insertAtCursor(view, '\n| Col 1 | Col 2 |\n|---|---|\n| a | b |\n')} title="Table"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">▦ Table</button>
            <span className="w-px h-5 bg-gray-300 mx-1" />
            <button onClick={() => undo(view)} title="Undo"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">↺</button>
            <button onClick={() => redo(view)} title="Redo"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">↻</button>
            <button onClick={() => openSearchPanel(view)} title="Find & replace (Ctrl+F)"
              className="px-2 py-1 text-sm rounded hover:bg-gray-200">🔍</button>
          </>
        )}
        <button onClick={() => setSplitView(v => !v)}
          className={`ml-auto px-2 py-1 text-sm rounded ${splitView ? 'bg-blue-100 text-blue-700' : 'hover:bg-gray-200'}`}>
          ⬛ Split
        </button>
      </div>

      <div className="flex bg-white rounded-lg border border-gray-200 overflow-hidden" style={{ height: '600px' }}>
        <div ref={editorContainerRef} className={splitView ? 'w-1/2 overflow-auto' : 'flex-1 overflow-auto'} />
        {splitView && (
          <div className="w-1/2 overflow-auto border-l border-gray-200 p-4">
            <MarkdownPreview content={content} onNavigateToDoc={() => {}} />
          </div>
        )}
        <EditorMinimap
          content={content}
          visibleStartLine={visibleLines.start}
          visibleEndLine={visibleLines.end}
          onScrollToLine={scrollToLine}
        />
      </div>

      <p className="text-xs text-gray-400">
        Ctrl/Cmd+S to save · Ctrl/Cmd+F to search · autosaves every 30s while there are unsaved changes
      </p>
    </div>
  )
}
