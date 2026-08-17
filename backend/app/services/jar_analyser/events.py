"""Event definition extractor.

Parses *.event.yml files found inside Spring Boot fat JARs.

The CPI event framework schema:
  events:
    entity/action:
      entityOperation: CREATE_OR_UPDATE
      queues:
        - applicationId: catalog-svc      # consuming service
          consumerType: someHandler        # handler bean name in that service

Every service bundles its OWN entity event YMLs (published events) inside
BOOT-INF/classes/<pkg>/model/*.event.yml.  Consuming services also bundle
the event YMLs of the services they consume (as transitive dependencies),
so a JAR may contain event YMLs from many different source services.

Detection logic:
  - Published events  = YMLs whose path is under this service's own package
                        (e.g. com/dxc/ecs/customers/model/Customer.event.yml
                         belongs to the customers service)
  - Consumed events   = entries in ANY event YML where queues[].applicationId
                        matches this service's own applicationId
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


@dataclass
class PublishedEvent:
    entity: str
    actions: list[str]
    operation: str | None = None          # entityOperation value
    exchange: str | None = None
    routing_key_pattern: str | None = None
    consumers: list[str] = field(default_factory=list)   # applicationId values
    consumer_types: list[str] = field(default_factory=list)  # consumerType values
    parameters: list[dict] = field(default_factory=list)  # YML parameters list
    rules: list[dict] = field(default_factory=list)       # YML rules list
    payload_class: str | None = None      # matched entity Java class FQN


@dataclass
class ConsumedEvent:
    source_service: str | None = None     # applicationId of the publishing service
    entity: str | None = None             # entity name from event key
    action: str | None = None             # action name from event key
    operation: str | None = None          # entityOperation value
    handler: str | None = None            # consumerType for this service
    parameters: list[dict] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    payload_class: str | None = None      # matched entity Java class FQN
    # Legacy fields kept for API compatibility
    queue: str | None = None
    exchange: str | None = None
    routing_key: str | None = None


@dataclass
class EventDefinition:
    filename: str
    path_in_jar: str
    content: str | None
    published_events: list[PublishedEvent] = field(default_factory=list)
    consumed_events: list[ConsumedEvent] = field(default_factory=list)


class EventDefinitionExtractor:

    @classmethod
    def from_jar(cls, jar_path: Path) -> list[EventDefinition]:
        """
        Analyse all .event.yml files in the JAR and derive consumed events
        from consumer class names in the bytecode.

        Returns one EventDefinition per unique YML filename.  Each carries:
          - published_events: events declared in that YML (this service owns the entity)
          - consumed_events:  derived from Consumer class names in service/event/<source>/ packages
        """
        # Step 1: build entity-class map for payload matching
        entity_classes = cls._scan_entity_classes(jar_path)

        # Step 2: read every .event.yml in the JAR
        raw_ymls: list[tuple[str, str, str]] = []  # (filename, path_in_jar, content)
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for entry in zf.namelist():
                    if not entry.endswith(".event.yml"):
                        continue
                    content = zf.read(entry).decode("utf-8", errors="replace")
                    filename = entry.rsplit("/", 1)[-1]
                    raw_ymls.append((filename, entry, content))
        except zipfile.BadZipFile:
            return []

        # Step 3: scan consumer classes from bytecode
        # Consumer classes live in service/event/<source_service>/<Entity><Action>Consumer.class
        # e.g. service/event/customer/ContractCreatedConsumer -> source=customer, entity=Contract, action=Created
        consumed_from_bytecode = cls._scan_consumer_classes(jar_path, entity_classes)

        # Step 4: parse published events from own YMLs
        own_pkg_prefix = cls._detect_own_package_prefix(jar_path)
        by_filename: dict[str, EventDefinition] = {}

        for filename, path_in_jar, content in raw_ymls:
            data = {}
            if _YAML_AVAILABLE:
                try:
                    data = yaml.safe_load(content) or {}
                except Exception:
                    pass

            is_own = own_pkg_prefix and path_in_jar.startswith(own_pkg_prefix)
            events_block = data.get("events", {})
            if not isinstance(events_block, dict):
                events_block = {}

            published: list[PublishedEvent] = []

            for event_key, event_data in events_block.items():
                if not isinstance(event_data, dict):
                    continue

                parts = str(event_key).split("/", 1)
                entity = parts[0]
                action = parts[1] if len(parts) > 1 else event_key
                operation = event_data.get("entityOperation")
                queues = [q for q in (event_data.get("queues") or []) if isinstance(q, dict)]
                parameters = event_data.get("parameters") or []
                rules = event_data.get("rules") or []
                consumer_app_ids = [q.get("applicationId", "") for q in queues]
                consumer_types = [q.get("consumerType", "") for q in queues]
                entity_name = filename.replace(".event.yml", "")
                payload_class = entity_classes.get(entity_name)

                if is_own:
                    published.append(PublishedEvent(
                        entity=entity,
                        actions=[action],
                        operation=operation,
                        consumers=consumer_app_ids,
                        consumer_types=consumer_types,
                        parameters=parameters,
                        rules=rules,
                        payload_class=payload_class,
                    ))

            # Generic schema fallback
            for section in ("publishes", "published"):
                for item in (data.get(section) or []):
                    if isinstance(item, dict):
                        published.append(PublishedEvent(
                            entity=str(item.get("entity", "")),
                            actions=_as_list(item.get("actions", [])),
                            exchange=item.get("exchange"),
                            routing_key_pattern=item.get("routingKeyPattern"),
                        ))

            if not published:
                continue

            if filename not in by_filename:
                by_filename[filename] = EventDefinition(
                    filename=filename,
                    path_in_jar=path_in_jar,
                    content=content,
                )
            by_filename[filename].published_events.extend(published)

        # Step 5: attach consumed events as a synthetic EventDefinition
        # Group by source service for a clean presentation
        if consumed_from_bytecode:
            by_source: dict[str, list[ConsumedEvent]] = {}
            for c in consumed_from_bytecode:
                key = c.source_service or "unknown"
                by_source.setdefault(key, []).append(c)
            for source, events in sorted(by_source.items()):
                synthetic_filename = f"{source}.consumed"
                ev = EventDefinition(
                    filename=synthetic_filename,
                    path_in_jar=f"bytecode/service/event/{source}/",
                    content=None,
                    consumed_events=events,
                )
                by_filename[synthetic_filename] = ev

        # Also handle generic consumes schema
        for filename, path_in_jar, content in raw_ymls:
            data = {}
            if _YAML_AVAILABLE:
                try:
                    data = yaml.safe_load(content) or {}
                except Exception:
                    pass
            consumed: list[ConsumedEvent] = []
            for section in ("consumes", "consumed", "subscriptions"):
                for item in (data.get(section) or []):
                    if isinstance(item, dict):
                        consumed.append(ConsumedEvent(
                            queue=item.get("queue"),
                            exchange=item.get("exchange"),
                            routing_key=item.get("routingKey") or item.get("routing_key"),
                            handler=item.get("handler"),
                        ))
            if consumed:
                if filename not in by_filename:
                    by_filename[filename] = EventDefinition(
                        filename=filename, path_in_jar=path_in_jar, content=content
                    )
                by_filename[filename].consumed_events.extend(consumed)

        return list(by_filename.values())

    # ------------------------------------------------------------------
    # Consumer class scanning (for consumed event detection)
    # ------------------------------------------------------------------

    @classmethod
    def _scan_consumer_classes(cls, jar_path: Path, entity_classes: dict[str, str]) -> list[ConsumedEvent]:
        """
        Derive consumed events from Consumer class names in the bytecode.

        Pattern: service/event/<source_service>/<Entity><Action>Consumer.class
        e.g.  service/event/customer/ContractCreatedConsumer
              -> source_service=customer-svc, entity=Contract, action=Created

        The sub-package name (customer, fulfillment, pricing, blobstore) identifies
        which service publishes the event.  The class name encodes entity + action.
        """
        _CLASS_ROOTS = (
            "content/lib/BOOT-INF/classes/",
            "BOOT-INF/classes/",
            "WEB-INF/classes/",
        )
        # Known action suffixes to strip from class name to get entity (longest first)
        _ACTION_SUFFIXES = [
            "CreatedOrUpdatedFor", "CreatedOrUpdated",
            "StateUpdated", "NameUpdated", "OwnerChanged", "OwnerUpdated",
            "AclUpdated", "DepartmentChanged", "CustomerIdsChanged",
            "DataCentersChanged", "PortalVisibleActionSetChanged",
            "CacheSyncFinished", "CacheSyncCreatedOrUpdated",
            "Created", "Updated", "Deleted", "Changed",
            "Cancelled", "Expired", "Finished",
        ]
        results: list[ConsumedEvent] = []
        seen: set[tuple[str, str, str]] = set()  # (source, entity, action) dedup

        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                entries = zf.namelist()
        except Exception:
            return results

        for entry in entries:
            if not entry.endswith("Consumer.class") or "$" in entry:
                continue

            # Must be an app class, not a framework class
            class_root = None
            for root in _CLASS_ROOTS:
                if entry.startswith(root):
                    class_root = root
                    break
            if not class_root:
                continue

            rel = entry[len(class_root):-6]  # strip root and .class
            # e.g. com/dxc/ecs/catalog/service/event/customer/ContractCreatedConsumer
            segs = rel.split("/")

            # Find 'event' segment — source sub-package is the one after it
            try:
                event_idx = segs.index("event")
            except ValueError:
                continue

            # Need at least: ...event/<source>/<ClassName>
            if event_idx + 2 >= len(segs):
                continue

            source_pkg = segs[event_idx + 1]   # e.g. 'customer', 'fulfillment'
            class_simple = segs[-1]             # e.g. 'ContractCreatedConsumer'

            # Strip 'Consumer' suffix
            name = class_simple[:-len("Consumer")]  # e.g. 'ContractCreated'

            # Skip base/abstract/infrastructure classes
            if name in ("Abstract", "Base", "CatalogEvent", "EventMessage", "") or name.startswith("Abstract"):
                continue

            own_segs = segs[:event_idx]  # e.g. ['com','dxc','ecs','catalog','service']

            # Skip self-consumed (same service package) — source_pkg matches own service.
            # own_segs always ends in a literal 'service' package segment immediately
            # before 'event' (e.g. ['com','dxc','ecs','catalog','service']), so the
            # service name is always the second-to-last element — own_segs[-2] — of
            # own_segs, regardless of how many vendor/company prefix segments precede
            # it. (A hardcoded front-index, own_segs[3], previously assumed exactly
            # three prefix segments — com/dxc/ecs — and silently misclassified
            # self-consumption on any jar-of-jars with a different package depth.)
            own_service_seg = own_segs[-2] if len(own_segs) >= 2 else ""
            if source_pkg == own_service_seg:
                continue

            # Parse entity + action by trying known suffixes
            entity = name
            action = ""
            for suffix in _ACTION_SUFFIXES:
                if name.endswith(suffix) and len(name) > len(suffix):
                    entity = name[:-len(suffix)]
                    action = suffix
                    break

            # Normalise source service name
            source_service = source_pkg + "-svc" if source_pkg else None

            # Payload class: try to match entity name to a known class
            payload_class = entity_classes.get(entity)

            key = (source_service or "", entity, action)
            if key in seen:
                continue
            seen.add(key)

            results.append(ConsumedEvent(
                source_service=source_service,
                entity=entity,
                action=action or None,
                handler=class_simple,
                payload_class=payload_class,
            ))

        return results

    # ------------------------------------------------------------------
    # Service identity / package detection
    # ------------------------------------------------------------------

    @classmethod
    def _detect_own_package_prefix(cls, jar_path: Path) -> str | None:
        """
        Find the path prefix for this service's own application classes.
        Returns e.g. 'content/lib/BOOT-INF/classes/com/dxc/ecs/customers/'
        """
        _CLASS_ROOTS = (
            "content/lib/BOOT-INF/classes/",
            "BOOT-INF/classes/",
            "WEB-INF/classes/",
        )
        _SKIP = ("org/", "com/fasterxml/", "com/rabbitmq/", "io/", "net/", "ch/")

        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                entries = zf.namelist()

            # Find all .event.yml paths to determine which package owns them
            # The service's OWN ymls are the ones deepest under its own model package
            # Heuristic: find the most common 5-segment package prefix among event YMLs
            yml_paths = [e for e in entries if e.endswith(".event.yml")]
            if not yml_paths:
                # Fall back: find the dominant app package from class files
                return cls._dominant_app_package(entries)

            # Count package prefixes at depth 5 (com/dxc/ecs/<service>/model/)
            from collections import Counter
            prefix_counts: Counter = Counter()
            for path in yml_paths:
                for root in _CLASS_ROOTS:
                    if path.startswith(root):
                        rel = path[len(root):]
                        segs = rel.split("/")
                        if len(segs) >= 4:
                            prefix = root + "/".join(segs[:4]) + "/"
                            prefix_counts[prefix] += 1
                        break

            if prefix_counts:
                return prefix_counts.most_common(1)[0][0]

        except Exception:
            pass
        return None

    @classmethod
    def _dominant_app_package(cls, entries: list[str]) -> str | None:
        """Find the dominant application package from class file paths."""
        _CLASS_ROOTS = (
            "content/lib/BOOT-INF/classes/",
            "BOOT-INF/classes/",
            "WEB-INF/classes/",
        )
        _SKIP_SEGS = {"org", "io", "net", "ch", "META-INF"}
        from collections import Counter
        counts: Counter = Counter()
        for entry in entries:
            if not entry.endswith(".class"):
                continue
            for root in _CLASS_ROOTS:
                if entry.startswith(root):
                    rel = entry[len(root):]
                    segs = rel.split("/")
                    if len(segs) >= 4 and segs[0] not in _SKIP_SEGS:
                        prefix = root + "/".join(segs[:4]) + "/"
                        counts[prefix] += 1
                    break
        if counts:
            return counts.most_common(1)[0][0]
        return None



    @classmethod
    def _scan_entity_classes(cls, jar_path: Path) -> dict[str, str]:
        """Return simple_name -> fqn for all application classes (non-framework)."""
        _SKIP = (
            "java.", "javax.", "jakarta.", "org.springframework.",
            "com.rabbitmq.", "org.apache.", "com.fasterxml.",
        )
        result: dict[str, str] = {}
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                for entry in zf.namelist():
                    if not entry.endswith(".class") or "$" in entry:
                        continue
                    for prefix in ("content/lib/BOOT-INF/classes/", "BOOT-INF/classes/", "WEB-INF/classes/"):
                        if entry.startswith(prefix):
                            internal = entry[len(prefix):-6]
                            fqn = internal.replace("/", ".")
                            if not any(fqn.startswith(p) for p in _SKIP):
                                simple = internal.rsplit("/", 1)[-1]
                                result[simple] = fqn
                            break
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Directory-based analysis (dev/test use)
    # ------------------------------------------------------------------

    @classmethod
    def from_directory(cls, directory: Path) -> list[EventDefinition]:
        results: list[EventDefinition] = []
        for yml_file in directory.rglob("*.event.yml"):
            content = yml_file.read_text(encoding="utf-8", errors="replace")
            rel = yml_file.relative_to(directory).as_posix()
            results.append(cls._parse_standalone(yml_file.name, rel, content))
        return results

    @classmethod
    def _parse_standalone(cls, filename: str, path_in_jar: str, content: str) -> EventDefinition:
        """Parse a single YML file without cross-service context (directory mode)."""
        published: list[PublishedEvent] = []
        consumed: list[ConsumedEvent] = []

        if _YAML_AVAILABLE:
            try:
                data = yaml.safe_load(content) or {}
                events_block = data.get("events", {})
                if isinstance(events_block, dict):
                    for event_key, event_data in events_block.items():
                        if not isinstance(event_data, dict):
                            continue
                        parts = str(event_key).split("/", 1)
                        entity = parts[0]
                        action = parts[1] if len(parts) > 1 else event_key
                        queues = [q for q in (event_data.get("queues") or []) if isinstance(q, dict)]
                        published.append(PublishedEvent(
                            entity=entity,
                            actions=[action],
                            operation=event_data.get("entityOperation"),
                            consumers=[q.get("applicationId", "") for q in queues],
                            consumer_types=[q.get("consumerType", "") for q in queues],
                            parameters=event_data.get("parameters") or [],
                            rules=event_data.get("rules") or [],
                        ))
            except Exception:
                pass

        return EventDefinition(
            filename=filename,
            path_in_jar=path_in_jar,
            content=content,
            published_events=published,
            consumed_events=consumed,
        )


def _as_list(val) -> list[str]:
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)] if val else []
