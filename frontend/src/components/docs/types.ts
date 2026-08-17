export interface DocLibrary {
  id: string
  name: string
  created_by: string | null
  created_at: string
}

export interface DocShelf {
  id: string
  library_id: string
  name: string
  created_by: string | null
  created_at: string
}

export interface DocSummary {
  id: string
  shelf_id: string
  name: string
  version: number
  created_by: string | null
  created_at: string
  updated_at: string
  size: number
  first_seen_report_id: string | null
  first_seen_sub_report_id: string | null
}

export interface DocFull extends DocSummary {
  content: string
}

// Search results additionally carry a relevance snippet — only populated
// on the SQLite/FTS5 path (Improvements Plan Stage 11); undefined on the
// Postgres/MySQL ILIKE fallback.
export interface DocSearchResult extends DocSummary {
  snippet?: string | null
}

export interface DocVersionBrief {
  id: string
  version: number
  created_by: string | null
  created_at: string
}

export interface DocDiffRow {
  tag: 'equal' | 'insert' | 'delete'
  a_line: number | null
  b_line: number | null
  text: string
}

export interface DocDiffResult {
  doc_a: DocVersionBrief
  doc_b: DocVersionBrief
  added: number
  removed: number
  rows: DocDiffRow[]
}

export interface DocTrashEntry {
  id: string
  shelf_id: string
  shelf_name: string
  library_name: string
  name: string
  version: number
  created_by: string | null
  deleted_at: string
}

export interface BugTrashEntry {
  id: string
  title: string
  severity: BugSeverity
  status: BugStatus
  reporter: string | null
  deleted_at: string
}

export interface DocAnnotation {
  id: string
  doc_id: string
  text: string
  color: string
  note: string | null
  prefix: string | null
  suffix: string | null
  created_by: string | null
  created_at: string
}

export interface DocMapNode {
  id: string
  name: string
  shelf_id: string
  shelf_name: string
  word_count: number
}

export type DocMapEdgeType = 'wiki' | 'heading' | 'keyword'

export interface DocMapEdge {
  source: string
  target: string
  type: DocMapEdgeType
}

export interface DocMapData {
  nodes: DocMapNode[]
  edges: DocMapEdge[]
  // Improvements Plan Stage 14 — manually-saved node positions, keyed by
  // doc id. Absent (undefined) on the all-libraries map, which has no
  // single library row to persist a layout onto.
  layout?: Record<string, { x: number; y: number }>
}

export interface KbEntry {
  id: string
  category: string
  severity: string
  pattern: string
  title: string
  plain_english: string
  causes: string[]
  fix_steps: string[]
  see_also: string[]
  doc_id: string
  library_id: string
  library_name: string
  shelf_id: string
  shelf_name: string
  // Only populated by topic-mode search results (Improvements Plan
  // Stage 11 follow-up) — undefined for regex pattern-mode matches.
  snippet?: string | null
  // Only populated by the usage endpoint (Improvements Plan Stage 16) —
  // undefined for search/diagnose results.
  match_count?: number
  last_matched_at?: string | null
}

export interface KbContextFinding {
  service: string
  config_key?: string
  config_file?: string
  value?: string
  is_placeholder?: boolean
  var_name?: string
  has_default?: boolean
  method?: string
  path?: string
  endpoint_id?: string
  sub_report_id?: string
  roles_required?: string[]
  authorities_required?: string[]
  is_public?: boolean
  expression?: string
  filename?: string
  version?: string
  description?: string
  ddl_operations?: string[]
  declared_port?: number
}

export interface KbSuggestedAction {
  label: string
  description: string
  cert_manager_tool: string | null
  cert_manager_params: Record<string, unknown>
}

export interface KbDiagnosisResult {
  kb_entry: KbEntry
  context_findings: KbContextFinding[]
  suggested_actions: KbSuggestedAction[]
  // Which parsed exception (stack_trace_parser.py) this result came from -
  // null when error_text didn't parse into a real trace and the whole raw
  // paste was matched instead (see error_diagnostician.diagnose()).
  matched_exception: { kind: 'root' | 'caused_by' | 'suppressed'; exception_class: string | null; message: string | null } | null
}

