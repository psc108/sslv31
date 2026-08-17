import { useEffect, useRef } from 'react'

interface Props {
  content: string
  visibleStartLine: number
  visibleEndLine: number
  onScrollToLine: (line: number) => void
}

// A scaled-down document overview, like a code editor minimap — genuinely
// custom (CodeMirror has no built-in equivalent), matching DocApp's own
// editor-minimap.js heuristic: 2px-tall colored bars per line, colour keyed
// by line content, plus a draggable/clickable viewport indicator.
const COLORS = {
  heading: '#3b82f6', // blue
  code: '#22c55e',    // green
  bullet: '#f59e0b',  // amber
  table: '#a855f7',   // purple
  body: '#e5e7eb',    // faint gray
}

function lineColor(line: string, inFence: { value: boolean }): string {
  if (/^```/.test(line.trim())) {
    inFence.value = !inFence.value
    return COLORS.code
  }
  if (inFence.value) return COLORS.code
  if (/^#{1,6}\s/.test(line)) return COLORS.heading
  if (/^\s*[-*+]\s|^\s*\d+\.\s/.test(line)) return COLORS.bullet
  if (/\|/.test(line)) return COLORS.table
  return COLORS.body
}

export default function EditorMinimap({ content, visibleStartLine, visibleEndLine, onScrollToLine }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const lines = content.split('\n')

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const width = canvas.width
    const height = canvas.height
    ctx.clearRect(0, 0, width, height)

    const lineHeight = Math.max(1, height / Math.max(1, lines.length))
    const inFence = { value: false }
    lines.forEach((line, i) => {
      ctx.fillStyle = lineColor(line, inFence)
      ctx.fillRect(2, i * lineHeight, width - 4, Math.max(1, lineHeight - 0.5))
    })

    // Viewport indicator
    const total = Math.max(1, lines.length)
    const top = (visibleStartLine / total) * height
    const bottom = (visibleEndLine / total) * height
    ctx.fillStyle = 'rgba(59, 130, 246, 0.15)'
    ctx.fillRect(0, top, width, Math.max(2, bottom - top))
    ctx.strokeStyle = 'rgba(59, 130, 246, 0.6)'
    ctx.strokeRect(0.5, top, width - 1, Math.max(2, bottom - top))
  }, [content, visibleStartLine, visibleEndLine])

  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const ratio = (e.clientY - rect.top) / rect.height
    const line = Math.max(1, Math.min(lines.length, Math.round(ratio * lines.length)))
    onScrollToLine(line)
  }

  return (
    <canvas
      ref={canvasRef}
      width={40}
      height={600}
      onClick={handleClick}
      className="w-10 h-full border-l border-gray-200 cursor-pointer bg-white"
      title="Document minimap — click to jump"
    />
  )
}
