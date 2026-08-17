"""Help endpoint — serves the operations guide parsed into sections."""

import re
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.security import require_api_key

router = APIRouter(prefix="/api/v1/help", tags=["Help"])

# Path to the operations guide
def _find_guide() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "Documentation" / "ssl_cert_manager_operations_guide.md",
        Path(__file__).resolve().parent.parent.parent.parent.parent / "Documentation" / "ssl_cert_manager_operations_guide.md",
        Path.cwd() / "Documentation" / "ssl_cert_manager_operations_guide.md",
        Path.cwd().parent / "Documentation" / "ssl_cert_manager_operations_guide.md",
        Path.home() / "ssl" / "Documentation" / "ssl_cert_manager_operations_guide.md",
        Path("/opt/certmanager/Documentation/ssl_cert_manager_operations_guide.md"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _parse_sections(content: str) -> list[dict]:
    """Parse markdown into sections based on ## headings."""
    sections = []
    current_section: dict | None = None
    fallback_counter = 100  # for unnumbered headings

    for line in content.split("\n"):
        # Match ## headings with numbers: ## 0. Title, ## 1. Title, ## 16. Title, ## 20. Title
        match = re.match(r"^## (\d+)\.\s+(.+)$", line)
        if match:
            if current_section:
                sections.append(current_section)
            current_section = {
                "id": match.group(1),
                "title": match.group(2).strip(),
                "content": "",
            }
            continue

        # Match ## headings without numbers (like "API Quick Reference")
        # but skip the Table of Contents heading
        match2 = re.match(r"^## (.+)$", line)
        if match2 and not match:
            title = match2.group(1).strip()
            if title.lower() == "table of contents":
                continue
            if current_section:
                sections.append(current_section)
            fallback_counter += 1
            current_section = {
                "id": str(fallback_counter),
                "title": title,
                "content": "",
            }
            continue

        if current_section:
            current_section["content"] += line + "\n"

    if current_section:
        sections.append(current_section)

    return sections


@router.get("/sections")
async def get_help_sections(
    _: str = Depends(require_api_key),
) -> dict:
    """Return the table of contents (section list) from the operations guide."""
    guide = _find_guide()
    if not guide:
        return {"available": False, "sections": [], "error": "Operations guide not found"}

    content = guide.read_text(encoding="utf-8")
    sections = _parse_sections(content)

    return {
        "available": True,
        "total_sections": len(sections),
        "sections": [{"id": s["id"], "title": s["title"]} for s in sections],
    }


@router.get("/sections/{section_id}")
async def get_help_section(
    section_id: str,
    _: str = Depends(require_api_key),
) -> dict:
    """Return the content of a specific section from the operations guide."""
    guide = _find_guide()
    if not guide:
        return {"available": False, "content": "", "error": "Operations guide not found"}

    content = guide.read_text(encoding="utf-8")
    sections = _parse_sections(content)

    for section in sections:
        if section["id"] == section_id:
            return {
                "available": True,
                "id": section["id"],
                "title": section["title"],
                "content": section["content"].strip(),
            }

    return {"available": False, "content": "", "error": f"Section {section_id} not found"}


@router.get("/full")
async def get_full_guide(
    _: str = Depends(require_api_key),
) -> dict:
    """Return the full operations guide as markdown."""
    guide = _find_guide()
    if not guide:
        return {"available": False, "content": "", "error": "Operations guide not found"}

    content = guide.read_text(encoding="utf-8")
    return {"available": True, "content": content}
