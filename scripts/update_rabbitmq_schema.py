"""Backfill RabbitMQ product config_schema in existing database."""
import json
import sys
sys.path.insert(0, "/opt/certmanager/backend")

import asyncio
from sqlalchemy import select
from app.core.database import async_session
from app.models.build_manager import BMProduct, BMProductVersion

CONFIG_SCHEMA = json.dumps([
    {"key": "rabbitmq_admin_password", "label": "Admin Password", "type": "password", "required": True, "default": "", "placeholder": "Enter admin (guest) password"},
    {"key": "rabbitmq_enable_management", "label": "Enable Management UI", "type": "checkbox", "required": False, "default": True},
    {"key": "rabbitmq_vhost", "label": "VHost", "type": "text", "required": False, "default": "/", "placeholder": "e.g. /ssp"},
    {"key": "rabbitmq_ssl_port", "label": "AMQPS Port (listeners.ssl.default)", "type": "number", "required": False, "default": 5671},
    {"key": "rabbitmq_ssl_cacertfile", "label": "CA Cert Path (ssl_options.cacertfile)", "type": "text", "required": False, "default": "/etc/rabbitmq/ssl/ca.crt"},
    {"key": "rabbitmq_ssl_certfile", "label": "Server Cert Path (ssl_options.certfile)", "type": "text", "required": False, "default": "/etc/rabbitmq/ssl/server.crt"},
    {"key": "rabbitmq_ssl_keyfile", "label": "Server Key Path (ssl_options.keyfile)", "type": "select", "required": False, "default": "/etc/rabbitmq/ssl/server.key", "options": ["/etc/rabbitmq/ssl/server.key", "/etc/rabbitmq/ssl/server.key.nopass"]},
    {"key": "rabbitmq_ssl_version_1", "label": "TLS Version 1 (ssl_options.versions.1)", "type": "text", "required": False, "default": "tlsv1.3"},
    {"key": "rabbitmq_ssl_version_2", "label": "TLS Version 2 (ssl_options.versions.2)", "type": "text", "required": False, "default": "tlsv1.2"},
    {"key": "rabbitmq_ssl_verify", "label": "Peer Verification (ssl_options.verify)", "type": "text", "required": False, "default": "verify_none", "placeholder": "verify_none or verify_peer"},
    {"key": "rabbitmq_ssl_fail_if_no_peer_cert", "label": "Fail If No Peer Cert", "type": "text", "required": False, "default": "false", "placeholder": "true or false"},
    {"key": "rabbitmq_tcp_listener", "label": "TCP Listener (listeners.tcp)", "type": "text", "required": False, "default": "none", "placeholder": "none or port number e.g. 5672"},
    {"key": "rabbitmq_management_ssl_port", "label": "Management HTTPS Port", "type": "number", "required": False, "default": 15671},
    {"key": "rabbitmq_heartbeat", "label": "Heartbeat (seconds)", "type": "number", "required": False, "default": 580},
    {"key": "rabbitmq_log_level", "label": "Log Level (log.file.level)", "type": "text", "required": False, "default": "info", "placeholder": "debug, info, warning, error"},
    {"key": "rabbitmq_loopback_users", "label": "Loopback Users", "type": "text", "required": False, "default": "none", "placeholder": "none or comma-separated usernames"},
    {"key": "rabbitmq_users", "label": "Users", "type": "list", "required": False, "default": [],
     "item_schema": [
         {"key": "name", "label": "Username", "type": "text", "required": True},
         {"key": "password", "label": "Password", "type": "password", "required": True},
         {"key": "tags", "label": "Tags", "type": "text", "required": False, "default": "", "placeholder": "e.g. administrator monitoring"},
         {"key": "vhost", "label": "VHost", "type": "text", "required": False, "default": "/"},
         {"key": "configure_priv", "label": "Configure", "type": "text", "required": False, "default": ".*"},
         {"key": "write_priv", "label": "Write", "type": "text", "required": False, "default": ".*"},
         {"key": "read_priv", "label": "Read", "type": "text", "required": False, "default": ".*"}
     ]},
    {"key": "rabbitmq_bulk_users", "label": "Bulk User Import (tab-separated: user  configure  write  read)", "type": "textarea", "required": False, "default": "",
     "placeholder": "blobstore\t.*\t.*\t.*\nrequest\t.*\t.*\t.*\nfulfillment\t.*\t.*\t.*"},
])


async def main():
    async with async_session() as db:
        result = await db.execute(select(BMProduct).where(BMProduct.name == "rabbitmq"))
        product = result.scalar_one_or_none()
        if not product:
            print("RabbitMQ product not found in catalogue")
            return

        result = await db.execute(
            select(BMProductVersion).where(BMProductVersion.product_id == product.id)
        )
        versions = result.scalars().all()
        for v in versions:
            v.config_schema = CONFIG_SCHEMA
            print(f"  Updated version {v.version} config_schema")

        await db.commit()
        print(f"Done — updated {len(versions)} RabbitMQ versions")


if __name__ == "__main__":
    asyncio.run(main())
