"""Pydantic schemas for API request/response validation."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Common ---

class SubjectSchema(BaseModel):
    cn: str = Field(..., min_length=1, max_length=255)
    o: str = ""
    ou: str = ""
    c: str = Field("", max_length=2)
    st: str = ""
    l: str = ""


class SANEntrySchema(BaseModel):
    type: str = Field(..., pattern="^(dns|ip|email|uri)$")
    value: str = Field(..., min_length=1)


# --- CA ---

class CACreateRequest(BaseModel):
    subject: SubjectSchema
    key_algo: str = Field("RSA", pattern="^(RSA|ECDSA|Ed25519)$")
    key_size: int = Field(4096)
    validity_days: int = Field(3650, gt=0, le=7300)
    parent_ca_id: str | None = None
    path_length: int = Field(1, ge=0, le=3)
    name_constraints: dict | None = None  # {"permitted": [".example.com"], "excluded": [".bad.com"]}
    policy_oid: str | None = None  # e.g. "1.3.6.1.4.1.99999.1.1"
    cps_url: str | None = None  # e.g. "http://pki.internal/cps"


class CAResponse(BaseModel):
    id: str
    cn: str
    subject_json: str
    key_algo: str
    key_size: int
    is_root: bool
    path_length: int
    parent_ca_id: str | None
    source: str
    expires_at: datetime
    created_at: datetime
    cert_pem: str
    has_key: bool = True


class CAListResponse(BaseModel):
    id: str
    cn: str
    key_algo: str
    key_size: int
    is_root: bool
    parent_ca_id: str | None
    expires_at: datetime
    created_at: datetime
    child_count: int = 0
    cert_count: int = 0
    has_key: bool = True
    source: str = "user"
    name_constraints: dict | None = None


# --- Certificate ---

class CertCreateRequest(BaseModel):
    profile: str = Field(..., pattern="^(server|client|code_sign|email|custom)$")
    signing_ca_id: str
    subject: SubjectSchema
    san: list[SANEntrySchema] = []
    key_algo: str = Field("RSA", pattern="^(RSA|ECDSA|Ed25519)$")
    key_size: int = Field(2048)
    validity_days: int = Field(365, gt=0)
    key_password: str | None = None
    p12_password: str | None = None
    generate_jks: bool = False
    jks_password: str | None = None
    tags: list[str] = []
    template: str | None = None  # Template name for policy enforcement


class CertResponse(BaseModel):
    id: str
    serial: str
    profile: str
    subject_json: str
    san_json: str
    key_algo: str
    key_size: int
    signing_ca_id: str
    status: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None
    cert_pem: str
    chain_pem: str


class CertListResponse(BaseModel):
    id: str
    serial: str
    profile: str
    subject_json: str
    san_json: str
    key_algo: str
    key_size: int
    signing_ca_id: str | None
    status: str
    expires_at: datetime
    created_at: datetime
    revoked_at: datetime | None
    expiry_warning: bool
    tags: list[str] = []
    auto_renew: bool = False
    renewed_from: str | None = None
    renewed_to: str | None = None


# --- TrustStore ---

class TrustStoreCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    store_type: str = Field("JKS", pattern="^(JKS|PKCS12)$")
    ca_ids: list[str] = Field(..., min_length=1)
    password: str = Field(..., min_length=6)


class TrustStoreResponse(BaseModel):
    id: str
    name: str
    store_type: str
    ca_ids_json: str
    created_at: datetime


# --- Audit ---

class AuditEventResponse(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    severity: str
    operator: str | None
    source_ip: str | None
    api_key_hint: str | None
    subject_type: str | None
    subject_id: str | None
    detail_json: str | None
    description: str | None


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
