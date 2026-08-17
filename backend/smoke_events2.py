from pathlib import Path
from app.services.jar_analyser.events import EventDefinitionExtractor

jar = Path('/data/jar_uploads/2026/07/16/2e233a2fcfc5/catalog-installer-2.6.8.jar')
results = EventDefinitionExtractor.from_jar(jar)
print('Files:', len(results))
for ev in results:
    print(f'  {ev.filename} - pub:{len(ev.published_events)} con:{len(ev.consumed_events)}')
    for c in ev.consumed_events:
        print(f'    CONSUMED from {c.source_service}: {c.entity}/{c.action} handler={c.handler} payload={c.payload_class}')
    for p in ev.published_events:
        print(f'    PUBLISHED: {p.entity}/{p.actions} consumers={p.consumers} payload={p.payload_class}')
