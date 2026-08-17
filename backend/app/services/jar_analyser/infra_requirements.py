"""Stage 5 of the infra-requirements plan — top-level "Infrastructure
Requirements" aggregator.

Combines Stages 1-3 (IAM, database, messaging) into one structure, computed
once per analysis run and persisted alongside Stage 3's consistency findings
and Stage 6's Perceived Purpose narrative. Report-level, not per-sub-report —
roles/DB/MQ requirements are inherently cross-service.
"""
from __future__ import annotations

from app.services.jar_analyser.iam_requirements import compute_iam_requirements
from app.services.jar_analyser.database_requirements import compute_database_requirements
from app.services.jar_analyser.messaging_requirements import compute_messaging_requirements


def compute_infra_requirements(sub_reports: list[dict]) -> dict:
    return {
        "iam": compute_iam_requirements(sub_reports),
        "database": compute_database_requirements(sub_reports),
        "messaging": compute_messaging_requirements(sub_reports),
    }