export interface BugPrefillData {
  title: string
  severity: BugSeverity
  actual: string
  logs: string
  envConfig: string
  tags: string[]
  reportId: string
  subReportId?: string
}

export interface KnownClassMatch {
  sub_report_id: string
  report_id: string
  service_name: string
  filename: string
  // Whether this class has been decompiled (Section 36) — only then is
  // there real source to jump to, rather than just knowing the class exists.
  decompiled: boolean
}

export interface StackFrame {
  class_name: string
  method_name: string
  file_name: string | null
  line_number: number | null
  is_native: boolean
  // False for JDK/framework/proxy plumbing — lets the UI dim noise frames
  // rather than making every frame equally prominent.
  is_application_frame: boolean
  // Every analysed service (across every uploaded jar) whose own scanned
  // classes include this exact class name — empty if unknown to this tool.
  known_in: KnownClassMatch[]
}

export interface DecodedException {
  kind: 'root' | 'caused_by' | 'suppressed'
  exception_class: string | null
  message: string | null
  // The deepest link in this exception's own causal chain — Java wraps and
  // rethrows as errors propagate up the stack, so the outermost exception is
  // usually just packaging, not the actual cause. Never true for `suppressed`.
  is_likely_root_cause: boolean
  frames: StackFrame[]
  kb_matches: KbEntry[]
}

export interface MlTopAnomaly {
  window_id: string
  score: number
  severity: string
  top_features: string[]
}

export interface MlCorrelatedIncident {
  exception_class: string | null
  window_id: string
  confidence: number
  matched_frames: string[]
}

export interface MlAnalysis {
  report_id: string
  analysed_at: string
  windows_analysed: number
  anomalous_windows: number
  top_anomalies: MlTopAnomaly[]
  correlated_incidents: MlCorrelatedIncident[]
  summary: string
  degraded: boolean
  degradation_reason: string
}

export interface DecodeStackTraceResponse {
  total_exceptions: number
  exceptions: DecodedException[]
  ml_analysis?: MlAnalysis | null
}

export type BugStatus = 'open' | 'investigating' | 'resolved' | 'closed' | 'wont-fix'
export type BugSeverity = 'critical' | 'high' | 'medium' | 'low'
export type BugFrequency = 'always' | 'intermittent' | 'one-off'

export interface BugSummary {
  id: string
  title: string
  status: BugStatus
  severity: BugSeverity
  frequency: BugFrequency | null
  tags: string[]
  report_id: string | null
  sub_report_id: string | null
  // Second, independent origin (Improvements Plan Stage 19) — mutually
  // exclusive with report_id/sub_report_id, never both set.
  bm_job_id: string | null
  reporter: string | null
  assignee_id: string | null
  assignee_username: string | null
  // Set when this bug was filed by the opt-in Ansible-failure auto-filer
  // rather than a human (Improvements Plan Stage 22).
  auto_created: boolean
  // Set when this bug has been explicitly marked as a duplicate of
  // another already-independently-filed bug — distinct from occurrences,
  // which link a bug to an additional report/job it was also seen on.
  duplicate_of_bug_id: string | null
  created_at: string
  updated_at: string
}

export interface BugFull extends BugSummary {
  description: string
  resolution: string | null
  comments: BugComment[]
  history: BugHistoryEntry[]
  occurrences: BugOccurrence[]
  attachments: BugAttachment[]
  // Only present (and only meaningful) when duplicate_of_bug_id is set —
  // resolved server-side so the detail view doesn't need a second fetch.
  duplicate_of_title?: string | null
}

export interface BugAttachment {
  id: string
  bug_id: string
  filename: string
  size_bytes: number
  content_type: string | null
  uploaded_by: string | null
  created_at: string
}

export interface BugComment {
  id: string
  bug_id: string
  author: string | null
  text: string
  created_at: string
}

export interface BugHistoryEntry {
  id: string
  bug_id: string
  action: string
  from_status: BugStatus | null
  to_status: BugStatus | null
  note: string | null
  actor: string | null
  created_at: string
}

export interface BugOccurrence {
  id: string
  bug_id: string
  // Exactly one of report_id/bm_job_id is set (Improvements Plan Stage 19).
  report_id: string | null
  sub_report_id: string | null
  bm_job_id: string | null
  note: string | null
  noted_by: string | null
  created_at: string
}
