"""Update uvicorn product config_schema and cert_requirements in existing DB."""
import json
import sqlite3

DB_PATH = "/data/certmanager.db"

UVICORN_SCHEMA = json.dumps([
    {"key": "uvicorn_port", "label": "Listen Port", "type": "number", "required": False, "default": 8000},
    {"key": "uvicorn_workers", "label": "Workers", "type": "number", "required": False, "default": 4},
    {"key": "uvicorn_app_module", "label": "App Module", "type": "text", "required": False, "default": "main:app", "placeholder": "e.g. main:app"},
    {"key": "uvicorn_app_repo", "label": "Git Repository", "type": "text", "required": False, "default": "", "placeholder": "https://git.internal/app.git (blank for sample app)"},
    {"key": "uvicorn_app_branch", "label": "Git Branch", "type": "text", "required": False, "default": "main"},
    {"key": "uvicorn_ssl_enabled", "label": "Enable TLS", "type": "text", "required": False, "default": "true"},
])

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Get uvicorn product id
cur.execute("SELECT id FROM bm_products WHERE name = 'uvicorn'")
row = cur.fetchone()
if not row:
    print("Uvicorn product not found")
    exit(1)

product_id = row[0]

# Update cert_requirements to include client_mtls
cur.execute(
    "UPDATE bm_products SET cert_requirements = ? WHERE id = ?",
    (json.dumps({"server_tls": True, "client_mtls": True}), product_id)
)

# Update config_schema on all uvicorn versions
cur.execute(
    "UPDATE bm_product_versions SET config_schema = ? WHERE product_id = ?",
    (UVICORN_SCHEMA, product_id)
)

conn.commit()
print(f"Updated uvicorn product {product_id}: config_schema and cert_requirements")
conn.close()
