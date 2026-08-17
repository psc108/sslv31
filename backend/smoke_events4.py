from pathlib import Path
from app.services.jar_analyser.events import EventDefinitionExtractor
import zipfile

jar = Path('/data/jar_uploads/2026/07/16/2e233a2fcfc5/catalog-installer-2.6.8.jar')

# List consumer classes
with zipfile.ZipFile(jar) as zf:
    entries = zf.namelist()
    consumers = [e for e in entries if 'Consumer' in e and e.endswith('.class') and '$' not in e
                 and 'BOOT-INF/classes' in e]
    print(f'Consumer classes ({len(consumers)}):')
    for c in sorted(consumers):
        print(' ', c)

# Also check what the own YMLs say about consumerTypes
print()
print('consumerTypes listed in own YMLs (what catalog-svc handles for itself):')
import yaml
with zipfile.ZipFile(jar) as zf:
    for entry in zf.namelist():
        if not entry.endswith('.event.yml'):
            continue
        data = yaml.safe_load(zf.read(entry).decode('utf-8', errors='replace')) or {}
        for ek, ev in (data.get('events') or {}).items():
            if not isinstance(ev, dict):
                continue
            for q in (ev.get('queues') or []):
                if q.get('applicationId') == 'catalog-svc':
                    print(f'  {ek} -> consumerType={q.get("consumerType")}')
