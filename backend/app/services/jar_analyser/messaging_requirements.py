"""Stage 3 of the infra-requirements plan — RabbitMQ provisioning
requirements.

Real-data finding this module is deliberately honest about: exchange/queue/
routing-key fields on extracted event definitions (events.py) are, in this
product's real bundles, essentially always unresolved — they're only
populated via a rarely-used "generic schema fallback" YAML shape. A complete
queue/exchange provisioning list is therefore NOT reliably derivable today.
What IS reliable: which services declare RabbitMQ config at all, their
connection facts (vhost/address/port — see connection_facts.py), and their
publish/consume topology role (reused from Stage 6's event-topology signal)
as a coarse read/write access hint. When exchange/queue/routing-key data
*is* present for a bundle, it's surfaced as a best-effort bonus, always
paired with the reliability caveat below rather than presented as complete.
"""
from __future__ import annotations

from app.services.jar_analyser.connection_facts import extract_connection_facts


def _topology_role(published: int, consumed: int) -> str:
    if published == 0 and consumed == 0:
        return "declares messaging config but no event topology was extracted"
    if published > consumed * 2:
        return "primarily a publisher (needs write access)"
    if consumed > published * 2:
        return "primarily a consumer (needs read access)"
    return "both a publisher and a consumer"


def compute_messaging_requirements(sub_reports: list[dict]) -> dict:
    per_service: dict[str, dict] = {}
    any_exchange_queue_data = False

    for sr in sub_reports:
        svc = sr.get("service_name") or sr.get("filename")
        keys = [k for cfg in sr.get("config_files", []) for k in cfg.get("keys", [])]
        mq = extract_connection_facts(keys).messaging if keys else None

        published = sum(len(ef.get("published") or []) for ef in sr.get("event_files", []))
        consumed = sum(len(ef.get("consumed") or []) for ef in sr.get("event_files", []))

        exchanges: set[str] = set()
        queues: set[str] = set()
        routing_keys: set[str] = set()
        for ef in sr.get("event_files", []):
            for p in ef.get("published") or []:
                if p.get("exchange"):
                    exchanges.add(p["exchange"])
                if p.get("routing_key_pattern"):
                    routing_keys.add(p["routing_key_pattern"])
            for c in ef.get("consumed") or []:
                if c.get("exchange"):
                    exchanges.add(c["exchange"])
                if c.get("queue"):
                    queues.add(c["queue"])
                if c.get("routing_key"):
                    routing_keys.add(c["routing_key"])
        if exchanges or queues or routing_keys:
            any_exchange_queue_data = True

        has_mq_config = bool(mq and (mq.virtual_host or mq.address or mq.externally_parameterized_keys))
        if not has_mq_config and published == 0 and consumed == 0:
            continue

        per_service[svc] = {
            "virtual_host": mq.virtual_host if mq else None,
            "address": mq.address if mq else None,
            "port": mq.port if mq else None,
            "ssl_enabled": mq.ssl_enabled if mq else None,
            "externally_parameterized_keys": mq.externally_parameterized_keys if mq else [],
            "published_event_count": published,
            "consumed_event_count": consumed,
            "role": _topology_role(published, consumed),
            "exchanges": sorted(exchanges),
            "queues": sorted(queues),
            "routing_keys": sorted(routing_keys),
        }

    requirements = [{"service": svc, **info} for svc, info in sorted(per_service.items())]

    known_gaps = [
        "Per-service virtual-host isolation policy and queue durability/TTL settings are operational "
        "decisions this tool cannot make from static analysis.",
    ]
    if not any_exchange_queue_data:
        known_gaps.append(
            "No exchange/queue/routing-key names could be statically resolved from this bundle's event "
            "definitions — the publisher/consumer role below is reliable, but a complete queue/exchange "
            "provisioning list is not derivable from this bundle's data."
        )

    return {
        "requirements": requirements,
        "known_gaps": known_gaps,
    }
