import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { findAnnotationRange, wrapRangeInMarks, clearAnnotationMarks, getSelectionAnchorInfo } from './annotationDom'
import type { DocAnnotation } from './types'

interface Props {
  docId: string
  containerRef: React.RefObject<HTMLDivElement>
  content: string
  // Re-anchoring can fail — content edited enough that a saved highlight's
  // text no longer appears at all — in which case that annotation is
  // silently skipped below. Reported up rather than rendered here: this
  // component's own output lands inside containerRef's DOM subtree, which
  // findAnnotationRange's text-node walk scans, so a plain-text notice here
  // risks polluting the very matching it's reporting on. DocReader renders
  // the actual notice outside that subtree.
  onUnanchoredChange?: (count: number) => void
}

// Matches DocApp's own annotations.js palette exactly.
const COLORS: { name: string; bg: string }[] = [
  { name: 'yellow', bg: '#fef08a' },
  { name: 'green', bg: '#bbf7d0' },
  { name: 'blue', bg: '#bfdbfe' },
  { name: 'pink', bg: '#fbcfe8' },
  { name: 'orange', bg: '#fed7aa' },
]

export default function AnnotationLayer({ docId, containerRef, content, onUnanchoredChange }: Props) {
  const { isOperator, isAdmin } = useAuth()
  const queryClient = useQueryClient()
  const [selectionPopup, setSelectionPopup] = useState<{ x: number; y: number; range: Range } | null>(null)
  const [editPopover, setEditPopover] = useState<{ x: number; y: number; annotation: DocAnnotation } | null>(null)
  const [noteDraft, setNoteDraft] = useState('')

  const { data: annotations } = useQuery<DocAnnotation[]>({
    queryKey: ['doc-annotations', docId],
    queryFn: () => api.get(`/docs/${docId}/annotations`).then(r => r.data),
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['doc-annotations', docId] })

  const openEditPopover = (ann: DocAnnotation, mark: HTMLElement) => {
    const rect = mark.getBoundingClientRect()
    setNoteDraft(ann.note || '')
    setEditPopover({ x: rect.left, y: rect.bottom + 4, annotation: ann })
  }

  // Re-apply highlights every time the rendered content or the annotation
  // list changes — matches DocApp's own re-apply-on-render approach rather
  // than trying to preserve DOM marks across a re-render (React owns this
  // subtree; a fresh clear-then-reapply pass is simpler and correct).
  useEffect(() => {
    const container = containerRef.current
    if (!container || !annotations) return
    clearAnnotationMarks(container)

    let unanchored = 0
    annotations.forEach(ann => {
      const range = findAnnotationRange(container, ann)
      if (!range) { unanchored++; return } // content changed enough that this one can't be re-anchored
      const colorHex = COLORS.find(c => c.name === ann.color)?.bg ?? COLORS[0]!.bg
      const marks = wrapRangeInMarks(range, 'doc-annotation-mark', (e) => {
        e.stopPropagation()
        if (isOperator) openEditPopover(ann, e.currentTarget as HTMLElement)
      }, { 'annotation-id': ann.id })
      marks.forEach(mark => {
        mark.style.backgroundColor = colorHex
        mark.style.cursor = isOperator ? 'pointer' : 'default'
        mark.style.borderRadius = '2px'
        if (ann.note) mark.title = ann.note
      })
    })
    onUnanchoredChange?.(unanchored)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, annotations, containerRef, isOperator])

  // Selection -> colour-picker popup. View-only roles can see existing
  // highlights (via hover title above) but can't create new ones.
  useEffect(() => {
    const container = containerRef.current
    if (!container || !isOperator) return
    const onMouseUp = () => {
      const sel = window.getSelection()
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) return
      const range = sel.getRangeAt(0)
      if (!container.contains(range.commonAncestorContainer)) return
      const rect = range.getBoundingClientRect()
      if (rect.width === 0 && rect.height === 0) return
      setSelectionPopup({ x: rect.left + rect.width / 2, y: rect.top - 8, range: range.cloneRange() })
    }
    container.addEventListener('mouseup', onMouseUp)
    return () => container.removeEventListener('mouseup', onMouseUp)
  }, [containerRef, isOperator])

  // Dismiss popups when starting a new interaction elsewhere. mousedown
  // (not click) so it fires before a *new* selection's own mouseup opens
  // its popup — otherwise this would immediately close what it just opened.
  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (target.closest('.doc-annotation-popup') || target.closest('.doc-annotation-popover')) return
      setSelectionPopup(null)
      setEditPopover(null)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  const createAnnotation = async (color: string) => {
    const container = containerRef.current
    const popup = selectionPopup
    setSelectionPopup(null)
    window.getSelection()?.removeAllRanges()
    if (!container || !popup) return
    const info = getSelectionAnchorInfo(container, popup.range)
    if (!info || !info.text.trim()) return
    await api.post(`/docs/${docId}/annotations`, { text: info.text, color, prefix: info.prefix, suffix: info.suffix })
    await invalidate()
  }

  const saveNote = async () => {
    if (!editPopover) return
    await api.patch(`/docs/annotations/${editPopover.annotation.id}`, { note: noteDraft })
    setEditPopover(null)
    await invalidate()
  }

  const changeColor = async (color: string) => {
    if (!editPopover) return
    await api.patch(`/docs/annotations/${editPopover.annotation.id}`, { color })
    setEditPopover(null)
    await invalidate()
  }

  const deleteAnnotation = async () => {
    if (!editPopover) return
    await api.delete(`/docs/annotations/${editPopover.annotation.id}`)
    setEditPopover(null)
    await invalidate()
  }

  return (
    <>
      {selectionPopup && (
        <div
          className="doc-annotation-popup fixed z-50 flex gap-1 bg-white border border-gray-200 rounded-full shadow-lg px-2 py-1.5 -translate-x-1/2 -translate-y-full"
          style={{ left: selectionPopup.x, top: selectionPopup.y }}
        >
          {COLORS.map(c => (
            <button key={c.name} onClick={() => createAnnotation(c.name)}
              className="w-5 h-5 rounded-full border border-gray-300 hover:scale-110 transition-transform"
              style={{ backgroundColor: c.bg }} title={`Highlight ${c.name}`} />
          ))}
        </div>
      )}

      {editPopover && (
        <div
          className="doc-annotation-popover fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg p-3 w-64"
          style={{ left: editPopover.x, top: editPopover.y }}
        >
          <div className="flex gap-1 mb-2">
            {COLORS.map(c => (
              <button key={c.name} onClick={() => changeColor(c.name)}
                className="w-5 h-5 rounded-full transition-all"
                style={{
                  backgroundColor: c.bg,
                  border: editPopover.annotation.color === c.name ? '2px solid #374151' : '2px solid #d1d5db',
                }} />
            ))}
          </div>
          <textarea
            value={noteDraft} onChange={e => setNoteDraft(e.target.value)}
            placeholder="Add a note…" rows={3}
            className="w-full border border-gray-300 rounded-md px-2 py-1 text-xs mb-2"
          />
          <div className="flex justify-between items-center">
            {isAdmin ? (
              <button onClick={deleteAnnotation} className="text-xs text-red-600 hover:underline">Delete</button>
            ) : <span />}
            <div className="flex gap-3">
              <button onClick={() => setEditPopover(null)} className="text-xs text-gray-500 hover:underline">Close</button>
              <button onClick={saveNote} className="text-xs text-blue-600 font-medium hover:underline">Save</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
