import asyncio
import json
from sqlalchemy import select, text
from app.core.database import engine
from app.models.build_manager import BMProduct, BMProductVersion

MYSQL_SCHEMA = json.dumps([
    {"key": "mysql_root_password", "label": "Root Password", "type": "password", "required": True, "default": "", "placeholder": "Enter root password"},
    {"key": "mysql_port", "label": "Port", "type": "number", "required": False, "default": 3306},
    {"key": "mysql_bind_address", "label": "Bind Address", "type": "text", "required": False, "default": "0.0.0.0"},
    {"key": "mysql_databases", "label": "Databases", "type": "list", "required": False, "default": [],
     "item_schema": [{"key": "name", "label": "Database Name", "type": "text", "required": True}]},
    {"key": "mysql_users", "label": "Users", "type": "list", "required": False, "default": [],
     "item_schema": [
         {"key": "name", "label": "Username", "type": "text", "required": True},
         {"key": "password", "label": "Password", "type": "password", "required": True},
         {"key": "host", "label": "Host", "type": "text", "required": False, "default": "%", "placeholder": "% for any host"},
         {"key": "priv", "label": "Privileges", "type": "text", "required": False, "default": "*.*:ALL PRIVILEGES", "placeholder": "db.*:ALL PRIVILEGES"}
     ]},
])

NGINX_SCHEMA = json.dumps([
    {"key": "nginx_server_name", "label": "Server Name", "type": "text", "required": False, "default": "_", "placeholder": "e.g. app.example.com"},
    {"key": "nginx_upstream", "label": "Upstream (proxy_pass)", "type": "text", "required": False, "default": "", "placeholder": "e.g. http://backend:8000"},
    {"key": "nginx_root", "label": "Document Root", "type": "text", "required": False, "default": "/var/www/html"},
])

async def main():
    async with engine.begin() as conn:
        # Update mysql versions
        await conn.execute(text(
            "UPDATE bm_product_versions SET config_schema = :schema WHERE product_id IN (SELECT id FROM bm_products WHERE name = 'mysql')"
        ), {"schema": MYSQL_SCHEMA})
        # Update nginx versions
        await conn.execute(text(
            "UPDATE bm_product_versions SET config_schema = :schema WHERE product_id IN (SELECT id FROM bm_products WHERE name = 'nginx')"
        ), {"schema": NGINX_SCHEMA})
    print("Updated config_schema for mysql and nginx")

asyncio.run(main())
