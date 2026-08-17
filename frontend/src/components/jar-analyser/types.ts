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

export interface InfraRequirement {
  kind?: 'role' | 'authority'
  name?: string
  service?: string
  database_name?: string
  reference_count?: number
  services?: string[]
  tables?: string[]
  [key: string]: unknown
}

export interface InfraRequirementsSection {
  requirements: InfraRequirement[]
  known_gaps: string[]
  connection?: Record<string, unknown>
  per_service?: Record<string, unknown>
  collisions?: { database_name: string; services: string[]; note: string }[]
  summary?: Record<string, unknown>
}

export interface InfraRequirements {
  iam: InfraRequirementsSection
  database: InfraRequirementsSection
  messaging: InfraRequirementsSection
}

export interface ReportListItem {
  report_id: string
  upload_id: string
  filename: string
  label: string | null
  jar_type: string
  implementation_title: string | null
  implementation_version: string | null
  implementation_vendor: string | null
  spring_boot_version: string | null
  service_count: number
  endpoint_count: number
  uploaded_at: string | null
  analysis_completed_at: string | null
}

export interface SubReportSummary {
  sub_report_id: string
  filename: string
  service_name: string | null
  jar_type: string
  declared_port: number | null
  spring_boot_version: string | null
  size_bytes: number
  depth: number
  group_name: string | null
  install_path: string | null
  analysis_duration_ms: number | null
}

export interface SubReportFull extends SubReportSummary {
  start_class: string | null
  application_name: string | null
  implementation_version: string | null
  manifest: Record<string, string>
  installer_metadata: Record<string, any>
  package_structure: Record<string, any>
  class_file_versions: Record<string, any>
  purpose_narrative: PurposeStatement[]
}

export interface PurposeStatement {
  category: string
  /** False for direct facts (part.yml categorisation, authored @Operation/@Schema
   *  text) — true for anything synthesised/inferred from static evidence. */
  is_inference: boolean
  text: string
  evidence: unknown
}

export interface Endpoint {
  id: string
  controller_class: string
  controller_simple: string
  http_method: string
  path: string
  full_path: string
  base_path: string | null
  method_name: string
  parameters: EndpointParam[]
  request_body: EndpointParam | null
  return_type: { java_type: string; simple_type: string } | null
  security: {
    annotation: string
    expression: string
    parsed_auth?: {
      public: boolean
      deny_all: boolean
      roles: string[]
      authorities: string[]
      authenticated_only: boolean
      raw: string
    } | null
  } | null
  confidence: string
  source_annotation: string
  signature_key: string
  is_paginated: boolean
  page_param: string | null
  size_param: string | null
  sort_param: string | null
  default_page_size: number | null
  is_deprecated?: boolean
  linked_tables: string[]
  is_proxied: boolean | null
  /** Developer-authored, from @Operation(summary=...) — not inferred by this tool. */
  doc_summary?: string | null
  /** Developer-authored, from @Operation(description=...) — not inferred by this tool. */
  doc_description?: string | null
  /** False when the return/request type is a generic container (erased at the
   *  bytecode level), Object, or an unresolvable external type. */
  payload_shape_known?: boolean | null
}

export interface EndpointParam {
  name: string
  location: string
  java_type?: string
  simple_type?: string
  required?: boolean
  default_value?: string | null
}

export interface Dependency {
  id: string
  filename: string
  group_id: string | null
  artifact_id: string | null
  version: string | null
  category: string | null
  size_bytes: number | null
  maven_coordinates: string | null
  source_path: string | null
  manifest_title: string | null
  manifest_vendor: string | null
  coordinates_source: string | null
}

export interface ConfigFile {
  id: string
  filename: string
  path_in_jar: string
  file_type: string
  profile: string | null
  content: string | null
  key_count: number | null
  encrypted_count: number | null
  placeholder_count: number | null
  ssl_key_count: number | null
  db_key_count: number | null
  mq_key_count: number | null
  keys: { key: string; value: string; is_encrypted: boolean; is_placeholder: boolean; category: string }[]
}

