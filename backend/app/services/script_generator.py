"""Script generation engine — renders platform-specific CA trust install scripts and bundle READMEs."""

from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
)


def _safe_name(cn: str) -> str:
    """Convert CN to filesystem-safe name."""
    return cn.lower().replace(" ", "-").replace(".", "-").replace("*", "wildcard")


def generate_install_script(
    platform: str,
    ca_cn: str,
    ca_filename: str = "root-ca.pem",
) -> str:
    """Generate a platform-specific CA trust installation script.

    Args:
        platform: One of 'debian', 'rhel', 'alpine', 'arch', 'windows'
        ca_cn: Common Name of the CA certificate
        ca_filename: Filename of the CA PEM file
    """
    template_map = {
        "debian": "scripts/install-ca-debian.sh.j2",
        "rhel": "scripts/install-ca-rhel.sh.j2",
        "alpine": "scripts/install-ca-alpine.sh.j2",
        "arch": "scripts/install-ca-arch.sh.j2",
        "windows": "scripts/install-ca-windows.ps1.j2",
    }

    template_path = template_map.get(platform)
    if not template_path:
        raise ValueError(f"Unsupported platform: {platform}")

    template = env.get_template(template_path)

    # DER filename for Windows (same base, .cer extension)
    ca_filename_der = ca_filename.rsplit(".", 1)[0] + ".cer"

    return template.render(
        timestamp=datetime.now(timezone.utc).isoformat(),
        ca_cn=ca_cn,
        ca_filename=ca_filename,
        ca_filename_der=ca_filename_der,
    )


def generate_all_scripts(ca_cn: str, ca_filename: str = "root-ca.pem") -> dict[str, str]:
    """Generate all platform scripts. Returns dict of filename -> content."""
    return {
        "install-ca-debian.sh": generate_install_script("debian", ca_cn, ca_filename),
        "install-ca-rhel.sh": generate_install_script("rhel", ca_cn, ca_filename),
        "install-ca-alpine.sh": generate_install_script("alpine", ca_cn, ca_filename),
        "install-ca-arch.sh": generate_install_script("arch", ca_cn, ca_filename),
        "install-ca-windows.ps1": generate_install_script("windows", ca_cn, ca_filename),
    }


def generate_bundle_readme(
    cn: str,
    serial: str,
    profile: str,
    ca_cn: str,
    expires_at: str,
    include_jks: bool = False,
) -> str:
    """Generate the README.txt for a certificate bundle ZIP."""
    template = env.get_template("bundle_readme.txt.j2")
    return template.render(
        timestamp=datetime.now(timezone.utc).isoformat(),
        cn=cn,
        serial=serial,
        profile=profile,
        ca_cn=ca_cn,
        ca_cn_safe=_safe_name(ca_cn),
        expires_at=expires_at,
        include_jks=include_jks,
    )


def generate_spring_boot_properties(
    store_type: str = "JKS",
    store_path: str = "/etc/pki/java/truststore.jks",
) -> str:
    """Generate Spring Boot JVM property snippet."""
    return f"""-Djavax.net.ssl.trustStore={store_path}
-Djavax.net.ssl.trustStorePassword=<password>
-Djavax.net.ssl.trustStoreType={store_type}
"""
