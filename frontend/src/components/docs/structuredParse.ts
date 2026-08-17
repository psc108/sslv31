// Stage 6 — heuristic markdown -> tier/card diagram schema. A close port of
// DocApp's structured-parse.js: H2 sections become colour-coded "tiers", H3
// subsections (or the H2's own body when it has none) become "cards" inside
// them, each card gets a keyword-guessed category badge, and any inline-code
// port-like tokens (`8080`, `443 tcp`) become port pills. Pure string→schema
// transform, no DOM/React here — StructuredView.tsx renders the result.

export type TierColor = 'blue' | 'green' | 'amber' | 'purple' | 'red' | 'orange' | 'indigo'

const TIER_COLORS: TierColor[] = ['blue', 'green', 'amber', 'purple', 'red', 'orange', 'indigo']

export interface CardPort { text: string; color: TierColor }
export interface CardBadge { text: string; color: TierColor }

export interface DiagramCard {
  id: string
  title: string
  badge: CardBadge
  body: string
  services?: string[]
  pills?: string[]
  ports?: CardPort[]
  footnote?: string
  wide?: boolean
}

export interface CardsNode { type: 'cards'; stretch: boolean; items: DiagramCard[] }
export interface TierNode { type: 'tier'; color: TierColor; label: string; children: CardsNode[] }
export interface ConnectorNode { type: 'connector' }
export type LayoutNode = TierNode | ConnectorNode

export interface DetailEntry {
  title: string
  sub: string
  rows: [string, string][]
  table?: { headers: string[]; rows: string[][] }
  cmds?: string
  note?: string
}

export interface FlowDef {
  name: string
  active: string[]
  dim: string[]
  label: string
}

export interface DiagramSchema {
  title: string
  layout: LayoutNode[]
  data: Record<string, DetailEntry>
  flows: Record<string, FlowDef>
}

interface RawH3 { heading: string; body: string[] }
interface RawH2 { heading: string; body: string[]; children: RawH3[] }
interface RawSections { title: string; children: RawH2[] }

export function markdownToSchema(src: string, categoryRules?: CategoryRule[]): DiagramSchema {
  const sections = splitBySections(src)

  const layout: LayoutNode[] = []
  sections.children.forEach((h2, idx) => {
    const color = TIER_COLORS[idx % TIER_COLORS.length]!
    layout.push(buildTier(h2, color, categoryRules))
    if (idx < sections.children.length - 1) layout.push({ type: 'connector' })
  })

  return {
    title: sections.title || 'Document',
    layout,
    data: buildDataIndex(sections),
    flows: buildFlows(sections),
  }
}

/** Counts every card that would actually render — used by callers to decide
 * whether a document has enough heading structure to be worth showing. */
export function countCards(schema: DiagramSchema): number {
  return schema.layout
    .filter((n): n is TierNode => n.type === 'tier')
    .reduce((sum, t) => sum + t.children.reduce((s, c) => s + c.items.length, 0), 0)
}

// ---------------------------------------------------------------------------
// Section splitting — H1 -> title, H2 -> tier, H3 -> card. Fenced code blocks
// are tracked so a '#' inside a code sample never counts as a heading.
// ---------------------------------------------------------------------------

