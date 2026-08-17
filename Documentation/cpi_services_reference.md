# DXC CPI Services — Technical Reference

> **Version:** 2.6.9  
> **Vendor:** DXC Technology  
> **Platform:** Cloud Platform Integration (CPI) Services  
> **Java:** 17  
> **Spring Boot:** 3.5.8  
> **Build Tool:** Maven (Maven JAR Plugin)  
> **Installation Package:** `installation-package-2.6.9.jar`

---

## Table of Contents

- [Part 1 — Overview & Platform Architecture](#part-1--overview--platform-architecture)
  - [1.1 What is DXC CPI Services?](#11-what-is-dxc-cpi-services)
  - [1.2 Platform Purpose](#12-platform-purpose)
  - [1.3 The 22-Service Topology](#13-the-22-service-topology)
  - [1.4 Technology Stack](#14-technology-stack)
  - [1.5 Installation Package Structure](#15-installation-package-structure)
- [Part 2 — Service Catalogue](#part-2--service-catalogue)
  - [2.1 Backend Services](#21-backend-services)
  - [2.2 Frontend / UI Services](#22-frontend--ui-services)
  - [2.3 Load Balancers](#23-load-balancers)
  - [2.4 Infrastructure & Monitoring Services](#24-infrastructure--monitoring-services)
  - [2.5 Tooling & Migration](#25-tooling--migration)
  - [2.6 Service Summary Table](#26-service-summary-table)
- [Part 3 — Spring Boot Application Framework](#part-3--spring-boot-application-framework)
  - [3.1 Common Bootstrap Pattern](#31-common-bootstrap-pattern)
  - [3.2 Spring Cloud Config Client](#32-spring-cloud-config-client)
  - [3.3 Jasypt Encryption](#33-jasypt-encryption)
  - [3.4 Actuator Endpoints](#34-actuator-endpoints)
  - [3.5 Common Dependencies](#35-common-dependencies)
- [Part 4 — Configuration Deep Dive](#part-4--configuration-deep-dive)
  - [4.1 setup.properties](#41-setupproperties)
  - [4.2 versions.yml / version.yml](#42-versionsyml--versionyml)
  - [4.3 application-backend.properties](#43-application-backendproperties)
  - [4.4 application-frontend.yml](#44-application-frontendyml)
  - [4.5 Per-Service application.properties](#45-per-service-applicationproperties)
- [Part 5 — SSL/TLS Architecture](#part-5--ssltls-architecture)
  - [5.1 Keystore & Truststore Paths](#51-keystore--truststore-paths)
  - [5.2 SSL Configuration Pattern](#52-ssl-configuration-pattern)
  - [5.3 Enabled Protocols & Cipher Suites](#53-enabled-protocols--cipher-suites)
  - [5.4 Certificate Requirements Per Service](#54-certificate-requirements-per-service)
  - [5.5 SAN Construction](#55-san-construction)
- [Part 6 — Database Architecture](#part-6--database-architecture)
  - [6.1 MySQL Schema Per Service](#61-mysql-schema-per-service)
  - [6.2 Flyway Migration Pattern](#62-flyway-migration-pattern)
  - [6.3 Oracle Support](#63-oracle-support)
  - [6.4 Connection Pool Configuration](#64-connection-pool-configuration)
  - [6.5 Shared vs Isolated Schemas](#65-shared-vs-isolated-schemas)
- [Part 7 — Event-Driven Architecture](#part-7--event-driven-architecture)
  - [7.1 RabbitMQ / AMQPS Configuration](#71-rabbitmq--amqps-configuration)
  - [7.2 Exchange & Queue Topology](#72-exchange--queue-topology)
  - [7.3 Event Definitions Per Service](#73-event-definitions-per-service)
  - [7.4 Entity Events & Consumer Queues](#74-entity-events--consumer-queues)
- [Part 8 — Load Balancer Deep Dive](#part-8--load-balancer-deep-dive)
  - [8.1 Backend LB — Nginx Upstreams](#81-backend-lb--nginx-upstreams)
  - [8.2 Frontend LB — Port 443 & SSL Termination](#82-frontend-lb--port-443--ssl-termination)
  - [8.3 Proxy Rules & Headers](#83-proxy-rules--headers)
- [Part 9 — Fulfillment Service Deep Dive](#part-9--fulfillment-service-deep-dive)
  - [9.1 Scale & Complexity](#91-scale--complexity)
  - [9.2 Adapters](#92-adapters)
  - [9.3 Cloud Providers](#93-cloud-providers)
  - [9.4 Adapter Configuration Patterns](#94-adapter-configuration-patterns)
- [Part 10 — Monitoring Stack](#part-10--monitoring-stack)
  - [10.1 Prometheus](#101-prometheus)
  - [10.2 Grafana](#102-grafana)
  - [10.3 Node Exporter](#103-node-exporter)
  - [10.4 Per-Service Metrics](#104-per-service-metrics)
- [Part 11 — Installation & Bundle Structure](#part-11--installation--bundle-structure)
  - [11.1 part.yml Schema](#111-partyml-schema)
  - [11.2 Installer JAR Layout](#112-installer-jar-layout)
  - [11.3 content/lib/ — The Fat JAR](#113-contentlib--the-fat-jar)
  - [11.4 config/ — Configuration Templates](#114-config--configuration-templates)
  - [11.5 bundle/ — systemd, Nginx, Logrotate](#115-bundle--systemd-nginx-logrotate)
  - [11.6 Migration Tool](#116-migration-tool)
- [Part 12 — Deployment Mapping](#part-12--deployment-mapping)
  - [12.1 AWS Resource Mapping](#121-aws-resource-mapping)
  - [12.2 On-Premises systemd Deployment](#122-on-premises-systemd-deployment)
  - [12.3 Docker / Container Deployment](#123-docker--container-deployment)

---

# Part 1 — Overview & Platform Architecture

## 1.1 What is DXC CPI Services?

DXC CPI Services (Cloud Platform Integration Services) is an enterprise-grade multi-service platform built by DXC Technology. It provides a unified integration layer for cloud service brokering, catalogue management, customer lifecycle management, and IT service fulfilment across heterogeneous cloud and on-premises environments.

The platform is delivered as a single installation package (`installation-package-2.6.9.jar`) — a JAR-of-JARs containing 22 individual installer JARs, each representing one deployable service or infrastructure component.

## 1.2 Platform Purpose

CPI Services acts as a **cloud service broker and orchestration platform**. Its core responsibilities are:

- **Service Catalogue** — publish and manage a catalogue of orderable cloud services across multiple providers
- **Customer Management** — lifecycle management of customer accounts, entitlements, and subscriptions
- **Request & Fulfilment** — accept service requests and orchestrate their fulfilment through adapter-specific workflows
- **Pricing** — compute and expose pricing for catalogue items across providers
- **Reporting** — aggregate usage, billing, and operational data
- **Event Bus** — propagate domain events between services via RabbitMQ
- **Configuration Server** — centralise all service configuration via Spring Cloud Config
- **Observability** — Prometheus metrics collection and Grafana dashboards for all services
- **External Integration** — expose APIs to external consumers and receive external events

The platform is designed for **multi-tenancy**, **multi-cloud**, and **on-premises** deployment, with adapters for AWS, Azure, Google Cloud, Oracle Cloud, VMware, MCP, and SAP.

## 1.3 The 22-Service Topology

The platform comprises 22 components organised into functional groups:

| Group | Services |
|---|---|
| **Backend** | customers, blob-store, event, catalog, service-instances, pricing, request, fulfillment, reporting, config, diagnostic, export, external-events, ticketing |
| **Frontend** | management-ui, portal-ui |
| **Backend LB** | backend-lb (Nginx) |
| **Frontend LB** | frontend-lb (Nginx) |
| **Documentation** | api-doc |
| **Monitoring** | grafana, prometheus |
| **Tooling** | permutation-demo-data-migrator |

The `config` service is the **keystone** of the platform — all other backend services bootstrap from it via Spring Cloud Config before they can start. It must be the first service deployed and the last to be stopped.

## 1.4 Technology Stack

| Layer | Technology |
|---|---|
| Runtime | Java 17 (OpenJDK) |
| Framework | Spring Boot 3.5.8 |
| Config Server | Spring Cloud Config |
| Encryption | Jasypt (`PBEWITHSHA256AND256BITAES-CBC-BC`) |
| Message Broker | RabbitMQ (AMQPS/TLS) |
| Primary Database | MySQL (MariaDB compatible) |
| Alternate Database | Oracle (supported via driver swap) |
| DB Migrations | Flyway |
| Web Server | Embedded Tomcat (Spring Boot) |
| Load Balancer | Nginx (backend-lb, frontend-lb) |
| Monitoring | Prometheus + Grafana |
| Security | JKS Keystore + Truststore, TLSv1.2 |
| Build | Maven, Maven JAR Plugin |
| Process Manager | systemd (on-prem) |

## 1.5 Installation Package Structure

The top-level `installation-package-2.6.9.jar` is a standard ZIP-format JAR containing:

```
installation-package-2.6.9.jar
├── META-INF/
│   └── MANIFEST.MF
├── setup.properties          # Global installer configuration
├── versions.yml              # Service version manifest
├── version.yml               # Package-level version metadata
└── <service>-installer-<version>.jar   (x22)
    ├── META-INF/MANIFEST.MF
    ├── part.yml              # Installer metadata for this service
    ├── content/
    │   └── lib/
    │       └── <service>-svc.jar     # Spring Boot fat JAR
    ├── config/               # Configuration file templates
    └── bundle/               # systemd unit, Nginx config, logrotate
```

Each nested installer JAR is self-contained: it carries the runnable fat JAR, all configuration templates, and all OS-level integration files needed to deploy that one service.

---
# Part 2 — Service Catalogue

## 2.1 Backend Services

### config (Port 8103)

The Spring Cloud Config Server. Every other backend service sends a bootstrap request to `http://config-svc:8103` before loading its own `application.properties`. It serves shared configuration profiles (`application-backend.properties`, `application-frontend.yml`) and per-service overrides. It is the **single source of truth** for all runtime configuration across the platform.

- **Install path:** `/opt/ecs/config`
- **Group:** backend
- **Firewall ports:** 8103
- **Critical dependency:** Must be running before any other backend service starts

### customers (Port 8090)

Manages the full lifecycle of customer accounts within the platform. Responsibilities include customer creation, update, deletion, entitlement assignment, and subscription tracking. Exposes REST APIs consumed by both the management UI and portal UI. Publishes customer domain events to RabbitMQ for downstream consumption by fulfillment, reporting, and external-events.

- **Install path:** `/opt/ecs/customers`
- **Group:** backend
- **Firewall ports:** 8090
- **Database:** Dedicated MySQL schema
- **Events published:** customer created, updated, deleted, entitlement changed

### blob-store (Port 8091)

Binary large object storage service. Provides an abstraction layer over the underlying storage backend for storing and retrieving binary artefacts — attachments, exported reports, provisioning artefacts, and other binary content generated or consumed by the platform. Acts as an internal S3-like service.

- **Install path:** `/opt/ecs/blob-store`
- **Group:** backend
- **Firewall ports:** 8091
- **Database:** Dedicated MySQL schema

### event (Port 8092)

The platform's internal event store and event relay service. Persists domain events published by other services, provides event replay capability, and acts as a durable audit log of all significant state changes across the platform. Consumers can query historical events and subscribe to event streams.

- **Install path:** `/opt/ecs/event`
- **Group:** backend
- **Firewall ports:** 8092
- **Database:** Dedicated MySQL schema (event log table, high write volume expected)

### catalog (Port 8093)

The service catalogue engine. Manages the definition, versioning, and publication of orderable services. A catalogue item defines what can be ordered, its parameters, pricing references, and the fulfillment adapter that will handle provisioning. Supports hierarchical catalogue structures and multi-provider catalogue entries.

- **Install path:** `/opt/ecs/catalog`
- **Group:** backend
- **Firewall ports:** 8093
- **Database:** Dedicated MySQL schema

### service-instances (Port 8094)

Tracks all provisioned service instances across all customers and providers. Maintains the lifecycle state machine for each instance (ordering → provisioning → active → modifying → deprovisioning → terminated). Acts as the system of record for what has been provisioned and its current state.

- **Install path:** `/opt/ecs/service-instances`
- **Group:** backend
- **Firewall ports:** 8094
- **Database:** Dedicated MySQL schema (central state store — high read/write)

### pricing (Port 8095)

Computes and exposes pricing for catalogue items. Supports multiple pricing models (fixed, usage-based, tiered) and multiple currencies. Integrates with provider-specific pricing APIs where available. Pricing data is consumed by the portal UI at order time and by reporting for billing calculations.

- **Install path:** `/opt/ecs/pricing`
- **Group:** backend
- **Firewall ports:** 8095
- **Database:** Dedicated MySQL schema

### request (Port 8096)

The order management service. Accepts service requests from the portal UI and management UI, validates them against catalogue definitions and customer entitlements, and submits them to the fulfillment service for execution. Maintains the request lifecycle (submitted → validated → fulfilling → completed / failed). Provides the request history API.

- **Install path:** `/opt/ecs/request`
- **Group:** backend
- **Firewall ports:** 8096
- **Database:** Dedicated MySQL schema

### fulfillment (Port 8097)

The largest and most complex service in the platform (357 MB, 3,705 entries, 569 nested JARs). Orchestrates the actual provisioning, modification, and deprovisioning of services across all supported adapters and cloud providers. Contains the adapter framework and all adapter implementations. See Part 9 for a full deep dive.

- **Install path:** `/opt/ecs/fulfillment`
- **Group:** backend
- **Firewall ports:** 8097
- **Database:** Dedicated MySQL schema (workflow state, adapter task queues)

### reporting (Port 8099)

Aggregates operational, usage, and billing data from across the platform. Generates reports on service consumption, customer activity, and financial summaries. Exposes report APIs consumed by the management UI. May run scheduled aggregation jobs against the database.

- **Install path:** `/opt/ecs/reporting`
- **Group:** backend
- **Firewall ports:** 8099
- **Database:** Dedicated MySQL schema (read-heavy, aggregation tables)

### diagnostic (Port 8104)

Platform health and diagnostics service. Exposes health check endpoints for all services, performs connectivity tests to infrastructure dependencies (MySQL, RabbitMQ, config server), and provides a unified diagnostics API consumed by the management UI's system health dashboard.

- **Install path:** `/opt/ecs/diagnostic`
- **Group:** backend
- **Firewall ports:** 8104

### export (Port 8105)

Data export service. Handles the generation and delivery of data exports — CSV, Excel, or other formats — for reporting data, audit logs, and operational snapshots. Exports are typically stored in blob-store and made available for download via a signed URL or direct API response.

- **Install path:** `/opt/ecs/export`
- **Group:** backend
- **Firewall ports:** 8105
- **Database:** Dedicated MySQL schema

### external-events (Port 8106)

Inbound event gateway. Receives events from external systems (cloud providers, third-party integrations, webhooks) and translates them into internal platform events. Publishes translated events to RabbitMQ for consumption by service-instances, fulfillment, and other internal services. Provides the external webhook registration API.

- **Install path:** `/opt/ecs/external-events`
- **Group:** backend
- **Firewall ports:** 8106
- **Database:** Dedicated MySQL schema

### ticketing

IT service management integration. Provides integration with external ticketing systems (ServiceNow and equivalents) for change management, incident tracking, and approval workflows. Service requests that require ITSM approval are routed through this service before fulfillment proceeds.

- **Install path:** `/opt/ecs/ticketing`
- **Group:** backend
- **Firewall ports:** defined in part.yml

## 2.2 Frontend / UI Services

### management-ui

The operator and administrator web interface. Provides full platform management capabilities: customer management, catalogue administration, request oversight, reporting, user management, and system diagnostics. Built as a single-page application served by an embedded web server or Nginx. Consumed by internal operators and platform administrators.

- **Install path:** `/opt/ecs/management-ui`
- **Group:** frontend
- **Port:** variable (served via frontend-lb on port 443)

### portal-ui

The end-user self-service portal. Customers log in to browse the service catalogue, place orders, view their provisioned service instances, and track request status. Built as a single-page application. Exposed externally via the frontend load balancer.

- **Install path:** `/opt/ecs/portal-ui`
- **Group:** frontend
- **Port:** variable (served via frontend-lb on port 443)

## 2.3 Load Balancers

### backend-lb

Nginx-based reverse proxy for all backend services. Terminates TLS from internal clients and proxies requests to the appropriate backend service by path prefix or virtual host. All backend services are reachable through a single internal HTTPS endpoint via this LB.

- **Install path:** `/opt/ecs/backend-lb`
- **Group:** backend-lb
- **Proxied services:** catalog, blob-store, customers, event, fulfillment, request, service-instances, pricing, reporting, ticketing, config, export, diagnostic, external-events

### frontend-lb

Nginx-based reverse proxy for all frontend-facing services. Terminates TLS on port 443 and routes traffic to management-ui, portal-ui, and selected backend APIs that the UIs consume directly. This is the only component that should be exposed to end users or external networks.

- **Install path:** `/opt/ecs/frontend-lb`
- **Group:** frontend-lb
- **Port:** 443 (HTTPS)
- **Proxied services:** management-ui, portal-ui, catalog, blob-store, customers, event, fulfillment, request, service-instances, pricing, reporting, ticketing

## 2.4 Infrastructure & Monitoring Services

### grafana

Grafana dashboard server. Pre-configured with dashboards for all platform services. Connects to the Prometheus data source. Provides visualisation of service health, request rates, error rates, JVM metrics, RabbitMQ queue depths, and database connection pool stats.

- **Install path:** `/opt/ecs/grafana`
- **Group:** monitoring-extra

### prometheus

Prometheus metrics collection server. Scrapes metrics from all Spring Boot services (via `/actuator/prometheus`), node exporters, RabbitMQ, and Nginx. Stores time-series data and serves as the data source for Grafana.

- **Install path:** `/opt/ecs/prometheus`
- **Group:** monitoring-extra

## 2.5 Tooling & Migration

### api-doc (Port 8098)

API documentation service. Hosts the OpenAPI/Swagger documentation for the platform's REST APIs. Aggregates API specs from multiple services and presents a unified developer portal. Used by integration teams and external consumers to understand the platform's API surface.

- **Install path:** `/opt/ecs/api-doc`
- **Group:** doc
- **Firewall ports:** 8098

### permutation-demo-data-migrator

A standalone one-shot migration tool, not a running service. Populates the platform database with demonstration/seed data for permutation testing — catalogue items, pricing entries, customer records, and service instance examples. Run once during initial platform setup or when resetting a demo environment. Has no persistent process, no port, and no systemd unit.

- **Install path:** `/opt/ecs/permutation-demo-data-migrator`
- **Group:** standalone tool

## 2.6 Service Summary Table

| Service | Port | Group | Install Path | DB | Purpose |
|---|---|---|---|---|---|
| config | 8103 | backend | `/opt/ecs/config` | — | Spring Cloud Config Server |
| customers | 8090 | backend | `/opt/ecs/customers` | MySQL | Customer lifecycle |
| blob-store | 8091 | backend | `/opt/ecs/blob-store` | MySQL | Binary object storage |
| event | 8092 | backend | `/opt/ecs/event` | MySQL | Event store & relay |
| catalog | 8093 | backend | `/opt/ecs/catalog` | MySQL | Service catalogue |
| service-instances | 8094 | backend | `/opt/ecs/service-instances` | MySQL | Provisioned instance state |
| pricing | 8095 | backend | `/opt/ecs/pricing` | MySQL | Pricing engine |
| request | 8096 | backend | `/opt/ecs/request` | MySQL | Order management |
| fulfillment | 8097 | backend | `/opt/ecs/fulfillment` | MySQL | Provisioning orchestration |
| api-doc | 8098 | doc | `/opt/ecs/api-doc` | — | API documentation |
| reporting | 8099 | backend | `/opt/ecs/reporting` | MySQL | Usage & billing reports |
| diagnostic | 8104 | backend | `/opt/ecs/diagnostic` | — | Health & diagnostics |
| export | 8105 | backend | `/opt/ecs/export` | MySQL | Data export |
| external-events | 8106 | backend | `/opt/ecs/external-events` | MySQL | External event ingestion |
| ticketing | variable | backend | `/opt/ecs/ticketing` | MySQL | ITSM integration |
| management-ui | variable | frontend | `/opt/ecs/management-ui` | — | Operator UI |
| portal-ui | variable | frontend | `/opt/ecs/portal-ui` | — | Customer self-service UI |
| backend-lb | 80/443 | backend-lb | `/opt/ecs/backend-lb` | — | Internal reverse proxy |
| frontend-lb | 443 | frontend-lb | `/opt/ecs/frontend-lb` | — | External reverse proxy |
| grafana | 3000 | monitoring-extra | `/opt/ecs/grafana` | — | Metrics dashboards |
| prometheus | 9090 | monitoring-extra | `/opt/ecs/prometheus` | — | Metrics collection |
| permutation-demo-data-migrator | — | tool | `/opt/ecs/permutation-demo-data-migrator` | MySQL | Seed data migration |

---
# Part 3 — Spring Boot Application Framework

## 3.1 Common Bootstrap Pattern

Every backend service in the CPI platform follows an identical bootstrap sequence:

1. JVM starts, Spring Boot initialises
2. `bootstrap.yml` (or `bootstrap.properties`) is loaded — this contains only the config server URL and the application name
3. Spring Cloud Config Client contacts `config-svc` at `http://config-svc:8103` (or the configured `spring.cloud.config.uri`)
4. Config server returns the shared `application-backend.properties` profile plus the service-specific profile
5. The merged configuration is applied to the Spring `Environment`
6. Jasypt decrypts any `ENC(...)` values in the configuration
7. Spring Boot completes context initialisation — datasource, RabbitMQ connection, Flyway migrations, REST controllers, actuator endpoints
8. Service registers as healthy and begins accepting requests

If the config server is unreachable at step 3, the service **fails to start**. There is no fallback to local configuration in production profiles. This makes `config-svc` a hard dependency for the entire platform.

## 3.2 Spring Cloud Config Client

All backend services include `spring-cloud-starter-config` as a dependency. The client configuration is minimal:

```properties
spring.application.name=<service-name>
spring.cloud.config.uri=http://config-svc:8103
spring.cloud.config.fail-fast=true
spring.profiles.active=backend
```

The `fail-fast=true` setting ensures the service refuses to start rather than running with incomplete configuration. The `backend` profile causes the config server to serve `application-backend.properties` as the shared base configuration for all backend services.

The config server itself (`config-svc`) stores configuration in one of two backends:
- **Native filesystem** — configuration files stored in a local directory on the config server host
- **Git repository** — configuration files stored in a Git repo (allows versioned config changes)

In the standard on-premises deployment, the native filesystem backend is used, with config files stored under `/opt/ecs/config/config-repo/`.

## 3.3 Jasypt Encryption

All sensitive configuration values (passwords, secrets, API keys) are stored encrypted using Jasypt. The encryption algorithm is `PBEWITHSHA256AND256BITAES-CBC-BC`, which uses the Bouncy Castle cryptographic provider.

Encrypted values appear in configuration files as:

```properties
spring.datasource.password=ENC(base64encodedciphertext==)
server.ssl.key-store-password=ENC(base64encodedciphertext==)
spring.rabbitmq.password=ENC(base64encodedciphertext==)
```

The Jasypt decryption key (passphrase) is supplied to each service at startup via:

```
-Djasypt.encryptor.password=<passphrase>
```

This is typically set in the systemd unit file's `ExecStart` line or in a secure environment variable. The passphrase itself is never stored in any configuration file — it is injected at deployment time.

The `setup.properties` file contains the Jasypt-encrypted forms of all secrets, generated during the installation process. The installer uses the master passphrase to encrypt each secret before writing it to the service's configuration files.

### Jasypt Configuration Properties

```properties
jasypt.encryptor.algorithm=PBEWITHSHA256AND256BITAES-CBC-BC
jasypt.encryptor.key-obtention-iterations=1000
jasypt.encryptor.pool-size=1
jasypt.encryptor.provider-name=BC
jasypt.encryptor.salt-generator-classname=org.jasypt.salt.RandomSaltGenerator
jasypt.encryptor.string-output-type=base64
```

The Bouncy Castle provider (`BC`) must be on the classpath — it is bundled inside the fat JAR for each service.

## 3.4 Actuator Endpoints

All services expose Spring Boot Actuator endpoints. The standard set enabled across the platform:

| Endpoint | Path | Purpose |
|---|---|---|
| health | `/actuator/health` | Liveness and readiness probe |
| info | `/actuator/info` | Build info, version |
| metrics | `/actuator/metrics` | Micrometer metrics |
| prometheus | `/actuator/prometheus` | Prometheus scrape endpoint |
| env | `/actuator/env` | Environment properties (restricted) |
| loggers | `/actuator/loggers` | Runtime log level adjustment |

The `health` endpoint is used by the diagnostic service to aggregate platform health. The `prometheus` endpoint is scraped by the Prometheus server on its configured scrape interval.

Actuator endpoints are typically secured — only accessible from internal networks or with an actuator-specific security token, not exposed through the load balancers to external clients.

## 3.5 Common Dependencies

The following dependencies appear across all or nearly all backend services, inferred from the JAR manifests and package structure:

| Dependency | Purpose |
|---|---|
| `spring-boot-starter-web` | Embedded Tomcat, REST controllers |
| `spring-boot-starter-data-jpa` | JPA/Hibernate ORM |
| `spring-boot-starter-security` | Spring Security |
| `spring-boot-starter-actuator` | Health, metrics, management endpoints |
| `spring-cloud-starter-config` | Config server client |
| `spring-boot-starter-amqp` | RabbitMQ / AMQP messaging |
| `jasypt-spring-boot-starter` | Jasypt encryption integration |
| `mysql-connector-j` | MySQL JDBC driver |
| `flyway-core` | Database migration |
| `micrometer-registry-prometheus` | Prometheus metrics export |
| `bouncy-castle` (`bcprov-jdk18on`) | Cryptographic provider for Jasypt |
| `spring-boot-starter-validation` | Bean validation (JSR-380) |

---

# Part 4 — Configuration Deep Dive

## 4.1 setup.properties

`setup.properties` is the master installer configuration file at the root of `installation-package-2.6.9.jar`. It is read by the installer process to drive the deployment of all services. It contains:

### Infrastructure Endpoints

```properties
# MySQL
db.host=<mysql-host>
db.port=3306
db.root.password=ENC(...)
db.name=<database-name>

# RabbitMQ
rabbitmq.host=<rabbitmq-host>
rabbitmq.port=5671
rabbitmq.username=<username>
rabbitmq.password=ENC(...)
rabbitmq.vhost=<vhost>

# Config Server
config.server.host=<config-host>
config.server.port=8103
```

### SSL / Security

```properties
# Jasypt master passphrase (used to encrypt all ENC(...) values)
parts.sslPassphraseEncoded=ENC(...)

# Keystore / truststore
ssl.keystore.path=/opt/ecs/security/server.keystore
ssl.keystore.password=ENC(...)
ssl.truststore.path=/opt/ecs/security/server.truststore
ssl.truststore.password=ENC(...)
```

### Service Hostnames

```properties
customers.host=<host>
catalog.host=<host>
fulfillment.host=<host>
# ... one entry per service
```

### Installer Behaviour

```properties
install.base.path=/opt/ecs
install.user=ecs
install.group=ecs
create.systemd.units=true
create.firewall.rules=true
```

## 4.2 versions.yml / version.yml

`versions.yml` is the service version manifest at the root of the installation package. It maps each service name to its version string:

```yaml
customers: 2.6.9
blob-store: 2.6.9
event: 2.6.9
catalog: 2.6.9
service-instances: 2.6.9
pricing: 2.6.9
request: 2.6.9
fulfillment: 2.6.9
api-doc: 2.6.9
reporting: 2.6.9
config: 2.6.9
diagnostic: 2.6.9
export: 2.6.9
external-events: 2.6.9
ticketing: 2.6.9
management-ui: 2.6.9
portal-ui: 2.6.9
backend-lb: 2.6.9
frontend-lb: 2.6.9
grafana: 2.6.9
prometheus: 2.6.9
permutation-demo-data-migrator: 2.6.9
```

`version.yml` is the package-level metadata:

```yaml
version: 2.6.9
buildDate: <build-timestamp>
vendor: DXC Technology
product: CPI Services
```

## 4.3 application-backend.properties

This is the **shared base configuration** served by the config server to all backend services. It is the most important configuration file in the platform — every backend service inherits every property defined here. Key sections:

### SSL Configuration (shared across all backend services)

```properties
server.ssl.enabled=true
server.ssl.key-store=/opt/ecs/security/server.keystore
server.ssl.key-store-password=${parts.sslPassphraseEncoded}
server.ssl.key-store-type=JKS
server.ssl.trust-store=/opt/ecs/security/server.truststore
server.ssl.trust-store-password=${parts.sslPassphraseEncoded}
server.ssl.trust-store-type=JKS
server.ssl.enabled-protocols=TLSv1.2
security.trust-store=/opt/ecs/security/server.truststore
security.trust-store-password=${parts.sslPassphraseEncoded}
```

### RabbitMQ Configuration (shared)

```properties
spring.rabbitmq.host=${rabbitmq.host}
spring.rabbitmq.port=5671
spring.rabbitmq.username=${rabbitmq.username}
spring.rabbitmq.password=${rabbitmq.password}
spring.rabbitmq.virtual-host=${rabbitmq.vhost}
spring.rabbitmq.ssl.enabled=true
spring.rabbitmq.ssl.key-store=/opt/ecs/security/server.keystore
spring.rabbitmq.ssl.key-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.trust-store=/opt/ecs/security/server.truststore
spring.rabbitmq.ssl.trust-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.algorithm=TLSv1.2
```

### Flyway Configuration (shared)

```properties
spring.flyway.enabled=true
spring.flyway.baseline-on-migrate=true
spring.flyway.locations=classpath:db/migration
```

### Actuator Configuration (shared)

```properties
management.endpoints.web.exposure.include=health,info,metrics,prometheus,loggers
management.endpoint.health.show-details=when-authorized
management.metrics.export.prometheus.enabled=true
```

### Jasypt Configuration (shared)

```properties
jasypt.encryptor.algorithm=PBEWITHSHA256AND256BITAES-CBC-BC
jasypt.encryptor.provider-name=BC
jasypt.encryptor.key-obtention-iterations=1000
jasypt.encryptor.pool-size=1
jasypt.encryptor.salt-generator-classname=org.jasypt.salt.RandomSaltGenerator
jasypt.encryptor.string-output-type=base64
```

### Event Publishing (shared)

```properties
events.exchange=ecs.events
events.routing-key-prefix=ecs
spring.rabbitmq.listener.simple.acknowledge-mode=manual
spring.rabbitmq.listener.simple.retry.enabled=true
spring.rabbitmq.listener.simple.retry.max-attempts=3
spring.rabbitmq.listener.simple.retry.initial-interval=1000
spring.rabbitmq.listener.simple.retry.multiplier=2.0
spring.rabbitmq.listener.simple.retry.max-interval=10000
```

## 4.4 application-frontend.yml

The shared configuration profile for frontend-facing services (management-ui, portal-ui). Served by the config server to services in the `frontend` group. Key sections:

### Backend API URLs

```yaml
api:
  customers: https://backend-lb/customers
  catalog: https://backend-lb/catalog
  fulfillment: https://backend-lb/fulfillment
  request: https://backend-lb/request
  service-instances: https://backend-lb/service-instances
  pricing: https://backend-lb/pricing
  reporting: https://backend-lb/reporting
  export: https://backend-lb/export
  diagnostic: https://backend-lb/diagnostic
  external-events: https://backend-lb/external-events
  ticketing: https://backend-lb/ticketing
```

### SSL (frontend services)

```yaml
server:
  ssl:
    enabled: true
    key-store: /opt/ecs/security/server.keystore
    key-store-password: ${parts.sslPassphraseEncoded}
    key-store-type: JKS
    trust-store: /opt/ecs/security/server.truststore
    trust-store-password: ${parts.sslPassphraseEncoded}
    enabled-protocols: TLSv1.2
```

## 4.5 Per-Service application.properties

Each service has its own `application.properties` that overrides or extends the shared base. The per-service config primarily sets:

- `server.port` — the service's listen port
- `spring.datasource.url` — the service-specific database URL
- `spring.datasource.username` / `spring.datasource.password` — DB credentials (Jasypt-encrypted)
- `spring.application.name` — used by the config server to identify the service
- Service-specific feature flags and integration endpoints

Example for `customers`:

```properties
server.port=8090
spring.application.name=customers
spring.datasource.url=jdbc:mysql://${db.host}:${db.port}/customers_db?useSSL=true&requireSSL=true&verifyServerCertificate=true&trustCertificateKeyStoreUrl=file:/opt/ecs/security/server.truststore&trustCertificateKeyStorePassword=${parts.sslPassphraseEncoded}
spring.datasource.username=${db.username}
spring.datasource.password=ENC(...)
spring.datasource.driver-class-name=com.mysql.cj.jdbc.Driver
spring.jpa.database-platform=org.hibernate.dialect.MySQL8Dialect
```

Note the MySQL JDBC URL includes `useSSL=true`, `requireSSL=true`, and `verifyServerCertificate=true` — the platform enforces TLS for all database connections, using the same truststore as the service-to-service TLS.

---
# Part 5 — SSL/TLS Architecture

## 5.1 Keystore & Truststore Paths

The platform uses a single shared security directory for all cryptographic material:

```
/opt/ecs/security/
├── server.keystore      # JKS keystore — contains the service's private key and certificate
└── server.truststore    # JKS truststore — contains trusted CA certificates
```

These paths are **hardcoded** across all service configurations. Every service on a given host uses the same keystore and truststore. This means:

- All services on a host share the same TLS certificate (the certificate must have SANs covering all service hostnames or use a wildcard)
- The truststore must contain the CA certificate(s) that signed all service certificates, the MySQL server certificate CA, and the RabbitMQ server certificate CA
- The keystore password and truststore password are the same value (`parts.sslPassphraseEncoded`) across all services

## 5.2 SSL Configuration Pattern

The SSL configuration is identical across all 14+ backend services, injected via `application-backend.properties`:

```properties
# Server TLS (inbound connections to this service)
server.ssl.enabled=true
server.ssl.key-store=/opt/ecs/security/server.keystore
server.ssl.key-store-password=${parts.sslPassphraseEncoded}
server.ssl.key-store-type=JKS
server.ssl.trust-store=/opt/ecs/security/server.truststore
server.ssl.trust-store-password=${parts.sslPassphraseEncoded}
server.ssl.trust-store-type=JKS
server.ssl.enabled-protocols=TLSv1.2

# Outbound TLS (when this service makes HTTPS calls to other services)
security.trust-store=/opt/ecs/security/server.truststore
security.trust-store-password=${parts.sslPassphraseEncoded}

# RabbitMQ TLS (AMQPS)
spring.rabbitmq.ssl.enabled=true
spring.rabbitmq.ssl.key-store=/opt/ecs/security/server.keystore
spring.rabbitmq.ssl.key-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.trust-store=/opt/ecs/security/server.truststore
spring.rabbitmq.ssl.trust-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.algorithm=TLSv1.2

# MySQL TLS (JDBC connection)
# Embedded in the JDBC URL:
# useSSL=true&requireSSL=true&verifyServerCertificate=true
# &trustCertificateKeyStoreUrl=file:/opt/ecs/security/server.truststore
# &trustCertificateKeyStorePassword=${parts.sslPassphraseEncoded}
```

This means every service enforces TLS on **three distinct connection paths**:

1. **Inbound HTTP** — clients connecting to the service's REST API over HTTPS
2. **Outbound AMQPS** — the service connecting to RabbitMQ over TLS port 5671
3. **Outbound JDBC** — the service connecting to MySQL over TLS port 3306

## 5.3 Enabled Protocols & Cipher Suites

The platform explicitly restricts TLS to **TLSv1.2 only**:

```properties
server.ssl.enabled-protocols=TLSv1.2
spring.rabbitmq.ssl.algorithm=TLSv1.2
```

TLSv1.3 is not enabled in the standard configuration. TLSv1.0 and TLSv1.1 are explicitly excluded. This is a deliberate security posture — TLSv1.2 is the minimum acceptable version for enterprise compliance in the environments this platform targets.

Cipher suite configuration is not explicitly set in the application properties, meaning the JVM default cipher suite list for TLSv1.2 applies. With Java 17, this includes:

- `TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384`
- `TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256`
- `TLS_DHE_RSA_WITH_AES_256_GCM_SHA384`
- `TLS_DHE_RSA_WITH_AES_128_GCM_SHA256`

## 5.4 Certificate Requirements Per Service

Because all services on a host share `/opt/ecs/security/server.keystore`, the certificate in that keystore must be valid for all services running on that host.

### Single-Host Deployment (all services on one machine)

The certificate must include SANs for:
- The host's FQDN (e.g., `cpi.example.com`)
- The host's short hostname (e.g., `cpi`)
- `localhost` and `127.0.0.1` (for local inter-service communication)
- The backend-lb hostname (if different)
- The frontend-lb hostname (if different)

### Multi-Host Deployment (services distributed across hosts)

Each host requires its own keystore with a certificate covering that host's FQDN and any service-specific DNS names. The truststore on every host must trust the CA that signed all other hosts' certificates, enabling mutual TLS between services.

### Certificate Type

- **Key algorithm:** RSA (2048-bit minimum, 4096-bit recommended for production)
- **Signature algorithm:** SHA-256 with RSA
- **Key usage:** Digital Signature, Key Encipherment
- **Extended key usage:** Server Authentication (1.3.6.1.5.5.7.3.1), Client Authentication (1.3.6.1.5.5.7.3.2)
- Both Server and Client authentication EKUs are required because services act as both TLS servers (accepting inbound) and TLS clients (making outbound calls to other services)

## 5.5 SAN Construction

For a standard single-host deployment, the minimum SAN set for the server certificate:

```
DNS: <hostname>
DNS: <hostname>.<domain>
DNS: backend-lb
DNS: frontend-lb
DNS: config-svc
DNS: localhost
IP:  127.0.0.1
IP:  <host-ip>
```

For a distributed deployment where each service group runs on a dedicated host:

| Host | Required SANs |
|---|---|
| Config host | `config-svc`, `config-svc.<domain>`, host FQDN |
| Backend host | All backend service names, `backend-lb`, host FQDN |
| Frontend host | `management-ui`, `portal-ui`, `frontend-lb`, host FQDN |
| DB host | MySQL hostname, host FQDN |
| RabbitMQ host | RabbitMQ hostname, host FQDN |

The truststore on every host must contain the CA certificate that signed all other hosts' certificates. In practice, a single internal CA is used to sign all certificates, and that CA's certificate is imported into every truststore.

---

# Part 6 — Database Architecture

## 6.1 MySQL Schema Per Service

Each backend service that requires persistence has its own dedicated MySQL database (schema). This follows the microservices pattern of database-per-service, ensuring schema isolation and independent migration lifecycles.

| Service | Database Name | Notes |
|---|---|---|
| customers | `customers_db` | Customer accounts, entitlements, subscriptions |
| blob-store | `blobstore_db` | Binary object metadata (content stored on filesystem or object store) |
| event | `event_db` | Event log — high write volume, append-mostly |
| catalog | `catalog_db` | Catalogue items, versions, parameters, provider mappings |
| service-instances | `serviceinstances_db` | Instance state machine, lifecycle history |
| pricing | `pricing_db` | Pricing rules, tiers, currency rates |
| request | `request_db` | Order records, request lifecycle, approval state |
| fulfillment | `fulfillment_db` | Workflow state, adapter task queues, execution history |
| reporting | `reporting_db` | Aggregated usage data, billing summaries, report definitions |
| export | `export_db` | Export job records, download links |
| external-events | `externalevents_db` | Inbound event log, webhook registrations |
| ticketing | `ticketing_db` | ITSM ticket references, approval workflows |

The `config`, `diagnostic`, `api-doc`, `management-ui`, `portal-ui`, `backend-lb`, `frontend-lb`, `grafana`, and `prometheus` services do not use MySQL.

## 6.2 Flyway Migration Pattern

All database-backed services use Flyway for schema management. Migration scripts are bundled inside the fat JAR at:

```
<service>-svc.jar
└── BOOT-INF/classes/db/migration/
    ├── V1__initial_schema.sql
    ├── V2__add_indexes.sql
    ├── V3__add_column_x.sql
    └── ...
```

Flyway runs automatically on service startup (`spring.flyway.enabled=true`). The `baseline-on-migrate=true` setting allows Flyway to manage schemas that were created outside of Flyway.

Migration scripts follow the standard Flyway naming convention:
- `V{version}__{description}.sql` — versioned migrations (run once, in order)
- `R__{description}.sql` — repeatable migrations (re-run when checksum changes)

The Flyway schema history table (`flyway_schema_history`) is created in each service's database schema, tracking which migrations have been applied.

## 6.3 Oracle Support

The platform supports Oracle as an alternative to MySQL. Oracle support is activated by:

1. Swapping the JDBC driver from `mysql-connector-j` to `ojdbc11`
2. Changing `spring.datasource.driver-class-name` to `oracle.jdbc.OracleDriver`
3. Changing `spring.jpa.database-platform` to `org.hibernate.dialect.OracleDialect`
4. Updating the JDBC URL to Oracle format: `jdbc:oracle:thin:@//<host>:<port>/<service>`
5. Ensuring Flyway migration scripts are Oracle-compatible (the platform ships dual SQL scripts for MySQL and Oracle)

Oracle support is present in the fulfillment service's adapter framework and in the shared database configuration templates. The installer's `setup.properties` includes a `db.type` property (`mysql` or `oracle`) that drives the driver selection.

## 6.4 Connection Pool Configuration

All services use HikariCP (the default Spring Boot connection pool) with the following shared configuration from `application-backend.properties`:

```properties
spring.datasource.hikari.connection-timeout=30000
spring.datasource.hikari.idle-timeout=600000
spring.datasource.hikari.max-lifetime=1800000
spring.datasource.hikari.maximum-pool-size=10
spring.datasource.hikari.minimum-idle=2
spring.datasource.hikari.pool-name=${spring.application.name}-pool
spring.datasource.hikari.connection-test-query=SELECT 1
```

The `maximum-pool-size=10` is the default. High-throughput services (fulfillment, service-instances, event) may override this in their per-service configuration.

HikariCP metrics are exposed via Micrometer and scraped by Prometheus, providing visibility into pool utilisation, connection wait times, and connection creation rates per service.

## 6.5 Shared vs Isolated Schemas

The platform uses **fully isolated schemas** — one database per service. There are no cross-service foreign keys or shared tables. Services communicate exclusively via:

- **REST API calls** (synchronous, service-to-service over HTTPS via backend-lb)
- **RabbitMQ events** (asynchronous, via the shared event bus)

This isolation means:
- Each service can be migrated independently without coordinating with other services
- A schema change in one service cannot break another service's database operations
- Each service's database can be scaled, backed up, and restored independently
- The reporting service aggregates data from other services via their REST APIs, not via direct database queries

The only shared database resource is the MySQL server instance itself — all schemas reside on the same MySQL server in the standard deployment, but they are logically isolated.

---
# Part 7 — Event-Driven Architecture

## 7.1 RabbitMQ / AMQPS Configuration

RabbitMQ is the platform's message broker. All inter-service asynchronous communication flows through RabbitMQ. The platform uses **AMQPS** (AMQP over TLS) exclusively — plaintext AMQP on port 5672 is not used. The standard port is **5671**.

The shared RabbitMQ configuration from `application-backend.properties`:

```properties
spring.rabbitmq.host=${rabbitmq.host}
spring.rabbitmq.port=5671
spring.rabbitmq.username=${rabbitmq.username}
spring.rabbitmq.password=ENC(...)
spring.rabbitmq.virtual-host=${rabbitmq.vhost}

# TLS
spring.rabbitmq.ssl.enabled=true
spring.rabbitmq.ssl.key-store=/opt/ecs/security/server.keystore
spring.rabbitmq.ssl.key-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.trust-store=/opt/ecs/security/server.truststore
spring.rabbitmq.ssl.trust-store-password=${parts.sslPassphraseEncoded}
spring.rabbitmq.ssl.algorithm=TLSv1.2

# Consumer reliability
spring.rabbitmq.listener.simple.acknowledge-mode=manual
spring.rabbitmq.listener.simple.retry.enabled=true
spring.rabbitmq.listener.simple.retry.max-attempts=3
spring.rabbitmq.listener.simple.retry.initial-interval=1000
spring.rabbitmq.listener.simple.retry.multiplier=2.0
spring.rabbitmq.listener.simple.retry.max-interval=10000
spring.rabbitmq.listener.simple.prefetch=1
```

Manual acknowledgement (`acknowledge-mode=manual`) means a consumer explicitly ACKs a message only after successfully processing it. If processing fails, the message is NACKed and requeued (up to `max-attempts=3` retries with exponential backoff). After 3 failures, the message is routed to a dead-letter queue.

## 7.2 Exchange & Queue Topology

The platform uses a **topic exchange** pattern. The main exchange is `ecs.events`. Routing keys follow the pattern:

```
ecs.<domain>.<entity>.<action>
```

Examples:
- `ecs.customers.customer.created`
- `ecs.catalog.item.updated`
- `ecs.request.order.submitted`
- `ecs.fulfillment.instance.provisioned`
- `ecs.service-instances.instance.state-changed`

Each service that consumes events declares its own **durable queue** bound to the exchange with one or more routing key patterns. Queue names follow the pattern:

```
<consuming-service>.<domain>.<entity>.<action>
```

Example — the `service-instances` service consuming fulfillment events:
```
service-instances.fulfillment.instance.provisioned
service-instances.fulfillment.instance.deprovisioned
```

### Dead Letter Exchange

A dead-letter exchange (`ecs.events.dlx`) and corresponding dead-letter queues (`<queue-name>.dlq`) are configured for all consumer queues. Messages that exhaust their retry attempts are routed to the DLQ for manual inspection and replay.

### Queue Durability

All queues are declared as **durable** — they survive RabbitMQ restarts. Messages are published as **persistent** (delivery mode 2). This ensures no events are lost during RabbitMQ restarts or brief outages.

## 7.3 Event Definitions Per Service

Each service ships `.event.yml` files inside its fat JAR that define the events it publishes and the events it consumes. These files serve as the contract between services.

### customers service events

**Published:**
```yaml
events:
  published:
    - entity: customer
      actions: [created, updated, deleted]
      exchange: ecs.events
      routingKeyPattern: ecs.customers.customer.{action}
    - entity: entitlement
      actions: [assigned, revoked]
      exchange: ecs.events
      routingKeyPattern: ecs.customers.entitlement.{action}
```

**Consumed:**
```yaml
events:
  consumed:
    - queue: customers.fulfillment.instance.provisioned
      exchange: ecs.events
      routingKey: ecs.fulfillment.instance.provisioned
      handler: CustomerInstanceProvisionedHandler
```

### catalog service events

**Published:**
```yaml
events:
  published:
    - entity: catalogItem
      actions: [created, updated, deleted, published, unpublished]
      exchange: ecs.events
      routingKeyPattern: ecs.catalog.item.{action}
    - entity: catalogVersion
      actions: [created, activated]
      exchange: ecs.events
      routingKeyPattern: ecs.catalog.version.{action}
```

### request service events

**Published:**
```yaml
events:
  published:
    - entity: order
      actions: [submitted, validated, approved, rejected, cancelled]
      exchange: ecs.events
      routingKeyPattern: ecs.request.order.{action}
```

**Consumed:**
```yaml
events:
  consumed:
    - queue: request.fulfillment.instance.provisioned
      routingKey: ecs.fulfillment.instance.provisioned
    - queue: request.fulfillment.instance.failed
      routingKey: ecs.fulfillment.instance.failed
    - queue: request.ticketing.approval.granted
      routingKey: ecs.ticketing.approval.granted
    - queue: request.ticketing.approval.rejected
      routingKey: ecs.ticketing.approval.rejected
```

### fulfillment service events

**Published:**
```yaml
events:
  published:
    - entity: instance
      actions: [provisioning, provisioned, failed, modifying, modified, deprovisioning, deprovisioned]
      exchange: ecs.events
      routingKeyPattern: ecs.fulfillment.instance.{action}
    - entity: task
      actions: [started, completed, failed]
      exchange: ecs.events
      routingKeyPattern: ecs.fulfillment.task.{action}
```

### service-instances service events

**Published:**
```yaml
events:
  published:
    - entity: instance
      actions: [state-changed, deleted]
      exchange: ecs.events
      routingKeyPattern: ecs.service-instances.instance.{action}
```

**Consumed:** All fulfillment instance events (to update the instance state machine).

### external-events service events

**Consumed:** External webhook payloads translated to internal events and published to `ecs.events` with appropriate routing keys.

## 7.4 Entity Events & Consumer Queues

The complete event flow for a service request lifecycle:

```
portal-ui
  -> POST /request/orders
    -> request-svc publishes: ecs.request.order.submitted
      -> fulfillment-svc consumes: starts provisioning workflow
        -> fulfillment-svc publishes: ecs.fulfillment.instance.provisioning
          -> service-instances-svc consumes: sets state = PROVISIONING
        -> fulfillment-svc publishes: ecs.fulfillment.instance.provisioned
          -> service-instances-svc consumes: sets state = ACTIVE
          -> request-svc consumes: sets order state = COMPLETED
          -> customers-svc consumes: records instance against customer
          -> reporting-svc consumes: records provisioning event for billing
          -> event-svc consumes: persists event to event log
```

This fan-out pattern means a single fulfillment event is consumed by 5+ services simultaneously, each updating their own state independently.

---

# Part 8 — Load Balancer Deep Dive

## 8.1 Backend LB — Nginx Upstreams

The `backend-lb` service is an Nginx reverse proxy that provides a single internal HTTPS endpoint for all backend services. Internal clients (management-ui, portal-ui, and inter-service calls) use the backend-lb rather than calling services directly.

### Nginx Upstream Configuration

```nginx
upstream customers {
    server 127.0.0.1:8090;
    keepalive 32;
}
upstream blob-store {
    server 127.0.0.1:8091;
    keepalive 32;
}
upstream event {
    server 127.0.0.1:8092;
    keepalive 32;
}
upstream catalog {
    server 127.0.0.1:8093;
    keepalive 32;
}
upstream service-instances {
    server 127.0.0.1:8094;
    keepalive 32;
}
upstream pricing {
    server 127.0.0.1:8095;
    keepalive 32;
}
upstream request {
    server 127.0.0.1:8096;
    keepalive 32;
}
upstream fulfillment {
    server 127.0.0.1:8097;
    keepalive 32;
}
upstream reporting {
    server 127.0.0.1:8099;
    keepalive 32;
}
upstream config {
    server 127.0.0.1:8103;
    keepalive 32;
}
upstream diagnostic {
    server 127.0.0.1:8104;
    keepalive 32;
}
upstream export {
    server 127.0.0.1:8105;
    keepalive 32;
}
upstream external-events {
    server 127.0.0.1:8106;
    keepalive 32;
}
```

### Path-Based Routing

```nginx
server {
    listen 443 ssl;
    server_name backend-lb;

    ssl_certificate     /opt/ecs/security/server.crt;
    ssl_certificate_key /opt/ecs/security/server.key;
    ssl_trusted_certificate /opt/ecs/security/ca.crt;
    ssl_protocols       TLSv1.2;
    ssl_verify_client   optional;

    location /customers/         { proxy_pass https://customers/; }
    location /blob-store/        { proxy_pass https://blob-store/; }
    location /event/             { proxy_pass https://event/; }
    location /catalog/           { proxy_pass https://catalog/; }
    location /service-instances/ { proxy_pass https://service-instances/; }
    location /pricing/           { proxy_pass https://pricing/; }
    location /request/           { proxy_pass https://request/; }
    location /fulfillment/       { proxy_pass https://fulfillment/; }
    location /reporting/         { proxy_pass https://reporting/; }
    location /config/            { proxy_pass https://config/; }
    location /diagnostic/        { proxy_pass https://diagnostic/; }
    location /export/            { proxy_pass https://export/; }
    location /external-events/   { proxy_pass https://external-events/; }
    location /ticketing/         { proxy_pass https://ticketing/; }
}
```

Note: The backend-lb proxies to backend services over HTTPS — the services themselves have TLS enabled, so the LB performs TLS re-encryption. The LB's truststore must contain the CA that signed the upstream service certificates.

## 8.2 Frontend LB — Port 443 & SSL Termination

The `frontend-lb` is the only component exposed to end users and external networks. It listens on port 443 and routes traffic to the UI services and selected backend APIs.

```nginx
server {
    listen 80;
    server_name <platform-fqdn>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name <platform-fqdn>;

    ssl_certificate     /opt/ecs/security/server.crt;
    ssl_certificate_key /opt/ecs/security/server.key;
    ssl_protocols       TLSv1.2;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Management UI
    location /management/ {
        proxy_pass https://management-ui/;
    }

    # Customer Portal (default)
    location / {
        proxy_pass https://portal-ui/;
    }

    # Backend APIs accessible to the UIs
    location /api/catalog/           { proxy_pass https://catalog/; }
    location /api/customers/         { proxy_pass https://customers/; }
    location /api/blob-store/        { proxy_pass https://blob-store/; }
    location /api/event/             { proxy_pass https://event/; }
    location /api/fulfillment/       { proxy_pass https://fulfillment/; }
    location /api/request/           { proxy_pass https://request/; }
    location /api/service-instances/ { proxy_pass https://service-instances/; }
    location /api/pricing/           { proxy_pass https://pricing/; }
    location /api/reporting/         { proxy_pass https://reporting/; }
    location /api/ticketing/         { proxy_pass https://ticketing/; }
}
```

## 8.3 Proxy Rules & Headers

Both load balancers inject standard proxy headers to preserve client information through the proxy chain:

```nginx
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Port  $server_port;

proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_connect_timeout 60s;
proxy_send_timeout    60s;
proxy_read_timeout    60s;

proxy_buffering    on;
proxy_buffer_size  4k;
proxy_buffers      8 4k;
```

Spring Boot services are configured to trust the `X-Forwarded-*` headers from the load balancer:

```properties
server.forward-headers-strategy=NATIVE
```

This ensures that Spring Security, session management, and redirect URLs use the original client IP and protocol rather than the proxy's internal address.

---
# Part 9 — Fulfillment Service Deep Dive

## 9.1 Scale & Complexity

The fulfillment service is by far the largest component in the CPI platform:

| Metric | Value |
|---|---|
| Fat JAR size | ~357 MB |
| JAR entries | 3,705 |
| Nested JARs (dependencies) | 569 |
| Port | 8097 |
| Install path | `/opt/ecs/fulfillment` |
| Database | `fulfillment_db` (MySQL) |

This scale reflects the fulfillment service's role as the **orchestration engine** for the entire platform. It contains the adapter framework, all adapter implementations, cloud provider SDKs, and the workflow engine that drives provisioning operations.

## 9.2 Adapters

The fulfillment service contains adapter implementations for multiple integration targets. Each adapter translates the platform's generic provisioning model into the specific API calls required by the target system.

### V2 Adapter

The platform's native V2 provisioning adapter. Implements the standard CPI provisioning protocol for services that natively support the V2 API. Used for first-party integrations where the target service was built to the CPI specification.

### OO (Operations Orchestrator) Adapter

Integrates with HP/Micro Focus Operations Orchestrator. Translates provisioning requests into OO flow executions. Used in environments where existing OO runbooks handle the actual provisioning logic. The adapter submits a flow execution request to OO and polls for completion.

### CAS (Cloud Automation Services) Adapter

Integrates with VMware Cloud Automation Services (formerly vRealize Automation). Submits deployment requests to CAS and tracks deployment lifecycle. Used for VMware-based private cloud provisioning.

### Snow (ServiceNow) Adapter

Integrates with ServiceNow for provisioning workflows that are managed through ITSM. Submits ServiceNow catalog item requests and tracks the resulting change/task records. Also used for approval workflows in conjunction with the ticketing service.

### ST2 (StackStorm) Adapter

Integrates with StackStorm (event-driven automation platform). Triggers StackStorm actions/workflows for provisioning operations. Used in environments where StackStorm is the automation backbone.

### AGILITY Adapter

Integrates with CA Agility Platform (formerly CA AppLogic). Handles provisioning of services on the Agility platform. Legacy adapter for environments still running CA Agility.

### ACE Adapter

Integrates with IBM ACE (App Connect Enterprise) or similar integration middleware. Used for provisioning workflows that require enterprise integration bus capabilities.

### CLOUDFORMS Adapter

Integrates with Red Hat CloudForms (now ManageIQ). Submits provisioning requests to CloudForms service catalogs and tracks order fulfilment. Used in Red Hat-based private cloud environments.

### ANSIBLE Adapter

Integrates with Ansible Tower / AWX. Triggers Ansible job templates for provisioning operations. One of the most flexible adapters — any provisioning operation that can be expressed as an Ansible playbook can be integrated via this adapter. Supports:
- Job template execution
- Workflow template execution
- Extra variables injection (service parameters passed as Ansible extra vars)
- Job status polling
- Output capture and storage in blob-store

### ALIMS Adapter

Integrates with ALIMS (Asset and Lifecycle Information Management System). Handles provisioning operations that require asset registration and lifecycle tracking in ALIMS. Used in environments with strict asset management requirements.

## 9.3 Cloud Providers

The fulfillment service contains cloud provider SDK integrations for direct cloud provisioning:

### AWS

Direct AWS provisioning via the AWS SDK for Java v2. Capabilities include:
- EC2 instance provisioning (launch, modify, terminate)
- RDS database provisioning
- S3 bucket creation and management
- VPC and networking resource management
- IAM role and policy management
- ECS/EKS workload deployment
- CloudFormation stack management

AWS credentials are configured via the standard AWS credential chain (environment variables, instance profile, or explicit access key/secret in Jasypt-encrypted configuration).

### Azure

Direct Azure provisioning via the Azure SDK for Java. Capabilities include:
- Virtual machine provisioning
- Azure SQL Database provisioning
- Storage account management
- Virtual network management
- Azure Active Directory integration
- ARM template deployment

### Google Cloud

Direct GCP provisioning via the Google Cloud Java client libraries. Capabilities include:
- Compute Engine instance provisioning
- Cloud SQL provisioning
- Cloud Storage bucket management
- VPC network management
- GKE cluster management

### Oracle Cloud

Direct OCI provisioning via the OCI Java SDK. Capabilities include:
- Compute instance provisioning
- Autonomous Database provisioning
- Object Storage management
- Virtual Cloud Network management

### VMware

VMware vSphere/vCenter integration via the vSphere Java API. Capabilities include:
- Virtual machine provisioning from templates
- Resource pool management
- Datastore management
- Network port group assignment
- vSphere tag management

### MCP (Managed Cloud Platform)

Integration with DXC's own Managed Cloud Platform. Proprietary adapter for provisioning services on DXC-managed infrastructure. Uses DXC-internal APIs.

### SAP

Integration with SAP Cloud Platform / SAP BTP. Handles provisioning of SAP services and environments. Used in enterprise environments with SAP as a core platform.

## 9.4 Adapter Configuration Patterns

Each adapter is configured via properties in the fulfillment service's `application.properties`, with sensitive values Jasypt-encrypted:

```properties
# Global adapter defaults
fulfillment.adapter.timeout=300000
fulfillment.adapter.retry.max-attempts=3
fulfillment.adapter.retry.backoff=5000

# Ansible adapter
fulfillment.adapter.ansible.url=https://ansible-tower.example.com
fulfillment.adapter.ansible.username=tower-user
fulfillment.adapter.ansible.password=ENC(...)
fulfillment.adapter.ansible.ssl.verify=true
fulfillment.adapter.ansible.ssl.trust-store=/opt/ecs/security/server.truststore

# AWS adapter
fulfillment.adapter.aws.region=eu-west-1
fulfillment.adapter.aws.access-key=ENC(...)
fulfillment.adapter.aws.secret-key=ENC(...)

# ServiceNow adapter
fulfillment.adapter.snow.url=https://instance.service-now.com
fulfillment.adapter.snow.username=ENC(...)
fulfillment.adapter.snow.password=ENC(...)

# VMware adapter
fulfillment.adapter.vmware.vcenter.url=https://vcenter.example.com
fulfillment.adapter.vmware.vcenter.username=ENC(...)
fulfillment.adapter.vmware.vcenter.password=ENC(...)
fulfillment.adapter.vmware.vcenter.ssl.trust-store=/opt/ecs/security/server.truststore
```

### Workflow Engine

The fulfillment service contains an internal workflow engine that manages multi-step provisioning operations. A provisioning workflow consists of:

1. **Validate** — check parameters against catalogue definition
2. **Pre-provision** — create supporting resources (DNS entries, firewall rules, etc.)
3. **Provision** — call the target adapter to create the primary resource
4. **Post-provision** — configure the provisioned resource, register in service-instances
5. **Notify** — publish `ecs.fulfillment.instance.provisioned` event

Each step is persisted to `fulfillment_db` so that workflows can be resumed after a service restart. Failed steps are retried according to the adapter's retry configuration. The workflow state is visible via the fulfillment service's REST API and surfaced in the management UI.

---

# Part 10 — Monitoring Stack

## 10.1 Prometheus

Prometheus is deployed as part of the CPI platform's monitoring stack. It scrapes metrics from all Spring Boot services, the Nginx load balancers, RabbitMQ, and the host system.

### Scrape Configuration

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'cpi-backend-services'
    scheme: https
    tls_config:
      ca_file: /opt/ecs/security/ca.crt
      cert_file: /opt/ecs/security/server.crt
      key_file: /opt/ecs/security/server.key
    static_configs:
      - targets:
          - 'localhost:8090'   # customers
          - 'localhost:8091'   # blob-store
          - 'localhost:8092'   # event
          - 'localhost:8093'   # catalog
          - 'localhost:8094'   # service-instances
          - 'localhost:8095'   # pricing
          - 'localhost:8096'   # request
          - 'localhost:8097'   # fulfillment
          - 'localhost:8099'   # reporting
          - 'localhost:8103'   # config
          - 'localhost:8104'   # diagnostic
          - 'localhost:8105'   # export
          - 'localhost:8106'   # external-events
    metrics_path: '/actuator/prometheus'

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']

  - job_name: 'rabbitmq'
    static_configs:
      - targets: ['<rabbitmq-host>:15692']

  - job_name: 'nginx-backend-lb'
    static_configs:
      - targets: ['localhost:9113']

  - job_name: 'nginx-frontend-lb'
    static_configs:
      - targets: ['localhost:9114']
```

Prometheus scrapes the Spring Boot `/actuator/prometheus` endpoint over HTTPS, using the platform's shared certificate and truststore.

### Storage

Prometheus stores time-series data locally at `/opt/ecs/prometheus/data`. The default retention period is 15 days. For longer retention, a remote write target (e.g., Amazon Managed Prometheus, Thanos, or Cortex) can be configured.

## 10.2 Grafana

Grafana is pre-configured with dashboards for all platform services. It connects to Prometheus as its primary data source.

### Data Source Configuration

```yaml
datasources:
  - name: Prometheus
    type: prometheus
    url: http://localhost:9090
    access: proxy
    isDefault: true
```

### Pre-Built Dashboards

| Dashboard | Panels |
|---|---|
| Platform Overview | Service health status, request rates, error rates for all services |
| JVM Metrics | Heap usage, GC pause times, thread counts, class loading — per service |
| HTTP Metrics | Request rate, latency percentiles (p50, p95, p99), error rate — per service |
| Database Metrics | HikariCP pool utilisation, connection wait time, active connections — per service |
| RabbitMQ Metrics | Queue depths, message rates, consumer counts, connection counts |
| Fulfillment Metrics | Active workflows, adapter call rates, workflow success/failure rates |
| Infrastructure | CPU, memory, disk I/O, network I/O — from node exporter |
| Nginx Metrics | Request rate, upstream response times, active connections — per LB |

### Authentication

Grafana is configured with local user authentication. The default admin credentials are set during installation via `setup.properties`. Grafana is not exposed through the frontend-lb — it is accessible only on its internal port (3000) or via a separate administrative access path.

## 10.3 Node Exporter

Prometheus Node Exporter is deployed on each host to collect OS-level metrics:

- CPU utilisation (per core, per mode)
- Memory usage (total, used, cached, buffers)
- Disk I/O (reads/writes per second, latency)
- Filesystem usage (per mount point)
- Network I/O (bytes in/out, packets, errors)
- System load averages
- Open file descriptors
- Process counts

Node Exporter listens on port 9100 and is scraped by Prometheus on the `node-exporter` job.

## 10.4 Per-Service Metrics

Each Spring Boot service exposes the following metric categories via Micrometer:

### HTTP Server Metrics
```
http_server_requests_seconds_count{method, uri, status}
http_server_requests_seconds_sum{method, uri, status}
http_server_requests_seconds_max{method, uri, status}
```

### JVM Metrics
```
jvm_memory_used_bytes{area, id}
jvm_memory_max_bytes{area, id}
jvm_gc_pause_seconds_count{action, cause}
jvm_gc_pause_seconds_sum{action, cause}
jvm_threads_live_threads
jvm_threads_daemon_threads
jvm_classes_loaded_classes
```

### HikariCP Metrics
```
hikaricp_connections_active{pool}
hikaricp_connections_idle{pool}
hikaricp_connections_pending{pool}
hikaricp_connections_timeout_total{pool}
hikaricp_connections_acquire_seconds{pool}
hikaricp_connections_creation_seconds{pool}
```

### RabbitMQ Metrics
```
rabbitmq_acknowledged_total
rabbitmq_rejected_total
rabbitmq_failed_to_publish_total
rabbitmq_not_acknowledged_published_total
rabbitmq_published_total
rabbitmq_consumed_total
```

### Custom Business Metrics (fulfillment)
```
fulfillment_workflows_active
fulfillment_workflows_completed_total{adapter, status}
fulfillment_adapter_calls_total{adapter, operation, status}
fulfillment_adapter_call_duration_seconds{adapter, operation}
```

---
# Part 11 — Installation & Bundle Structure

## 11.1 part.yml Schema

Every installer JAR contains a `part.yml` at its root. This file is the installer's manifest for that service — it tells the installer framework everything it needs to know to deploy the service. The full schema:

```yaml
name: <service-name>
version: <version>
installPath: /opt/ecs/<service-name>

group: <group>
# One of: backend, frontend, backend-lb, frontend-lb, doc, monitoring-extra

templates:
  - source: config/application.properties
    destination: /opt/ecs/<service>/config/application.properties
    variables:
      - db.host
      - db.port
      - rabbitmq.host
      - parts.sslPassphraseEncoded

chmod:
  - path: /opt/ecs/<service>/bin/<service>-svc.jar
    mode: "0755"
    owner: ecs
    group: ecs
  - path: /opt/ecs/<service>/config/
    mode: "0750"
    owner: ecs
    group: ecs
  - path: /opt/ecs/security/server.keystore
    mode: "0640"
    owner: ecs
    group: ecs

firewallPorts:
  - port: <service-port>
    protocol: tcp
    direction: inbound
    description: "<service-name> API"

buildInfo:
  buildTime: <ISO-8601-timestamp>
  gitCommit: <short-sha>
  gitBranch: <branch>
  builtBy: <ci-system>
```

### Group Values and Their Meaning

| Group | Meaning |
|---|---|
| `backend` | Spring Boot microservice, runs as systemd unit, has a port |
| `frontend` | UI application, served by embedded server or Nginx |
| `backend-lb` | Nginx instance proxying backend services |
| `frontend-lb` | Nginx instance proxying frontend services, port 443 |
| `doc` | Documentation service |
| `monitoring-extra` | Monitoring component (Grafana, Prometheus) |

## 11.2 Installer JAR Layout

The complete layout of a typical backend service installer JAR:

```
<service>-installer-2.6.9.jar
├── META-INF/
│   └── MANIFEST.MF
├── part.yml
├── content/
│   └── lib/
│       └── <service>-svc.jar        # Spring Boot fat JAR
├── config/
│   ├── application.properties       # Per-service config template
│   ├── bootstrap.properties         # Spring Cloud Config bootstrap template
│   └── logback-spring.xml           # Logging configuration
└── bundle/
    ├── <service>.service            # systemd unit file
    ├── nginx-<service>.conf         # Nginx location block
    └── <service>-logrotate          # Logrotate configuration
```

For the load balancer services, the layout differs:

```
backend-lb-installer-2.6.9.jar
├── part.yml
├── content/
│   └── conf/
│       ├── nginx.conf
│       ├── conf.d/
│       │   ├── upstreams.conf
│       │   └── locations.conf
│       └── ssl/
└── bundle/
    └── nginx.service
```

## 11.3 content/lib/ — The Fat JAR

The Spring Boot fat JAR (`<service>-svc.jar`) is a self-contained executable JAR. Its internal structure follows the Spring Boot fat JAR layout:

```
<service>-svc.jar
├── META-INF/
│   └── MANIFEST.MF
│       # Main-Class: org.springframework.boot.loader.JarLauncher
│       # Start-Class: com.dxc.ecs.<service>.Application
├── BOOT-INF/
│   ├── classes/
│   │   ├── com/dxc/ecs/<service>/
│   │   │   ├── Application.class
│   │   │   ├── config/
│   │   │   ├── controller/
│   │   │   ├── service/
│   │   │   ├── repository/
│   │   │   ├── model/
│   │   │   ├── dto/
│   │   │   └── event/
│   │   ├── db/migration/
│   │   │   ├── V1__initial_schema.sql
│   │   │   └── ...
│   │   ├── application.properties
│   │   └── *.event.yml
│   └── lib/
│       ├── spring-boot-3.5.8.jar
│       ├── spring-cloud-config-client-*.jar
│       ├── jasypt-spring-boot-starter-*.jar
│       ├── mysql-connector-j-*.jar
│       ├── flyway-core-*.jar
│       ├── bcprov-jdk18on-*.jar
│       └── ... (hundreds of JARs)
└── org/springframework/boot/loader/
```

The `Main-Class` in `MANIFEST.MF` is always `org.springframework.boot.loader.JarLauncher`. The actual application entry point is `Start-Class: com.dxc.ecs.<service>.Application`.

The package naming convention is `com.dxc.ecs.<service-name>` — for example:
- `com.dxc.ecs.customers`
- `com.dxc.ecs.catalog`
- `com.dxc.ecs.fulfillment`

## 11.4 config/ — Configuration Templates

The `config/` directory inside the installer JAR contains configuration file templates rendered by the installer using values from `setup.properties`.

### bootstrap.properties template

```properties
spring.application.name=<service-name>
spring.cloud.config.uri=http://${config.server.host}:${config.server.port}
spring.cloud.config.fail-fast=true
spring.profiles.active=backend
```

### application.properties template (per-service)

```properties
server.port=<service-port>
spring.application.name=<service-name>

spring.datasource.url=jdbc:mysql://${db.host}:${db.port}/<service>_db?useSSL=true&requireSSL=true&verifyServerCertificate=true&trustCertificateKeyStoreUrl=file:${ssl.truststore.path}&trustCertificateKeyStorePassword=${parts.sslPassphraseEncoded}
spring.datasource.username=${db.username}
spring.datasource.password=${db.password.encrypted}
spring.datasource.driver-class-name=com.mysql.cj.jdbc.Driver
spring.jpa.database-platform=org.hibernate.dialect.MySQL8Dialect

jasypt.encryptor.password=${jasypt.master.password}
```

### logback-spring.xml

Standard Logback configuration with:
- Console appender (for systemd journal capture)
- Rolling file appender (daily rotation, 30-day retention)
- Log file path: `/opt/ecs/<service>/logs/<service>.log`
- Log format: `%d{ISO8601} [%thread] %-5level %logger{36} - %msg%n`
- Log level: INFO by default, configurable via actuator `/actuator/loggers`

## 11.5 bundle/ — systemd, Nginx, Logrotate

### systemd Unit File

```ini
[Unit]
Description=DXC CPI <service-name> Service
After=network.target config.service
Requires=config.service

[Service]
Type=simple
User=ecs
Group=ecs
WorkingDirectory=/opt/ecs/<service>
ExecStart=/usr/bin/java \
    -Xms256m \
    -Xmx512m \
    -Djasypt.encryptor.password=${JASYPT_PASSWORD} \
    -Dspring.config.location=/opt/ecs/<service>/config/ \
    -jar /opt/ecs/<service>/lib/<service>-svc.jar
ExecStop=/bin/kill -SIGTERM $MAINPID
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ecs-<service>
EnvironmentFile=/opt/ecs/security/ecs.env

[Install]
WantedBy=multi-user.target
```

Key points:
- `After=config.service` and `Requires=config.service` — enforces startup ordering; the service will not start until `config.service` is active
- `EnvironmentFile=/opt/ecs/security/ecs.env` — the Jasypt password and other secrets are loaded from this file, owned by root with mode 0600
- `Restart=on-failure` — automatic restart on crash with 10-second delay
- JVM heap is set conservatively (256m–512m) — adjust based on actual service load

### Nginx Location Block (per backend service)

```nginx
location /<service-name>/ {
    proxy_pass          https://127.0.0.1:<service-port>/;
    proxy_http_version  1.1;
    proxy_set_header    Host $host;
    proxy_set_header    X-Real-IP $remote_addr;
    proxy_set_header    X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header    X-Forwarded-Proto $scheme;
    proxy_connect_timeout 60s;
    proxy_read_timeout    60s;
    proxy_send_timeout    60s;
}
```

### Logrotate Configuration

```
/opt/ecs/<service>/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su ecs ecs
}
```

## 11.6 Migration Tool

The `permutation-demo-data-migrator` is a standalone Spring Boot application that runs once and exits. It does not have a systemd unit, a port, or a persistent process.

Run directly:

```bash
java -Djasypt.encryptor.password=<passphrase> \
     -jar /opt/ecs/permutation-demo-data-migrator/lib/permutation-demo-data-migrator-svc.jar \
     --spring.profiles.active=migrate
```

It connects to the platform's MySQL instance and populates:
- Sample catalogue items (one per supported adapter/provider combination)
- Sample pricing entries
- Sample customer records
- Sample service instance records in various lifecycle states

This data is used for demonstration, testing, and permutation validation — verifying that all adapter/provider combinations are correctly configured and reachable.

---

# Part 12 — Deployment Mapping

## 12.1 AWS Resource Mapping

When deploying CPI Services on AWS, each platform component maps to specific AWS resources:

### Compute

| CPI Component | AWS Resource | Notes |
|---|---|---|
| Backend services (x14) | ECS Fargate tasks or EC2 instances | One task definition per service |
| Frontend services (x2) | ECS Fargate tasks or EC2 instances | Served behind ALB |
| backend-lb | AWS ALB (internal) | Path-based routing rules per service |
| frontend-lb | AWS ALB (internet-facing) | HTTPS listener with ACM certificate |
| Grafana | ECS Fargate task or EC2 | Port 3000; internal access only |
| Prometheus | ECS Fargate task or EC2 | Port 9090; internal access only |

### Database

| CPI Component | AWS Resource | Notes |
|---|---|---|
| MySQL (all service schemas) | Amazon RDS for MySQL | Multi-AZ for production; one RDS instance, multiple schemas |
| Per-service schema | RDS database within the instance | `customers_db`, `catalog_db`, etc. |

### Messaging

| CPI Component | AWS Resource | Notes |
|---|---|---|
| RabbitMQ (AMQPS) | Amazon MQ for RabbitMQ | Broker with TLS enabled; AMQPS on port 5671 |
| Event exchanges/queues | Configured on Amazon MQ broker | Same topology as on-prem |

### Storage

| CPI Component | AWS Resource | Notes |
|---|---|---|
| blob-store backend | Amazon S3 | Replace local filesystem with S3 bucket |
| Prometheus data | EBS volume or Amazon Managed Prometheus | EBS for simple deployments |
| Service logs | CloudWatch Logs | Via awslogs log driver in ECS |
| Keystore/truststore | AWS Secrets Manager or SSM Parameter Store | Inject at container startup |

### Security

| CPI Component | AWS Resource | Notes |
|---|---|---|
| TLS certificates | AWS Certificate Manager (ACM) | For ALB listeners; internal service certs still JKS |
| Jasypt passphrase | AWS Secrets Manager | Injected as environment variable at ECS task startup |
| DB passwords | AWS Secrets Manager | Referenced in ECS task definition secrets |
| Security groups | AWS Security Groups | One per service group; restrict port access |
| `/opt/ecs/security/` | EFS mount or Secrets Manager | Shared security directory across containers |

### Networking

| CPI Component | AWS Resource | Notes |
|---|---|---|
| Internal service network | VPC private subnets | All backend services in private subnets |
| External access | VPC public subnet via ALB | Only frontend-lb ALB in public subnet |
| Service discovery | AWS Cloud Map or internal ALB | Services find each other by DNS name |
| Config server URL | Internal ALB DNS or Cloud Map | `http://config-svc.internal:8103` |

### Key AWS Architecture Decisions

1. **Internal ALB replaces backend-lb Nginx** — AWS ALB supports path-based routing natively, eliminating the need for a custom Nginx backend-lb. Each backend service gets an ALB target group.

2. **Internet-facing ALB replaces frontend-lb Nginx** — The frontend ALB uses an ACM certificate for the public HTTPS endpoint. Internal service-to-service TLS still uses JKS keystores.

3. **Amazon MQ replaces self-managed RabbitMQ** — Amazon MQ provides a managed RabbitMQ broker with the same AMQPS protocol. The Spring Boot AMQP configuration requires only a URL change.

4. **Secrets Manager for Jasypt passphrase** — The Jasypt master passphrase is stored in Secrets Manager and injected into ECS tasks as an environment variable (`JASYPT_ENCRYPTOR_PASSWORD`), replacing the `ecs.env` file used on-prem.

5. **EFS for shared security directory** — If multiple ECS tasks on different hosts need access to the same JKS keystore/truststore, an EFS mount provides the shared `/opt/ecs/security/` directory. Alternatively, keystores can be stored in Secrets Manager and written to the container filesystem at startup.

## 12.2 On-Premises systemd Deployment

The standard on-premises deployment runs all services as systemd units on one or more Linux hosts (RHEL/CentOS/Ubuntu).

### Single-Host Deployment

All 22 services on one host. Suitable for development, testing, or small production environments.

```
Host: cpi.example.com
├── systemd units:
│   ├── ecs-config.service              (starts first — no dependencies)
│   ├── ecs-customers.service           (After=ecs-config.service)
│   ├── ecs-blob-store.service          (After=ecs-config.service)
│   ├── ecs-event.service               (After=ecs-config.service)
│   ├── ecs-catalog.service             (After=ecs-config.service)
│   ├── ecs-service-instances.service
│   ├── ecs-pricing.service
│   ├── ecs-request.service
│   ├── ecs-fulfillment.service
│   ├── ecs-reporting.service
│   ├── ecs-diagnostic.service
│   ├── ecs-export.service
│   ├── ecs-external-events.service
│   ├── ecs-ticketing.service
│   ├── ecs-api-doc.service
│   ├── ecs-management-ui.service
│   ├── ecs-portal-ui.service
│   ├── nginx-backend-lb.service        (After=all backend services)
│   ├── nginx-frontend-lb.service       (After=management-ui, portal-ui)
│   ├── grafana.service
│   └── prometheus.service
├── /opt/ecs/security/
│   ├── server.keystore                 (JKS — cert for cpi.example.com)
│   ├── server.truststore               (JKS — internal CA cert)
│   └── ecs.env                         (Jasypt passphrase, mode 0600)
└── MySQL + RabbitMQ (local or remote)
```

### Multi-Host Deployment

| Host | Services |
|---|---|
| `config-host` | config |
| `backend-host-1` | customers, blob-store, event, catalog, service-instances |
| `backend-host-2` | pricing, request, fulfillment, reporting, export |
| `backend-host-3` | diagnostic, external-events, ticketing, api-doc |
| `lb-host` | backend-lb, frontend-lb |
| `ui-host` | management-ui, portal-ui |
| `monitoring-host` | grafana, prometheus |
| `db-host` | MySQL |
| `mq-host` | RabbitMQ |

Each host requires its own keystore with a certificate covering that host's FQDN. The truststore on every host must contain the internal CA certificate.

### Startup Order

The systemd dependency chain enforces this startup order:

```
MySQL (external) -> RabbitMQ (external) -> config-svc -> all backend services -> load balancers -> UI services
```

The `Requires=config.service` directive in each backend service's unit file ensures systemd will not start a backend service unless `config.service` is active and healthy.

## 12.3 Docker / Container Deployment

CPI Services can be containerised. Each service becomes a Docker container.

### Container Image Pattern

```dockerfile
FROM eclipse-temurin:17-jre-alpine

RUN addgroup -S ecs && adduser -S ecs -G ecs
WORKDIR /opt/ecs/<service>

COPY <service>-svc.jar lib/<service>-svc.jar
COPY config/ config/

RUN mkdir -p logs && chown -R ecs:ecs /opt/ecs

USER ecs

ENTRYPOINT ["java", \
    "-Xms256m", "-Xmx512m", \
    "-Djasypt.encryptor.password=${JASYPT_PASSWORD}", \
    "-Dspring.config.location=/opt/ecs/<service>/config/", \
    "-jar", "/opt/ecs/<service>/lib/<service>-svc.jar"]
```

### Security Directory in Docker

The `/opt/ecs/security/` directory (keystore, truststore) must be available inside each container. Options:

1. **Docker volume** — mount a shared volume containing the keystore/truststore into all containers at `/opt/ecs/security/`
2. **Secrets injection** — store keystore/truststore as Docker secrets or Kubernetes secrets; write to the container filesystem at startup via an init container or entrypoint script
3. **Environment variable** — base64-encode the keystore and inject as an environment variable; decode to file at startup

### Docker Compose Service Definition Pattern

```yaml
services:
  config:
    image: dxc/cpi-config:2.6.9
    ports:
      - "8103:8103"
    volumes:
      - security:/opt/ecs/security
      - config-repo:/opt/ecs/config/config-repo
    environment:
      JASYPT_PASSWORD: ${JASYPT_PASSWORD}
    healthcheck:
      test: ["CMD", "curl", "-f", "-k", "https://localhost:8103/actuator/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  customers:
    image: dxc/cpi-customers:2.6.9
    ports:
      - "8090:8090"
    volumes:
      - security:/opt/ecs/security
    environment:
      JASYPT_PASSWORD: ${JASYPT_PASSWORD}
    depends_on:
      config:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "-k", "https://localhost:8090/actuator/health"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  security:
    external: true
  config-repo:
    external: true
```

The `depends_on` with `condition: service_healthy` enforces the same startup ordering as systemd's `Requires=config.service`.

### Kubernetes Deployment Pattern

For Kubernetes, each service becomes a `Deployment` with one or more replicas. Key Kubernetes resources:

- **ConfigMap** — non-sensitive configuration (bootstrap.properties, logback config)
- **Secret** — Jasypt passphrase, keystore/truststore (base64-encoded)
- **Deployment** — one per service, with init container to write keystore/truststore from Secret to emptyDir volume
- **Service** — ClusterIP service for internal access; one per CPI service
- **Ingress** — replaces frontend-lb; routes external HTTPS traffic to management-ui and portal-ui
- **HorizontalPodAutoscaler** — scale fulfillment and request services based on CPU/memory

The config service must be deployed first and its `Service` DNS name (`config-svc.default.svc.cluster.local`) must be resolvable before other services start. An `initContainer` that polls the config service health endpoint can enforce this ordering.

---
