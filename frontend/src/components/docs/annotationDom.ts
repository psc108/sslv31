// Pure DOM utilities for text-highlight annotations — Stage 4. Matches
// DocApp's own annotations.js approach: annotations are anchored against
// the *rendered* text (not the raw markdown source, which differs —
// `**bold**` renders as `bold`), using a text-index + prefix/suffix fuzzy
// match to re-locate a highlight after re-render, since there's no stable
// DOM position to persist across renders.

import type { DocAnnotation } from './types'

interface TextIndexEntry { node: Text; start: number; end: number }

export function buildTextIndex(container: Element): { fullText: string; entries: TextIndexEntry[] } {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  let fullText = ''
  const entries: TextIndexEntry[] = []
  let node: Node | null
  while ((node = walker.nextNode())) {
    const text = node as Text
    const start = fullText.length
    fullText += text.data
    entries.push({ node: text, start, end: fullText.length })
  }
  return { fullText, entries }
}

function offsetToPosition(entries: TextIndexEntry[], offset: number): { node: Text; offset: number } | null {
  for (const e of entries) {
    if (offset >= e.start && offset <= e.end) {
      return { node: e.node, offset: offset - e.start }
    }
  }
  return null
}

/** Derives {text, prefix, suffix} for a freshly-made selection, anchored
 * against the same flattened-text-index scheme used for re-locating
 * persisted annotations later — so create and re-anchor share one model. */
export function getSelectionAnchorInfo(container: Element, range: Range): { text: string; prefix: string; suffix: string } | null {
  const { fullText, entries } = buildTextIndex(container)
  let start = -1, end = -1
  for (const e of entries) {
    if (start === -1 && e.node === range.startContainer) start = e.start + range.startOffset
    if (e.node === range.endContainer) end = e.start + range.endOffset
  }
  if (start === -1 || end === -1 || end <= start) return null
  return {
    text: fullText.slice(start, end),
    prefix: fullText.slice(Math.max(0, start - 30), start),
    suffix: fullText.slice(end, end + 30),
  }
}

/** Re-locates a persisted annotation in freshly-rendered content. Only
 * `text` is required to find candidate occurrences; `prefix`/`suffix`
 * disambiguate when the text appears more than once — matches DocApp's
 * annotations.js findBestMatch(). Returns null if the text no longer
 * appears at all (known limitation, same as source: content that changed
 * enough loses the highlight rather than guessing). */
export function findAnnotationRange(container: Element, ann: Pick<DocAnnotation, 'text' | 'prefix' | 'suffix'>): Range | null {
  if (!ann.text) return null
  const { fullText, entries } = buildTextIndex(container)

  const occurrences: number[] = []
  let idx = fullText.indexOf(ann.text)
  while (idx !== -1) {
    occurrences.push(idx)
    idx = fullText.indexOf(ann.text, idx + 1)
  }
  if (occurrences.length === 0) return null

  let bestIdx = occurrences[0]!
  if (occurrences.length > 1) {
    let bestScore = -1
    for (const o of occurrences) {
      const actualPrefix = fullText.slice(Math.max(0, o - 30), o)
      const actualSuffix = fullText.slice(o + ann.text.length, o + ann.text.length + 30)
      let score = 0
      if (ann.prefix && actualPrefix.endsWith(ann.prefix)) score += 2
      else if (ann.prefix && ann.prefix.length >= 10 && actualPrefix.includes(ann.prefix.slice(-10))) score += 1
      if (ann.suffix && actualSuffix.startsWith(ann.suffix)) score += 2
      else if (ann.suffix && ann.suffix.length >= 10 && actualSuffix.includes(ann.suffix.slice(0, 10))) score += 1
      if (score > bestScore) { bestScore = score; bestIdx = o }
    }
  }

  const start = offsetToPosition(entries, bestIdx)
  const end = offsetToPosition(entries, bestIdx + ann.text.length)
  if (!start || !end) return null

  const range = document.createRange()
  range.setStart(start.node, start.offset)
  range.setEnd(end.node, end.offset)
  return range
}

/** Wraps every text node intersecting `range` in its own <mark> — a range
 * spanning multiple inline elements (e.g. highlighting across a **bold**
 * boundary) can't be wrapped by a single element without breaking the DOM
 * structure. Splits the start/end text nodes first so every node the
 * TreeWalker visits afterward is either fully inside or fully outside the
 * range — the standard correct technique for this, not the naive
 * single-surroundContents() approach which throws on partial-node ranges. */
export function wrapRangeInMarks(
  range: Range,
  className: string,
  onClick: (e: MouseEvent) => void,
  dataAttrs: Record<string, string>,
): HTMLElement[] {
  if (range.startContainer.nodeType === Node.TEXT_NODE) {
    const startNode = range.startContainer as Text
    if (range.startOffset > 0 && range.startOffset < startNode.data.length) {
      const after = startNode.splitText(range.startOffset)
      range.setStart(after, 0)
    }
  }
  if (range.endContainer.nodeType === Node.TEXT_NODE) {
    const endNode = range.endContainer as Text
    if (range.endOffset > 0 && range.endOffset < endNode.data.length) {
      endNode.splitText(range.endOffset)
      range.setEnd(endNode, endNode.data.length)
    }
  }

  const walker = document.createTreeWalker(range.commonAncestorContainer, NodeFilter.SHOW_TEXT)
  const nodesToWrap: Text[] = []
  let node: Node | null
  while ((node = walker.nextNode())) {
    if (range.intersectsNode(node) && (node as Text).data.length > 0) {
      nodesToWrap.push(node as Text)
    }
  }

  const marks: HTMLElement[] = []
  nodesToWrap.forEach(textNode => {
    const mark = document.createElement('mark')
    mark.className = className
    Object.entries(dataAttrs).forEach(([k, v]) => mark.setAttribute(`data-${k}`, v))
    mark.addEventListener('click', onClick)
    textNode.parentNode?.insertBefore(mark, textNode)
    mark.appendChild(textNode)
    marks.push(mark)
  })
  return marks
}

/** Undoes wrapRangeInMarks — unwraps every <mark data-annotation-id> back
 * into plain text and merges adjacent text nodes, so the next apply pass
 * starts from a clean slate rather than double-wrapping. */
export function clearAnnotationMarks(container: Element) {
  container.querySelectorAll('mark[data-annotation-id]').forEach(mark => {
    const parent = mark.parentNode
    if (!parent) return
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark)
    parent.removeChild(mark)
    parent.normalize()
  })
}
