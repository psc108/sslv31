"""Environment variable / placeholder catalogue.

Aggregates all ``${VAR_NAME:default}`` placeholders from every config file
across all services into a unified catalogue grouped by variable name.

Each entry records:
  - var_name      : the placeholder key, e.g. ``parts.export.db.url``
  - default_value : the default after the colon, or None
  - category      : inferred from the config key context
  - usages        : list of {service, config_key, config_file} dicts
"""
from __future__ import annotations

import re
from typing import Any

# Matches ${VAR_NAME} or ${VAR_NAME:default_value}
_PH_RE = re.compile(r'\$\{([^}:]+)(?::([^}]*))?\}')

# Category inference from config key name
_CAT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'datasource|jdbc|flyway|db\.', re.I),          'database'),
    (re.compile(r'rabbitmq|amqp|event\.',        re.I),          'messaging'),
    (re.compile(r'ssl|keystore|truststore|tls',  re.I),          'ssl'),
    (re.compile(r'server\.port|\.port$',         re.I),          'port'),
    (re.compile(r'serviceaccount|password|secret|credential|token', re.I), 'security'),
    (re.compile(r'url|uri|host|address',         re.I),          'url'),
    (re.compile(r'logging\.|logback',            re.I),          'logging'),
    (re.compile(r'management\.|actuator',        re.I),          'actuator'),
]

CATEGORY_COLOUR: dict[str, str] = {
    'database':  'purple',
    'messaging': 'orange',
    'ssl':       'blue',
    'port':      'gray',
    'security':  'red',
    'url':       'green',
    'logging':   'yellow',
    'actuator':  'gray',
    'other':     'gray',
}


def _infer_category(config_key: str, existing_category: str) -> str:
    """Refine the category using the config key name."""
    for pattern, cat in _CAT_RULES:
        if pattern.search(config_key):
            return cat
    # Fall back to the category already set by config_files.py
    if existing_category in ('database', 'ssl', 'messaging', 'server', 'logging', 'actuator'):
        return existing_category
    return 'other'


def build_placeholder_catalogue(sub_reports: list[dict]) -> list[dict[str, Any]]:
    """
    sub_reports: list of dicts with keys:
      service_name, config_files (each with keys list)

    Returns a list of catalogue entries sorted by var_name, each:
      {
        var_name, default_value, category,
        usage_count,
        services: [service_name, ...],
        usages: [{service, config_key, config_file, category}, ...]
      }
    """
    # var_name -> {default_value, category, usages: [...]}
    catalogue: dict[str, dict] = {}

    for sr in sub_reports:
        svc = sr.get('service_name') or sr.get('filename', 'unknown')
        for cf in sr.get('config_files', []):
            fname = cf.get('filename', '')
            for k in cf.get('keys', []):
                if not k.get('is_placeholder'):
                    continue
                value = k.get('value', '') or ''
                config_key = k.get('key', '')
                existing_cat = k.get('category', 'other')

                # Extract all placeholders from the value (may be multiple)
                for m in _PH_RE.finditer(value):
                    var_name = m.group(1)
                    default = m.group(2)  # None if no colon
                    category = _infer_category(config_key, existing_cat)

                    if var_name not in catalogue:
                        catalogue[var_name] = {
                            'var_name': var_name,
                            'default_value': default,
                            'category': category,
                            'usages': [],
                        }
                    else:
                        # Prefer a non-None default if we find one
                        if catalogue[var_name]['default_value'] is None and default is not None:
                            catalogue[var_name]['default_value'] = default

                    usage = {
                        'service': svc,
                        'config_key': config_key,
                        'config_file': fname,
                    }
                    # Deduplicate usages (same service+key combo)
                    existing_usages = catalogue[var_name]['usages']
                    if not any(u['service'] == svc and u['config_key'] == config_key for u in existing_usages):
                        existing_usages.append(usage)

    # Build final list
    result = []
    for entry in sorted(catalogue.values(), key=lambda e: e['var_name']):
        services = sorted({u['service'] for u in entry['usages']})
        result.append({
            'var_name': entry['var_name'],
            'default_value': entry['default_value'],
            'mandatory': entry['default_value'] is None,
            'category': entry['category'],
            'usage_count': len(entry['usages']),
            'services': services,
            'usages': entry['usages'],
        })

    return result
