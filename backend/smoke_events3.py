from pathlib import Path
from app.services.jar_analyser.events import EventDefinitionExtractor
import zipfile

jar = Path('/data/jar_uploads/2026/07/16/2e233a2fcfc5/catalog-installer-2.6.8.jar')

# Check own app id detection
app_id = EventDefinitionExtractor._detect_own_app_id(jar)
pkg_prefix = EventDefinitionExtractor._detect_own_package_prefix(jar)
print('own_app_id:', app_id)
print('own_pkg_prefix:', pkg_prefix)

# List all event YMLs
with zipfile.ZipFile(jar) as zf:
    ymls = [e for e in zf.namelist() if e.endswith('.event.yml')]
    print(f'\nAll event YMLs ({len(ymls)}):')
    for y in sorted(ymls):
        print(' ', y)
