"""AWS credential management endpoints for Build Manager."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import AuthContext, require_role

router = APIRouter(prefix="/api/v1/aws", tags=["aws"])


class CredentialsInput(BaseModel):
    access_key_id: str = Field(..., min_length=16, max_length=128)
    secret_access_key: str = Field(..., min_length=1, max_length=512)
    session_token: str = Field(default="", max_length=4096)
    region: str = Field(default="eu-west-2", max_length=32)


@router.post("/credentials", status_code=204)
async def store_credentials(
    body: CredentialsInput,
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    """Store AWS credentials in memory (admin only).  Does not validate — call
    /validate-credentials separately to confirm they work."""
    from app.services.build_manager.aws_credentials import set_credentials
    set_credentials(
        access_key_id=body.access_key_id,
        secret_access_key=body.secret_access_key,
        session_token=body.session_token,
        region=body.region,
    )


@router.post("/validate-credentials")
async def validate_credentials(
    auth: AuthContext = Depends(require_role("admin")),
) -> dict:
    """Validate stored credentials via STS get-caller-identity."""
    from app.services.build_manager.aws_credentials import validate_credentials as _validate
    result = _validate()
    if not result["valid"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/credential-status")
async def credential_status(
    auth: AuthContext = Depends(require_role("admin", "operator")),
) -> dict:
    """Return current credential status without re-validating."""
    from app.services.build_manager.aws_credentials import get_status
    return get_status()


@router.delete("/credentials", status_code=204)
async def clear_credentials(
    auth: AuthContext = Depends(require_role("admin")),
) -> None:
    """Clear stored credentials from memory."""
    from app.services.build_manager.aws_credentials import clear_credentials as _clear
    _clear()