function splitBySections(src: string): RawSections {
  const lines = src.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  let title = ''
  const root: RawSections = { children: [], title: '' }
  let currentH2: RawH2 | null = null
  let currentH3: RawH3 | null = null
  let inFence = false

  for (const line of lines) {
    if (/^(`{3,}|~{3,})/.test(line)) {
      inFence = !inFence
      appendLine(currentH3 || currentH2, line)
      continue
    }
    if (inFence) {
      appendLine(currentH3 || currentH2, line)
      continue
    }

    const h1 = line.match(/^#\s+(.+)/)
    if (h1) { title = stripMd(h1[1]!); continue }

    const h2 = line.match(/^##\s+(.+)/)
    if (h2) {
      currentH3 = null
      currentH2 = { heading: stripMd(h2[1]!), body: [], children: [] }
      root.children.push(currentH2)
      continue
    }

    const h3 = line.match(/^###\s+(.+)/)
    if (h3) {
      currentH3 = { heading: stripMd(h3[1]!), body: [] }
      if (!currentH2) {
        currentH2 = { heading: 'Overview', body: [], children: [] }
        root.children.push(currentH2)
      }
      currentH2.children.push(currentH3)
      continue
    }

    appendLine(currentH3 || currentH2, line)
  }

  root.title = title
  return root
}

function appendLine(target: RawH2 | RawH3 | null, line: string): void {
  target?.body.push(line)
}

// ---------------------------------------------------------------------------
// Tier / card building
// ---------------------------------------------------------------------------

function buildTier(h2: RawH2, color: TierColor, categoryRules?: CategoryRule[]): TierNode {
  const tier: TierNode = { type: 'tier', color, label: h2.heading, children: [] }
  const cards: DiagramCard[] = []

  if (h2.children.length === 0) {
    cards.push(makeCard(h2.heading, h2.body, color, 0, categoryRules))
  } else {
    const h2Content = classify(h2.body)
    if (h2Content.summary) cards.push(makeCard(h2.heading, h2.body, color, 0, categoryRules))
    h2.children.forEach((h3, idx) => cards.push(makeCard(h3.heading, h3.body, color, idx + 1, categoryRules)))
  }

  if (cards.length) tier.children.push({ type: 'cards', stretch: cards.length > 2, items: cards })
  return tier
}

function makeCard(heading: string, bodyLines: string[], tierColor: TierColor, idx: number, categoryRules?: CategoryRule[]): DiagramCard {
  const id = slugify(heading)
  const badgeColor = TIER_COLORS[(TIER_COLORS.indexOf(tierColor) + idx) % TIER_COLORS.length]!
  const c = classify(bodyLines)

  const card: DiagramCard = {
    id,
    title: heading,
    badge: { text: categorize(heading, categoryRules), color: badgeColor },
    body: buildCardBody(c),
  }

  if (c.tasks.length) {
    card.services = c.tasks.map(t => (t.checked ? '✓ ' : '○ ') + t.text)
  } else if (c.bullets.length) {
    card.services = c.bullets.slice(0, 8)
  }

  if (c.table) {
    card.pills = c.table.rows.slice(0, 5).map(r => truncate(r.join(' · '), 60))
  }

  if (c.codeBlocks.length && !card.body) {
    card.body = c.codeBlocks[0]!.split('\n').slice(0, 3).map(l => l.substring(0, 60)).join('\n')
  }

  const ports = extractPorts(bodyLines)
  if (ports.length) card.ports = ports

  if (c.bullets.length > 2 || c.tasks.length > 2) card.wide = true

  if (c.callout) card.footnote = '⚠ ' + c.callout

  return card
}

function buildCardBody(c: Classified): string {
  if (c.summary) return truncate(c.summary, 200)
  if (c.bullets.length) return c.bullets.slice(0, 3).join(' · ')
  if (c.tasks.length) {
    const done = c.tasks.filter(t => t.checked).length
    return `${done}/${c.tasks.length} complete`
  }
  if (c.table) return `${c.table.rows.length} rows · ${c.table.headers.join(', ')}`
  if (c.codeBlocks.length) return c.codeBlocks[0]!.split('\n').slice(0, 2).join('\n')
  return ''
}

// ---------------------------------------------------------------------------
// Content classification — turns a section's raw body lines into the shapes
// a card can render (a short summary paragraph, a bullet/task list, a table,
// a code sample, or a callout note).
// ---------------------------------------------------------------------------

interface Classified {
  summary: string
  codeBlocks: string[]
  bullets: string[]
  tasks: { checked: boolean; text: string }[]
  table: { headers: string[]; rows: string[][] } | null
  callout: string | null
}

function classify(bodyLines: string[] | undefined): Classified {
  const lines = bodyLines || []
  let summary = ''
  const codeBlocks: string[] = []
  const bullets: string[] = []
  const tasks: { checked: boolean; text: string }[] = []
  let table: { headers: string[]; rows: string[][] } | null = null
  let callout: string | null = null
  let inFence = false
  let fenceLines: string[] = []

  for (const line of lines) {
    if (/^(`{3,}|~{3,})/.test(line)) {
      if (inFence) { codeBlocks.push(fenceLines.join('\n')); fenceLines = [] }
      inFence = !inFence
      continue
    }
    if (inFence) { fenceLines.push(line); continue }

    const taskMatch = line.match(/^\s*[-*+]\s+\[([ xX])\]\s+(.*)/)
    if (taskMatch) {
      tasks.push({ checked: taskMatch[1] !== ' ', text: stripMd(taskMatch[2]!) })
      continue
    }

    const bulletMatch = line.match(/^\s*[-*+]\s+(.*)/)
    if (bulletMatch) { bullets.push(stripMd(bulletMatch[1]!)); continue }

    const orderedMatch = line.match(/^\s*\d+\.\s+(.*)/)
    if (orderedMatch) { bullets.push(stripMd(orderedMatch[1]!)); continue }

    if (line.startsWith('>')) {
      const stripped = line.replace(/^>\s?/, '')
      const calloutMatch = stripped.match(/^\[!(NOTE|WARNING|TIP|DANGER|IMPORTANT|CAUTION)\]/i)
      if (calloutMatch) { callout = calloutMatch[1]!; continue }
      const text = stripMd(stripped).trim()
      if (text) summary += (summary ? '\n' : '') + text
      continue
    }

    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      if (!table) table = { headers: [], rows: [] }
      const cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim())
      if (/^[\s:-]+$/.test(cells.join(''))) continue
      if (!table.headers.length) table.headers = cells
      else table.rows.push(cells)
      continue
    }

    if (line.trim() && !line.match(/^---+$/) && !line.match(/^\*\*\*+$/) && !line.match(/^___+$/)) {
      const clean = stripMd(line).trim()
      if (clean) summary += (summary ? '\n' : '') + clean
    }
  }

  return { summary, codeBlocks, table, bullets, callout, tasks }
}

