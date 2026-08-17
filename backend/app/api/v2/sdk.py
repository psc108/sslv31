"""SDK generation and documentation endpoints."""

from fastapi import APIRouter, Depends
from app.core.config import settings
from app.core.security import get_auth_context, AuthContext

router = APIRouter(prefix="/api/v2/sdk", tags=["SDK"])


@router.get("/python")
async def get_python_sdk(auth: AuthContext = Depends(get_auth_context)) -> dict:
    """Generate Python SDK source code."""
    base_url = settings.BASE_URL
    sdk_code = f'''"""CertManager Python SDK — auto-generated client library."""

import httpx
from typing import Optional


class CertManagerClient:
    """Python client for the SSL Certificate Manager API."""

    def __init__(self, base_url: str = "{base_url}", api_key: str = "", token: str = ""):
        self.base_url = base_url.rstrip("/")
        self._session = httpx.Client(base_url=self.base_url, timeout=30.0)
        if token:
            self._session.headers["Authorization"] = f"Bearer {{token}}"
        elif api_key:
            self._session.headers["X-API-Key"] = api_key

    def close(self):
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # --- Health ---

    def health(self) -> dict:
        """Check API health."""
        return self._session.get("/api/v1/health").json()

    # --- Certificate Authorities ---

    def list_cas(self) -> list[dict]:
        """List all Certificate Authorities."""
        return self._session.get("/api/v1/ca").json()

    def create_ca(self, cn: str, key_algo: str = "RSA", key_size: int = 4096,
                  validity_days: int = 3650, **kwargs) -> dict:
        """Create a new Certificate Authority."""
        body = {{"cn": cn, "key_algo": key_algo, "key_size": key_size,
                "validity_days": validity_days, **kwargs}}
        return self._session.post("/api/v1/ca", json=body).json()

    # --- Certificates ---

    def list_certs(self, page: int = 1, page_size: int = 50, **filters) -> dict:
        """List certificates with pagination and filtering."""
        params = {{"page": page, "page_size": page_size, **filters}}
        return self._session.get("/api/v1/cert", params=params).json()

    def issue_cert(self, signing_ca_id: str, cn: str, profile: str = "server",
                   san: list[dict] | None = None, validity_days: int = 398,
                   key_algo: str = "RSA", key_size: int = 2048, **kwargs) -> dict:
        """Issue a new certificate."""
        body = {{
            "signing_ca_id": signing_ca_id,
            "subject": {{"cn": cn}},
            "profile": profile,
            "san": san or [{{"type": "dns", "value": cn}}],
            "validity_days": validity_days,
            "key_algo": key_algo,
            "key_size": key_size,
            **kwargs,
        }}
        return self._session.post("/api/v1/cert", json=body).json()

    def get_cert(self, serial: str) -> dict:
        """Get certificate details by serial."""
        return self._session.get(f"/api/v1/cert/{{serial}}").json()

    def revoke_cert(self, serial: str, reason: str = "unspecified") -> dict:
        """Revoke a certificate."""
        return self._session.delete(f"/api/v1/cert/{{serial}}", json={{"reason": reason}}).json()

    def inspect_cert(self, serial: str) -> dict:
        """Inspect certificate extensions and metadata."""
        return self._session.get(f"/api/v1/cert/{{serial}}/inspect").json()

    # --- CSR ---

    def generate_csr(self, cn: str, san: list[dict] | None = None,
                     key_algo: str = "RSA", key_size: int = 2048) -> dict:
        """Generate a Certificate Signing Request."""
        body = {{"subject": {{"cn": cn}}, "san": san or [], "key_algo": key_algo, "key_size": key_size}}
        return self._session.post("/api/v1/csr", json=body).json()

    def sign_csr(self, csr_id: str, signing_ca_id: str, validity_days: int = 398,
                 profile: str = "server") -> dict:
        """Sign a pending CSR."""
        body = {{"signing_ca_id": signing_ca_id, "validity_days": validity_days, "profile": profile}}
        return self._session.post(f"/api/v1/csr/{{csr_id}}/sign", json=body).json()

    # --- Export ---

    def export_cert(self, serial: str, fmt: str = "pem") -> bytes:
        """Export certificate in specified format (pem, der, chain, key, p12, jks, bundle)."""
        resp = self._session.get(f"/api/v1/export/{{serial}}/{{fmt}}")
        resp.raise_for_status()
        return resp.content

    # --- Templates ---

    def list_templates(self) -> list[dict]:
        """List certificate templates."""
        return self._session.get("/api/v1/templates").json()

    # --- Audit ---

    def get_audit_log(self, page: int = 1, page_size: int = 50) -> dict:
        """Get audit log entries."""
        return self._session.get("/api/v1/audit", params={{"page": page, "page_size": page_size}}).json()

    # --- Tools ---

    def decode_cert(self, pem: str) -> dict:
        """Decode a PEM certificate."""
        return self._session.post("/api/v1/tools/decode", json={{"pem": pem}}).json()

    def check_remote(self, host: str, port: int = 443) -> dict:
        """Check remote server TLS certificate."""
        return self._session.post("/api/v1/tools/remote-check", json={{"host": host, "port": port}}).json()

    # --- Compliance ---

    def run_compliance_scan(self, scan_type: str = "full") -> dict:
        """Run compliance scan."""
        return self._session.post("/api/v1/compliance/scan", json={{"scan_type": scan_type}}).json()
'''
    return {
        "language": "python",
        "filename": "certmanager_sdk.py",
        "version": "1.0.0",
        "requires": ["httpx>=0.28.0"],
        "source": sdk_code,
    }


