# JAR Analyser — Developer Reference

## Table of Contents

1. [Overview](#1-overview)
2. [Uploading a JAR](#2-uploading-a-jar)
3. [What Gets Extracted](#3-what-gets-extracted)
4. [The Report Browser](#4-the-report-browser)
5. [Top-Level Report View](#5-top-level-report-view)
6. [Service Sub-Report View](#6-service-sub-report-view)
7. [Exports](#7-exports)
8. [Version Diffing](#8-version-diffing)
9. [Storefront Developer Guide](#9-storefront-developer-guide)
   - [9a. Nginx Configuration Generator](#9a-nginx-configuration-generator)
10. [Cross-Report Search](#10-cross-report-search)
11. [Auth Requirements](#11-auth-requirements)
12. [Pagination Detection](#12-pagination-detection)
13. [Validation Constraints](#13-validation-constraints)
14. [Deprecation Detection](#14-deprecation-detection)
15. [Internal / Dead Endpoint Detection](#15-internal--dead-endpoint-detection)
16. [Config Placeholder Resolution (Mandatory vs Optional)](#16-config-placeholder-resolution-mandatory-vs-optional)
17. [Security Posture Summary](#17-security-posture-summary)
18. [Service Topology](#18-service-topology)
19. [RabbitMQ Message Bus View](#19-rabbitmq-message-bus-view)
20. [Flyway Schema Reconstruction](#20-flyway-schema-reconstruction)
    - [20a. Cross-Version DB Schema Diff](#20a-cross-version-db-schema-diff)
21. [Migration Risk Scoring](#21-migration-risk-scoring)
22. [Error Message Knowledge Base](#22-error-message-knowledge-base)
23. [Context-Aware Error Diagnosis](#23-context-aware-error-diagnosis)
24. [API Reference](#24-api-reference)
25. [Integration with Other Tools](#25-integration-with-other-tools)
26. [Analysis Accuracy & Limitations](#26-analysis-accuracy--limitations)
27. [Roles & Permissions](#27-roles--permissions)
28. [Diagnostic Collection Tool](#28-diagnostic-collection-tool)
29. [Consistency Findings (Static Cross-Validation)](#29-consistency-findings-static-cross-validation)
30. [Developer-Authored Documentation](#30-developer-authored-documentation)
31. [Endpoint Confidence & Opaque Payload Flagging](#31-endpoint-confidence--opaque-payload-flagging)
32. [Perceived Purpose Narrative](#32-perceived-purpose-narrative)
33. [Infrastructure Requirements](#33-infrastructure-requirements)
34. [Scheduled Jobs](#34-scheduled-jobs)
35. [Actuator / Management Endpoint Exposure](#35-actuator--management-endpoint-exposure)
36. [On-Demand Decompilation](#36-on-demand-decompilation)
37. [String Constant Search](#37-string-constant-search)
38. [Outbound Integration Discovery](#38-outbound-integration-discovery)
39. [Outbound Call Response & Error Handling](#39-outbound-call-response--error-handling)

---

## 1. Overview

The JAR Analyser performs static bytecode analysis on Spring Boot fat JARs, WAR files, and ZIP bundles of JARs. It extracts a comprehensive technical inventory without executing any code — no JVM is started, no network connections are made.

The primary audience is:

- **Plugin developers** building integrations on top of the platform's services
- **Storefront developers** building branded customer-facing shop fronts
- **Platform engineers** tracking API changes across releases
- **Architects** auditing service dependencies and infrastructure requirements

Analysis is performed once on upload and stored in the database. All subsequent views, exports, and comparisons are served from that stored data — re-uploading the same file (by SHA-256) is detected and skipped unless you explicitly re-run.

### Feature summary

| Feature | Where to find it |
|---------|-----------------|
| REST endpoint extraction | Sub-report → Endpoints tab |
| Auth / security requirements | Sub-report → Endpoints tab (Auth column) · Top-level → Auth Requirements feed |
| Pagination detection | Sub-report → Endpoints tab (Paginated badge / filter) |
| Deprecation detection | Sub-report → Endpoints tab (Deprecated badge / filter) · Storefront Guide Section 3 |
| Internal endpoint detection | Sub-report → Endpoints tab (Internal badge / filter) · Storefront Guide Section 3 |
| DTO schema viewer with constraint badges | Sub-report → Schemas tab |
| Dependency catalogue | Sub-report → Dependencies tab |
| Config file viewer | Sub-report → Config tab |
| Flyway migration scripts | Sub-report → Migrations tab |
| Flyway schema reconstruction | Sub-report → Migrations tab → Current Schema panel |
| Migration risk scoring | Sub-report → Migrations tab (🔴/🟡/🟢 badge per script, reasons in expand panel) |
| Cross-version DB schema diff | Diff view → DB Schema sub-tab |
| RabbitMQ event definitions | Sub-report → Events tab |
| RabbitMQ message bus topology | Top-level → Message Bus tab |
| Workflow viewer | Sub-report → Workflows tab |
| Error response catalogue | Sub-report → Errors tab |
| Service topology diagram | Top-level → Topology tab |
| Storefront Developer Guide | Top-level → Developer Guide tab · ⬇ Storefront Guide export |
| OpenAPI 3.0 spec export | Sub-report → ⬇ OpenAPI · Top-level → ⬇ OpenAPI (combined) |
| Postman collection export | Sub-report → ⬇ Postman |
| TypeScript / JavaScript SDK export | Sub-report or Top-level → ⬇ TS SDK / ⬇ JS SDK |
| Version diff & change report | Report browser → ⚖ Compare versions |
| Environment variable catalogue | Top-level → Env Vars tab (mandatory/optional split) · Storefront Guide Section 9 |
| Cross-report full-text search | Browser → 🔍 Search Reports · Top-level → 🔍 Search |
| Error message knowledge base | Docs → 🔍 Error KB Search (Search / Decode / Diagnose / Usage tabs — see the Docs guide's own Error Knowledge Base section) · `GET /docs/error-kb/search` |
| Context-aware error diagnosis | Docs → 🔍 Error KB Search → 🔬 Diagnose tab (pick a report) · `POST /jar-analyser/reports/{id}/diagnose` — see Section 23 below |
| SSL/TLS diagnostic integration | Diagnose tab's results → 🔧 Fix with Cert Manager buttons (error-specific deep links) |
| Diagnostic collection tool | Top-level report → 🩺 Diagnostics — download script, upload bundle, view cert/port/log/config findings |
| Consistency findings (static cross-validation) | Top-level report → 🔍 Consistency Findings banner |
| Developer-authored documentation (`@Operation`/`@Schema`) | Sub-report → Endpoints/Schemas tabs — green "Developer-authored" cards, distinct from inferred content |
| Endpoint confidence & opaque payload flagging | Sub-report → Endpoints tab — Confidence column, Opaque payload filter |
| Perceived Purpose narrative | Sub-report → Overview tab → Perceived Purpose card |
| Infrastructure Requirements (IAM/MySQL/RabbitMQ provisioning) | Top-level report → 🏗 Infrastructure Requirements section |
| Scheduled jobs (`@Scheduled`/`@Schedules`) | Sub-report → Scheduled Jobs tab |
| Actuator/management endpoint exposure | Top-level report → 🔓 Actuator Exposure Findings section |


---

## 2. Uploading a JAR

Supported file types: `.jar`, `.war`, `.zip` (a ZIP bundle containing multiple JARs).

Upload via the **Upload & Analyse** button on the browser page, or directly via the API:

```
POST /api/v1/jar-analyser/upload
Content-Type: multipart/form-data

file=<binary>
label=<optional readable label>
skip_if_duplicate=false
```

The upload is streamed to disk in 1 MB chunks — files up to 5 GB are supported. A SHA-256 and MD5 hash are computed during streaming. If `skip_if_duplicate=true` and the same file has been uploaded before, the existing report ID is returned immediately without re-analysing.

Analysis runs as a background task. Poll for completion:

```
GET /api/v1/jar-analyser/uploads/{upload_id}/status
```

Response fields: `status` (`pending` | `analysing` | `completed` | `failed`), `report_id` (populated on completion).


---

## 3. What Gets Extracted

### 3.1 JAR Type Detection

The analyser classifies each JAR into one of several types based on manifest entries, directory structure, and class content:

| Type | Description |
|------|-------------|
| `spring_boot_fat` | Standalone Spring Boot application with embedded server |
| `library` | Service JAR within a bundle (most common in multi-service ZIPs) |
| `frontend_installer` | Contains a compiled frontend (React/Angular/Vue) |
| `nginx_installer` | Nginx configuration and binary installer |
| `monitoring_installer` | Prometheus, Grafana, or similar monitoring stack |
| `unknown` | Could not be classified with confidence |

Detection confidence is stored as a float (0–1). Values below 0.5 indicate the type is a best guess.

### 3.2 Endpoints

REST endpoints are extracted by scanning for Spring MVC and JAX-RS annotations in the bytecode:

- `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@PatchMapping`, `@DeleteMapping`
- `@Path`, `@GET`, `@POST`, `@PUT`, `@DELETE` (JAX-RS)

For each endpoint the analyser records:

- HTTP method and full path (base path + method path combined)
- Controller class and simple name
- Java method name
- Path parameters, query parameters, and request body type
- Return type (including generic parameters where resolvable)
- Security expression (`@PreAuthorize` / `@Secured` value) — parsed into structured auth requirements (see Section 11)
- Pagination flags — whether the endpoint accepts Spring `Pageable` parameters (see Section 12)
- Deprecation flag — whether the Java method carries `@Deprecated` (see Section 14)
- Confidence level (`HIGH` | `MEDIUM` | `LOW`)

### 3.3 Auth / Security Extraction

Every `@PreAuthorize`, `@Secured`, and `@RolesAllowed` expression found on a controller method is parsed into a structured auth requirement object:

```json
{
  "public": false,
  "deny_all": false,
  "authenticated_only": false,
  "roles": ["ADMIN", "OPERATOR"],
  "authorities": ["catalog:read"],
  "raw": "hasAnyRole('ADMIN','OPERATOR')"
}
```

Supported SpEL expressions: `hasRole`, `hasAnyRole`, `hasAuthority`, `hasAnyAuthority`, `isAuthenticated`, `permitAll`, `denyAll`.

The parsed result drives:
- The **Auth** badge column in the Endpoints tab
- The `@auth` JSDoc comment in the Storefront Guide and SDK
- The `/auth-requirements` aggregation feed (see Section 15)

### 3.4 DTO Schemas

Java classes annotated with `@JsonSerialize`, `@JsonDeserialize`, `@JsonProperty`, or identified as Lombok `@Data`/`@Builder` classes are scanned for field-level metadata:

- Field name and JSON serialisation name (`@JsonProperty` value)
- Java type and OpenAPI equivalent type
- Whether the field is required, nullable, or `@JsonIgnore`d
- Collection element type for `List<T>`, `Set<T>`
- Validation constraints (`@NotNull`, `@NotBlank`, `@Size`, `@Min`, `@Max`, `@Pattern`, `@Email`, etc.) — surfaced as constraint badges in the Schemas tab and as JSDoc comments in the Storefront Guide (see Section 13)
- Enum values with their serialised string representations

### 3.5 Dependencies

Every JAR nested inside the fat JAR is recorded as a dependency. Maven coordinates (`groupId:artifactId:version`) are extracted from:

1. `META-INF/maven/{groupId}/{artifactId}/pom.properties` (most reliable)
2. `META-INF/MANIFEST.MF` `Implementation-Title` / `Implementation-Version`
3. Filename parsing as a fallback

Dependencies are categorised automatically: `spring`, `database`, `messaging`, `security`, `testing`, `logging`, `cloud`, `internal`, `other`.

### 3.6 Configuration

Spring Boot `application.properties` and `application.yml` files (including profile variants like `application-prod.yml`) are extracted and parsed. Each key-value pair is stored individually, enabling search across all config across all services.

Keys are flagged if they contain:
- SSL/TLS configuration (`ssl.`, `keystore`, `truststore`)
- Database connection details (`datasource`, `jdbc`)
- Message broker settings (`rabbitmq`, `amqp`)
- Encrypted values (`{cipher}` prefix)
- Placeholder values (`${...}`)

Frontend API URL keys (`api.<service>.url`) are also extracted and used to build the service topology graph (see Section 14).

### 3.7 Database Migrations

Flyway migration scripts (`V{version}__{description}.sql`) are extracted and parsed. For each script the analyser records the version number, description, DDL operations performed (`CREATE TABLE`, `ALTER TABLE`, `DROP`, etc.), and the tables affected.

### 3.8 Events

RabbitMQ / Spring AMQP event definitions are extracted from `@RabbitListener`, `@RabbitHandler`, and `@SendTo` annotations, as well as any YAML event definition files bundled in the JAR. Consumed events carry a `source_service` field identifying the publishing service — this is used to build the service topology graph (see Section 14).

### 3.9 Workflows

Workflows are either auto-detected from the bytecode (sequences of related endpoint calls inferred from service method chains) or manually uploaded as a `workflows.yml` file via the API. Workflows describe multi-step business processes and are used to generate the Storefront Guide flow examples.

### 3.10 Error Responses

`@ExceptionHandler` methods and `@ControllerAdvice` classes are scanned to build a catalogue of HTTP error responses — which exception maps to which HTTP status code, and what the response body schema looks like.

### 3.11 Installer Metadata

For ZIP bundles that include installer JARs, the analyser extracts:

- `part.yml` — per-service installer manifest (name, install path, group, firewall ports, templates)
- `setup.properties` — global installer configuration
- `versions.yml` — service version manifest
- Nginx upstream configuration — proxy targets extracted from bundled `nginx.conf` files

Nginx upstream data is used to build the service topology graph (see Section 14).

### 3.12 Developer-Authored Documentation

`@Operation(summary=..., description=...)` and `@Schema(description=...)` annotation element values are extracted from the bytecode — these are the only source of real developer-authored explanation available once compiled (Javadoc and source comments never survive compilation). See Section 30.

### 3.13 Endpoint Confidence & Payload Shape

Beyond the basic `HIGH`/`MEDIUM`/`LOW` confidence from annotation clarity, each endpoint's confidence is refined based on whether its return type and request body actually resolve to a known shape in this bundle, and a `payload_shape_known` flag marks endpoints whose payload is a generic container, raw `Object`, or otherwise unresolvable. See Section 31.

### 3.14 Consistency Findings

Because endpoints, DTO schemas, Flyway migrations, event definitions, and Nginx/frontend config are all extracted independently, they can be cross-checked against each other for accuracy signals a single extraction pass could not surface on its own — no live system is contacted. See Section 29.

### 3.15 Perceived Purpose Narrative

A rule-based synthesis combining domain vocabulary, event topology role, DB ownership, dependency fingerprint, part.yml categorisation, auth posture, and developer-authored text (Section 3.12) into a per-service "Perceived Purpose" summary. Every inferred statement is explicitly hedged; facts are stated plainly. See Section 32.

### 3.16 Infrastructure Requirements

A report-level synthesis of what needs provisioning on the IAM/auth service, MySQL, and RabbitMQ — built from roles/authorities, Flyway table ownership, and connection config already extracted elsewhere, never from live infrastructure. See Section 33.

### 3.17 Scheduled Jobs

`@Scheduled`/`@Schedules` annotated methods are extracted from bytecode — the same annotation-element-value technique used for endpoint extraction, applied to any class (not just controllers). Reveals background/batch work — cron expressions, fixed-rate/fixed-delay intervals — that nothing else in this tool surfaces. See Section 34.

### 3.18 Actuator / Management Endpoint Exposure

`management.endpoints.web.exposure.include`/`.exclude` and related config keys are checked for services that broaden Spring Boot Actuator's exposure to sensitive management endpoints (`env`, `heapdump`, `shutdown`, etc.), cross-referenced with whether the management port matches the main app port and whether that port is reachable via the Nginx proxy. See Section 35.


---

## 4. The Report Browser

The browser lists all completed analysis reports. Each card shows:

- Original filename and SHA-256 (truncated)
- Platform version (`Implementation-Version` from the manifest)
- Service count, total endpoint count
- Analysis timestamp and duration

Use the **⚖ Compare versions** button to select two reports for a diff. Use **🔍 Search Reports** to search across all reports simultaneously. The Error Message Knowledge Base itself is reached from Docs, not from here — see [Section 22](#22-error-message-knowledge-base).

Reports can be filtered by version string or searched by filename/title.

---

## 5. Top-Level Report View

When you open a report for a ZIP bundle (the most common case for a full platform release), the top-level view has several tabs:

### Overview tab

- Manifest metadata: vendor, version, Java version required, Spring Boot version
- SHA-256 of the uploaded file
- Summary cards: service count, total endpoints, dependencies, ports, migrations
- Feature flags: SSL config detected, database config, RabbitMQ config, ports in use
- Service index table: all nested services with their port, group, type, and size

Click **View →** on any service row to drill into that service's sub-report.

### Topology tab

A force-directed diagram and adjacency table showing inter-service dependencies. See Section 18 for full details.

### Message Bus tab

A cross-service RabbitMQ event topology view showing every published event, its publisher, payload class, exchange/routing key, and all known consumers. See Section 19 for full details.

### Env Vars tab

A searchable catalogue of every `${placeholder}` variable found across all service config files. Variables are split into **Mandatory** (no default value — must be set before deployment) and **Optional** (have a default). See Section 16 for full details.

### Nginx Configs tab

Four ready-to-deploy Nginx configuration variants generated from the upstream proxy data bundled in the installer. See Section 9a for full details.

### Developer Guide tab

An in-browser viewer for the Storefront Developer Guide, split into 9 labelled section tabs with line numbers, search, and a status bar. See Section 9 for full details.

### Outbound tab

Statically-discovered outbound integration signals (Feign clients, `@Value`-injected URL/host config keys) aggregated across every service in this report, plus response/error-handling signals for any classes that have been decompiled. See [Section 38](#38-outbound-integration-discovery) and [Section 39](#39-outbound-call-response--error-handling) for full details.

### DTO Conflicts tab

Flags DTOs and enums that share the same class name across two or more services in this report but don't actually agree on shape (different fields, types, or enum values) — the kind of silent incompatibility that's easy to miss when each service's schema is only ever reviewed in isolation. Backed by `GET /jar-analyser/reports/{id}/dto-conflicts`.

There's no dedicated **🛠 Error Lookup** button here any more — the Error Message Knowledge Base (including diagnosis scoped to this report) is reached from Docs. See [Section 22](#22-error-message-knowledge-base) and [Section 23](#23-context-aware-error-diagnosis).

### Re-running Analysis

The **↺ Re-run** button re-analyses the original uploaded file without re-uploading. Use this after a bug fix in the analyser itself, or to pick up schema improvements. The button shows a spinner and status text while analysis runs, and navigates to the new report automatically on completion.


---

## 6. Service Sub-Report View

Each service has the following tabs:

### Overview

Manifest details, start class, application name, declared port, Spring Boot version, package structure summary, and class file version distribution. Also includes the **Security Posture** card — see Section 17.

### Endpoints

Full paginated list of all extracted REST endpoints. Filter controls:

| Filter | Description |
|--------|-------------|
| HTTP method | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| Path contains | Substring match on the full path |
| Confidence | `HIGH`, `MEDIUM`, `LOW` |
| Auth | `public`, `authenticated`, `role:<name>`, `authority:<name>` |
| Paginated only | Show only endpoints that accept Spring `Pageable` parameters |
| Deprecated only | Show only endpoints flagged `@Deprecated` in the bytecode |
| Hide deprecated | Exclude deprecated endpoints from results |
| Internal only | Show only endpoints not reachable via the Nginx proxy |
| Hide internal | Exclude internal (unproxied) endpoints from results |

Each row shows the method badge, full path, controller, Java method name, and:

- **Auth badge** — derived from the parsed `@PreAuthorize` / `@Secured` expression. Colours: green = public, blue = authenticated, amber = role-restricted, purple = authority-restricted, red = deny-all, grey = unknown. Click to see the raw expression.
- **Paginated badge** (cyan) — shown when the endpoint accepts `page` / `size` / `sort` query parameters or returns a Spring `Page<T>` type.
- **Deprecated badge** (orange) — shown when the Java controller method carries `@Deprecated`. The endpoint path is also rendered with strikethrough styling. Do not target deprecated endpoints for new integrations.
- **Internal badge** (grey) — shown when the endpoint's service is not reachable via the Nginx reverse proxy. These endpoints are internal-only and should not be called directly from external clients. See Section 15.
- **Example panel** — expand any row to see auto-generated JSON request and response examples built from the DTO schemas.

### Dependencies

All JARs bundled inside this service JAR. Filter by category. Shows Maven coordinates, version, and file size.

### Config

All extracted configuration files with their key-value pairs. Sensitive keys (SSL, DB, MQ) are highlighted. Profile-specific files are labelled.

### Schemas

All extracted DTO classes and enums. Each schema shows its fields with types, nullability, and inline constraint badges:

| Badge colour | Meaning |
|-------------|---------|
| Rose | Validation constraint (`max 255`, `not blank`, `≥ 0`, `pattern`, etc.) |

Hover over a constraint badge to see the original Java annotation string. Enums show their serialised string values. Use the search bar to find a specific type by name or field.

### Events

RabbitMQ event definitions — published topics and consumed queues, with source service attribution on consumed events.

### Migrations

Flyway migration scripts in version order, with DDL operation summary, affected tables, and a **risk badge** (🔴/🟡/🟢) on every row. See Section 21 for full details on risk scoring. The **Current Schema** panel (toggle at the top of the tab) replays all migrations to show the reconstructed current-state schema — tables, columns, types, nullability, primary keys, indexes, and foreign keys. See Section 20 for full details.

### Workflows

Auto-detected and manually uploaded multi-step business process definitions. Each workflow shows its steps with HTTP method, path, input/output mapping, and polling conditions.

### Errors

HTTP error response catalogue extracted from `@ExceptionHandler` and `@ControllerAdvice` classes. Shows exception class, HTTP status, and response body schema.

### Service Guide tab

A read-only in-browser viewer for the per-service Storefront Guide markdown, with line numbers and search. This is the same content as the downloadable Storefront Guide export, scoped to this service.


---

## 7. Exports

### Per-Service Exports

Available from the export buttons in a sub-report view:

| Export | Format | Description |
|--------|--------|-------------|
| OpenAPI | `.json` | OpenAPI 3.0.3 spec — paths, components/schemas, security schemes, request/response bodies |
| Postman | `.json` | Postman Collection v2.1 with one folder per controller, example request bodies from schemas, path variables as `{{variable}}` |
| JS SDK | `.js` | Auto-generated ES2020 class with one method per endpoint, fetch-based, no dependencies |
| TS SDK | `.ts` | Same as JS SDK with full TypeScript interfaces for all DTOs |

The Markdown export for individual services is available via the API (`/export/markdown`) but not surfaced as a UI button — use the Service Guide tab for in-browser reading.

### Top-Level Report Exports

Available from the export buttons on the top-level report view:

| Export | Format | Description |
|--------|--------|-------------|
| OpenAPI (combined) | `.json` | Combined OpenAPI 3.0.3 spec for all services — schemas are prefixed with the service name to avoid collisions |
| JS SDK | `.js` | Combined SDK with one class per service plus a `PlatformClient` wrapper |
| TS SDK | `.ts` | Combined TypeScript SDK |
| Storefront Guide | `.ts` | Purpose-built guide for shop-front developers (see Section 9) |
| Nginx Configs | `.zip` | Four Nginx configuration variants as a ZIP archive (see Section 9a) |

### Diff Exports

Available from the diff view:

| Export | Format | Description |
|--------|--------|-------------|
| Raw Diff | `.md` | Machine-readable diff of all changes |
| Change Report (MD) | `.md` | Formal structured change report with risk assessment |
| Change Report (PDF) | `.pdf` | Print-ready PDF version of the change report |

### OpenAPI 3.0.3 Spec

The generated OpenAPI spec includes:

- `info` — service name, version, description
- `servers` — `http://localhost:{declared_port}`
- `paths` — all extracted endpoints with parameters, request bodies, and response schemas
- `components/schemas` — all DTO classes and enums with field types, required lists, and `x-constraints` extensions
- `components/securitySchemes` — `bearerAuth` (JWT) scheme
- Per-operation `security` requirements derived from `@PreAuthorize` expressions
- `x-security-expression` extension on each operation with the raw SpEL string

The combined top-level spec prefixes all schema names with `{service}__` (e.g. `catalog__ProductDto`) to prevent collisions across services.


---

## 8. Version Diffing

Select two reports and click **⚖ Compare versions** (or use the diff button in the browser) to generate a diff report.

The diff engine compares:

- **Endpoints**: added, removed, modified (path, method, parameters, return type, security)
- **Dependencies**: added, removed, version changed (with semver classification: major/minor/patch)
- **Config keys**: added, removed, value changed
- **Schemas**: field additions, removals, type changes — classified as `breaking`, `potentially_breaking`, or `none`
- **DB Schema**: table and column changes reconstructed from Flyway migrations — classified by risk (`high`, `medium`, `low`). See [Section 20a](#20a-cross-version-db-schema-diff).

Breaking changes are surfaced prominently with a red banner. The summary bar shows counts across all categories including DB tables added/dropped and columns added/dropped.

### Breaking Change Classification

| Change | Classification |
|--------|---------------|
| Endpoint removed | Breaking |
| Required field removed from request body | Breaking |
| Field type changed | Breaking |
| HTTP method changed | Breaking |
| Required field added to request body | Potentially breaking |
| Optional field removed from response | Potentially breaking |
| New endpoint added | None |
| Optional field added | None |
| Dependency version bump (major) | Potentially breaking |
| DB column dropped | Breaking |
| DB column type changed | Breaking |
| DB column added NOT NULL without default | Breaking |
| DB table dropped | Breaking |
| DB table added | None |
| DB column added (nullable or with default) | None |
| DB index / FK added or dropped | Medium risk |

---

## 9. Storefront Developer Guide

The **⬇ Storefront Guide** export (and the **Developer Guide** tab on the top-level report) generates a single TypeScript (or JavaScript) file specifically for developers building branded customer shop fronts. It is distinct from the SDK exports in that it:

- Filters out internal, admin, and integration endpoints — only public-facing API paths are included
- Focuses on the six storefront-relevant services: Catalog, Request, Pricing, Customers, ServiceInstances, Fulfillment
- Includes only the DTO types that those public endpoints actually use
- Provides a `PlatformClient` wrapper that composes all six service clients
- Includes annotated flow examples showing realistic multi-step call sequences

The guide is regenerated from the live scanned data each time it is downloaded, so it always reflects the actual API shape of the version you are viewing.

### In-browser viewer

The **Developer Guide** tab splits the generated file into 9 labelled section tabs:

| Tab | Content |
|-----|---------|
| ① Interfaces | TypeScript interfaces for all public-facing DTOs |
| ② ApiClient | Fetch-based base class with auth and error handling |
| ③ Service Clients | Per-domain client classes with JSDoc |
| ④ Pagination | `PaginatedResponse<T>` interface and `paginate()` helper |
| ⑤ Code Examples | Annotated multi-step flow examples |
| ⑥ Auth | Auth requirements summary by role and authority |
| ⑦ Topology | Mermaid diagram of inter-service dependencies |
| ⑧ Event Bus | Published events per service with consumer annotations |
| ⑨ Env Vars | Environment variable catalogue grouped by category |

Each tab has a line-number gutter, a search bar scoped to that section, and a status bar showing section line count and total file size. Copy and download buttons are available on every tab.

### Guide sections

The generated file contains nine sections:

#### Section 1 — TypeScript Interfaces

One `export interface` per DTO used by a public endpoint. Fields include JSDoc constraint comments derived from validation annotations:

```typescript
export interface ProductDto {
  /** @required @maxLength 255 @notBlank */
  name: string
  /** @min 0 @max 99999 */
  price?: number
  /** @required @email */
  contactEmail: string
}
```

#### Section 2 — ApiClient Base Class

A fetch-based `ApiClient` class with JWT bearer token and API key authentication, URL construction, query parameter serialisation, and error normalisation into a typed `ApiError`.

#### Section 3 — Per-Domain Service Clients

One class per storefront domain (e.g. `CatalogClient extends ApiClient`). Each method corresponds to a public endpoint and includes:

- `@auth` JSDoc comment showing the required role, authority, or `public`
- `@deprecated` JSDoc comment on any method whose Java handler is annotated `@Deprecated` — do not use these methods for new integrations
- `@example request` and `@example response` blocks with realistic JSON generated from the DTO schemas

If any deprecated endpoints are present in the scanned version, a warning comment is emitted at the top of Section 3:

```
// ⚠ 3 deprecated endpoints in this version — marked with @deprecated below.
```

#### Section 4 — Pagination

`PaginatedResponse<T>` interface and an `async function* paginate()` helper for iterating all pages. Lists all paginated endpoints detected in this version.

#### Section 5 — Storefront Code Examples

Eight annotated `async function` examples showing realistic multi-step flows driven by the actual scanned endpoints:

1. Browse the portal catalogue — `/portal/catalog-items`, options model
2. Compute price before ordering — `/prices/computations`
3. Place an order — `POST /orders` → poll order-items → fetch action-fulfillments
4. Handle approval-gated orders — detect `waitingForExternalApproval`, `GET/PUT /approval-items`
5. Track orders from the customer dashboard — list orders, order-items, fulfillments
6. Manage customer profile & contracts — customer, contracts, rate cards
7. View active service instances — state, sub-state, ACL, service fulfillment record
8. Raise a change action — upgrade-actions → `POST /actions` → poll to terminal state

Each flow includes:
- `// ⚡ Async events fired:` annotations on steps that trigger async messaging
- Polling loops with `setTimeout` for long-running state transitions
- Schema-driven `// → ReturnType { fields }` comments on responses
- Required-fields-first body hints

> **Method name caveat** — method names in the examples are derived from Java bytecode and do not always match the HTTP path. A name like `getOptionsModel` may actually serve `/portal/catalog-items/{id}/options-model`. Always cross-reference with Section 3 where each method is annotated with its exact HTTP verb and path in the JSDoc comment above it.

#### Section 6 — Auth Requirements

A comment block listing every unique role and authority required across all public endpoints, with the list of endpoints that require each one.

#### Section 7 — Service Topology

A Mermaid diagram block showing inter-service dependencies (event, nginx proxy, API call edges). Paste into [mermaid.live](https://mermaid.live) to render interactively.

#### Section 8 — Event Bus

A per-service listing of every published RabbitMQ event, formatted as a comment block. Each entry shows the entity/action pair, the payload class, the exchange and routing key, and the list of known consumers (merged from declared event YAML and bytecode-detected `@RabbitListener` handlers):

```typescript
// ─── catalog ───────────────────────────────────────────────────────────────
// Publisher: catalog
//   product/created [ProductCreatedEvent] → portal-ui, customer-svc
//     exchange: catalog.events  routing-key: product.created
//   product/updated [ProductUpdatedEvent] → portal-ui
//     exchange: catalog.events  routing-key: product.updated
```

This section is generated from the same data that powers the Message Bus tab (see Section 16). It is useful for storefront developers who need to react to platform events via a webhook or message bridge.

#### Section 9 — Environment Variables

All `${placeholder}` variables found across every service config file, grouped by category (database, messaging, security, etc.) with default values and the services that reference each variable.

### Usage

```typescript
import PlatformClient from './storefront-guide'

const platform = new PlatformClient({
  baseUrl: 'https://platform.example.com',
  token: '<jwt-from-login>',
})

// Browse the portal catalogue
const catalogPage = await platform.catalog.getPortalCatalogItems()

// Place an order
const orderResponse = await platform.request.createOrders({ items: [...] })
```

---

### 9a. Nginx Configuration Generator

The **⚙️ Nginx Configs** tab (and the **⬇ Nginx Configs** ZIP export) generates four ready-to-deploy Nginx configuration variants from the upstream proxy data bundled in the installer.

### Variants

| Variant | Description |
|---------|-------------|
| On-Prem — Standard | Single-node deployment. Upstreams use the `host` placeholder from `part.yml`. SSL termination at Nginx with `proxy_redirect` rewriting for HTTPS redirects. |
| On-Prem — HA | Multi-node deployment. Upstreams use `host1` and `host2` placeholders with `least_conn` load balancing. |
| AWS / ALB | ALB handles SSL termination. Nginx listens on port 80 only, `proxy_redirect off`. Upstreams use the `host` placeholder. |
| Docker | Single-host Docker deployment. Upstreams use `127.0.0.1` with the declared service port. `proxy_redirect off`. |

### Frontend / Backend toggle

Each variant is available in two flavours:
- **Frontend LB** — 20 upstreams including all UI services and monitoring
- **Backend LB** — 18 upstreams (no UI services)

### Service port reference

The tab includes a service port reference grid showing every upstream service name and its declared port, derived from the installer `part.yml` metadata.

### API

```
GET /api/v1/jar-analyser/reports/{id}/nginx-configs
```

Returns a JSON object with keys `on_prem_standard`, `on_prem_ha`, `aws_alb`, and `docker`, each containing `frontend` and `backend` config strings.


---

## 10. Cross-Report Search

The **🔍 Search Reports** button (in the browser) and **🔍 Search** button (in a top-level report) open a search panel that queries across all stored data simultaneously.

Search covers: endpoint paths, controller names, method names, dependency coordinates, config keys and values, DTO class names and field names, event filenames, and migration descriptions.

Results are grouped by service and categorised. Click any result to navigate directly to the relevant tab in the correct sub-report.

#### Search tips

- Search is case-insensitive and uses substring matching (`ILIKE`)
- Minimum query length is 2 characters
- Use the category filter pills to narrow results to a specific data type
- Searching within a top-level report scopes results to that report's services only
- Searching from the browser searches across all reports

---

## 11. Auth Requirements

### In the Endpoints tab

Every endpoint row shows an **Auth** badge derived from the parsed `@PreAuthorize` / `@Secured` expression:

| Badge | Meaning |
|-------|---------|
| 🟢 public | `permitAll()` — no token required |
| 🔵 authenticated | `isAuthenticated()` — any valid JWT or API key |
| 🟡 ROLE:name | `hasRole('name')` or `hasAnyRole(...)` |
| 🟣 authority:name | `hasAuthority('name')` or `hasAnyAuthority(...)` |
| 🔴 DENY ALL | `denyAll()` — always returns 403 |
| ⚪ unknown | No security annotation found — treat as requiring authentication |

Use the **Auth** filter dropdown to show only endpoints matching a specific auth requirement (e.g. `role:ADMIN`, `public`, `authenticated`).

### Auth Requirements feed

The `/auth-requirements` API endpoint aggregates auth data across all services in a report:

```
GET /api/v1/jar-analyser/reports/{id}/auth-requirements
```

Response structure:

```json
{
  "summary": {
    "unique_roles": ["ADMIN", "OPERATOR"],
    "unique_authorities": ["catalog:read", "catalog:write"],
    "public_endpoint_count": 4,
    "authenticated_only_count": 12,
    "unsecured_count": 0
  },
  "by_role": {
    "ADMIN": [{ "service": "catalog", "method": "DELETE", "path": "/api/catalog/v1/items/{id}" }]
  },
  "by_authority": { ... },
  "public_endpoints": [...],
  "authenticated_only": [...],
  "unsecured": [...]
}
```

This feed is consumed by the SSL Cert Manager's access control tooling and can be used in CI/CD pipelines to assert that no unintended public endpoints have been introduced.

### In the Storefront Guide

Each generated client method carries an `@auth` JSDoc comment:

```typescript
/** GET /api/catalog/v1/items
 * @auth roles: OPERATOR, ADMIN
 * @example response
 *   { "id": "3fa85f64-...", "name": "Example Name" }
 */
getCatalogItems(): Promise<unknown> {
  return this._request('GET', '/api/catalog/v1/items')
}
```

Section 6 of the guide lists every unique role and authority with the endpoints that require each one.

### SpEL expression support

The security parser handles the following Spring Security SpEL expressions:

| Expression | Parsed as |
|-----------|-----------|
| `permitAll()` | `public: true` |
| `denyAll()` | `deny_all: true` |
| `isAuthenticated()` | `authenticated_only: true` |
| `hasRole('X')` | `roles: ["X"]` |
| `hasAnyRole('X','Y')` | `roles: ["X", "Y"]` |
| `hasAuthority('X')` | `authorities: ["X"]` |
| `hasAnyAuthority('X','Y')` | `authorities: ["X", "Y"]` |
| Combined with `&&` / `\|\|` | All roles and authorities extracted |


---

## 12. Pagination Detection

The analyser detects endpoints that accept Spring `Pageable` parameters and documents the pagination contract explicitly.

### Detection logic

An endpoint is flagged as paginated if any of the following are true:

- Its query parameters include a `page`-family name (`page`, `pageNumber`, `pageNo`, `pageIndex`)
- Its query parameters include a `size`-family name (`size`, `pageSize`, `limit`, `perPage`)
- Its return type is a Spring `Page<T>`, `PageImpl<T>`, or `Slice<T>`

When detected, the following fields are stored alongside the endpoint:

| Field | Description |
|-------|-------------|
| `is_paginated` | `true` if pagination was detected |
| `page_param` | Name of the page-index parameter (e.g. `page`) |
| `size_param` | Name of the page-size parameter (e.g. `size`) |
| `sort_param` | Name of the sort parameter (e.g. `sort`) |
| `default_page_size` | Default value of the size parameter if declared |

### In the Endpoints tab

Paginated endpoints show a cyan **paginated** badge in the path cell. Use the **Paginated only** checkbox filter to show only paginated endpoints.

### Pagination contract

All paginated endpoints follow the Spring `Page<T>` response contract:

```json
{
  "content": [...],
  "totalElements": 142,
  "totalPages": 8,
  "number": 0,
  "size": 20,
  "first": true,
  "last": false,
  "empty": false
}
```

Standard query parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `page` | Zero-based page index | `0` |
| `size` | Number of items per page | `20` |
| `sort` | Field and direction, e.g. `name,asc` or `createdAt,desc` | none |

Multiple `sort` parameters are supported: `?sort=name,asc&sort=createdAt,desc`.

Always check `totalPages` before requesting the next page. Requesting a page beyond `totalPages - 1` returns an empty `content` array.

### In the Storefront Guide

Section 4 of the generated guide includes:

- The `PaginatedResponse<T>` TypeScript interface
- An `async function* paginate()` helper for iterating all pages without manual page tracking
- A list of all paginated endpoints detected in this version

```typescript
// Iterate all pages of a paginated endpoint:
for await (const page of paginate((p, s) => catalog.listItems({ page: p, size: s }))) {
  for (const item of page) {
    console.log(item)
  }
}
```

### Known limitation

The bytecode scanner extracts `@RequestParam` annotations reliably for most JARs. In some compiled JARs the parameter metadata is not present in the bytecode (debug info stripped), in which case `parameters_json` will be empty and pagination detection falls back to return-type analysis only.


---

## 13. Validation Constraints

Validation annotations on DTO fields are extracted during bytecode scanning and surfaced in two places: the Schemas tab and the Storefront Guide.

### Supported annotations

| Annotation | Displayed as |
|-----------|-------------|
| `@NotNull` | `not null` badge |
| `@NotBlank` | `not blank` badge |
| `@NotEmpty` | `not empty` badge |
| `@Size(min=N, max=M)` | `len N–M` badge (or `max M` / `min N` if only one bound) |
| `@Min(N)` | `≥ N` badge |
| `@Max(N)` | `≤ N` badge |
| `@Email` | `email` badge |
| `@Pattern(regexp=...)` | `pattern` badge |
| `@Positive` | `> 0` badge |
| `@Negative` | `< 0` badge |
| `@Future` | `future` badge |
| `@Past` | `past` badge |

### In the Schemas tab

Constraint badges appear inline on each field row in rose/pink colouring. Hover over a badge to see the original Java annotation string (e.g. `@Size(max=255)`).

### In the Storefront Guide

Section 1 of the generated guide emits JSDoc constraint comments above each constrained field:

```typescript
export interface CustomerDto {
  /** @required @maxLength 255 @notBlank */
  name: string
  /** @minLength 10 @maxLength 1000 */
  description?: string
  /** @required @min 0 @max 99999 */
  accountNumber: number
  /** @required @email */
  emailAddress: string
  /** @pattern ^[A-Z]{2}[0-9]{6}$ */
  referenceCode?: string
}
```

These comments are recognised by most TypeScript-aware editors and API documentation generators (TypeDoc, TSDoc).

### In the OpenAPI spec

Constraints are included in the generated OpenAPI spec as an `x-constraints` extension array on each property:

```json
"name": {
  "type": "string",
  "x-constraints": ["@Size(max=255)", "@NotBlank"]
}
```

Standard OpenAPI constraint keywords (`minLength`, `maxLength`, `minimum`, `maximum`, `pattern`) are also set where the annotation maps directly.


---

## 14. Deprecation Detection

The analyser detects controller methods annotated with Java's `@Deprecated` annotation and flags those endpoints throughout the UI and generated artefacts.

### Detection

During bytecode scanning, every controller method's `RuntimeVisibleAnnotations` attribute is checked for the `Ljava/lang/Deprecated;` descriptor. If found, the endpoint is stored with `is_deprecated: true`.

This covers:
- Methods annotated with `@Deprecated` in source code (compiled to `Ljava/lang/Deprecated;` in the class file)
- Methods where the `@Deprecated` annotation was added at the class level (class-level deprecation is not currently propagated to individual methods — only method-level annotations are detected)

### In the Endpoints tab

Deprecated endpoints are visually distinguished:

- An orange **deprecated** badge appears in the path cell
- The endpoint path is rendered with ~~strikethrough~~ styling
- Two filter controls are available:
  - **Deprecated only** — show only deprecated endpoints
  - **Hide deprecated** — exclude deprecated endpoints from the list

### In the Storefront Guide

Section 3 of the generated guide marks deprecated methods with a `@deprecated` JSDoc comment:

```typescript
/** GET /api/catalog/v1/legacy-items
 * @deprecated This endpoint is marked @Deprecated in the source — do not use for new integrations.
 * @auth roles: OPERATOR, ADMIN
 */
getLegacyItems(): Promise<unknown> {
  return this._request('GET', '/api/catalog/v1/legacy-items')
}
```

If any deprecated endpoints exist in the scanned version, a count note is emitted at the top of Section 3:

```
// ⚠ 3 deprecated endpoints in this version — marked with @deprecated below.
```

This note is omitted entirely when no deprecated endpoints are present.

### In the API

The `is_deprecated` field is included on every endpoint object returned by the endpoints list endpoint. Two new filter parameters are available:

| Parameter | Type | Description |
|-----------|------|-------------|
| `deprecated_only` | boolean | If `true`, return only deprecated endpoints |
| `hide_deprecated` | boolean | If `true`, exclude deprecated endpoints from results |

Example — list all deprecated endpoints across a service:

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints?deprecated_only=true
```

Example — list only active (non-deprecated) endpoints:

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints?hide_deprecated=true
```

### In the Diff

When comparing two versions, endpoints that transition from non-deprecated to deprecated are surfaced in the diff as a `deprecated` change type — classified as `potentially_breaking` since consumers relying on that endpoint should migrate.

### Limitations

- Only method-level `@Deprecated` annotations are detected. Class-level deprecation (deprecating the entire controller) is not currently propagated to individual endpoint rows.
- The `@Deprecated` annotation must be present in the compiled bytecode (`RetentionPolicy.RUNTIME` or `RetentionPolicy.CLASS`). Annotations stripped by obfuscation tools will not be detected.
- Existing endpoints scanned before this feature was introduced will have `is_deprecated: false` regardless of their actual annotation state. Re-run analysis (`↺ Re-run`) to pick up deprecation flags on previously scanned JARs.

---

## 15. Internal / Dead Endpoint Detection

The analyser cross-references each service against the Nginx proxy configuration bundled in the installer to determine whether the service is reachable via the reverse proxy. Endpoints belonging to services that are not proxied are flagged as internal.

### Detection logic

At bundle analysis time, the analyser builds a set of proxied service names from the nginx sub-report (`jar_type = "nginx_installer"`):

- `installer_metadata.nginx.service_dependencies` — flat list of service names that the Nginx installer proxies
- `installer_metadata.nginx.upstreams` — named upstream objects (upstream name is normalised to a service name)

Service names are normalised before comparison — the suffixes `-svc`, `-upstream`, `-service`, and `-installer` are stripped so that `catalog-svc`, `catalog-upstream`, and `catalog` all resolve to the same name.

Each endpoint is then stamped with `is_proxied`:

| Value | Meaning |
|-------|---------|
| `true` | Service is reachable via the Nginx proxy |
| `false` | Service is present in the bundle but not proxied — internal only |
| `null` | No nginx sub-report was found in the bundle — proxy status unknown |

### In the Endpoints tab

Endpoints where `is_proxied = false` show a grey **internal** badge in the path cell. Two filter controls are available:

- **Internal only** — show only endpoints belonging to unproxied services
- **Hide internal** — exclude internal endpoints from the list (useful when building a public-facing integration)

### In the Storefront Guide

Section 3 of the generated guide emits an `@internal` JSDoc comment on any method whose service is not proxied:

```typescript
/** POST /api/internal-svc/v1/jobs
 * @internal Not reachable via the Nginx proxy — do not call from external clients.
 * @auth roles: ADMIN
 */
createJob(body: JobRequest): Promise<JobResponse> {
  return this._request('POST', '/api/internal-svc/v1/jobs', body)
}
```

### In the API

The `is_proxied` field is included on every endpoint object returned by the endpoints list endpoint. Two filter parameters are available:

| Parameter | Type | Description |
|-----------|------|-------------|
| `internal_only` | boolean | If `true`, return only endpoints where `is_proxied = false` |
| `hide_internal` | boolean | If `true`, exclude endpoints where `is_proxied = true` or `null` |

Example — list all internal endpoints in a service:

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints?internal_only=true
```

Example — list only externally reachable endpoints:

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints?hide_internal=true
```

### Limitations

- Detection requires a `nginx_installer` sub-report in the bundle. Single-JAR uploads and bundles without an Nginx installer will have `is_proxied = null` on all endpoints.
- The matching is service-level, not path-level. If a service is proxied, all its endpoints are considered proxied — individual path exclusions in the Nginx config are not currently resolved.
- Existing endpoints scanned before migration `039` was applied will have `is_proxied = null`. Use ↺ Re-run to populate the field.

---

## 16. Config Placeholder Resolution (Mandatory vs Optional)

The placeholder catalogue (Env Vars tab) distinguishes between variables that have a default value and those that do not. Variables without a default are **mandatory** — the service will fail to start if they are not set in the deployment environment.

### How mandatory is determined

Spring Boot placeholder syntax is `${VAR_NAME:default_value}`. The analyser parses every `${...}` expression found in config files:

| Syntax | Result |
|--------|--------|
| `${DB_URL}` | `mandatory: true` — no default, must be provided |
| `${DB_URL:jdbc:mysql://localhost/mydb}` | `mandatory: false` — has a default |
| `${DB_URL:}` | `mandatory: false` — default is an empty string |

### In the Env Vars tab

The tab now shows three stat cards at the top:

- **N unique variables** — total across all services
- **N required (no default)** — amber card; these must be set before deployment
- **N optional** — have a default value

Mandatory variables are visually distinguished:

- Amber `⚠ required` badge in the Variable column
- Amber-tinted row background
- Default column shows `— no default` in amber text instead of a value
- Expanded detail panel shows a warning: *"This variable has no default value and must be set in the deployment environment before the service will start."*

A three-way toggle filter lets you show **All**, **⚠ Required**, or **Optional** variables. This is the fastest way to build a deployment checklist — switch to Required, export the list, and work through it before provisioning a new environment.

### In the Storefront Guide

Section 9 of the generated guide lists mandatory variables first within each category, annotated with `// ⚠ REQUIRED — no default`:

```
// [DATABASE]
//   DB_URL                                                   // ⚠ REQUIRED — no default
//     used by: catalog, request, customers
//   DB_PASSWORD                                              // ⚠ REQUIRED — no default
//     used by: catalog, request, customers
//   DB_POOL_SIZE                                               (default: 10)
//     used by: catalog
```

### In the API

The `/env-vars` endpoint now returns a `mandatory` boolean on each item and a `mandatory_count` summary field:

```
GET /api/v1/jar-analyser/reports/{id}/env-vars
```

New response fields:

| Field | Description |
|-------|-------------|
| `mandatory_count` | Number of variables with no default value |
| `items[].mandatory` | `true` if the variable has no default |

New filter parameter:

| Parameter | Type | Description |
|-----------|------|-------------|
| `mandatory_only` | boolean | If `true`, return only variables where `mandatory = true` |

Example — list all mandatory variables for a report:

```
GET /api/v1/jar-analyser/reports/{id}/env-vars?mandatory_only=true
```

Use this in CI/CD pipelines to assert that all mandatory variables are present in the target environment's secret store before deployment.

### Limitations

- Detection is purely syntactic — the `${VAR:default}` pattern is parsed from the raw config file content. Variables that are resolved programmatically (e.g. via `@Value` with a `PropertySourcesPlaceholderConfigurer` bean) are not detected.
- A variable with an empty default (`${VAR:}`) is classified as optional even though an empty value may cause a runtime error. Review empty-default variables manually.
- The same variable name may appear with a default in one service and without a default in another. The catalogue records the first non-null default found; if any service declares the variable without a default, `mandatory` is set to `true` for that service's usage but the catalogue entry uses the first-seen default.

---

## 17. Security Posture Summary

The **Security Posture** card on the sub-report Overview tab provides an at-a-glance breakdown of how every endpoint in the service is secured. It is designed to make security regressions immediately visible — an endpoint accidentally made public, or a role requirement silently dropped, shows up here without needing to scan the full Endpoints tab.

### Summary counts

The card shows six counts:

| Category | Description |
|----------|-------------|
| Public | Endpoints with `permitAll()` — no token required |
| Authenticated | Endpoints requiring any valid JWT (`isAuthenticated()`) |
| Role-gated | Endpoints restricted to one or more named roles (`hasRole` / `hasAnyRole`) |
| Authority-gated | Endpoints restricted to one or more named authorities (`hasAuthority` / `hasAnyAuthority`) |
| Deny-all | Endpoints with `denyAll()` — always return 403 |
| Unannotated | Endpoints with no `@PreAuthorize` / `@Secured` annotation — treat as requiring authentication |

### Role and authority chips

Below the count grid, the card lists every unique role and authority required across the service as clickable chips. Clicking a chip opens the Endpoints tab pre-filtered to that role or authority.

### Expandable endpoint lists

The **Public endpoints** and **Unannotated endpoints** lists are expandable. These are the two categories most likely to indicate a security issue:

- **Public** — confirm each entry is intentionally public-facing
- **Unannotated** — these endpoints have no security annotation; the actual access control depends on global Spring Security configuration and should be reviewed

### In the Diff view

When comparing two versions, endpoints whose security expression changes from secured to unsecured (or vice versa) are highlighted in the diff with before/after values and classified as a breaking change. This catches cases where a `@PreAuthorize` annotation is accidentally removed.

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/security-posture
```

Response structure:

```json
{
  "sub_report_id": "...",
  "total_endpoints": 42,
  "summary": {
    "public_count": 3,
    "authenticated_only_count": 8,
    "role_gated_count": 24,
    "authority_gated_count": 5,
    "deny_all_count": 0,
    "unannotated_count": 2,
    "unique_roles": ["ADMIN", "OPERATOR"],
    "unique_authorities": ["catalog:read", "catalog:write"]
  },
  "public_endpoints": [
    { "method": "GET", "path": "/api/catalog/v1/items", "endpoint_id": "..." }
  ],
  "authenticated_only_endpoints": [...],
  "by_role": {
    "ADMIN": [{ "method": "DELETE", "path": "/api/catalog/v1/items/{id}", "endpoint_id": "..." }]
  },
  "by_authority": { ... },
  "deny_all_endpoints": [],
  "unannotated_endpoints": [...]
}
```

This endpoint is consumed by the Security Posture card in the sub-report Overview tab and can also be used in CI/CD pipelines to assert that no unintended public or unannotated endpoints have been introduced.

### Limitations

- The posture summary is derived from `parsed_auth_json` on each endpoint, which is populated during analysis from `@PreAuthorize` / `@Secured` expressions. Endpoints scanned before auth extraction was implemented will have `unannotated_count` inflated — use ↺ Re-run to refresh.
- Global Spring Security configuration (e.g. `HttpSecurity.authorizeRequests()` in a `WebSecurityConfigurerAdapter`) is not currently parsed. Endpoints that appear unannotated may still be protected by a global rule.

---

## 18. Service Topology

The **Topology** tab on the top-level report view renders a force-directed diagram and adjacency table showing inter-service dependencies across the entire platform.

### Data sources

The topology graph is built from three already-extracted data sources — no additional scanning is required:

| Source | Edge type | Example |
|--------|-----------|---------|
| Consumed events (`source_service` field) | `event` (amber) | `customer → catalog` (ContractDeleted) |
| Nginx upstream config (`installer_metadata.nginx.upstreams`) | `nginx` (indigo) | `frontend-lb → catalog` |
| Frontend API URL config (`api.<service>.url` keys) | `api_url` (green) | `portal-ui → fulfillment` |

### Node types

| Type | Colour | Description |
|------|--------|-------------|
| `service` | Blue | Backend Spring Boot service |
| `load_balancer` | Amber | Nginx load balancer / reverse proxy |
| `frontend` | Purple | UI application (portal, management console) |
| `infrastructure` | Grey | Supporting infrastructure (config server, blob store) |

Service names are normalised — `-svc`, `-upstream`, and `-service` suffixes are stripped so that `catalog-svc`, `catalog-upstream`, and `catalog` all resolve to the same node.

### Diagram view

The SVG force-directed diagram runs a 120-step physics simulation (repulsion + spring attraction) entirely in the browser — no external libraries. Arrow markers are colour-coded by edge type. Node labels are truncated to 16 characters; the full name is visible in the adjacency table.

### Table view

The adjacency table lists every node with its type, declared port, and all outgoing dependencies. Each dependency chip shows the target service name and the edge type (Event, Nginx proxy, API call).

Toggle between diagram and table views using the buttons in the top-right of the topology panel.

### Topology API

```
GET /api/v1/jar-analyser/reports/{id}/topology
```

Response:

```json
{
  "report_id": "...",
  "nodes": [
    { "id": "catalog", "label": "catalog", "type": "service", "port": 8093 },
    { "id": "frontend-lb", "label": "frontend-lb", "type": "load_balancer", "port": 443 }
  ],
  "edges": [
    { "from": "customer", "to": "catalog", "via": "event", "label": "ContractDeleted" },
    { "from": "frontend-lb", "to": "catalog", "via": "nginx", "label": "catalog-upstream" },
    { "from": "portal-ui", "to": "catalog", "via": "api_url", "label": "api.catalog.url" }
  ]
}
```

### In the Storefront Guide

Section 7 of the generated guide includes a Mermaid `graph LR` diagram block. Paste it into [mermaid.live](https://mermaid.live) or any Mermaid-compatible renderer to visualise the topology:

```
graph LR
  frontend_lb["frontend-lb:443"]:::lb
  catalog["catalog:8093"]
  portal_ui("portal-ui"):::ui
  frontend_lb -.->|proxy| catalog
  portal_ui -->|API| catalog
  classDef lb fill:#fbbf24,stroke:#d97706,color:#000
  classDef ui fill:#818cf8,stroke:#4f46e5,color:#fff
```


---

## 19. RabbitMQ Message Bus View

The **🐰 Message Bus** tab on the top-level report view provides a cross-service event topology — every RabbitMQ event published by any service in the platform, with its consumers, exchange, routing key, and payload class.

### Data sources

The message bus view is built from two already-extracted data sources:

| Source | What it contributes |
|--------|--------------------|
| Event YAML files bundled in each JAR (`events.yml`, `*-events.yml`) | Published events with exchange, routing key, payload class, and declared consumers |
| `@RabbitListener` / `@RabbitHandler` bytecode annotations | Bytecode-detected consumers, merged by entity/action/source_service key |

Declared consumers (from YAML) and bytecode-detected consumers are deduplicated and merged into a single consumer list per event.

### Summary cards

Three cards at the top of the tab show:

- **Total events** — distinct entity/action pairs across all publishers
- **Publishers** — number of services that publish at least one event
- **Consumers** — number of services that consume at least one event

### Filter bar

| Filter | Description |
|--------|-------------|
| Text search | Substring match on event name, payload class, exchange, or routing key |
| Publisher | Dropdown — filter to events published by a specific service |
| Consumer | Dropdown — filter to events consumed by a specific service |

### Event table

Each row shows:

| Column | Description |
|--------|-------------|
| Publisher | Service that publishes the event |
| Event | `entity/action` pair (e.g. `product/created`) |
| Payload | Java payload class name |
| Consumers | Comma-separated list of consuming services |
| Exchange | RabbitMQ exchange name |

Expand any row to see the full detail panel:

- Exchange and routing key
- Full payload class name
- All consumers with their handler method (if detected from bytecode)

### API

```
GET /api/v1/jar-analyser/reports/{id}/message-bus
```

Response:

```json
{
  "total_events": 120,
  "publishers": ["blob-store", "catalog", "config"],
  "consumers": ["catalog", "catalog-svc", "customer-svc"],
  "rows": [
    {
      "publisher": "catalog",
      "event": "product/created",
      "payload_class": "ProductCreatedEvent",
      "exchange": "catalog.events",
      "routing_key": "product.created",
      "consumers": ["portal-ui", "customer-svc"],
      "consumer_details": [
        { "service": "portal-ui", "handler": null, "source": "declared" },
        { "service": "customer-svc", "handler": "onProductCreated", "source": "bytecode" }
      ]
    }
  ]
}
```

### In the Storefront Guide

Section 8 of the generated guide contains a comment block listing every published event per service with its consumers. See [Section 9 — Storefront Developer Guide](#9-storefront-developer-guide) for the format.


---

## 20. Flyway Schema Reconstruction

The **Current Schema** panel in the Migrations tab reconstructs the current logical database schema by replaying all Flyway migration scripts in version order — no running database required. The panel only appears for services that have Flyway migration scripts; if a service has no migrations, the Migrations tab shows a "No migration scripts found" message and the toggle is not displayed.

### How it works

The reconstructor processes `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, and `RENAME TABLE` statements in migration version order using a regex-based SQL parser (no external dependencies). The result is the schema as it would exist after all migrations have been applied.

### Supported DDL operations

| Statement | Effect |
|-----------|--------|
| `CREATE TABLE` | Adds table with all columns, primary key, and inline constraints |
| `DROP TABLE` | Removes table from the schema |
| `RENAME TABLE` / `ALTER TABLE ... RENAME TO` | Renames table |
| `ALTER TABLE ... ADD COLUMN` | Adds column to existing table |
| `ALTER TABLE ... DROP COLUMN` | Removes column |
| `ALTER TABLE ... MODIFY` / `ALTER COLUMN` | Updates column type and nullability |
| `ALTER TABLE ... ADD PRIMARY KEY` | Sets primary key on existing table |
| `ALTER TABLE ... ADD FOREIGN KEY` | Records foreign key relationship |
| `CREATE [UNIQUE] INDEX` | Records index on table |
| `DROP INDEX` | Removes index |

### Current Schema panel

The panel is accessed by clicking the **Current Schema** toggle at the top of the Migrations tab (visible only when the service has at least one migration script). It shows:

- Summary bar: number of tables reconstructed and migrations replayed
- Filter bar: substring search on table name
- Per-table expandable rows showing:
  - Column name, data type, nullability, default value, PK flag
  - Primary key declaration
  - Indexes (with UNIQUE flag)
  - Foreign key relationships (columns → referenced table and columns)

Primary key columns are highlighted in amber. NOT NULL columns are shown in red. Click any table row to expand or collapse its detail.

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/schema-reconstruction
```

Response:

```json
{
  "sub_report_id": "...",
  "migration_count": 52,
  "table_count": 64,
  "tables": [
    {
      "table": "catalog_item",
      "columns": [
        { "name": "id", "type": "BIGINT", "nullable": false, "primary_key": true, "default": null },
        { "name": "name", "type": "VARCHAR(255)", "nullable": false, "primary_key": false, "default": null },
        { "name": "price", "type": "DECIMAL(10,2)", "nullable": true, "primary_key": false, "default": null }
      ],
      "primary_key": ["id"],
      "indexes": [
        { "name": "idx_catalog_item_name", "columns": ["name"], "unique": false }
      ],
      "foreign_keys": [
        { "name": "fk_catalog_item_category", "columns": ["category_id"], "references": "category", "ref_columns": ["id"] }
      ]
    }
  ]
}
```

### In the Storefront Guide

Section 10 of the generated guide contains a per-service table listing for every service that has Flyway migrations. Each table shows its columns with types and nullability, and foreign key relationships.

---

### 20a. Cross-Version DB Schema Diff

When comparing two reports, the diff engine reconstructs the database schema for each version (using the same Flyway replay logic as the Current Schema panel) and computes a structural diff between them. The result appears in the **DB Schema** sub-tab of each service accordion in the diff view.

This section only appears for services that have Flyway migrations in both versions being compared. Services with no migrations are silently skipped.

### Risk classification

Each change is assigned a risk level:

| Risk | Colour | Change types |
|------|--------|--------------|
| 🔴 High | Red | `COLUMN_DROPPED`, `TYPE_CHANGED`, `TABLE_DROPPED`, `COLUMN_ADDED` NOT NULL without default |
| 🟡 Medium | Amber | `INDEX_CHANGED`, `FK_CHANGED`, `CONSTRAINT_CHANGED` |
| 🟢 Low | Green | `TABLE_ADDED`, `COLUMN_ADDED` (nullable or with default) |

High-risk changes are counted in the diff's **breaking changes** total and listed in the breaking change details banner.

### Change types

| Type | Description |
|------|-------------|
| `TABLE_ADDED` | New table present in version B but not A |
| `TABLE_DROPPED` | Table present in version A removed in version B |
| `COLUMN_ADDED` | New column added to an existing table |
| `COLUMN_DROPPED` | Column removed from an existing table |
| `TYPE_CHANGED` | Column data type or length changed |
| `CONSTRAINT_CHANGED` | Column nullability or default value changed |
| `INDEX_CHANGED` | Index added, dropped, or uniqueness changed |
| `FK_CHANGED` | Foreign key added or dropped |

### DB Schema sub-tab

Changes are grouped by table. Each row shows:

- Change type badge
- Column name (where applicable)
- Old value → new value (for `TYPE_CHANGED` and `CONSTRAINT_CHANGED`)
- Risk badge (High / Medium / Low)

`COLUMN_ADDED NOT NULL without default` rows are highlighted in red as they will cause migration failures on non-empty tables.

### Summary bar

The diff summary bar includes four DB counters:

| Counter | Description |
|---------|-------------|
| DB Tables + | Tables added in version B |
| DB Tables − | Tables dropped in version B |
| DB Cols + | Columns added across all tables |
| DB Cols − | Columns dropped across all tables |

### In the change report

The exported change report (Markdown and PDF) includes a **Database Schema Changes** section per service with a risk-icon table listing every change. High-risk changes are also included in the executive summary DB Tables and DB Columns rows.

### API

DB schema diffs are included in the standard diff response — no separate endpoint is needed:

```
GET /api/v1/jar-analyser/diff/{id}
```

Each service entry in `service_diffs` includes a `db_schema_diffs` array:

```json
{
  "service": "catalog",
  "db_schema_diffs": [
    {
      "change_type": "COLUMN_ADDED",
      "table": "catalog_item",
      "column": "external_ref",
      "old_type": null,
      "new_type": "VARCHAR(255)",
      "old_nullable": null,
      "new_nullable": true,
      "risk": "low"
    },
    {
      "change_type": "TYPE_CHANGED",
      "table": "catalog_item",
      "column": "price",
      "old_type": "DECIMAL(10,2)",
      "new_type": "DECIMAL(12,4)",
      "old_nullable": null,
      "new_nullable": null,
      "risk": "high"
    }
  ]
}
```

The diff summary object also includes `db_tables_added`, `db_tables_dropped`, `db_columns_added`, and `db_columns_dropped` integer totals.

### Limitations

- Only standard ANSI SQL DDL is parsed. Database-specific syntax (e.g. MySQL `ENGINE=InnoDB`, PostgreSQL `SERIAL`, Oracle `NUMBER`) is handled at the type level but engine-specific clauses are ignored.
- Complex `ALTER TABLE` statements with multiple operations in a single statement (e.g. `ALTER TABLE t ADD COLUMN a INT, ADD COLUMN b VARCHAR(50)`) are parsed as a single ADD — only the first column is captured. Split into separate statements in migrations for full accuracy.
- Stored procedures, triggers, views, and sequences are not reconstructed.
- Column comments (`COMMENT 'text'`) are stripped during parsing.
- Migrations scanned before this feature was introduced will reconstruct correctly — the reconstructor reads the `content` field already stored in the database.


---

## 21. Migration Risk Scoring

Every Flyway migration script is automatically scored for deployment risk based on the DDL operations it contains. The score is computed at query time by replaying migrations in version order and evaluating each script against the schema state *before* it runs — so risk is assessed in context, not in isolation.

### Risk levels

| Level | Badge | Meaning |
|-------|-------|---------|
| High | 🔴 | The migration will likely fail on a non-empty database, cause irreversible data loss, or violate a referential integrity constraint |
| Medium | 🟡 | The migration may cause issues depending on data state or table size, but will not unconditionally fail |
| Low | 🟢 | Standard structural change with no known failure modes |

### Risk factors

| DDL pattern | Risk | Reason |
|-------------|------|--------|
| `ALTER TABLE … ADD COLUMN … NOT NULL` without `DEFAULT` on an existing table | 🔴 High | Will fail with `Column cannot be null` on any non-empty table. The table must be empty or a `DEFAULT` must be supplied. |
| `DROP COLUMN` | 🔴 High | Irreversible — data in the column is permanently lost. Cannot be rolled back without a restore. |
| `DROP TABLE` | 🔴 High | Irreversible — all rows in the table are permanently lost. |
| `MODIFY` / `ALTER COLUMN` on a column referenced by a foreign key in another table | 🔴 High | The referencing FK constraint may be violated if the column type or length changes incompatibly. |
| `ADD FOREIGN KEY` | 🟡 Medium | All existing rows must satisfy the new constraint. Will fail if orphaned rows exist. |
| Structural change on a table with 3 or more FK references from other tables | 🟡 Medium | Heavily-referenced tables are likely to be large and may acquire table-level locks during the migration, causing downtime. |
| `CREATE TABLE` | 🟢 Low | Additive — no effect on existing data. |
| `ADD COLUMN` (nullable or with `DEFAULT`) | 🟢 Low | Safe on non-empty tables. |
| `CREATE INDEX` / `DROP INDEX` | 🟢 Low | Index changes do not affect data integrity. |

### In the Migrations tab

The Migrations tab now shows:

- A **risk badge** (🔴/🟡/🟢) as the first column on every migration row
- **Row tinting** — high-risk rows have a red background, medium-risk rows have an amber background
- A **risk summary bar** above the table when any high or medium-risk migrations are present, showing the count of each
- A **four-way filter** (All / High / Medium / Low) to focus on migrations of a specific risk level
- **Risk reasons** in the expand panel — when you click a row, any risk factors are shown in a coloured box above the SQL content, with one bullet point per factor explaining exactly what was detected and why it is risky

Example expand panel for a high-risk migration:

```
Risk factors:
• ADD COLUMN `order.tenant_id` NOT NULL without DEFAULT — will fail on non-empty table
• MODIFY `order.status` — FK from `order_item` references this column; constraint violation risk
```

### In the API

The `/migrations` endpoint now returns `risk` and `risk_reasons` on every migration object:

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/migrations
```

New response fields per migration:

| Field | Type | Description |
|-------|------|-------------|
| `risk` | string | `"high"`, `"medium"`, or `"low"` |
| `risk_reasons` | string[] | List of plain-English explanations for each risk factor detected. Empty array for low-risk migrations. |

Example response fragment:

```json
[
  {
    "id": "...",
    "version": "1.42",
    "description": "Add tenant_id to order table",
    "script_type": "versioned",
    "statement_count": 2,
    "tables_affected": ["order"],
    "risk": "high",
    "risk_reasons": [
      "ADD COLUMN `order.tenant_id` NOT NULL without DEFAULT — will fail on non-empty table"
    ],
    "content": "ALTER TABLE order ADD COLUMN tenant_id VARCHAR(36) NOT NULL;"
  },
  {
    "id": "...",
    "version": "1.43",
    "description": "Add index on order status",
    "script_type": "versioned",
    "statement_count": 1,
    "tables_affected": ["order"],
    "risk": "low",
    "risk_reasons": [],
    "content": "CREATE INDEX idx_order_status ON order (status);"
  }
]
```

Use the `risk` field in CI/CD pipelines to gate deployments on high-risk migrations:

```bash
MIGRATIONS=$(curl -s https://platform-tools/api/v1/jar-analyser/reports/$REPORT_ID/sub-reports/$SUB_ID/migrations \
  -H "X-API-Key: $API_KEY")
HIGH_RISK=$(echo $MIGRATIONS | jq '[.[] | select(.risk == "high")] | length')
[ "$HIGH_RISK" -gt 0 ] && echo "WARNING: $HIGH_RISK high-risk migration(s) require DBA review before deployment"
```

### In the change report

The exported change report (Markdown and PDF) includes a **Migration Risk** section above the per-service changes when any high-risk migrations are present in the new version. Each high-risk migration is listed with its version, description, and risk reasons.

### Limitations

- Risk scoring is heuristic — it detects known dangerous patterns but cannot guarantee that a migration will succeed or fail. Always test migrations against a copy of production data before deploying.
- The `ADD COLUMN NOT NULL without DEFAULT` check only flags columns added to *existing* tables. A `NOT NULL` column in a `CREATE TABLE` statement is always safe.
- The FK-reference count heuristic (medium risk for tables with 3+ FK references) is based on the schema state at the time the migration runs, not on actual row counts. A heavily-referenced table with zero rows will still be flagged.
- Scoring requires the migration `content` field to be populated. Migrations where content was not extracted (e.g. very large scripts that exceeded the storage limit) will be scored as `low` by default.
- No new database migration is required for this feature — risk is computed at query time from the existing `content` field.

---

## 22. Error Message Knowledge Base

The Error Message Knowledge Base no longer has its own standalone page or API namespace inside JAR Analyser. The old **🛠 Error Lookup** button, its `/api/v1/jar-analyser/error-kb*` endpoints, and the dedicated `jar_kb_entries` table it once read from were all removed once the KB was folded into Docs — every KB entry is now an ordinary Doc (Library → Shelf → Doc, same as any other document), whose content encodes a regex pattern and severity as two parseable lines at the top, followed by normal markdown (plain-English explanation, Likely Causes, Fix Steps, See Also). One entry point, one storage model, one search index, instead of two knowledge bases slowly drifting apart.

Reached via **Docs → 🔍 Error KB Search**, with four tabs:

- **🔍 Search** — paste error text (regex-pattern match, with an automatic topic-search fallback) or browse by category keyword
- **🧵 Decode** — parses a full pasted stack trace into its actual exception chain, matches each exception against the KB independently, flags the likely root cause, and cross-references every frame against every analysed service across every upload
- **🔬 Diagnose** — this guide's own [Section 23](#23-context-aware-error-diagnosis): context-aware diagnosis scoped to one JAR Analyser report you pick, plus a **🐛 Create Bug** action on each result
- **📊 Usage** — match-count stats per KB entry, across Search/Decode/Diagnose

Plus a **+ New Entry** tab (admin/operator) for adding or extending KB entries by hand.

Full detail on all four tabs, the KB entry markdown convention, and how to add a new entry lives in the Docs guide's own **[Error Knowledge Base](docs_operations_guide.md#9-error-knowledge-base)** section — this guide only documents the one piece of it that's genuinely JAR-Analyser-specific: Section 23 below, context-aware diagnosis against a loaded report.

---

## 23. Context-Aware Error Diagnosis

Context-aware diagnosis cross-references a pasted error against the data extracted from one specific report — reached via Docs → 🔍 Error KB Search → 🔬 Diagnose tab (a dedicated tab, pick the report from a dropdown; see the Docs guide's own Error Knowledge Base section for Search/Decode/Usage, the other three tabs living alongside it). Instead of returning generic KB entries, it returns the same KB matches enriched with **report-specific context findings** — the exact services, config keys, endpoints, or migration scripts from the loaded report that are most likely involved in the error.

Diagnose deliberately stays scoped to the one report you pick — unlike Docs' own **Decode** tab, which searches every analysed upload tenant-wide, the whole point of Diagnose is "what does this mean for *this specific report*." Under the hood, though, it shares Decode's own exception-chain parser (`app/services/stack_trace_parser.py`) rather than treating the pasted text as one flat blob — see below.

### How it works

Clicking **🔬 Diagnose** calls:

```
POST /api/v1/jar-analyser/reports/{id}/diagnose
{ "error_text": "<pasted error or stack trace>" }
```

The backend:

1. Parses `error_text` into its exception chain (root + any `Caused by:`/`Suppressed:` links, same parser as Decode). Each **root cause** — the deepest link in its own chain, since Java wraps and rethrows as an error propagates up the call stack — is searched against the KB **independently**, so a wrapped root cause's own text isn't diluted by matching against the whole raw paste including an outer wrapper exception's unrelated text. A pasted snippet with no real `at ...` frames (most short/manually-typed error descriptions) doesn't parse into a real chain at all and falls back to matching the whole raw text, exactly like this endpoint's original behaviour.
2. Each root cause's own frames are checked against a class-name index built from *this report's own services only* (`JarStringConstant`, scoped by `report_id` — not the tenant-wide lookup Decode's global cross-reference uses). When a frame names a class this tool recognises as belonging to one specific service in the report, `context_findings` below are scoped to just that service instead of every service in the report; with no correlation (the common case for a short, non-trace paste), it searches the whole report exactly as before.
3. For each KB match, applies a **context rule** based on the entry's category, run against the (possibly service-scoped) report data
4. Returns each match enriched with `context_findings`, `suggested_actions`, and `matched_exception` (which parsed exception this result came from — `null` when `error_text` didn't parse into a real trace) — results across multiple root causes are deduped by KB entry id, so the same entry matched by two different exceptions in the paste still appears once.

### Context rules by category

| KB Category | Context rule applied | What it finds in the report |
|-------------|---------------------|-----------------------------|
| SSL/TLS | SSL config extractor | Config keys containing `keystore`, `truststore`, `ssl.key`, `ssl.cert`, `javax.net.ssl`, `server.ssl` across all services |
| Spring Security/Auth | Auth endpoint extractor | Secured endpoints — if the error text contains a URL path, only endpoints matching that path are returned; otherwise the first 10 secured endpoints across all services |
| Database/Flyway | DB config extractor | Config keys containing `datasource`, `jdbc`, `spring.jpa` across all services |
| RabbitMQ | RabbitMQ config extractor | Config keys containing `rabbitmq`, `amqp` across all services |
| HTTP Client | HTTP config extractor | Declared service ports and config keys containing `url`, `host`, `port`, `base-url`, `uri` with HTTP values |
| Spring Boot Startup | DB config extractor | Same as Database/Flyway — most startup failures are DB-related |

Two additional pattern overrides take priority over the category rule:

| Pattern detected in error text | Override rule applied |
|-------------------------------|---------------------|
| `Could not resolve placeholder`, `${VAR_NAME}` | Placeholder extractor — finds the specific variable name in the error and locates which service config files reference it, whether it has a default value, and whether it is mandatory |
| `FlywayException`, `checksum mismatch`, `Validate failed` | Flyway extractor — lists all migration scripts across all services with their version, description, and DDL operations |

### Diagnosis results in the UI

Diagnosis results are displayed as **blue-bordered cards** (compared to the plain grey-bordered cards in standard KB search). Each card shows:

- The KB entry header (severity badge, category pill, entry ID, title, plain-English description) — same as standard search
- A **🔬 N context findings** badge in the header showing how many report-specific findings were found
- Expandable panel containing:
  - **Likely Causes** and **Fix Steps** from the KB entry (same as standard search)
  - **📋 Report Context Findings** — a list of blue-tinted chips, one per finding, showing:
    - Service name
    - Config key and value (with amber `(placeholder)` label if the value is a `${...}` expression)
    - Red `⚠ no default` label for mandatory placeholders
    - Endpoint method and path (for auth findings)
    - Required roles (for auth findings)
    - Migration filename and version (for Flyway findings)
    - Declared port (for HTTP findings)
  - **✅ Suggested Actions** — a list of green-tinted action cards, each with:
    - A short action label
    - A description referencing the specific service and config key found
    - A **🔧 Fix with Cert Manager** deep-link button (SSL findings only) that opens the relevant SSL Cert Manager tool pre-filled with the extracted values
  - **🐛 Create Bug** — opens Bug Tracker's New Bug form (no extra API round trip — the whole prefill travels as plain data already in hand, since Diagnose and Bug Tracker are both reached from the same Docs page), pre-filled with: title (exception class + KB entry title), severity (from the KB entry), actual behaviour (the exception's own class/message), the raw pasted text as Logs/stack traces, every context finding flattened into Relevant config, the KB category as a tag, and a link to this report — plus the specific service, only when every context finding for this result agrees on one (left blank otherwise, rather than guessing). Every field stays editable before saving, same as filling the form out by hand.

### Cert Manager deep links

For SSL/TLS errors, suggested actions include **🔧 Fix with Cert Manager** deep-link buttons. The tool opened and the parameters pre-filled depend on the specific KB entry matched:

| KB entry | Error | Cert Manager tools opened |
|----------|-------|---------------------------|
| `ssl-001` / `ssl-005` | PKIX path building failed / empty trust store | TrustStore Builder (`/tools?tool=keystore&service=<name>`) + Remote Server Check (`/tools?tool=remote&host=<host>&port=<port>`) |
| `ssl-002` | SSL handshake failure | TrustStore Builder + Java TLS Debug command generator (`/tools?tool=javadebug`) + Connection Test (`/tools?tool=conntest&host=<host>&port=<port>`) |
| `ssl-003` | Certificate expired | Remote Server Check pre-filled with host:port + CSR renewal (`/csr`) |
| `ssl-004` | Hostname mismatch / no SAN | Certificate Decoder (`/tools?tool=decode`) + CSR generator pre-filled with service hostname as CN (`/csr?cn=<host>`) |
| `ssl-006` | Keystore integrity / wrong password | PKCS#12 Builder (`/tools?tool=p12`) |

The host and port values are extracted from the report's config files — `server.address`, `spring.application.name`, and `declared_port` from the service sub-report. If no hostname is found in config, the service name is used as a fallback.

The SSL Cert Manager's **Remote Server Check** and **Connection Test** tools are pre-filled with the extracted host and port via query parameters, so the check is ready to run immediately on arrival.

No cert manager backend changes are required — all links use existing tool routes with query parameters.

### API

```
POST /api/v1/jar-analyser/reports/{id}/diagnose
Content-Type: application/json

{ "error_text": "<pasted error or stack trace>" }
```

Response:

```json
{
  "report_id": "...",
  "error_text": "PKIX path building failed...",
  "total": 2,
  "results": [
    {
      "kb_entry": {
        "id": "ssl-001",
        "category": "SSL/TLS",
        "severity": "critical",
        "title": "PKIX path building failed — untrusted certificate",
        "plain_english": "Java cannot verify the server's certificate...",
        "causes": ["..."],
        "fix_steps": ["..."],
        "see_also": ["ssl-002", "ssl-005"]
      },
      "matched_exception": { "kind": "root", "exception_class": "sun.security.provider.certpath.SunCertPathBuilderException", "message": "unable to find valid certification path to requested target" },
      "context_findings": [
        {
          "service": "catalog",
          "sub_report_id": "...",
          "config_file": "application.yml",
          "config_key": "server.ssl.trust-store",
          "value": "${TRUST_STORE_PATH}",
          "is_placeholder": true
        }
      ],
      "suggested_actions": [
        {
          "label": "Build/verify trust store for catalog",
          "description": "Config key `server.ssl.trust-store` = `${TRUST_STORE_PATH}`. Use the TrustStore builder to create a merged cacerts + internal CA trust store.",
          "cert_manager_tool": "keystore",
          "cert_manager_params": { "service": "catalog" }
        },
        {
          "label": "Inspect live TLS certificate on catalog:8093",
          "description": "Use Remote Server Check to fetch and inspect the certificate chain presented by the service.",
          "cert_manager_tool": "remote",
          "cert_manager_params": { "host": "catalog", "port": 8093 }
        }
      ]
    }
  ]
}
```

`matched_exception` is `null` when `error_text` didn't parse into a real exception chain (no recognisable `at ...` frames/header) and the whole raw paste was matched instead — the pre-existing behaviour, still the fallback for a short, manually-typed error description. Every `context_findings` entry now carries its own `sub_report_id` (previously only the auth-endpoint extractor did), which is what lets the frame-correlation scoping above, and Create Bug's own-service prefill, work for any finding type.

The endpoint requires at minimum `readonly` role. It loads all sub-reports' endpoints, config files, and migration scripts in a single pass before running the context rules.

### Limitations

- Context rules are heuristic — they match config keys by substring and endpoints by path substring. They will not find every relevant config key in every case.
- The auth endpoint extractor only returns endpoints that have a `@PreAuthorize` / `@Secured` annotation. Endpoints protected only by global Spring Security configuration will not appear in context findings.
- Frame-to-service correlation depends on the class having at least one string constant of its own to be discoverable (see the Docs guide's Decode tab section for why that's true for almost all real business-logic classes, but not an absolute guarantee) — a frame naming a class this tool has never indexed simply can't correlate, and context findings fall back to searching the whole report exactly as before.
- The placeholder extractor only finds variables whose name appears literally in the error text as `${VAR_NAME}` or `'VAR_NAME'`. Variables referenced indirectly will not be found.
- Diagnosis requires a completed report. If the report is still analysing, the endpoint returns 404.

---

## 24. API Reference

All endpoints require authentication. Use either a JWT bearer token (`Authorization: Bearer <token>`) or an API key (`X-API-Key: <key>`).

### Upload & Status

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jar-analyser/upload` | Upload a JAR/WAR/ZIP for analysis |
| `GET` | `/api/v1/jar-analyser/uploads/{id}/status` | Poll analysis status |
| `POST` | `/api/v1/jar-analyser/uploads/{id}/reanalyse` | Re-run analysis on existing upload |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/reports` | List all completed reports (paginated, filterable) |
| `GET` | `/api/v1/jar-analyser/reports/{id}` | Get top-level report detail |
| `DELETE` | `/api/v1/jar-analyser/reports/{id}` | Delete a report (admin only) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports` | List all services in a report |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}` | Get service detail |

### Service Data

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints` | List endpoints (paginated, filterable) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints/{ep_id}/examples` | Request/response JSON examples for one endpoint |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/dependencies` | List dependencies |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/config` | List config files |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/schemas` | List DTO schemas |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/schemas/{class_name}` | Get single DTO schema |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/migrations` | List migration scripts |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/schema-reconstruction` | Reconstructed current DB schema (tables, columns, PKs, FKs, indexes) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/security-posture` | Security posture summary — counts by auth type, public/unannotated endpoint lists, by_role/by_authority groupings |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/events` | List event definitions |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/workflows` | List workflows |
| `POST` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/workflows` | Upload manual workflows YAML |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/scheduled-jobs` | List extracted `@Scheduled`/`@Schedules` jobs |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/errors` | List error response catalogue |

#### Endpoint filter parameters

The `/endpoints` list endpoint accepts the following query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `http_method` | string | Filter by HTTP verb (`GET`, `POST`, etc.) |
| `path_contains` | string | Substring match on full path |
| `confidence` | string | `HIGH`, `MEDIUM`, or `LOW` |
| `auth_filter` | string | `public`, `authenticated`, `role:NAME`, `authority:NAME` |
| `paginated_only` | boolean | If `true`, return only paginated endpoints |
| `deprecated_only` | boolean | If `true`, return only deprecated endpoints |
| `hide_deprecated` | boolean | If `true`, exclude deprecated endpoints from results |
| `internal_only` | boolean | If `true`, return only endpoints where `is_proxied = false` |
| `hide_internal` | boolean | If `true`, exclude endpoints where `is_proxied = true` or `null` |
| `opaque_only` | boolean | If `true`, return only endpoints where `payload_shape_known = false` — see Section 31 |
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Items per page (default: 50, max: 200) |

Endpoint objects also include `doc_summary` / `doc_description` (Section 30) and `payload_shape_known` (Section 31). DTO schema objects (`/schemas`) include a `description` field with the same developer-authored/fact semantics. Sub-report detail (`GET .../sub-reports/{sub_id}`) includes a `purpose_narrative` array (Section 32). Top-level report detail (`GET /reports/{id}`) includes `consistency_findings` (Section 29), `infra_requirements` (Section 33), and `actuator_exposure` (Section 35).

### Exports

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/reports/{id}/export/markdown` | Full report as markdown |
| `GET` | `/api/v1/jar-analyser/reports/{id}/export/json` | Full report as JSON |
| `GET` | `/api/v1/jar-analyser/reports/{id}/export/openapi` | Combined OpenAPI 3.0.3 spec (all services) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/export/sdk?lang=js\|ts` | Combined platform SDK |
| `GET` | `/api/v1/jar-analyser/reports/{id}/export/storefront-guide?lang=ts\|js` | Storefront developer guide |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/export/markdown` | Service report as markdown |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/export/openapi` | Per-service OpenAPI 3.0.3 spec |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/export/postman` | Postman Collection v2.1 |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/export/sdk?lang=js\|ts` | Per-service SDK |

### Diff

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jar-analyser/diff` | Create a diff between two reports |
| `GET` | `/api/v1/jar-analyser/diff` | List all diff reports |
| `GET` | `/api/v1/jar-analyser/diff/{id}` | Get diff detail |
| `GET` | `/api/v1/jar-analyser/diff/{id}/export/markdown` | Raw diff as markdown |
| `GET` | `/api/v1/jar-analyser/diff/{id}/export/change-report/markdown` | Formal change report (MD) |
| `GET` | `/api/v1/jar-analyser/diff/{id}/export/change-report/pdf` | Formal change report (PDF) |

### Search & Integration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/search?q=...` | Cross-report full-text search (endpoints/dependencies/config/schemas/events/migrations) |
| `GET` | `/api/v1/jar-analyser/strings/search?q=...` | Cross-report string-constant search (Section 37) — optional `report_id` to scope to one upload |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/strings?q=...` | One service's own string constants, browsable/filterable |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/outbound-integrations` | One service's outbound integration signals (Section 38) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/outbound-integrations` | Every service's outbound integration signals across the whole report |
| `GET` | `/api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/outbound-call-sites` | One service's decompiled-source call-site response/error-handling signals (Section 39) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/outbound-call-sites` | Every decompiled service's call-site signals across the whole report |
| `GET` | `/api/v1/jar-analyser/reports/{id}/auth-requirements` | Aggregated auth requirements (roles, authorities, public endpoints) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/topology` | Inter-service dependency graph (nodes + edges) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/message-bus` | Cross-service RabbitMQ event topology (publishers, consumers, exchange/routing key) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/ssl-requirements` | SSL cert SAN suggestions for this platform version |
| `GET` | `/api/v1/jar-analyser/reports/{id}/build-manager-feed` | Service inventory feed for Build Manager |
| `GET` | `/api/v1/jar-analyser/reports/{id}/nginx-configs` | Four Nginx config variants (on-prem standard/HA, AWS/ALB, Docker) |
| `GET` | `/api/v1/jar-analyser/reports/{id}/env-vars` | Environment variable / placeholder catalogue — mandatory/optional split, filterable by category, service, or `mandatory_only` |
| `GET` | `/api/v1/jar-analyser/reports/{id}/port-inventory` | All declared ports across all services |

### Error Knowledge Base & Diagnosis

KB entries themselves are ordinary Docs now, not a JAR-Analyser-owned table — see [Section 22](#22-error-message-knowledge-base) and the Docs guide's own `GET/POST /docs/error-kb/*` endpoints (search, decode, categories, usage). The one endpoint still owned by JAR Analyser is the report-scoped diagnosis itself:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/jar-analyser/reports/{id}/diagnose` | Context-aware diagnosis, scoped to this one report — KB match enriched with report-specific findings (Section 23) |

### Diagnostics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostic-script` | Download report-specific bash collection script |
| `POST` | `/api/v1/jar-analyser/reports/{id}/diagnostics` | Upload a diagnostic bundle (`.tar.gz`) and trigger analysis |
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostics` | List all diagnostic runs for a report |
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostics/{run_id}` | Get full diagnostic run detail |
| `DELETE` | `/api/v1/jar-analyser/reports/{id}/diagnostics/{run_id}` | Delete a diagnostic run (admin only) |


---

## 25. Integration with Other Tools

### SSL Cert Manager

The `/ssl-requirements` endpoint returns a structured payload that the SSL Cert Manager can consume directly to suggest SANs and SSL configuration for a platform deployment. It extracts keystore/truststore paths, enabled TLS protocols, and client-auth requirements from the scanned config files.

#### SSL/TLS Diagnostic Integration (Priority 20)

The JAR Analyser's context-aware diagnosis is deeply integrated with the SSL Cert Manager's existing tools. When an SSL/TLS error is diagnosed against a loaded report, the suggested actions include **🔧 Fix with Cert Manager** buttons that open the relevant tool pre-filled with values extracted from the report's config files.

The integration is entirely frontend-driven — no SSL Cert Manager backend changes are required. The JAR Analyser backend extracts the host, port, trust store path, and keystore path from the report's config files and returns them as `cert_manager_tool` and `cert_manager_params` fields in the diagnosis response. The frontend constructs the deep-link URL and opens it in a new tab.

**Tool routing by error type:**

| SSL error | Config data extracted | Cert Manager tool | Pre-filled fields |
|-----------|----------------------|-------------------|-------------------|
| PKIX path building failed (`ssl-001`) | Trust store config key + service port | TrustStore Builder + Remote Server Check | `service=<name>`, `host=<host>`, `port=<port>` |
| Empty trust store (`ssl-005`) | Trust store config key + service port | TrustStore Builder + Remote Server Check | `service=<name>`, `host=<host>`, `port=<port>` |
| SSL handshake failure (`ssl-002`) | Trust store config key + service port | TrustStore Builder + Java TLS Debug + Connection Test | `host=<host>`, `port=<port>` |
| Certificate expired (`ssl-003`) | Service hostname + declared port | Remote Server Check + CSR renewal | `host=<host>`, `port=<port>` |
| Hostname mismatch (`ssl-004`) | Service hostname + declared port | Certificate Decoder + CSR generator | `cn=<host>` |
| Keystore integrity / wrong password (`ssl-006`) | Keystore config key | PKCS#12 Builder | — |

**Hostname resolution order** (for `host` parameter):
1. `server.address` config key value (if not a placeholder)
2. `spring.application.name` config key value (if not a placeholder)
3. Service name from the sub-report

**ToolsPage deep-link support:** The SSL Cert Manager's `/tools` page reads the `?tool=` query parameter on load and pre-selects the corresponding tool tab. The Remote Server Check tool additionally reads `?host=` and `?port=` query parameters to pre-fill its input fields, so the check is ready to run immediately on arrival.

**Supported tool routes:**

| `cert_manager_tool` value | URL opened |
|--------------------------|------------|
| `keystore` | `/tools?tool=keystore` |
| `remote` | `/tools?tool=remote&host=<host>&port=<port>` |
| `javadebug` | `/tools?tool=javadebug` |
| `conntest` | `/tools?tool=conntest&host=<host>&port=<port>` |
| `decode` | `/tools?tool=decode` |
| `p12` | `/tools?tool=p12` |
| `csr` | `/csr?cn=<cn>` |

### Build Manager

The `/build-manager-feed` endpoint returns a service inventory in the format expected by the Build Manager's environment provisioning system. It includes per-service infrastructure requirements (database, RabbitMQ, config server), firewall ports, systemd unit names, and dependency ordering.

### CI/CD Pipeline Integration

The API is designed to be called from CI/CD pipelines. A typical pipeline step:

```bash
# Upload the new release JAR
UPLOAD=$(curl -s -X POST https://platform-tools/api/v1/jar-analyser/upload \
  -H "X-API-Key: $API_KEY" \
  -F "file=@release.zip" \
  -F "label=v2.7.0-rc1")

UPLOAD_ID=$(echo $UPLOAD | jq -r .upload_id)

# Wait for analysis
while true; do
  STATUS=$(curl -s https://platform-tools/api/v1/jar-analyser/uploads/$UPLOAD_ID/status \
    -H "X-API-Key: $API_KEY" | jq -r .status)
  [ "$STATUS" = "completed" ] && break
  [ "$STATUS" = "failed" ] && exit 1
  sleep 5
done

REPORT_ID=$(curl -s https://platform-tools/api/v1/jar-analyser/uploads/$UPLOAD_ID/status \
  -H "X-API-Key: $API_KEY" | jq -r .report_id)

# Assert no unintended public endpoints were introduced
AUTH=$(curl -s https://platform-tools/api/v1/jar-analyser/reports/$REPORT_ID/auth-requirements \
  -H "X-API-Key: $API_KEY")
PUBLIC_COUNT=$(echo $AUTH | jq .summary.public_endpoint_count)
[ "$PUBLIC_COUNT" -gt "$EXPECTED_PUBLIC_COUNT" ] && echo "WARNING: new public endpoints detected"

# Generate change report against previous release
DIFF=$(curl -s -X POST https://platform-tools/api/v1/jar-analyser/diff \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"report_a_id\": \"$PREV_REPORT_ID\", \"report_b_id\": \"$REPORT_ID\"}")

DIFF_ID=$(echo $DIFF | jq -r .diff_id)

# Download change report PDF
curl -s https://platform-tools/api/v1/jar-analyser/diff/$DIFF_ID/export/change-report/pdf \
  -H "X-API-Key: $API_KEY" -o change-report.pdf
```

---

## 26. Analysis Accuracy & Limitations

The analyser operates on compiled bytecode, not source code. This has implications:

**What works well:**
- Spring MVC `@RequestMapping` family annotations are reliably extracted
- JAX-RS `@Path` annotations are reliably extracted
- Lombok `@Data` / `@Builder` classes are detected and their fields inferred
- `@JsonProperty` names are extracted accurately
- `@PreAuthorize` / `@Secured` SpEL expressions are parsed into structured auth requirements
- Flyway migration scripts are extracted verbatim
- Validation annotations (`@NotNull`, `@Size`, `@Min`, `@Max`, etc.) are extracted from field descriptors

**Known limitations:**
- Generic return types (e.g. `ResponseEntity<List<MyDto>>`) may resolve to `unknown` if the generic parameter is erased at compile time
- Programmatically registered routes (e.g. `RouterFunction` in Spring WebFlux) are not detected
- Endpoints behind dynamic proxies or reflection may be missed
- Config values that are resolved at runtime from environment variables appear as `${ENV_VAR}` placeholders
- Spring Cloud Gateway Java DSL routes (`RouteLocatorBuilder`) are extracted at `MEDIUM` confidence — path patterns are recovered from the constant pool but complex predicate chains may not fully resolve
- `@RequestParam` annotations may not be present in bytecode if debug info was stripped during compilation — in this case pagination detection falls back to return-type analysis only
- **Deprecation detection** — only method-level `@Deprecated` annotations are detected. Class-level controller deprecation is not propagated to individual endpoint rows. Endpoints scanned before migration `037` was applied will have `is_deprecated: false` regardless of their actual state; use ↺ Re-run to refresh.
- **Internal endpoint detection** — detection is service-level, not path-level. Individual path exclusions in the Nginx config are not resolved. Bundles without an `nginx_installer` sub-report will have `is_proxied = null` on all endpoints. Endpoints scanned before migration `039` was applied will have `is_proxied = null`; use ↺ Re-run to populate.
- **Security posture summary** — derived from `parsed_auth_json` on each endpoint. Endpoints scanned before auth extraction was implemented will have inflated `unannotated_count`. Global Spring Security configuration (`HttpSecurity`) is not parsed — unannotated endpoints may still be protected by a global rule. Use ↺ Re-run to refresh auth data.
- **Migration risk scoring** — heuristic-based; detects known dangerous DDL patterns but cannot guarantee migration success or failure. Risk is computed at query time from the stored `content` field — no re-run is needed to see risk scores on previously analysed JARs. Migrations where `content` was not extracted are scored `low` by default.
- **Storefront Guide method names** — method names in the generated code examples are taken from the Java bytecode method name, which does not always correspond to the HTTP path. For example, a method named `getOptionsModel` may be the handler for `GET /portal/catalog-items/{id}/options-model`. The method name is used as-is from the bytecode; the authoritative mapping is the `@auth` JSDoc comment in Section 3 of the guide, which always shows the exact HTTP verb and path.
- **Consistency findings** — heuristic cross-checks between independently-extracted data, not confirmed defects; a flagged mismatch always needs manual checking. See Section 29.
- **Developer-authored documentation** — only present where the codebase actually uses `@Operation`/`@Schema` annotations; largely or entirely absent bundles will show no authored text. See Section 30.
- **Endpoint confidence & opaque payload flagging** — `payload_shape_known` can only ever be as accurate as bytecode generic erasure allows; a generic container's element type (e.g. `ResponseEntity<T>`) is fundamentally unrecoverable from the method descriptor, so it is always reported as opaque even if the real element type is well understood by the original developers. See Section 31.
- **Perceived Purpose narrative** — a rule-based synthesis, not an LLM or live-verified summary; every inferred statement is explicitly hedged and should be read as "worth considering," not "confirmed." See Section 32.
- **Infrastructure Requirements** — depends entirely on what's statically present in config keys and migrations; externally-parameterised values (the norm for production-profile config in most real bundles) cannot be resolved to a literal, and RabbitMQ exchange/queue/routing-key names are frequently unresolvable from event definitions alone. Every gap is stated explicitly rather than silently omitted. See Section 33.
- **Scheduled jobs** — a Spring placeholder value (`${...}`, including one embedded inside a `#{...}` SpEL expression) is never resolved to a literal cadence; it's flagged as config-driven instead. `@Scheduled` on non-Spring-managed classes (never registered as a bean) would still be extracted even though it would never actually run — this tool cannot know bean registration, only annotation presence. See Section 34.
- **Actuator/management endpoint exposure** — checks only the framework-level `management.endpoints.web.exposure.*` configuration; custom Spring Security rules that separately restrict `/actuator/**` are not parsed (same limitation as Security Posture, Section 17). A finding here is a "worth manually checking" signal, not a confirmed live vulnerability. See Section 35.
- **On-demand decompilation** — local variable and parameter names only survive if the jar was compiled with debug info retained (the default for most Maven/Gradle builds, but not universal); without it, CFR emits generic names (`var1`, `var2`, ...) instead of the original identifiers. Decompiled source is a reconstruction, not the original — comments and exact formatting are never recoverable, and CFR's fidelity, while very good, is not perfect on unusual bytecode (heavy `invokedynamic`/lambda metaprogramming, some annotation-processor-generated code). See Section 36.

**Spring Cloud Gateway routes** are extracted from three sources:
- `application.yml` / `application.properties` — `spring.cloud.gateway.routes[*]` blocks are parsed as structured data. Path predicates, Method predicates, filters, and target URIs (`lb://service-name`) are all extracted. Confidence: `HIGH`.
- `@Bean RouteLocator` methods — `@Configuration` classes with `@Bean` methods returning `RouteLocator` are detected. Path patterns and `lb://` URIs are recovered from the class constant pool. Confidence: `MEDIUM`.
- `@Bean RouterFunction` methods — same constant-pool approach for WebFlux functional routing. Confidence: `MEDIUM`.

Gateway routes appear in the Endpoints tab alongside regular controller endpoints. The `source_annotation` field is `SCG:yaml`, `SCG:bean`, or `SCG:router`. The `base_path` field contains the target URI (e.g. `lb://catalog-service`).

**Confidence levels:**
- `HIGH` — annotation found directly on the method, path fully resolved
- `MEDIUM` — annotation found but path partially inferred
- `LOW` — endpoint inferred from class structure without a direct annotation match

Low-confidence endpoints should be verified against the running service before being relied upon.

---

## 27. Roles & Permissions

| Action | Admin | Operator | Auditor | ReadOnly |
|--------|:-----:|:--------:|:-------:|:--------:|
| Upload JAR | ✓ | ✓ | ✗ | ✗ |
| View reports | ✓ | ✓ | ✓ | ✓ |
| Export (all formats) | ✓ | ✓ | ✓ | ✓ |
| Create diff | ✓ | ✓ | ✓ | ✓ |
| Re-run analysis | ✓ | ✓ | ✗ | ✗ |
| Upload workflows | ✓ | ✓ | ✗ | ✗ |
| Delete report | ✓ | ✗ | ✗ | ✗ |
| Search | ✓ | ✓ | ✓ | ✓ |
| View topology | ✓ | ✓ | ✓ | ✓ |
| View auth requirements feed | ✓ | ✓ | ✓ | ✓ |
| Search error KB | ✓ | ✓ | ✓ | ✓ |
| Create / edit KB entry | ✓ | ✓ | ✗ | ✗ |
| Delete KB entry | ✓ | ✗ | ✗ | ✗ |
| Context-aware diagnosis | ✓ | ✓ | ✓ | ✓ |
| Download diagnostic script | ✓ | ✓ | ✓ | ✓ |
| Upload diagnostic bundle | ✓ | ✓ | ✗ | ✗ |
| View diagnostic runs | ✓ | ✓ | ✓ | ✓ |
| Delete diagnostic run | ✓ | ✗ | ✗ | ✗ |
| Download diagnostic script | ✓ | ✓ | ✓ | ✓ |
| Upload diagnostic bundle | ✓ | ✓ | ✗ | ✗ |
| View diagnostic runs | ✓ | ✓ | ✓ | ✓ |
| Delete diagnostic run | ✓ | ✗ | ✗ | ✗ |

---

## 28. Diagnostic Collection Tool

The **🩺 Diagnostics** button on the top-level report view opens a workflow for collecting live server diagnostics and analysing them against the report's known configuration. It is designed for situations where a service is misbehaving on a deployed server and you need to correlate what the JAR Analyser knows about the platform with what is actually happening on the host.

### Workflow overview

1. Click **🩺 Diagnostics** on any top-level report
2. Click **⬇ Download Collection Script** — a bash script tailored to this specific report is generated and downloaded
3. Copy the script to the target server and run it: `sudo bash diag-collect-<version>.sh`
4. The script produces a timestamped `.tar.gz` bundle at `/tmp/diag_<hostname>_<timestamp>.tar.gz`
5. Upload the bundle via the **Upload Diagnostic Bundle** panel
6. The analyser unpacks and processes the bundle in the background — the run status polls automatically
7. Select the completed run from the run list to view findings

### Collection script

The script is generated at download time from the report's extracted data — it knows the install paths, config file locations, SSL keystore/truststore paths, declared ports, and RabbitMQ connection details for every service in the bundle. It does not need to be edited before running.

The script collects:

| Category | What is collected |
|----------|------------------|
| System info | `uname`, `/etc/os-release`, hostname, date, uptime, `df -h`, `free -m`, `java -version`, `JAVA_HOME`, listening ports (`ss`/`netstat`), systemd failed units |
| JVM cacerts | `keytool -list` output from the JVM's `lib/security/cacerts` |
| Per-service config files | `application.properties`, `application.yml`, and profile variants from the known install path |
| Per-service logs | Last 2000 lines of every `.log`/`.out`/`.err` file in the service log directory |
| Per-service journal | Last 500 lines from `journalctl -u <service>` |
| SSL cert metadata | `openssl x509 -text` (PEM/CRT) or `keytool -list` (JKS/P12) output — **no private key material is collected** |
| Port checks | TCP reachability check for every declared service port and DB port |
| RabbitMQ | TCP check on AMQP port + `curl` to the management API (`/api/overview`, `/api/nodes`) if accessible |
| Nginx | `/etc/nginx` and `/opt/nginx/conf` config files, last 200 lines of nginx journal |
| Manifest | `manifest.json` recording report ID, platform version, hostname, OS, and collected services |
| Capabilities | `capabilities.json` recording which tools were available on the host |

The bundle is packaged as a `.tar.gz` and the script prints the output path on completion.

### Script prerequisites

The script is designed to run as much as possible even when optional tools are absent — it detects available tools at startup and skips sections gracefully when a tool is missing. The only hard requirement is `bash` and `tar`.

| Tool | Used for | Fallback if absent |
|------|----------|--------------------|
| `openssl` | PEM/CRT certificate inspection | `[SKIP]` message written to cert output file |
| `keytool` (JDK) | JKS/P12 keystore inspection + JVM cacerts | `[SKIP]` message written to cert output file |
| `java` | `java -version` + locating JVM cacerts | JVM section skipped |
| `nc` (netcat) | TCP port connectivity checks | Falls back to bash `/dev/tcp` redirection |
| `curl` | RabbitMQ management API queries | `[SKIP]` message written; port check still runs |
| `ss` | Listening port list | Falls back to `netstat`; if neither present, `[SKIP]` noted |
| `netstat` | Listening port list (fallback) | Skipped if `ss` also absent |
| `journalctl` | Systemd service journal | `[SKIP]` message written to journal file |
| `grep -P` (PCRE) | DB URL host/port extraction | Falls back to `sed`-based extraction |
| `tar`, `gzip` | Bundle packaging | **Required** — pre-installed on all supported distros |

#### Recommended packages by OS

Install these before running the script for full coverage:

| OS | Package manager | Packages |
|----|----------------|----------|
| RHEL / CentOS 8+ | `dnf install` | `openssl`, `java-17-openjdk`, `nmap-ncat`, `curl`, `iproute` |
| Ubuntu / Debian | `apt-get install` | `openssl`, `default-jdk`, `netcat-openbsd`, `curl`, `iproute2` |
| Amazon Linux 2023 | `dnf install` | `openssl`, `java-17-amazon-corretto`, `nmap-ncat`, `curl`, `iproute` |
| Alpine Linux | `apk add` | `openssl`, `openjdk17`, `netcat-openbsd`, `curl`, `iproute2` |

The prerequisites panel on the Diagnostics page shows this table inline alongside the download button.

### Limited collection warning

When a bundle is uploaded from a server where one or more tools were absent, the completed run displays an amber **⚠ Limited collection** banner listing the missing tools. The banner notes which analysis passes are incomplete (certificate inspection, JVM cacerts, journal logs, port checks) and directs you to install the missing packages and re-run the script for a full report.

The `capabilities.json` file in the bundle records the exact tool availability at collection time. The analyser reads this file and sets `limited_collection: true` in the run summary when any key tool was absent.

### Analysis passes

When a bundle is uploaded the analyser runs five passes:

| Pass | What it does |
|------|-------------|
| **Certificate analysis** | Parses every `openssl x509 -text` and `keytool -list` output file. Extracts subject, issuer, expiry date, SANs, and alias list. Flags expired certificates and certificates expiring within 30 days. |
| **Log / journal scan** | Runs the Error KB pattern matcher against every collected log tail and journal file. Returns KB matches with the triggering log line and fix steps. |
| **Config validation** | Compares collected config files against the report's known placeholder variables. Flags unresolved `${VAR}` expressions and mandatory variables that have no default and appear unset. |
| **Port reachability** | Parses every `port_*.txt` file written by the script's `port_check()` function. Returns open/closed status per service and port. |
| **RabbitMQ summary** | Parses the management API `overview.json` if collected. Extracts RabbitMQ version, Erlang version, node name, and message stats. |

### Run results

Completed runs display:

- **Summary cards** — cert issues, port checks, log findings, config issues
- **⚠ Limited collection banner** (if applicable) — lists missing tools
- **OS / Environment Info** — collapsible raw `os_info.txt` content
- **Certificate Analysis** — per-cert table with subject, expiry, days remaining, and any issues
- **Port Checks** — per-port open/closed table
- **RabbitMQ** — version, Erlang version, node, message stats
- **Log Findings** — KB matches from log/journal files with severity badge, service, and triggering line
- **Config Issues** — unresolved placeholders and mandatory unset variables
- **All Findings** — deduplicated, severity-sorted combined list of all findings from all passes

### Multiple runs

Multiple bundles can be uploaded for the same report — for example, one per server in a multi-node deployment, or before and after a configuration change. All runs are listed in the left panel; click any run to view its results. Runs can be deleted individually (admin only).

### API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostic-script` | Download the report-specific collection script (`.sh`) |
| `POST` | `/api/v1/jar-analyser/reports/{id}/diagnostics` | Upload a `.tar.gz` bundle — triggers background analysis |
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostics` | List all diagnostic runs for this report |
| `GET` | `/api/v1/jar-analyser/reports/{id}/diagnostics/{run_id}` | Get full run detail including all findings |
| `DELETE` | `/api/v1/jar-analyser/reports/{id}/diagnostics/{run_id}` | Delete a run (admin only) |

`POST /diagnostics` accepts a `multipart/form-data` body with a single `file` field. The bundle must be a `.tar.gz` file and must not exceed 500 MB. The response is returned immediately with `status: "pending"` and a `status_url` to poll.

`GET /diagnostics/{run_id}` response (completed run):

```json
{
  "run_id": "...",
  "report_id": "...",
  "status": "completed",
  "uploaded_by": "admin",
  "uploaded_at": "2026-07-20T10:00:00Z",
  "bundle_filename": "diag_myserver_20260720_100000.tar.gz",
  "bundle_size_bytes": 1048576,
  "hostname": "myserver.example.internal",
  "os_id": "rhel",
  "platform_version": "2.6.9",
  "summary": {
    "total_findings": 3,
    "critical": 1,
    "high": 1,
    "medium": 1,
    "low": 0,
    "cert_files_analysed": 4,
    "log_files_scanned": 6,
    "ports_checked": 8,
    "config_files_collected": 12,
    "limited_collection": false,
    "missing_tools": []
  },
  "cert_results": [...],
  "port_results": [...],
  "rmq_summary": {...},
  "config_issues": [...],
  "log_findings": [...],
  "findings": [...],
  "os_info": "=== uname ===\nLinux myserver ..."
}
```

### Database

Diagnostic runs are stored in the `jar_diagnostic_runs` table (migration `041`):

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `report_id` | UUID | FK to `analysis_reports` |
| `uploaded_by` | VARCHAR | Username |
| `uploaded_at` | DATETIME | Upload timestamp |
| `bundle_filename` | VARCHAR | Original filename |
| `bundle_size_bytes` | INTEGER | Bundle size |
| `hostname` | VARCHAR | Hostname from `manifest.json` |
| `os_id` | VARCHAR | OS ID from `manifest.json` (e.g. `rhel`, `ubuntu`) |
| `platform_version` | VARCHAR | Platform version from `manifest.json` |
| `status` | VARCHAR | `pending`, `analysing`, `completed`, `failed` |
| `summary_json` | TEXT | Summary counts JSON |
| `findings_json` | TEXT | All findings JSON |
| `cert_results_json` | TEXT | Certificate analysis results JSON |
| `port_results_json` | TEXT | Port check results JSON |
| `rmq_summary_json` | TEXT | RabbitMQ summary JSON |
| `config_issues_json` | TEXT | Config validation issues JSON |
| `log_findings_json` | TEXT | Log/journal KB matches JSON |
| `os_info` | TEXT | Raw `os_info.txt` content |
| `error` | TEXT | Error message if status is `failed` |

### Limitations

- The collection script requires `sudo` (or root) to read service config files and keystores that are owned by the service user. Running without `sudo` will result in many `[SKIP]` entries in the collection log.
- Private key files are never collected — the script only reads certificate metadata via `openssl x509 -text` and `keytool -list`. Keystore passwords are not collected either; `keytool -list` is attempted with `changeit` and then with an empty password as fallbacks.
- Log collection is limited to the last 2000 lines per file and 500 journal lines per service to keep bundle sizes manageable. For deep log analysis, collect logs separately.
- The RabbitMQ management API check uses default credentials (`guest:guest`). If the management API is secured with non-default credentials, the `overview.json` will be empty or contain an auth error.
- Bundle size is capped at 500 MB on upload. Very large log directories should be excluded or the log tail limit reduced by editing the script before running.
- Analysis runs as a background task. If the server is restarted while a run is in `analysing` state, the run will remain stuck. Delete it and re-upload the bundle.

---

## 29. Consistency Findings (Static Cross-Validation)

Endpoints, DTO schemas, Flyway migrations, event definitions, and Nginx/frontend config are all extracted independently of each other. Since there is no live system to verify against, cross-checking these independently-extracted sources against one another is the next best source of accuracy signal — a genuine mismatch between two independently-derived facts is a real finding, not a guess.

### What gets cross-checked

| Check | Compares | Flags when |
|-------|----------|-----------|
| DTO field type vs. DB column type | A DTO field's bytecode-derived type (via `table_linker.py`'s endpoint→table linkage) against the Flyway-reconstructed column type for the same field | The type families are incompatible (e.g. DTO says `int`, migration defines `VARCHAR`) — text/numeric/boolean/datetime family mismatches only, to avoid noise. MySQL `TINYINT` is recognised as the standard boolean-storage convention and is not flagged against a `boolean` DTO field. |
| Event payload vs. DTO schema | An event's declared `payload_class` (from `.event.yml`) against the set of DTO schemas actually extracted in this bundle | The payload class isn't found — either it's a cross-JAR resolution gap (see below) or the event definition is stale/aspirational |
| Service wiring | Service names referenced by Nginx upstream config and frontend `api.<service>.url` keys against the actual sub-report service names in the bundle | A referenced service name doesn't resolve to any analysed sub-report (after normalising `-svc`/`-upstream` suffixes and camelCase/kebab-case) |
| Cross-service DTO resolution gaps | DTO/event payload class names against schemas extracted from every sub-report in the bundle (not just the owning service) | A class is referenced from another service but never extracted anywhere — likely a shared library type not present as its own JAR entry. Flagged as a resolution gap, not a defect, since resolving genuinely cross-JAR shared types is out of scope. |

All four checks are deliberately conservative — only high-confidence, low-noise signals are surfaced. On the real `installation-package` bundles used to validate this feature, an early version of the type-family check produced 292 false positives from the MySQL-boolean-as-`TINYINT` convention alone; the check was tightened until real findings were sparse enough to review individually.

### In the UI

The top-level report view shows a blue **🔍 N Consistency Finding(s)** banner (only when findings exist) listing up to 50 findings with a `[type]` tag and a plain-English note. A footer indicates when more findings exist than are shown (export the full report for the complete list).

### API

`GET /api/v1/jar-analyser/reports/{id}` includes a `consistency_findings` array:

```json
{
  "consistency_findings": [
    {
      "type": "dto_db_type_mismatch",
      "service": "catalog",
      "note": "Field 'price' on CatalogItemDto is typed as 'string' but the linked column 'catalog_item.price' is DECIMAL(10,2)"
    },
    {
      "type": "event_payload_unresolved",
      "service": "customers",
      "note": "Event 'contract/renewed' declares payload class ContractRenewalPayload, which was not found in any analysed sub-report"
    }
  ]
}
```

Each finding is tagged with the `service` it was found against and a plain-English `note`. Findings are computed once per analysis run and persisted — no separate endpoint call is needed.

### Limitations

- Findings are heuristic cross-checks, not confirmed defects — always worth manually checking, never a definitive bug report.
- Only high-confidence, conservative signals are surfaced by design; a genuine issue that doesn't clear the noise threshold will not be flagged.
- Cross-service DTO resolution gaps cannot distinguish "shared library type not present as a JAR entry" from "genuinely broken/stale event definition" — both produce the same finding type.
- Computation is best-effort — a bug in any individual check logs an error and returns no findings for that run rather than failing the whole analysis.
- Re-run analysis (↺ Re-run) to compute findings on reports analysed before this feature was introduced.

---

## 30. Developer-Authored Documentation

Javadoc and source-code comments are stripped by the Java compiler and are never present in bytecode — but annotation *element values* (string literals passed to annotations) survive compilation. `@Operation(summary=..., description=...)` and `@Schema(description=...)` are the only source of real developer intent this tool can ever access, so they are extracted and deliberately kept visually and structurally distinct from anything this tool infers.

### What gets extracted

| Source | Field | Where it ends up |
|--------|-------|-------------------|
| `@Operation(summary=...)` | `doc_summary` | `JarEndpoint.doc_summary` |
| `@Operation(description=...)` | `doc_description` | `JarEndpoint.doc_description` |
| `@Schema(description=...)` on a DTO class | `description` | `JarDtoSchema.description` |
| `@Schema(description=...)` on a DTO field | `description` | Embedded in that field's entry in `fields_json` |

Old-style `@ApiOperation`/`@ApiModel` (Swagger 2) annotations are not currently extracted — a real-data check across the reference `installation-package` bundles found 218 `@Operation` and 442 `@Schema` occurrences and zero old-Swagger occurrences, so springdoc/OpenAPI 3 annotations were prioritised.

### In the UI

Wherever this text appears, it is labeled **"Developer-authored"** in green/emerald styling — never mixed in with inferred content:

- **Endpoints tab** — a short `doc_summary` line appears under the path in the table row; expanding a row shows a green "Developer-authored (@Operation)" card with the full `doc_summary`/`doc_description`.
- **Schemas tab** — a green "Developer-authored (@Schema)" card appears above the field table when a class-level `description` is present; individual fields with their own description show a small "i" marker (hover for the text).
- **Perceived Purpose card** (Section 32) — when present, authored text is surfaced first and labeled **Fact**, distinct from the **Inferred** statements below it.

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/schemas
```

Endpoint objects include `doc_summary` and `doc_description` (both `null` when absent). DTO schema objects include `description` (class-level) and each field in `fields_json` includes its own `description`.

### Limitations

- Only present where the analysed codebase actually uses `@Operation`/`@Schema` — a bundle that doesn't use these annotations will show no authored text anywhere, and this is expected rather than a bug.
- `@Operation(description=...)` values are often written for API-reference documentation and may include markdown sub-sections (roles-allowed lists, example JSON request/response bodies) — see Section 32 for how the Perceived Purpose narrative cleans these into short snippets. The Endpoints tab detail panel shows the text verbatim, including any markdown.

---

## 31. Endpoint Confidence & Opaque Payload Flagging

Confidence was previously binary and based only on whether the annotation's path parsed cleanly — it said nothing about whether the *payload shape* was actually known. A fully-resolved DTO and a raw `ResponseEntity<?>` used to get reported identically. Confidence is now a combination of annotation clarity and payload resolution, and an explicit `payload_shape_known` flag makes the boundary of what this tool can know visible instead of papering over it.

### Why generic containers are fundamentally unresolvable

Java method descriptors (JVMS §4.3.3) erase generic type parameters — `ResponseEntity<CustomerDto>` and `ResponseEntity<?>` compile to the exact same descriptor. There is no way to statically recover the wrapped type of a generic container from bytecode alone. This is not a gap that could be closed with more extraction work — it's a fundamental limit of what survives compilation.

### Resolution rules

A return type or request body is considered **resolved** (payload shape known) when:
- It's a well-known JDK/wrapper scalar (`String`, `Integer`, `Boolean`, `LocalDate`, `UUID`, etc.), or
- Its simple type name matches a DTO schema actually extracted from this bundle

It is considered **opaque** (payload shape not known) when:
- It's a generic container whose element type is erased (`ResponseEntity`, `Response`, `List`, `Map`, `Optional`, `Page`, etc. — regardless of what the source code specifies in angle brackets), or
- It's a raw `Object`/`void` with no structure, or
- It's a type name not found anywhere in this bundle (an unresolvable external type)

### Confidence combination

Starting from the existing annotation-clarity confidence (`HIGH`/`MEDIUM`), the count of opaque directions (return type, request body) only ever **downgrades**, never upgrades:

| Opaque count | Effect |
|--------------|--------|
| 0 | Confidence unchanged |
| 1 (one of return/request is opaque) | `HIGH` → `MEDIUM`; `MEDIUM` stays `MEDIUM` |
| 2 (both opaque) | Confidence set to `LOW` |

On the real `installation-package` bundles, this surfaced that 579 of 1016 endpoints (57%) have an opaque payload in at least one direction — dominated by JAX-RS `Response` return types, which are ubiquitous in that codebase and always opaque under the erasure rule above.

### In the UI

- Endpoint rows show an **opaque payload** badge (orange) in the path cell when `payload_shape_known = false`.
- The **Opaque payload only** checkbox filter shows only endpoints with an unresolved payload shape.
- The expanded endpoint detail panel shows an orange notice explaining that the shown type name should be treated as a container, not a resolved contract, when opaque.

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/endpoints?opaque_only=true
```

Endpoint objects include `payload_shape_known` (boolean). See the filter parameter table in Section 24.

### Limitations

- `payload_shape_known` is a boundary marker, not a defect flag — a `false` value simply means this tool cannot know the shape, not that anything is wrong with the endpoint.
- The erasure limitation is permanent for generic containers; no future extraction improvement can recover an erased type parameter from the method descriptor alone.
- Confidence only ever downgrades from the annotation-clarity baseline — a `MEDIUM` endpoint with fully resolved payloads stays `MEDIUM`, it is never upgraded to `HIGH`.

---

## 32. Perceived Purpose Narrative

Nothing elsewhere in this tool synthesises a narrative — every other view is a mechanical listing of extracted facts. The Perceived Purpose card combines several already-extracted signals into a short, evidence-cited summary of what a service appears to do.

### Signals combined

| Signal | Source | Framing |
|--------|--------|---------|
| Developer-authored text | `@Operation`/`@Schema` (Section 30) | Fact — quoted directly, weighted above everything else when present |
| Platform categorisation | `part.yml` group/name (`installer_meta.py`) | Fact — the platform's own architects' categorisation |
| Domain vocabulary | Most frequent meaningful tokens from DTO class names, DB table names, and controller names (structural/technical words like `Dto`, `Controller`, `Response` excluded) | Inferred |
| Event topology role | Ratio of published to consumed events for the service | Inferred |
| DB ownership | Tables created/altered by the service's own Flyway migrations | Inferred |
| Dependency fingerprint | Bundled cloud-SDK dependencies (AWS/Azure/Google Cloud) | Inferred |
| Auth posture | Ratio of public vs. role/authority-gated endpoints | Inferred |

### The one hard constraint

Every **inferred** statement is phrased as *"Based on the following static evidence — ... — this service appears to ..."*, with the evidence cited inline, never asserted as fact. Statements built from genuine facts (authored text, `part.yml` categorisation) are phrased plainly instead — hedging a fact would be dishonest in the other direction. This distinction is non-negotiable and is enforced structurally: every statement carries an explicit `is_inference` flag.

### In the UI

The sub-report **Overview** tab shows a **Perceived Purpose** card (when any statements were generated) above the Security Posture card. Each statement is shown in a coloured box — indigo for **Inferred**, emerald for **Fact** — with the badge shown inline. The developer-authored-text statement (when present) shows its individual quotes as a bullet list rather than one run-on paragraph.

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}
```

Response includes a `purpose_narrative` array:

```json
{
  "purpose_narrative": [
    {
      "category": "authored_intent",
      "is_inference": false,
      "text": "Developer-authored documentation (from @Operation/@Schema annotations):",
      "evidence": ["Exports blob binary data", "Imports a blob"]
    },
    {
      "category": "event_topology",
      "is_inference": true,
      "text": "Based on the following static evidence — this service publishes 2 event type(s) and consumes 0 — this service appears to be primarily a publisher of domain events (a likely system-of-record).",
      "evidence": { "published_count": 2, "consumed_count": 0, "role": "primarily a publisher of domain events (a likely system-of-record)" }
    }
  ]
}
```

### Limitations

- This is a purely static, rule-based synthesiser — not an LLM, not a live-verified summary. Statements should be read as "worth considering," never as confirmed fact (except the explicitly fact-labeled ones).
- Domain vocabulary extraction is generic (frequency-based tokenisation with a structural-word stoplist) rather than a hardcoded keyword list, so it works across differently-named products, but may surface less obviously meaningful terms for codebases with unusual naming conventions.
- `@Operation(description=...)` text used in the authored-intent statement has markdown sub-sections (headings, code fences) stripped and is truncated to ~200 characters for readability — the full text remains available verbatim on the endpoint/schema itself (Section 30).
- Computation is best-effort — a bug in the synthesiser logs an error and produces an empty narrative for that sub-report rather than failing the whole analysis.

---

## 33. Infrastructure Requirements

A report-level synthesis of what needs to be provisioned on the IAM/auth service, MySQL, and RabbitMQ before a bundle will run — built entirely from data already extracted elsewhere (roles/authorities, Flyway table ownership, connection config keys, event topology). No live infrastructure is ever contacted; this is a static-only complement to the "Infra Diagnostics" tool (Section 28's sibling live-verification system), not a replacement for it.

### Non-negotiables

- **Evidence-cited, never invented.** Every requirement line names the concrete endpoint/migration/config-key it came from.
- **Explicit gaps, not silent omission.** Where this tool fundamentally cannot know something (IAM domain/project placement, DB grant scoping, RabbitMQ vhost policy), the report says so directly rather than guessing or showing nothing.
- **Externally parameterised values are never resolved to a literal.** A config value like `${parts.blob-store.db.url}` genuinely has no value in the bundle — and even where a Spring placeholder has an embedded default (`${test.db.url:jdbc:mysql://localhost/mydb}`), that default is a local-test fixture in real bundles, not deployment guidance, so it is deliberately never surfaced as if it were a real value. Instead, the requirement records that the key is present and must be supplied at deploy time.

### IAM / Auth Service

Reuses the same role/authority-per-endpoint aggregation that powers the `/auth-requirements` feed (Section 11), reframed as "what must exist in the IAM service" — each role/authority shows its reference count and the services that require it. Connection facts (auth URL, project name) are shown when a literal value is present in config. An explicit gap statement always notes that IAM domain/project placement is a deployment decision this tool cannot make, and flags separately when no IAM connection config was found at all in the bundle (common — auth is often validated against tokens issued by an external IAM service not shipped as part of the bundle).

### MySQL / Database

Groups Flyway-derived table ownership under the database name resolved from each service's JDBC URL — "database `mydb` should contain tables: X, Y (created by service Z's migrations)". A cross-service collision check flags when two services declare the same database name (worth confirming it's intentional sharing, not an accidental collision). Also detects MySQL usage via the literal `db.type`/driver-class config keys even when the connection URL itself is externally parameterised. Whether each service's DB user should be scoped to only its own tables or shared is stated as an explicit gap, not a recommendation — the table-ownership data is the raw input to that decision.

### RabbitMQ

**A real limitation this section is upfront about:** exchange/queue/routing-key names on extracted event definitions are, in real bundles, essentially always unresolved — reliably populated only via a rarely-used fallback event-YAML shape. What *is* reliable: which services declare RabbitMQ config at all, their connection facts (virtual host, broker address, port — recognising both the generic Spring Boot `spring.rabbitmq.*` convention and this platform's own `event.rabbitmq.*` convention), and each service's publish/consume topology role (reused from the Perceived Purpose narrative, Section 32) as a coarse read/write access hint. When exchange/queue/routing-key data *is* resolvable for a bundle, it's shown as a bonus — always paired with the reliability caveat, never presented as a complete queue-provisioning list.

### In the UI

The top-level report view shows a teal **🏗 Infrastructure Requirements** section (when any requirements were computed) with three sub-panels — IAM / Auth Service, MySQL / Database, RabbitMQ — each listing its requirements plus an italic "ⓘ" line per explicit gap.

### API

`GET /api/v1/jar-analyser/reports/{id}` includes an `infra_requirements` object:

```json
{
  "infra_requirements": {
    "iam": {
      "requirements": [
        { "kind": "role", "name": "BLOB_STORE_ADMIN", "reference_count": 3, "services": ["blob-store"] }
      ],
      "connection": { "auth_url": null, "auth_host": null, "project_name": null, "services_with_iam_config": [] },
      "known_gaps": ["..."],
      "summary": { "unique_role_count": 80, "unique_authority_count": 0, "public_endpoint_count": 0, "unsecured_endpoint_count": 63 }
    },
    "database": {
      "requirements": [
        { "database_name": "ticketing_db", "services": ["ticketing"], "tables": ["ticket", "ticket_comment"] }
      ],
      "per_service": { "blob-store": { "is_mysql": true, "db_type": "mysql", "tables": ["blob_table", "lock_record"], "...": "..." } },
      "collisions": [],
      "known_gaps": ["..."]
    },
    "messaging": {
      "requirements": [
        { "service": "blob-store", "virtual_host": "/", "address": "rabbit.example.com:443", "role": "primarily a publisher (needs write access)", "exchanges": [], "queues": [] }
      ],
      "known_gaps": ["..."]
    }
  }
}
```

`infra_requirements` is `null` when not yet computed (reports analysed before this feature was introduced — use ↺ Re-run to populate).

### Limitations

- Database and messaging requirements are only as complete as the literal (non-placeholder) config values present in the bundle — in practice, most real production-profile config externalises connection details completely, so the `requirements` list may legitimately be empty while `known_gaps` still surfaces the useful raw data (e.g. per-service table ownership) that couldn't be grouped under a resolved name.
- RabbitMQ exchange/queue/routing-key provisioning data is frequently unresolvable — see the RabbitMQ section above. The publisher/consumer role signal remains reliable even when queue names are not.
- This is a sibling to, not an integration with, the live-verification "Infra Diagnostics" tool (Section 28) — the two systems do not currently share output, though Infra Diagnostics' own config-key prefill (`connection_facts.py`) is the same shared module this feature uses, so the two will never disagree about what a given config key means.
- Computation is best-effort — a bug in any individual sub-section logs an error and produces an empty `infra_requirements` object for that run rather than failing the whole analysis.

---

## 34. Scheduled Jobs

Nothing in this tool surfaced background/batch work before this feature — every other view describes request-driven behaviour (endpoints) or event-driven behaviour (RabbitMQ). `@Scheduled` (and the repeatable `@Schedules` container) methods are extracted using the same bytecode-annotation technique as endpoint extraction, applied to any class in the bundle rather than just `@RestController`/`@Controller` classes, since a scheduled method can live on any Spring-managed bean.

### What gets extracted

For each `@Scheduled` method: the declaring class, method name, and whichever schedule element was set — `cron` (+ optional `zone`), `fixedRate`/`fixedRateString`, `fixedDelay`/`fixedDelayString`, or `initialDelay`/`initialDelayString`. A pre-rendered `display` string (e.g. `"cron: 0 0 2 * * *"` or `"every 30000ms after previous run completes (fixed delay)"`) is computed once so the API/UI don't need to re-derive it.

### Config-driven schedules

Real-data finding: on the reference `installation-package` bundle, the large majority of scheduled jobs use the `*String` variants with Spring placeholder syntax — often embedded inside a SpEL expression, e.g. `#{1000 * new Integer('${customerContractCache.syncAllIntervalSec:86400}')}` — rather than a literal numeric value. Consistent with this tool's handling of config placeholders elsewhere (Section 33), the embedded value (including any default after the `:`) is never resolved and surfaced as if it were real deployment guidance — it's flagged `is_config_driven: true` instead, since the actual cadence is only known once the property is set in the deployment environment.

### In the UI

Each service's **Scheduled Jobs** tab (sub-report view) lists every extracted job: declaring class, method name, the rendered schedule, and a `config-driven` badge when the cadence isn't a literal value. The Perceived Purpose card (Section 32) also folds in a one-line signal when a service has scheduled jobs — "this service appears to perform periodic/background processing in addition to handling requests."

### API

```
GET /api/v1/jar-analyser/reports/{id}/sub-reports/{sub_id}/scheduled-jobs
```

```json
[
  {
    "id": "...",
    "declaring_class": "com.dxc.ecs.blobstore.service.DataService",
    "declaring_class_simple": "DataService",
    "method_name": "updateContent",
    "cron": null,
    "fixed_rate_ms": null,
    "fixed_delay_ms": null,
    "initial_delay_ms": null,
    "zone": null,
    "is_config_driven": true,
    "display": "every ${data-svc.update-period-ms} after previous run completes (fixed delay, config-driven)"
  }
]
```

### Limitations

- A Spring placeholder value is never resolved to a literal cadence, even when it has an embedded default — the same "never show a value we can't guarantee is real deployment guidance" discipline used throughout this tool.
- `@Scheduled` presence is detected from the annotation alone — this tool cannot know whether the declaring class is actually registered as a Spring bean (e.g. via component scanning or explicit `@Bean` registration), so an annotated method on a class that's never instantiated by Spring would still appear here even though it would never run in practice. This is expected to be rare (annotating a method you don't intend to schedule serves no purpose) but is a real static-analysis boundary.
- The repeatable `@Schedules` container is supported (multiple `@Scheduled` on one method), but this was validated with synthetic fixtures — no real bundle analysed so far happened to use it.

---

## 35. Actuator / Management Endpoint Exposure

Spring Boot Actuator's management endpoints are a real, common production vulnerability class — an `/actuator/env` or `/actuator/heapdump` left reachable without authentication can leak secrets or enable further attacks. This is checked purely from static config evidence, cross-referenced with data this tool already extracts (Nginx proxy reachability, declared ports) — no live target is ever contacted.

### What gets checked

`management.endpoints.web.exposure.include` (and `.exclude`) — already categorised `"actuator"` by the config-key scanner (any `management.*`/`spring.actuator*` key) — is parsed to determine which endpoints are exposed over HTTP. A curated set of endpoints that leak information or enable abuse **the moment they're exposed**, with no secondary flag required, is checked for overlap:

`env`, `heapdump`, `threaddump`, `beans`, `configprops`, `mappings`, `loggers`, `httptrace`/`httpexchanges`, `auditevents`

`shutdown` is treated as a special case — unlike the endpoints above, listing it in `exposure.include` has no effect unless `management.endpoint.shutdown.enabled=true` is **also** explicitly set, so both conditions are required before it's flagged.

### Risk levels

| Risk | Condition |
|------|-----------|
| 🔴 High | A sensitive endpoint is exposed, the management port is the same as the main app port, **and** the service is reachable via the Nginx proxy |
| 🟡 Medium | A sensitive endpoint is exposed and the management port is the same as the main app port, but proxy reachability is unknown or not proxied |
| 🟢 Low | A sensitive endpoint is exposed, but a separate `management.server.port` is configured — a deliberate, common hardening pattern |
| ⚪ Unknown | `exposure.include` itself is externally parameterised — cannot resolve what's actually exposed |

A service with only `health`/`info`/`metrics`/`prometheus` exposed (the common case — confirmed against the reference bundle, where every service using Actuator restricted itself to these) produces no finding at all — only evidence of *broadened* exposure to something on the sensitive list is surfaced, to avoid noise on the framework-default-safe case.

### In the UI

The top-level report view shows a red **🔓 N Actuator Exposure Finding(s)** section (only when findings exist) listing each flagged service with its risk badge, the exposed sensitive endpoints, whether it shares the app's port, and Nginx-proxy reachability where known.

### API

`GET /api/v1/jar-analyser/reports/{id}` includes an `actuator_exposure` object:

```json
{
  "actuator_exposure": {
    "services": [
      {
        "service": "config",
        "sensitive_endpoints_exposed": ["env", "heapdump"],
        "exposure_is_wildcard": false,
        "management_port": null,
        "management_address": null,
        "same_port_as_app": true,
        "externally_proxied": true,
        "legacy_security_disabled": false,
        "risk": "high",
        "evidence": ["management.endpoints.web.exposure.include"]
      }
    ],
    "known_gaps": ["..."]
  }
}
```

### Limitations

- Custom Spring Security configuration (`HttpSecurity`/`SecurityFilterChain` rules) that separately restricts `/actuator/**` is not parsed — the same documented limitation as Security Posture (Section 17). A high-risk finding here does not mean the endpoint is actually unauthenticated in practice, only that the framework-level exposure configuration doesn't restrict it.
- Per-endpoint enablement (`management.endpoint.<name>.enabled=false`) is not cross-referenced except for `shutdown`'s required explicit enable flag — a listed endpoint could still be individually disabled.
- Real-data finding: some bundles store the exposure list as a genuine YAML list that gets flattened to a Python-list-repr string (e.g. `"['health', 'info']"` instead of `"health,info"`) rather than the documented comma-separated format — both forms are parsed identically.
- Whether the management port is actually reachable from outside the host is a network/firewall question this tool cannot verify; same-port-as-app and Nginx-proxy status are the best available static signals.

---

## 36. On-Demand Decompilation

Every other analysis pass in this tool (endpoints, DTO schemas, dependencies, migrations, events — Section 3) reads a class's *structure*: its declared methods, fields, and annotations, parsed straight from the classfile format. None of that ever looks inside a method body — the compiled bytecode instructions that make up the method's actual logic are read but never decoded (`classfile.py` stores the `Code` attribute's raw bytes without interpreting them). On-demand decompilation closes that gap: it reconstructs real, readable Java source from the bytecode itself, using two independent decompilers run together on every decompile — [CFR](https://github.com/leibnitz27/cfr) and [Vineflower](https://github.com/Vineflower/vineflower) (both bundled into the `certmanager` image as single jars — no separate install needed).

This is a genuinely different kind of analysis from everything else in this tool — reconstructing source from bytecode is a hard problem in its own right, which is why it shells out to dedicated, mature decompilers rather than attempting it with the same lightweight bytecode parser used for structural extraction.

### Two engines, run together

CFR and Vineflower use different internal heuristics, so a class that comes out thin or wrong from one is often fine from the other. Rather than making the user pick one upfront, both run automatically on every decompile (concurrently, so wall-clock time is bounded by whichever engine is slower, not their sum) — the class viewer shows a CFR/Vineflower toggle next to each class's source so you can compare, and a class only one engine struggles with doesn't sink the jar's overall result (a jar is "completed" if *either* engine produced classes).

The two engines don't always agree on where a class file's own package path starts — CFR auto-normalizes a Spring Boot/WAR fat-jar's internal wrapper directories (`BOOT-INF/classes/`, `WEB-INF/classes/`) to bare package paths, while Vineflower preserves them literally. This tool strips those same markers from Vineflower's output before storing it, so both engines agree on the same `class_name` for the same class — this is what makes the cross-engine dedup in the class tree and the per-class toggle work correctly for "jar of jars" installer bundles, which is the majority case here.

### Scope

Decompilation covers **every class each engine finds in the targeted jar** — not just your own application code. Unlike the annotation scanner (which filters to app-owned packages when looking for controllers/components), a decompile run makes no such filter: framework and third-party classes bundled in the same jar are decompiled too, if the engine reaches them. It is scoped per **nested jar** — for a Spring Boot fat jar this reaches everything under `BOOT-INF/classes/` (your application code) and any classes at the jar's own root, but does not separately unpack and decompile the third-party dependency jars nested inside `BOOT-INF/lib/*.jar` — those remain opaque binary entries as far as a single invocation against the outer jar is concerned.

### Triggering

Two actions, both on-demand — nothing is decompiled automatically on upload:

- **Decompile this jar** — on a service's own Source tab (Section 6), decompiles every class in that one nested jar.
- **🧬 Decompile All Jars** — on the top-level report view (Section 5), decompiles every nested jar in the bundle, one at a time (one JVM invocation per jar, not run in parallel).

Both take a **timeout**, in seconds (default 120, capped at 900) — this applies **per jar**, not to the whole batch. If a single jar's CFR invocation exceeds the timeout it's recorded as timed out and the run moves on to the next jar (for "Decompile All Jars") rather than failing the whole batch.

### How it works

A jar's bytes aren't kept around after its initial analysis completes — the extracted nested-jar working directory is deleted once the upload's analysis finishes, so only structural facts about it (filename, install depth) are persisted. Triggering a decompile re-derives the jar's actual bytes from the original uploaded bundle (which *is* kept permanently) using the exact same extraction/fat-jar-resolution rules the initial analysis used, so the jar decompiled is guaranteed to be the same one that was originally analysed.

Decompiled source is stored per-class *per engine* in the database (the same storage model already used for migration scripts, event files, and config file content elsewhere in this tool) — re-decompiling a jar replaces its previously stored classes for both engines.

### In the UI

- **Service Source tab** — a package/class tree on the left (grouped and searchable, deduplicated across engines so a class decompiled by both is still one tree entry), a read-only syntax-highlighted Java viewer on the right with a CFR/Vineflower toggle next to the filename (the engine that didn't produce output for a given class is shown disabled rather than erroring). A "⬇ Download source (zip)" button exports every decompiled class for that one jar, with separate `cfr/` and `vineflower/` folders preserving each engine's package directory structure.
- **Top-level report view** — the "🧬 Decompile All Jars" button shows a live progress banner (jars processed / total, failures called out by name) while running, and a "⬇ Download all decompiled source (zip)" button once complete — one top-level folder per service, `cfr/`/`vineflower/` subfolders underneath each.

### API

```
POST /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompile              { "timeout_seconds": 120 }
POST /api/v1/jar-analyser/reports/{report_id}/decompile-all                               { "timeout_seconds": 120 }
GET  /api/v1/jar-analyser/reports/{report_id}/decompile-runs/{run_id}
GET  /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompile-runs
GET  /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes
GET  /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes/{class_name}?engine=cfr|vineflower
GET  /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompiled-classes/{class_name}/facts
GET  /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/decompile/export
GET  /api/v1/jar-analyser/reports/{report_id}/decompile/export
```

Both `POST` endpoints return `202`-style immediately (`run_id` + a status URL) — decompilation runs in the background and is polled, the same pattern used by the Diagnostic Collection Tool (Section 28). The source endpoint's `engine` query param defaults to `cfr`; if that engine has no output for the requested class, the response falls back to whichever engine does and reports the actual engine used via its `engine` field, plus which engines are available via `available_engines`.

### Limitations

- Local variable and parameter names only survive if the jar was compiled with debug info retained — see the note in Section 26.
- Decompiler fidelity is very good but not perfect on unusual bytecode (heavy `invokedynamic`/lambda metaprogramming, some annotation-processor-generated code) — this is exactly why both engines run on every decompile, so one engine's gap is often covered by the other. A class where *both* engines fail cleanly is recorded as a per-jar failure/timeout in the run's results, not silently dropped.
- Third-party dependency jars nested inside a fat jar's own `BOOT-INF/lib/` are not separately unpacked and decompiled (see Scope above).
- This is a genuinely different, heavier operation than the rest of this tool's analysis passes — decompiling a large jar with two engines takes real CPU time, which is why it's on-demand rather than automatic on every upload.

---

## 37. String Constant Search

Every other search in this tool (Section 24's `GET /search`, the class-facts endpoints) matches *structured* facts this tool already extracted — endpoint paths, dependency coordinates, config keys. None of them can answer "what code actually produces this exact error message I saw in a log?" — that text lives inside a method body, not in any of the structural facts above. String Constant Search closes that gap: every string literal a class's own bytecode embeds (log messages, exception text, Swagger doc comments, JSON keys, format templates) is extracted and indexed automatically, so you can paste text you saw at runtime and find exactly which class — and which service — it came from.

### How it's extracted

A compiled class file's constant pool already gets fully parsed during ordinary analysis (for class/method/field names and annotations — `classfile.py`'s `_read_constant_pool`). What's new here is reading the pool's `CONSTANT_String` entries too: the JVM spec only creates one of these for a `Utf8` value the compiler actually used as a string literal somewhere in that class (an `ldc` instruction in a method body, a string-valued annotation element, or a static final field initialiser) — never for the far more numerous method/field descriptors and internal type names that also live in the same pool as plain `Utf8` entries. That precision means no heuristic filtering is needed to keep noise out.

This runs **automatically during ordinary analysis** — unlike Decompilation (Section 36), there's no separate trigger and no opt-in. Every jar you upload or re-analyse is immediately searchable.

### Scope

Same class scope as the annotation scanner (Section 3) reaches for endpoints/components — your own application code within each nested service jar, with common framework packages (Spring, Hibernate, Jackson, etc.) filtered out by default. Like Decompilation, this does **not** open the third-party dependency jars nested inside `BOOT-INF/lib/*.jar` — those stay opaque. For a "which of *our* services logs this" question, that's the right scope: results won't be cluttered with hits from inside a bundled library.

### Where to search

- **🔍 Search Reports** (top of the JAR Analyser home page, and inside a report's own view) — the same search modal used for endpoints/dependencies/config now has a **🔤 String** category alongside the existing ones. Leave "All" selected to see string hits mixed in with everything else, or click the String pill to see only those. Opened from the home page, this searches every analysed jar; opened from inside one report, it's scoped to that upload's own nested services only (useful for a "jar of jars" bundle where you want to search across all its services without pulling in unrelated uploads).
- **🔤 Strings tab** — on a service's own sub-report view, alongside Endpoints/Dependencies/Source/etc. Lists (and lets you filter) that one jar's own string constants directly, without needing to already know a search term.

A hit shows the matched text, the fully-qualified class it came from, and which service/jar that class belongs to — clicking it jumps straight to that service's Strings tab.

### API

```
GET /api/v1/jar-analyser/strings/search?q=...&report_id=...&page=1&page_size=25
GET /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/strings?q=...&page=1&page_size=50
```

The first is the global (or, with `report_id`, one-upload-scoped) search — SQLite FTS5-ranked with a highlighted snippet when running on SQLite (this tool's default), falling back to a plain substring match on Postgres/MySQL. The second lists one sub-report's own strings, a simple substring filter since one service's own rows are never numerous enough to need ranking.

### Limitations

- Only covers classes the annotation scanner reaches — third-party jars bundled inside `BOOT-INF/lib/*.jar` are not scanned (see Scope above).
- A string appearing in the bytecode doesn't guarantee it's ever actually logged at runtime with that exact formatting — format-string placeholders (`%s`, `{}`) are stored as-is, not resolved against any particular call site.
- Reports analysed before this feature existed have no string constants until re-analysed (via "Re-analyse" on the upload) — this only runs going forward, there's no retroactive backfill of old reports.

---

## 38. Outbound Integration Discovery

Endpoints (Section 3) tell you which REST endpoints a service *exposes* — calls coming **in**. Nothing else in this tool answers the opposite question: which external systems does a service call **out** to? That matters most when something outside the analysed bundle is involved — a third-party API, a platform service like VMware vRealize Automation (vRA) — and the question on hand is "which of our services actually talks to that system, and at what URL", before ever reaching for a proxy, `tcpdump`, or JVM network-debug flags.

### How it's discovered

Two independent, purely static signals — both read straight from already-parsed structural facts, no method-body decoding involved (see the note on why that's a deliberate limit, below):

- **Feign clients** — a class annotated `@FeignClient(name=..., url=..., value=...)`. These attributes are explicit and unambiguous: `name`/`value` identify the logical target, `url` is the base URL (often itself a placeholder resolved against config, same as below). A Feign client declared with only `name` (no `url`) still tells you "this class integrates with a logical service named X", even when the literal URL is resolved via service discovery at runtime rather than static config.
- **`@Value`-injected config keys** — any field carrying `@Value("${some.key}")` where the key name matches the same `url|uri|host|address` heuristic this tool's own placeholder catalogue (Section 24's env-var catalogue) already uses to categorise config keys. This is a heuristic, not proof: a field being injected with a URL-shaped config value doesn't prove that field is ever actually used to build an outbound HTTP call inside that class's method bodies — reading method bodies is precisely the thing this tool's structural parser deliberately never does automatically (the same reason Decompilation, Section 36, exists as a separate, heavier, on-demand step). Treat a `config_value` signal as "worth a look", not as confirmed.

Whichever placeholder key is found, this tool tries to resolve it to an actual value using **this same sub-report's own config files** — if `vra.api.url` is genuinely set in `application.yml`, you see the real configured value; if the key is only ever supplied externally (a Kubernetes ConfigMap, an env var set at deploy time), there's nothing in the analysed jar itself to resolve it against, and only the bare key name is shown. A placeholder's own inline default (`${key:default}`) is used as a fallback when nothing in this bundle's config sets the key explicitly.

This runs **automatically during ordinary analysis** — same as String Constant Search (Section 37), not opt-in like Decompilation.

### Where to find it

- **🌐 Outbound tab** — on a service's own sub-report view, listing just that jar's own signals.
- **🌐 Outbound top-level tab** — on the report view, aggregating every service's signals in one place, grouped by service — the "which of our services talk to which external systems" view for a jar-of-jars bundle, without opening each service one at a time.

Each row shows the kind (Feign client vs. config-driven URL), the declaring class, the target/field name, the config key (if placeholder-driven), and the resolved value when this tool could determine one.

### API

```
GET /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/outbound-integrations
GET /api/v1/jar-analyser/reports/{report_id}/outbound-integrations
```

The first is scoped to one service; the second aggregates every service in the report, each item tagged with its own `service_name`/`sub_report_id`. Neither is paginated — this data set is small per service (a handful of signals, not hundreds), so there's no ranking or paging concern the way there is for String Constant Search.

### Limitations

- Same class scope as everything else the annotation scanner reaches — third-party jars bundled inside `BOOT-INF/lib/*.jar` are not scanned, so a call made entirely from inside a bundled library (rather than your own code) won't show up.
- `config_value` signals are a heuristic correlation, not confirmed usage — see "How it's discovered" above. Feign client signals are exact (an explicit annotation), config-value signals are not.
- Doesn't (and can't, without decoding method bodies) tell you the response type expected back, or how errors from the call are handled — that's a deliberately separate, heavier follow-up scoped to already-decompiled classes, not part of this automatic pass.
- Reports analysed before this feature existed have nothing here until re-analysed (via "Re-analyse" on the upload) — same as String Constant Search, no retroactive backfill.

---

## 39. Outbound Call Response & Error Handling

Section 38 tells you a class calls out to an external system. It deliberately stops there — knowing *what response that call expects back*, and *how errors from it are handled*, needs reading inside the method body, which is exactly what this tool's structural bytecode parser never does. This section closes that gap, for classes you've actually decompiled.

### How it works

A text scan over already-decompiled source (CFR/Vineflower output, Section 36) for known outbound-call shapes:

- **JAX-RS Client** — `someWebTarget.path(...).request(...).get()` (or `.post()`/`.put()`/`.delete()`). This is the pattern actually found throughout this tool's own real fixture jar's client classes (`jakarta.ws.rs.client.WebTarget`) — not assumed generically, confirmed by reading real decompiled output before writing the detection patterns.
- **RestTemplate** — `restTemplate.exchange(...)`, `.getForObject(...)`, `.getForEntity(...)`, `.postForObject(...)`, `.postForEntity(...)`.
- **WebClient** — `.bodyToMono(...)` / `.bodyToFlux(...)`.

For each call site found, the tool locates the *enclosing method* (scanning backward for the nearest method signature, then forward-counting braces to find its closing one — a best-effort span, not a real parser) and looks within it for:

- **Response type** — `response.readEntity(X.class)` (JAX-RS), a trailing `X.class` argument on the call itself (RestTemplate/WebClient), or a `ParameterizedTypeReference<X>`/`GenericType<X>` for generic responses.
- **Status-code branches** — `response.getStatus() == Response.Status.NOT_FOUND.getStatusCode()`-style comparisons, both `==` and `!=`, capturing which status name (or raw numeric code) is being checked.
- **Thrown exceptions** — `throw new X(...)` within the method (the common pattern observed here: a non-2xx status leads to throwing a custom exception, not a try/catch).
- **Caught exceptions** — `catch (X e)` blocks, including multi-catch (`catch (X | Y e)`), for codebases that do wrap the call in a try/catch instead.

None of this is proof of exact behaviour — a `catch`/`throw`/status-check found "in the enclosing method" is the best signal obtainable without real control-flow analysis, not confirmation it's handling *this specific* call (most accurate for the common one-outbound-call-per-method style this tool's own fixture jar actually uses).

### When it runs

Only when a class is decompiled — **not automatic** like Section 38's integration discovery. Triggered from the same decompile run: right after a class's source is collected, it's scanned once (preferring CFR's output; Vineflower only fills in classes CFR had no source for, to avoid two near-identical rows per class). Re-decompiling a jar replaces its previous call-site rows, same as it replaces decompiled source itself.

### Where to find it

Appended below the integration signals on the same **🌐 Outbound** tab (both the per-service tab and the report-level aggregate) introduced in Section 38 — a "📥 Response Handling" section that only appears once at least one call site has been found, i.e. once the jar (or that specific class) has actually been decompiled.

### API

```
GET /api/v1/jar-analyser/reports/{report_id}/sub-reports/{sub_id}/outbound-call-sites
GET /api/v1/jar-analyser/reports/{report_id}/outbound-call-sites
```

Same scoping shape as Section 38's endpoints — one service, or every service in the report that's actually been decompiled (services never decompiled simply don't appear).

### Limitations

- Nothing shows here until the relevant jar has been decompiled — this is opt-in and on-demand, layered on top of an already opt-in feature (Decompilation itself).
- A regex-based text scan over decompiler output, not a real Java parser — unusual formatting, heavy nesting, or nonstandard call patterns can cause a method's boundary (and therefore its correlated exceptions/status-checks) to be misattributed.
- Only the three call shapes listed are recognised. A service using a different HTTP client library, or calling out via a hand-rolled `java.net.http.HttpClient`/`HttpURLConnection`, won't be picked up.
- Re-decompiling replaces this data for that jar — there's no history of how a call site's error handling has changed over time (unlike, say, the version diffing built for other parts of this tool).
