from pathlib import Path
from app.services.jar_analyser.events import EventDefinitionExtractor

jar = Path('/data/jar_uploads/2026/07/17/e58425ce9e0d/customers-installer-2.6.8.jar')
results = EventDefinitionExtractor.from_jar(jar)
print('Files:', len(results))
for ev in results:
    print(' ', ev.filename, '- pub:', len(ev.published_events), 'con:', len(ev.consumed_events))
    for c in ev.consumed_events:
        print('    CONSUMED:', c.source_service, c.entity, '/', c.action, 'handler:', c.handler)
    for p in ev.published_events:
        print('    PUBLISHED:', p.entity, '/', p.actions, 'payload:', p.payload_class)