// ---------------------------------------------------------------------------
// Detail data — full content behind each card's click-through panel.
// ---------------------------------------------------------------------------

function buildDataIndex(sections: RawSections): Record<string, DetailEntry> {
  const data: Record<string, DetailEntry> = {}
  for (const h2 of sections.children) {
    const h2c = classify(h2.body)
    if (h2.children.length === 0 || h2c.summary) {
      data[slugify(h2.heading)] = buildDetail(h2.heading, h2.body, '')
    }
    for (const h3 of h2.children) {
      data[slugify(h3.heading)] = buildDetail(h3.heading, h3.body, h2.heading)
    }
  }
  return data
}

function buildDetail(heading: string, bodyLines: string[], parentHeading: string): DetailEntry {
  const c = classify(bodyLines)
  const entry: DetailEntry = { title: heading, sub: parentHeading, rows: [] }

  if (c.summary) c.summary.split('\n').filter(Boolean).forEach(s => entry.rows.push(['', s]))

  if (c.bullets.length) {
    c.bullets.forEach(b => {
      const kv = b.match(/^([^:–—]+)[:\s–—]+(.+)/)
      if (kv) entry.rows.push([kv[1]!.trim(), kv[2]!.trim()])
      else entry.rows.push(['•', b])
    })
  }

  if (c.tasks.length) c.tasks.forEach(t => entry.rows.push([t.checked ? '✓' : '○', t.text]))

  if (c.table) entry.table = { headers: c.table.headers, rows: c.table.rows }

  if (c.codeBlocks.length) entry.cmds = c.codeBlocks.join('\n\n')

  if (c.callout) entry.note = c.callout

  return entry
}

// ---------------------------------------------------------------------------
// Flow generation — one "flow" per H2, listing which card ids belong to it
// (for the "Highlight section" toolbar in StructuredView).
// ---------------------------------------------------------------------------