export interface MigrationScript {
  id: string
  filename: string
  version: string | null
  description: string | null
  script_type: string
  size_bytes: number | null
  statement_count: number | null
  ddl_operations: string[]
  tables_affected: string[]
  content: string | null
  risk?: 'high' | 'medium' | 'low'
  risk_reasons?: string[]
}

export interface ConsumedEvent {
  source_service: string | null
  entity: string | null
  action: string | null
  operation: string | null
  handler: string | null
  parameters: { name: string; attribute: string }[]
  rules: { type: string; attribute: string; targetValue?: string }[]
  payload_class: string | null
  queue: string | null
  exchange: string | null
  routing_key: string | null
}

export interface PublishedEvent {
  entity: string
  actions: string[]
  operation: string | null
  consumers: string[]
  consumer_types: string[]
  parameters: { name: string; attribute: string }[]
  rules: { type: string; attribute: string; targetValue?: string }[]
  payload_class: string | null
}

export interface EventFile {
  id: string
  filename: string
  path_in_jar: string
  content: string | null
  published: PublishedEvent[]
  consumed: ConsumedEvent[]
}

export interface ErrorResponse {
  id: string
  http_status: number | null
  exception_class: string | null
  response_schema_class: string | null
  scope: string
  controller_class: string | null
  fields: any[]
}

export interface ScheduledJob {
  id: string
  declaring_class: string
  declaring_class_simple: string
  method_name: string
  cron: string | null
  fixed_rate_ms: number | null
  fixed_delay_ms: number | null
  initial_delay_ms: number | null
  zone: string | null
  is_config_driven: boolean
  display: string
}

export interface DiffSummary {
  services_added: number
  services_removed: number
  services_changed: number
  endpoints_added: number
  endpoints_removed: number
  endpoints_changed: number
  dependencies_added: number
  dependencies_removed: number
  dependencies_version_changed: number
  config_keys_added: number
  config_keys_removed: number
  config_keys_changed: number
  migration_scripts_added: number
  migration_scripts_removed: number
  security_changes: number
  schema_fields_added: number
  schema_fields_removed: number
  schema_fields_type_changed: number
  breaking_changes: number
  breaking_change_details: string[]
  db_tables_added: number
  db_tables_dropped: number
  db_columns_added: number
  db_columns_dropped: number
}

export interface DiffReport {
  diff_id: string
  created_at: string | null
  report_a_id: string
  report_b_id: string
  label_a: string | null
  label_b: string | null
  summary: DiffSummary
  warnings: string[]
  report_a?: { report_id: string; version: string | null; label: string }
  report_b?: { report_id: string; version: string | null; label: string }
  service_diffs?: ServiceDiff[]
}

export interface FieldDiff {
  field: string
  change: 'ADDED' | 'REMOVED' | 'TYPE_CHANGED' | 'ENUM_VALUE_ADDED' | 'ENUM_VALUE_REMOVED'
  type?: string
  type_from?: string
  type_to?: string
  required?: boolean
  impact: 'breaking' | 'potentially_breaking' | 'none' | 'review'
}

export interface SchemaDiff {
  class_name: string
  simple_name: string
  is_enum: boolean
  field_diffs: FieldDiff[]
}

export interface DbSchemaDiff {
  change: 'TABLE_ADDED' | 'TABLE_DROPPED' | 'COLUMN_ADDED' | 'COLUMN_DROPPED' | 'TYPE_CHANGED' | 'CONSTRAINT_CHANGED' | 'INDEX_CHANGED' | 'FK_CHANGED'
  table: string
  column: string | null
  risk: 'high' | 'medium' | 'low'
  detail: {
    from?: string
    to?: string
    type?: string
    nullable?: boolean
    default?: string | null
    nullable_from?: boolean
    nullable_to?: boolean
    kind?: string
    name?: string | null
    columns?: string[]
    references?: string
    ref_columns?: string[]
    pk_from?: string[]
    pk_to?: string[]
  }
}