@router.get("/cli")
async def get_cli_tool(auth: AuthContext = Depends(get_auth_context)) -> dict:
    """Generate CLI tool source code (Typer-based)."""
    base_url = settings.BASE_URL
    cli_code = f'''"""CertManager CLI — command-line interface for SSL Certificate Manager."""

import json
import sys
from pathlib import Path
from typing import Optional

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Install dependencies: pip install typer[all] rich httpx")
    sys.exit(1)

from certmanager_sdk import CertManagerClient

app = typer.Typer(name="certmanager", help="SSL Certificate Manager CLI")
console = Console()

# Config file: ~/.certmanager/config.json
CONFIG_PATH = Path.home() / ".certmanager" / "config.json"


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {{"url": "{base_url}", "api_key": ""}}


def _client() -> CertManagerClient:
    cfg = _load_config()
    return CertManagerClient(base_url=cfg["url"], api_key=cfg.get("api_key", ""),
                             token=cfg.get("token", ""))


@app.command()
def configure(url: str = typer.Option("{base_url}", help="API base URL"),
              api_key: str = typer.Option("", help="API key")):
    """Configure CLI connection settings."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({{"url": url, "api_key": api_key}}, indent=2))
    console.print(f"[green]Config saved to {{CONFIG_PATH}}[/green]")


@app.command()
def health():
    """Check API health."""
    with _client() as c:
        result = c.health()
        status = result.get("status", "unknown")
        color = "green" if status == "ok" else "yellow"
        console.print(f"[{{color}}]Status: {{status}}[/{{color}}]")
        console.print(f"Version: {{result.get('version', '?')}}")


@app.command()
def issue(cn: str = typer.Argument(..., help="Common Name"),
          ca: str = typer.Option(..., help="Signing CA ID"),
          profile: str = typer.Option("server", help="Certificate profile"),
          san: Optional[list[str]] = typer.Option(None, help="SAN entries (dns:example.com)"),
          days: int = typer.Option(398, help="Validity days"),
          algo: str = typer.Option("RSA", help="Key algorithm"),
          size: int = typer.Option(2048, help="Key size")):
    """Issue a new certificate."""
    san_list = []
    for s in (san or [cn]):
        if ":" in s:
            t, v = s.split(":", 1)
        else:
            t, v = "dns", s
        san_list.append({{"type": t, "value": v}})

    with _client() as c:
        result = c.issue_cert(signing_ca_id=ca, cn=cn, profile=profile,
                              san=san_list, validity_days=days,
                              key_algo=algo, key_size=size)
        console.print(f"[green]Certificate issued[/green]")
        console.print(f"  Serial: {{result.get('serial', '?')}}")
        console.print(f"  Expires: {{result.get('expires_at', '?')}}")


@app.command()
def revoke(serial: str = typer.Argument(..., help="Certificate serial"),
           reason: str = typer.Option("unspecified", help="Revocation reason")):
    """Revoke a certificate."""
    with _client() as c:
        result = c.revoke_cert(serial, reason=reason)
        console.print(f"[yellow]Certificate {{serial}} revoked ({{reason}})[/yellow]")


@app.command()
def export(serial: str = typer.Argument(..., help="Certificate serial"),
           fmt: str = typer.Option("pem", help="Format: pem, der, chain, key, p12, jks, bundle"),
           output: Optional[str] = typer.Option(None, "-o", help="Output file")):
    """Export a certificate."""
    with _client() as c:
        data = c.export_cert(serial, fmt=fmt)
        if output:
            Path(output).write_bytes(data)
            console.print(f"[green]Exported to {{output}} ({{len(data)}} bytes)[/green]")
        else:
            if fmt in ("pem", "chain"):
                console.print(data.decode())
            else:
                console.print(f"[yellow]Binary format — use -o to save ({{len(data)}} bytes)[/yellow]")


@app.command(name="list")
def list_certs(page: int = typer.Option(1), profile: Optional[str] = typer.Option(None),
               status: Optional[str] = typer.Option(None)):
    """List certificates."""
    with _client() as c:
        filters = {{}}
        if profile:
            filters["profile"] = profile
        if status:
            filters["status"] = status
        result = c.list_certs(page=page, **filters)
        table = Table(title=f"Certificates (page {{page}})")
        table.add_column("Serial", style="cyan")
        table.add_column("CN")
        table.add_column("Profile")
        table.add_column("Status")
        table.add_column("Expires")
        for item in result.get("items", []):
            subj = json.loads(item.get("subject_json", "{{}}"))
            table.add_row(
                item.get("serial", "")[:16],
                subj.get("cn", ""),
                item.get("profile", ""),
                item.get("status", ""),
                str(item.get("expires_at", ""))[:10],
            )
        console.print(table)
        console.print(f"Total: {{result.get('total', 0)}}")


@app.command()
def renew(serial: str = typer.Argument(..., help="Certificate serial to renew")):
    """Renew a certificate from existing cert."""
    with _client() as c:
        result = c._session.post(f"/api/v1/lifecycle/{{serial}}/renew").json()
        console.print(f"[green]Renewed[/green]: {{result.get('new_serial', '?')}}")


@app.command()
def cas():
    """List Certificate Authorities."""
    with _client() as c:
        result = c.list_cas()
        table = Table(title="Certificate Authorities")
        table.add_column("ID", style="cyan")
        table.add_column("CN")
        table.add_column("Type")
        for ca in result:
            table.add_row(ca.get("id", "")[:8], ca.get("cn", ""), ca.get("ca_type", "root"))
        console.print(table)


if __name__ == "__main__":
    app()
'''
    return {
        "language": "python",
        "filename": "certmanager_cli.py",
        "version": "1.0.0",
        "requires": ["typer[all]>=0.9.0", "rich>=13.0.0", "httpx>=0.28.0"],
        "install_instructions": "pip install typer[all] rich httpx",
        "source": cli_code,
    }


