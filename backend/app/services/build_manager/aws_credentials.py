"""In-memory AWS credential store for Build Manager AWS operations.

Credentials are STS temporary tokens (key + secret + session token) and are
held only in process memory — never persisted to disk or database.  They are
wiped automatically when the container restarts, which is fine because STS
tokens expire within 12 hours anyway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory store (module-level singleton)
# ---------------------------------------------------------------------------

@dataclass
class _CredentialStore:
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    region: str = "eu-west-2"
    account_id: str = ""
    arn: str = ""
    validated_at: datetime | None = None
    valid: bool = False

_store = _CredentialStore()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_credentials(
    access_key_id: str,
    secret_access_key: str,
    session_token: str,
    region: str = "eu-west-2",
) -> None:
    """Store credentials in memory.  Clears previous validation state."""
    global _store
    _store.access_key_id = access_key_id.strip()
    _store.secret_access_key = secret_access_key.strip()
    _store.session_token = session_token.strip()
    _store.region = region.strip() or "eu-west-2"
    _store.account_id = ""
    _store.arn = ""
    _store.validated_at = None
    _store.valid = False


def validate_credentials() -> dict[str, Any]:
    """Call STS get-caller-identity with the stored credentials.

    Returns a dict with keys: valid, account_id, arn, error.
    Updates the in-memory store with the result.
    """
    if not _store.access_key_id or not _store.secret_access_key:
        return {"valid": False, "account_id": "", "arn": "", "error": "No credentials stored"}

    try:
        import boto3
        session = boto3.Session(
            aws_access_key_id=_store.access_key_id,
            aws_secret_access_key=_store.secret_access_key,
            aws_session_token=_store.session_token or None,
            region_name=_store.region,
        )
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        _store.account_id = identity["Account"]
        _store.arn = identity["Arn"]
        _store.validated_at = datetime.now(timezone.utc)
        _store.valid = True
        logger.info("AWS credentials validated: account=%s arn=%s", _store.account_id, _store.arn)
        return {"valid": True, "account_id": _store.account_id, "arn": _store.arn, "error": None}
    except Exception as exc:
        _store.valid = False
        _store.account_id = ""
        _store.arn = ""
        error_msg = str(exc)
        logger.warning("AWS credential validation failed: %s", error_msg)
        return {"valid": False, "account_id": "", "arn": "", "error": error_msg}


def get_status() -> dict[str, Any]:
    """Return current credential status without re-validating."""
    return {
        "configured": bool(_store.access_key_id),
        "valid": _store.valid,
        "account_id": _store.account_id,
        "arn": _store.arn,
        "region": _store.region,
        "validated_at": _store.validated_at.isoformat() if _store.validated_at else None,
    }


def get_boto3_session() -> Any:
    """Return a boto3 Session using the stored credentials.

    Raises RuntimeError if credentials are not configured or not validated.
    """
    if not _store.valid:
        raise RuntimeError("AWS credentials are not configured or have not been validated")
    import boto3
    return boto3.Session(
        aws_access_key_id=_store.access_key_id,
        aws_secret_access_key=_store.secret_access_key,
        aws_session_token=_store.session_token or None,
        region_name=_store.region,
    )


def clear_credentials() -> None:
    """Wipe all stored credentials."""
    global _store
    _store = _CredentialStore()