export interface ServiceDiff {
  service_name: string
  change: 'ADDED' | 'REMOVED' | 'CHANGED'
  port_change?: { from: number | null; to: number | null } | null
  version_change?: { from: string | null; to: string | null } | null
  spring_boot_version_change?: { from: string | null; to: string | null } | null
  endpoint_diffs?: EndpointDiff[]
  dependency_diffs?: DepDiff[]
  config_diffs?: ConfigDiff[]
  migration_diffs?: MigDiff[]
  schema_diffs?: SchemaDiff[]
  db_schema_diffs?: DbSchemaDiff[]
}

export interface EndpointDiff {
  change: 'ADDED' | 'REMOVED' | 'CHANGED'
  service: string
  http_method: string
  path: string
  detail?: {
    parameters_added?: EndpointParam[]
    parameters_removed?: EndpointParam[]
    security_changed?: { from: string | null; to: string | null; importance: string }
    return_type_changed?: { from: any; to: any }
    controller_changed?: { from: string; to: string }
  } | null
}

export interface DepDiff {
  change: 'ADDED' | 'REMOVED' | 'CHANGED'
  service: string
  maven_coordinates: string
  version?: string | null
  version_from?: string | null
  version_to?: string | null
}

export interface ConfigDiff {
  change: 'ADDED' | 'REMOVED' | 'CHANGED'
  service: string
  file: string
  key: string
  value?: string
  value_from?: string
  value_to?: string
}

export interface MigDiff {
  change: 'ADDED' | 'REMOVED'
  service: string
  version: string
  filename: string
  description?: string | null
  warning?: boolean
}

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

export interface WorkflowStep {
  name: string
  method: string
  path: string
  description: string | null
  input_from: Record<string, string>
  output: string | null
  query_params: Record<string, string>
  body_fields: string[]
  poll_until: string | null
  endpoint_ref: string | null
}

export interface Workflow {
  id: string
  name: string
  description: string | null
  category: string
  source: 'auto_detected' | 'manual'
  steps: WorkflowStep[]
}

export interface DecompiledClassSummary {
  class_name: string
  package_name: string
  simple_name: string
}

export interface DecompiledClassSource extends DecompiledClassSummary {
  source: string | null
  /** The engine this source actually came from — may differ from the
   *  requested engine if that one produced no output for this class. */
  engine: 'cfr' | 'vineflower'
  available_engines: ('cfr' | 'vineflower')[]
}

export interface DecompileEngineResult {
  status: 'completed' | 'failed' | 'timed_out' | 'no_classes'
  classes_decompiled: number
  error: string | null
}

export interface DecompileRunResult {
  sub_report_id: string
  filename: string
  status: 'completed' | 'failed' | 'timed_out' | 'no_classes'
  classes_decompiled: number
  error: string | null
  engines?: Partial<Record<'cfr' | 'vineflower', DecompileEngineResult>>
}

export interface DecompileRun {
  run_id: string
  report_id: string
  sub_report_id: string | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  timeout_seconds: number
  jars_total: number
  jars_completed: number
  jars_failed: number
  started_at: string | null
  finished_at: string | null
  results: DecompileRunResult[]
  error: string | null
}

export interface ConfigExample {
  root_class_name: string
  format: string
  /** "bundled" — a real document found shipped in the jar itself (always
   *  preferred). "synthesized" — structurally valid, built from this tool's
   *  own structural analysis, not from any real deployment. Never AI-generated. */
  source: 'bundled' | 'synthesized'
  /** Present on the detail fetch, absent on the list. */
  content?: string
}

export interface DecompiledClassFacts {
  endpoints: Endpoint[]
  scheduled_jobs: ScheduledJob[]
  dto_schema: DtoSchema | null
  error_handlers: ErrorResponse[]
}