@router.get("/bash")
async def get_bash_examples(auth: AuthContext = Depends(get_auth_context)) -> dict:
    """Generate curl/bash script examples."""
    base_url = settings.BASE_URL
    return {
        "language": "bash",
        "examples": [
            {
                "name": "Health check",
                "command": f'curl -s {base_url}/api/v1/health | jq .',
            },
            {
                "name": "List CAs",
                "command": f'curl -s -H "X-API-Key: $API_KEY" {base_url}/api/v1/ca | jq .',
            },
            {
                "name": "Issue certificate",
                "command": f'''curl -s -X POST {base_url}/api/v1/cert \\
  -H "X-API-Key: $API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "signing_ca_id": "$CA_ID",
    "subject": {{"cn": "app.internal"}},
    "profile": "server",
    "san": [{{"type": "dns", "value": "app.internal"}}],
    "validity_days": 398
  }}' | jq .''',
            },
            {
                "name": "Export as PKCS#12",
                "command": f'curl -s -H "X-API-Key: $API_KEY" {base_url}/api/v1/export/$SERIAL/p12 -o cert.p12',
            },
            {
                "name": "Revoke certificate",
                "command": f'''curl -s -X DELETE {base_url}/api/v1/cert/$SERIAL \\
  -H "X-API-Key: $API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"reason": "superseded"}}' | jq .''',
            },
            {
                "name": "Run compliance scan",
                "command": f'''curl -s -X POST {base_url}/api/v1/compliance/scan \\
  -H "X-API-Key: $API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{{"scan_type": "full"}}' | jq .''',
            },
        ],
    }


@router.get("/openapi-url")
async def get_openapi_url() -> dict:
    """Return the OpenAPI spec URL for SDK auto-generation tools."""
    return {
        "openapi_url": "/api/openapi.json",
        "docs_url": "/api/docs",
        "generators": {
            "python": "openapi-python-client generate --url {base_url}/api/openapi.json",
            "typescript": "npx openapi-typescript {base_url}/api/openapi.json -o types.ts",
            "go": "oapi-codegen -package certmanager {base_url}/api/openapi.json > client.go",
            "java": "openapi-generator-cli generate -i {base_url}/api/openapi.json -g java -o sdk-java/",
        },
    }
