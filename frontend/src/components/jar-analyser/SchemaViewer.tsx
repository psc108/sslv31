import { useState } from 'react'

export interface DtoField {
  name: string
  json_name: string
  java_type: string
  simple_type: string
  openapi_type: string
  openapi_format: string | null
  required: boolean
  nullable: boolean
  constraints: string[]
  is_collection: boolean
  collection_element_type: string | null
  is_map: boolean
  json_ignored: boolean
  is_enum_type: boolean
  /** Developer-authored, from @Schema(description=...) on the field — not inferred by this tool. */
  description?: string | null
}

export interface DtoSchema {
  id: string
  class_name: string
  simple_name: string
  is_enum: boolean
  is_lombok: boolean
  source_note: string | null
  enum_values: { name: string; serialised_as: string; display?: string }[]
  fields: DtoField[]
  /** Developer-authored, from @Schema(description=...) — not inferred by this tool. */
  description?: string | null
}

interface Props {
  schema: DtoSchema
  /** If true, renders inline without a card wrapper */
  inline?: boolean
  /** Map of simple_name -> enum_values for inline enum pills on DTO fields */
  enumLookup?: Record<string, { name: string; serialised_as: string }[]>
}

function parseConstraints(constraints: string[]): Record<string, string> {
  const result: Record<string, string> = {}
  for (const s of constraints) {
    const sl = s.toLowerCase()
    const sizeMax = s.match(/@Size\s*\([^)]*\bmax\s*=\s*(\d+)/i)
    const sizeMin = s.match(/@Size\s*\([^)]*\bmin\s*=\s*(\d+)/i)
    const minVal  = s.match(/@Min\s*\(\s*(?:value\s*=\s*)?(\d+)/i)
    const maxVal  = s.match(/@Max\s*\(\s*(?:value\s*=\s*)?(\d+)/i)
    const pattern = s.match(/@Pattern\s*\([^)]*regexp\s*=\s*["']([^"']+)/i)
    if (sizeMax) result['maxLength'] = sizeMax[1]!
    if (sizeMin) result['minLength'] = sizeMin[1]!
    if (minVal)  result['min'] = minVal[1]!
    if (maxVal)  result['max'] = maxVal[1]!
    if (pattern) result['pattern'] = pattern[1]!
    if (sl.includes('notblank'))  result['notBlank'] = ''
    if (sl.includes('notempty'))  result['notEmpty'] = ''
    if (sl.includes('notnull') && !sl.includes('notblank')) result['notNull'] = ''
    if (sl.includes('email'))     result['email'] = ''
    if (sl.includes('positive'))  result['positive'] = ''
    if (sl.includes('negative'))  result['negative'] = ''
    if (sl.includes('future'))    result['future'] = ''
    if (sl.includes('past'))      result['past'] = ''
  }
  return result
}

function ConstraintBadges({ constraints }: { constraints: string[] }) {
  if (!constraints.length) return <span className="text-gray-300">—</span>
  const c = parseConstraints(constraints)
  const badges: { label: string; title: string }[] = []
  if ('notBlank' in c)   badges.push({ label: 'not blank', title: '@NotBlank' })
  if ('notEmpty' in c)   badges.push({ label: 'not empty', title: '@NotEmpty' })
  if ('notNull' in c)    badges.push({ label: 'not null',  title: '@NotNull' })
  if ('email' in c)      badges.push({ label: 'email',     title: '@Email' })
  if ('positive' in c)   badges.push({ label: '> 0',       title: '@Positive' })
  if ('negative' in c)   badges.push({ label: '< 0',       title: '@Negative' })
  if ('future' in c)     badges.push({ label: 'future',    title: '@Future' })
  if ('past' in c)       badges.push({ label: 'past',      title: '@Past' })
  if (c['minLength'] !== undefined && c['maxLength'] !== undefined)
    badges.push({ label: `len ${c['minLength']}–${c['maxLength']}`, title: `@Size(min=${c['minLength']}, max=${c['maxLength']})` })
  else if (c['maxLength'] !== undefined)
    badges.push({ label: `max ${c['maxLength']}`, title: `@Size(max=${c['maxLength']})` })
  else if (c['minLength'] !== undefined)
    badges.push({ label: `min ${c['minLength']}`, title: `@Size(min=${c['minLength']})` })
  if (c['min'] !== undefined && c['max'] !== undefined)
    badges.push({ label: `${c['min']}–${c['max']}`, title: `@Min(${c['min']}) @Max(${c['max']})` })
  else if (c['min'] !== undefined)
    badges.push({ label: `≥ ${c['min']}`, title: `@Min(${c['min']})` })
  else if (c['max'] !== undefined)
    badges.push({ label: `≤ ${c['max']}`, title: `@Max(${c['max']})` })
  if (c['pattern'])
    badges.push({ label: 'pattern', title: `@Pattern(${c['pattern']})` })
  if (!badges.length) return <span className="text-gray-400 text-xs font-mono">{constraints.join(' ')}</span>
  return (
    <span className="flex flex-wrap gap-1">
      {badges.map((b, i) => (
        <span key={i} title={b.title}
          className="px-1.5 py-0 bg-rose-50 border border-rose-200 text-rose-700 rounded text-xs font-medium leading-5 cursor-help">
          {b.label}
        </span>
      ))}
    </span>
  )
}

function TypeBadge({ field }: { field: DtoField }) {
  if (field.is_collection) {
    const elem = field.collection_element_type ?? 'object'
    return <span className="font-mono text-xs text-purple-700">{elem}[]</span>
  }
  if (field.is_map) {
    return <span className="font-mono text-xs text-purple-700">map</span>
  }
  const colour =
    field.openapi_type === 'string' ? 'text-green-700' :
    field.openapi_type === 'integer' || field.openapi_type === 'number' ? 'text-blue-700' :
    field.openapi_type === 'boolean' ? 'text-amber-700' :
    field.openapi_type === 'array' ? 'text-purple-700' :
    'text-gray-600'
  const label = field.openapi_format
    ? `${field.openapi_type}(${field.openapi_format})`
    : field.openapi_type
  return <span className={`font-mono text-xs ${colour}`}>{label}</span>
}

function EnumPills({ values }: { values: { name: string; serialised_as: string }[] }) {
  return (
    <span className="flex flex-wrap gap-1 mt-0.5">
      {values.map(v => (
        <button
          key={v.name}
          title={v.name}
          onClick={() => navigator.clipboard.writeText(v.serialised_as)}
          className="px-1.5 py-0 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded text-xs font-mono hover:bg-indigo-100 transition leading-5"
        >
          {v.serialised_as}
        </button>
      ))}
    </span>
  )
}

function FieldRow({ f, enumLookup }: { f: DtoField; enumLookup?: Record<string, { name: string; serialised_as: string }[]> }) {
  if (f.json_ignored) return null
  const enumValues = enumLookup?.[f.simple_type] ?? enumLookup?.[f.collection_element_type ?? ''] ?? null
  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="px-3 py-1.5 font-mono text-xs text-gray-800">
        {f.json_name !== f.name
          ? <><span>{f.json_name}</span><span className="text-gray-400 ml-1 text-xs">(Java: {f.name})</span></>
          : f.name}
        {f.description && (
          <span
            title={`Developer-authored (@Schema): ${f.description}`}
            className="ml-1 px-1 bg-emerald-100 text-emerald-700 rounded text-xs font-sans font-medium cursor-help"
          >
            i
          </span>
        )}
      </td>
      <td className="px-3 py-1.5"><TypeBadge field={f} /></td>
      <td className="px-3 py-1.5 text-xs">
        {f.required
          ? <span className="text-red-600 font-medium">yes</span>
          : <span className="text-gray-400">no</span>}
      </td>
      <td className="px-3 py-1.5 text-xs text-gray-500">
        {enumValues
          ? <EnumPills values={enumValues} />
          : <ConstraintBadges constraints={f.constraints} />}
      </td>
    </tr>
  )
}

function AuthoredDescription({ text }: { text: string }) {
  return (
    <div className="p-2 mb-2 bg-emerald-50 border border-emerald-200 rounded space-y-1">
      <span className="inline-block px-1.5 py-0.5 bg-emerald-600 text-white rounded text-xs font-medium">
        Developer-authored (@Schema)
      </span>
      <p className="text-xs text-emerald-800 whitespace-pre-wrap">{text}</p>
    </div>
  )
}

export default function SchemaViewer({ schema, inline = false, enumLookup }: Props) {
  const [open, setOpen] = useState(true)

  const content = schema.is_enum ? (
    <div className="space-y-1">
      {schema.description && <AuthoredDescription text={schema.description} />}
      {schema.source_note && (
        <p className="text-xs text-amber-600 italic mb-2">{schema.source_note}</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {schema.enum_values.map(v => (
          <button
            key={v.name}
            title={v.display ?? v.name}
            onClick={() => navigator.clipboard.writeText(v.serialised_as)}
            className="px-2 py-0.5 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded text-xs font-mono hover:bg-indigo-100 transition"
          >
            {v.serialised_as}
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-400 mt-1">Click a value to copy</p>
    </div>
  ) : (
    <div>
      {schema.description && <AuthoredDescription text={schema.description} />}
      {schema.source_note && (
        <p className="text-xs text-amber-600 italic mb-2">{schema.source_note}</p>
      )}
      {schema.fields.filter(f => !f.json_ignored).length === 0 ? (
        <p className="text-xs text-gray-400">No fields extracted.</p>
      ) : (
        <table className="w-full text-xs border border-gray-200 rounded overflow-hidden">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-1.5 text-left font-medium text-gray-600">Field</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-600">Type</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-600">Required</th>
              <th className="px-3 py-1.5 text-left font-medium text-gray-600">Constraints / Values</th>
            </tr>
          </thead>
          <tbody>
            {schema.fields.map((f, i) => <FieldRow key={i} f={f} enumLookup={enumLookup} />)}
          </tbody>
        </table>
      )}
    </div>
  )

  if (inline) return content

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 hover:bg-gray-100 transition text-left"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold text-gray-800">{schema.simple_name}</span>
          {schema.is_enum && (
            <span className="px-1.5 py-0.5 bg-indigo-100 text-indigo-700 rounded text-xs">enum</span>
          )}
          {schema.is_lombok && (
            <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded text-xs">lombok</span>
          )}
          <span className="text-xs text-gray-400">{schema.class_name}</span>
        </div>
        <span className="text-gray-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="p-3">{content}</div>}
    </div>
  )
}
