// --- Common ---

export interface Subject {
  cn: string
  o: string
  ou: string
  c: string
  st: string
  l: string
}

export interface SANEntry {
  type: 'dns' | 'ip' | 'email' | 'uri'
  value: string
}

// --- CA ---

export interface CA {
  id: string
  cn: string
  subject_json: string
  key_algo: string
  key_size: number
  is_root: boolean
  path_length: number
  parent_ca_id: string | null
  source: string
  expires_at: string
  created_at: string
  cert_pem: string
}

export interface CAListItem {
  id: string
  cn: string
  key_algo: string
  key_size: number
  is_root: boolean
  parent_ca_id: string | null
  expires_at: string
  created_at: string
  child_count: number
  cert_count: number
  name_constraints?: { permitted?: string[]; excluded?: string[] } | null
}

export interface CACreateRequest {
  subject: Subject
  key_algo: string
  key_size: number
  validity_days: number
  parent_ca_id?: string | null
  path_length: number
}

// --- Certificate ---

export interface Certificate {
  id: string
  serial: string
  profile: string
  subject_json: string
  san_json: string
  key_algo: string
  key_size: number
  signing_ca_id: string
  status: string
  expires_at: string
  created_at: string
  revoked_at: string | null
  cert_pem: string
  chain_pem: string
}

export interface CertListItem {
  id: string
  serial: string
  profile: string
  subject_json: string
  san_json: string
  key_algo: string
  key_size: number
  signing_ca_id: string
  status: string
  expires_at: string
  created_at: string
  revoked_at: string | null
  expiry_warning: boolean
  tags: string[]
}

export interface CertCreateRequest {
  profile: string
  signing_ca_id: string
  subject: Subject
  san: SANEntry[]
  key_algo: string
  key_size: number
  validity_days: number
  key_password?: string | null
  p12_password?: string | null
  generate_jks?: boolean
  jks_password?: string | null
}

// --- TrustStore ---

export interface TrustStore {
  id: string
  name: string
  store_type: string
  ca_ids_json: string
  created_at: string
}

export interface TrustStoreCreateRequest {
  name: string
  store_type: string
  ca_ids: string[]
  password: string
}

// --- Audit ---

export interface AuditEvent {
  id: number
  timestamp: string
  event_type: string
  severity: string
  operator: string | null
  source_ip: string | null
  api_key_hint: string | null
  subject_type: string | null
  subject_id: string | null
  detail_json: string | null
  description: string | null
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