function buildFlows(sections: RawSections): Record<string, FlowDef> {
  if (sections.children.length < 2) return {}
  const flows: Record<string, FlowDef> = {}

  const allIds = sections.children.flatMap(h2 => {
    const ids = h2.children.map(c => slugify(c.heading))
    const sc = classify(h2.body)
    if (!ids.length || sc.summary) ids.unshift(slugify(h2.heading))
    return ids
  })

  sections.children.forEach(h2 => {
    const ids = h2.children.map(h3 => slugify(h3.heading))
    const h2c = classify(h2.body)
    if (!ids.length || h2c.summary) ids.unshift(slugify(h2.heading))
    const dim = allIds.filter(id => !ids.includes(id))
    flows[slugify(h2.heading)] = { name: h2.heading, active: ids, dim, label: h2.heading }
  })

  return flows
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function extractPorts(bodyLines: string[] | undefined): CardPort[] {
  const ports: CardPort[] = []
  const re = /`:?(\d{2,5}(?:[–-]\d{2,5})?(?:\s+\w+)?)`/g
  const text = (bodyLines || []).join('\n')
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    ports.push({ text: ':' + m[1]!.replace(/^:/, ''), color: 'blue' })
  }
  return ports.slice(0, 6)
}

export interface CategoryRule {
  id: string
  pattern: string
  label: string
  sort_order: number
  created_by: string | null
  created_at: string
}

// Improvements Plan Stage 13 — this used to be the *only* mapping, a fixed
// hardcoded array. It's now also the seed data for the category_rules table
// (see migration 080), so out-of-the-box behaviour is unchanged; this array
// only still matters as the fallback used before the real rules have loaded
// from the API (or if that fetch fails), and for anything (like a unit test)
// that calls categorize()/markdownToSchema() without fetching rules at all.
export const DEFAULT_CATEGORY_RULES: [RegExp, string][] = [
  [/database|rds|sql|dynamo|data/, 'Data'],
  [/cache|redis|elastic/, 'Cache'],
  [/queue|sqs|rabbit|kafka|message/, 'Queue'],
  [/api|gateway|endpoint|route/, 'API'],
  [/auth|identity|iam|cognito|keystone/, 'Auth'],
  [/monitor|alarm|cloud\s?watch|log/, 'Monitor'],
  [/storage|s3|efs|bucket|file/, 'Storage'],
  [/network|vpc|subnet|dns|route/, 'Network'],
  [/deploy|ci|cd|pipeline|build/, 'Deploy'],
  [/security|encrypt|kms|secret|tls|ssl/, 'Security'],
  [/server|ec2|instance|compute|lambda|container/, 'Compute'],
  [/frontend|ui|web|nginx|react/, 'Frontend'],
  [/backend|service|micro/, 'Backend'],
  [/test|qa|check/, 'Test'],
  [/config|setting|param/, 'Config'],
  [/keyboard|shortcut|key/, 'Keys'],
  [/feature|overview|intro|start|getting/, 'Overview'],
  [/table|list|item/, 'List'],
  [/code|block|syntax|example/, 'Code'],
  [/callout|note|warning|tip|alert/, 'Info'],
  [/quote|blockquote|cite/, 'Quote'],
  [/task|todo|checklist/, 'Tasks'],
  [/arch|design|pattern|struct/, 'Arch'],
  [/render|display|view|format/, 'Render'],
  [/search|find|filter|query/, 'Search'],
  [/add|new|creat|extend|plugin/, 'Extend'],
]

function categorize(heading: string, rules?: CategoryRule[]): string {
  const h = heading.toLowerCase()
  if (rules && rules.length > 0) {
    for (const r of rules) {
      // A rule's pattern is validated server-side at write time (a bad
      // regex is rejected with a 422 before it ever reaches the DB), but
      // stay defensive here anyway rather than letting one bad row break
      // every Structured View render for every doc.
      try {
        if (new RegExp(r.pattern, 'i').test(h)) return r.label
      } catch { /* skip an unparseable pattern, keep checking the rest */ }
    }
    return 'Section'
  }
  for (const [re, label] of DEFAULT_CATEGORY_RULES) if (re.test(h)) return label
  return 'Section'
}

function stripMd(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[`*_~#]/g, '')
    .trim()
}

function truncate(str: string, max: number): string {
  if (str.length <= max) return str
  return str.slice(0, max) + '…'
}

function slugify(text: string): string {
  return text.toLowerCase()
    .replace(/[`*_~[\]()#]/g, '')
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
}
