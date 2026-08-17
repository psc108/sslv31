"""Infrastructure diagnostics service registry.

Each entry describes a supported infrastructure component.
Questionnaire and analyser modules are resolved by service id.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceMeta:
    id: str
    display_name: str
    description: str
    icon: str


SERVICES: dict[str, ServiceMeta] = {
    "mysql": ServiceMeta(
        id="mysql",
        display_name="MySQL",
        description="MySQL database server — connectivity, SSL/TLS, user permissions, replication",
        icon="database",
    ),
    "rabbitmq": ServiceMeta(
        id="rabbitmq",
        display_name="RabbitMQ",
        description="RabbitMQ message broker — service status, SSL/TLS, vhost permissions, queue health",
        icon="message-square",
    ),
    "keystone": ServiceMeta(
        id="keystone",
        display_name="Keystone",
        description="OpenStack Keystone identity service — token endpoint, SSL/TLS, service accounts, endpoint catalogue",
        icon="key",
    ),
}
