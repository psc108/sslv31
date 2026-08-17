"""Static error message knowledge base for JAR Analyser."""
from __future__ import annotations
import re
from typing import TypedDict


class KBEntry(TypedDict):
    id: str
    category: str
    severity: str          # critical | high | medium | low
    pattern: str           # regex matched against pasted error text
    title: str
    plain_english: str
    causes: list[str]
    fix_steps: list[str]
    see_also: list[str]


KB: list[KBEntry] = [

    # ── SSL / TLS ────────────────────────────────────────────────────────────
    {
        "id": "ssl-001",
        "category": "SSL/TLS",
        "severity": "critical",
        "pattern": r"PKIX path building failed|unable to find valid certification path",
        "title": "PKIX path building failed — untrusted certificate",
        "plain_english": "Java cannot verify the server's certificate because the signing CA is not in the JVM trust store.",
        "causes": [
            "The server presents a self-signed or internal CA certificate not imported into the JVM cacerts.",
            "An intermediate CA certificate is missing from the server's TLS chain.",
            "The wrong trust store is being loaded at runtime.",
        ],
        "fix_steps": [
            "Import the root/intermediate CA into the JVM trust store: keytool -importcert -alias myca -file ca.pem -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit",
            "Or point the JVM at a custom trust store: -Djavax.net.ssl.trustStore=/path/to/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit",
            "Verify the server sends the full chain: openssl s_client -connect host:port -showcerts",
            "Use the SSL Cert Manager TrustStore builder to create a merged cacerts + internal CA trust store.",
        ],
        "see_also": ["ssl-002", "ssl-005"],
    },
    {
        "id": "ssl-002",
        "category": "SSL/TLS",
        "severity": "critical",
        "pattern": r"SSLHandshakeException|handshake_failure|Received fatal alert: handshake_failure",
        "title": "SSL handshake failure",
        "plain_english": "The TLS handshake between client and server failed — they could not agree on a cipher suite, protocol version, or certificate.",
        "causes": [
            "No common TLS protocol version (e.g. server requires TLS 1.3, client only supports TLS 1.2).",
            "No overlapping cipher suite.",
            "Client certificate required (mTLS) but not provided.",
            "Certificate hostname mismatch.",
        ],
        "fix_steps": [
            "Enable TLS debug logging: -Djavax.net.debug=ssl:handshake",
            "Check server-supported protocols: openssl s_client -connect host:port -tls1_2",
            "For mTLS: supply a client keystore via -Djavax.net.ssl.keyStore and -Djavax.net.ssl.keyStorePassword",
            "Ensure the certificate SAN/CN matches the hostname being connected to.",
        ],
        "see_also": ["ssl-001", "ssl-003"],
    },
    {
        "id": "ssl-003",
        "category": "SSL/TLS",
        "severity": "high",
        "pattern": r"Certificate expired|NotAfter|certificate has expired",
        "title": "Certificate has expired",
        "plain_english": "The TLS certificate presented by the server (or client) is past its expiry date.",
        "causes": [
            "Server certificate not renewed before expiry.",
            "An intermediate CA in the chain has expired.",
            "System clock skew causing a valid cert to appear expired.",
        ],
        "fix_steps": [
            "Check expiry: openssl s_client -connect host:port </dev/null | openssl x509 -noout -dates",
            "Renew the certificate via the SSL Cert Manager (CSR renewal flow).",
            "Check system time on both client and server: date -u",
            "Use the SSL Cert Manager expiry monitor to get alerts before certificates expire.",
        ],
        "see_also": ["ssl-001"],
    },
    {
        "id": "ssl-004",
        "category": "SSL/TLS",
        "severity": "high",
        "pattern": r"No subject alternative names|hostname.*doesn.t match|Certificate for .* doesn.t match",
        "title": "Certificate hostname mismatch",
        "plain_english": "The hostname you are connecting to is not listed in the certificate's Subject Alternative Names (SAN).",
        "causes": [
            "Certificate issued for www.example.com but connecting to api.example.com.",
            "Certificate only has a CN, no SAN extension (deprecated since RFC 2818).",
            "Connecting via IP address but certificate only has DNS SANs.",
        ],
        "fix_steps": [
            "Reissue the certificate with the correct SANs covering all hostnames and IPs used.",
            "Add a wildcard SAN (*.example.com) if multiple subdomains are needed.",
            "Verify current SANs: openssl x509 -in cert.pem -noout -text | grep -A1 'Subject Alternative'",
        ],
        "see_also": ["ssl-002"],
    },
    {
        "id": "ssl-005",
        "category": "SSL/TLS",
        "severity": "medium",
        "pattern": r"trustAnchors parameter must be non-empty|TrustStore.*empty|KeyStore.*no trusted certificate",
        "title": "Empty or missing trust store",
        "plain_english": "The JVM was pointed at a trust store file that is empty or does not exist.",
        "causes": [
            "javax.net.ssl.trustStore system property points to a non-existent file.",
            "Trust store file exists but contains no certificates.",
            "Wrong password supplied — store loaded but appears empty.",
        ],
        "fix_steps": [
            "Verify the file exists and is readable at the configured path.",
            "List contents: keytool -list -keystore truststore.jks -storepass changeit",
            "Rebuild the trust store using the SSL Cert Manager TrustStore builder.",
            "If using Spring Boot, check spring.ssl.bundle or server.ssl.trust-store properties.",
        ],
        "see_also": ["ssl-001"],
    },
    {
        "id": "ssl-006",
        "category": "SSL/TLS",
        "severity": "medium",
        "pattern": r"Keystore was tampered with|password was incorrect|Keystore.*integrity check failed",
        "title": "KeyStore integrity check failed — wrong password",
        "plain_english": "The keystore file could not be opened because the password is wrong or the file is corrupted.",
        "causes": [
            "Incorrect keystore password in configuration.",
            "Keystore file was corrupted during transfer or storage.",
            "JKS keystore opened with PKCS12 type or vice versa.",
        ],
        "fix_steps": [
            "Double-check the password in your application config / environment variable.",
            "Verify keystore type: keytool -list -keystore store.jks (try both -storetype JKS and PKCS12).",
            "Re-export the keystore from the SSL Cert Manager if the file may be corrupted.",
        ],
        "see_also": ["ssl-005"],
    },

    # ── Spring Security / Auth ───────────────────────────────────────────────
    {
        "id": "auth-001",
        "category": "Spring Security/Auth",
        "severity": "high",
        "pattern": r"401 Unauthorized|Full authentication is required|AuthenticationException",
        "title": "401 Unauthorized — authentication required",
        "plain_english": "The request reached a secured endpoint without valid credentials.",
        "causes": [
            "Missing or expired JWT / Bearer token in the Authorization header.",
            "API key not included or incorrect.",
            "Session cookie expired.",
            "Spring Security is blocking the endpoint and no credentials were supplied.",
        ],
        "fix_steps": [
            "Include the Authorization: Bearer <token> header in the request.",
            "Re-authenticate to obtain a fresh token (POST /api/v1/auth/login).",
            "Check token expiry — decode the JWT at jwt.io and inspect the exp claim.",
            "For service-to-service calls, ensure the API key is set in the X-API-Key header.",
        ],
        "see_also": ["auth-002"],
    },
    {
        "id": "auth-002",
        "category": "Spring Security/Auth",
        "severity": "high",
        "pattern": r"403 Forbidden|Access is denied|AccessDeniedException|not permitted",
        "title": "403 Forbidden — insufficient permissions",
        "plain_english": "The user is authenticated but does not have the role or authority required for this operation.",
        "causes": [
            "User role (e.g. READ_ONLY) does not include the required permission.",
            "Method-level @PreAuthorize annotation requires a role the user lacks.",
            "CSRF token missing on a state-changing request.",
            "IP allowlist or network policy blocking the request.",
        ],
        "fix_steps": [
            "Check the user's assigned role and the permission matrix for the endpoint.",
            "Elevate the user's role via the admin panel if appropriate.",
            "For CSRF: ensure the X-XSRF-TOKEN header is included on POST/PUT/DELETE.",
            "Review Spring Security configuration for hasRole / hasAuthority rules.",
        ],
        "see_also": ["auth-001", "auth-003"],
    },
    {
        "id": "auth-003",
        "category": "Spring Security/Auth",
        "severity": "high",
        "pattern": r"JWT expired|ExpiredJwtException|Token has expired|JwtException",
        "title": "JWT token expired",
        "plain_english": "The JSON Web Token used for authentication has passed its expiry time.",
        "causes": [
            "Token TTL is short and the client did not refresh it.",
            "Server clock and client clock are out of sync (clock skew).",
            "Token was issued with an incorrect exp claim.",
        ],
        "fix_steps": [
            "Re-authenticate to get a new token.",
            "Implement token refresh logic in the client before expiry.",
            "Check clock sync between services: ntpdate -q pool.ntp.org",
            "Increase JWT_EXPIRY_MINUTES in application config if the TTL is too aggressive.",
        ],
        "see_also": ["auth-001"],
    },
    {
        "id": "auth-004",
        "category": "Spring Security/Auth",
        "severity": "medium",
        "pattern": r"Invalid signature|SignatureException|JWT signature does not match",
        "title": "JWT signature verification failed",
        "plain_english": "The JWT token's signature cannot be verified — the signing key used to create it does not match the key used to verify it.",
        "causes": [
            "Application restarted and a new random secret was generated, invalidating old tokens.",
            "Different instances using different JWT secrets (missing shared secret config).",
            "Token was tampered with.",
        ],
        "fix_steps": [
            "Ensure all instances share the same JWT_SECRET environment variable.",
            "After a secret rotation, all clients must re-authenticate.",
            "Set a stable JWT_SECRET in your .env / Kubernetes secret rather than auto-generating.",
        ],
        "see_also": ["auth-003"],
    },
    {
        "id": "auth-005",
        "category": "Spring Security/Auth",
        "severity": "medium",
        "pattern": r"CORS.*blocked|Cross-Origin.*policy|has been blocked by CORS",
        "title": "CORS policy blocking request",
        "plain_english": "The browser blocked the request because the server's CORS policy does not allow the origin making the request.",
        "causes": [
            "Frontend origin not listed in the server's allowed origins.",
            "Preflight OPTIONS request returning 403 or missing Access-Control headers.",
            "Credentials (cookies/auth headers) sent on a cross-origin request without allowCredentials=true.",
        ],
        "fix_steps": [
            "Add the frontend origin to CORS_ORIGINS in the backend config.",
            "Ensure the OPTIONS preflight returns Access-Control-Allow-Origin and Access-Control-Allow-Headers.",
            "If using credentials, set allowCredentials=true and specify an explicit origin (not *).",
        ],
        "see_also": [],
    },

    # ── Spring Boot Startup ──────────────────────────────────────────────────
    {
        "id": "boot-001",
        "category": "Spring Boot Startup",
        "severity": "critical",
        "pattern": r"APPLICATION FAILED TO START|BeanCreationException|Error creating bean",
        "title": "Spring Boot application failed to start — bean creation error",
        "plain_english": "Spring could not create one or more beans during startup, preventing the application from starting.",
        "causes": [
            "A required dependency (database, message broker, external service) is unavailable.",
            "Missing or invalid configuration property required by a bean.",
            "Circular dependency between beans.",
            "Class not found — missing JAR on the classpath.",
        ],
        "fix_steps": [
            "Read the full stack trace — the root cause is usually at the bottom after 'Caused by:'.",
            "Check that all required services (DB, RabbitMQ, Redis) are running and reachable.",
            "Verify all required environment variables / application.properties values are set.",
            "Run with --debug flag to get the auto-configuration report: java -jar app.jar --debug",
        ],
        "see_also": ["boot-002", "db-001"],
    },
    {
        "id": "boot-002",
        "category": "Spring Boot Startup",
        "severity": "critical",
        "pattern": r"Port \d+ was already in use|Address already in use|BindException",
        "title": "Port already in use",
        "plain_english": "The port the application is trying to bind to is already occupied by another process.",
        "causes": [
            "Another instance of the application is already running.",
            "A different service is using the same port.",
            "Previous process did not shut down cleanly and the port is in TIME_WAIT.",
        ],
        "fix_steps": [
            "Find the process: lsof -i :<port> or netstat -tulpn | grep <port>",
            "Kill the conflicting process or change server.port in application.properties.",
            "On Windows: netstat -ano | findstr :<port> then taskkill /PID <pid> /F",
        ],
        "see_also": [],
    },
    {
        "id": "boot-003",
        "category": "Spring Boot Startup",
        "severity": "high",
        "pattern": r"NoSuchBeanDefinitionException|No qualifying bean of type|required a bean of type",
        "title": "No qualifying bean found",
        "plain_english": "Spring tried to inject a dependency but could not find a matching bean in the application context.",
        "causes": [
            "Missing @Component / @Service / @Repository annotation on the implementation class.",
            "Component scan not covering the package where the class lives.",
            "Conditional bean (@ConditionalOnProperty) not activated due to missing config.",
            "Profile mismatch — bean only created for a different Spring profile.",
        ],
        "fix_steps": [
            "Add the appropriate stereotype annotation (@Service, @Component, etc.).",
            "Check @SpringBootApplication / @ComponentScan covers the package.",
            "Verify the required property is set if the bean uses @ConditionalOnProperty.",
            "Check active profiles: spring.profiles.active in application.properties.",
        ],
        "see_also": ["boot-001"],
    },
    {
        "id": "boot-004",
        "category": "Spring Boot Startup",
        "severity": "high",
        "pattern": r"UnsatisfiedDependencyException|Unsatisfied dependency expressed through",
        "title": "Unsatisfied dependency — constructor/field injection failed",
        "plain_english": "Spring could not inject a required dependency into a bean's constructor or field.",
        "causes": [
            "The dependency bean itself failed to initialise (check root cause).",
            "Multiple beans of the same type without @Primary or @Qualifier.",
            "Dependency is in a different application context (e.g. parent/child context).",
        ],
        "fix_steps": [
            "Follow the 'Caused by' chain to find the actual root failure.",
            "If multiple beans: add @Primary to the preferred implementation or @Qualifier at the injection point.",
            "Check for circular dependencies — consider @Lazy injection or refactoring.",
        ],
        "see_also": ["boot-001", "boot-003"],
    },
    {
        "id": "boot-005",
        "category": "Spring Boot Startup",
        "severity": "medium",
        "pattern": r"ConfigurationPropertiesBindException|Binding to target.*failed|Could not bind properties",
        "title": "Configuration properties binding failed",
        "plain_english": "Spring Boot could not bind application properties to a @ConfigurationProperties class — likely a missing or wrongly-typed property.",
        "causes": [
            "Required property not set in application.properties / environment.",
            "Property value cannot be converted to the target type (e.g. string → integer).",
            "Typo in property name.",
        ],
        "fix_steps": [
            "Check the error message for the exact property name that failed.",
            "Add the missing property to application.properties or as an environment variable.",
            "Validate types — durations need format like 30s, sizes like 10MB.",
        ],
        "see_also": ["boot-001"],
    },

    # ── RabbitMQ ─────────────────────────────────────────────────────────────
    {
        "id": "rmq-001",
        "category": "RabbitMQ",
        "severity": "critical",
        "pattern": r"Connection refused.*5672|AmqpConnectException|Could not connect to RabbitMQ",
        "title": "Cannot connect to RabbitMQ broker",
        "plain_english": "The application cannot reach the RabbitMQ broker on port 5672.",
        "causes": [
            "RabbitMQ is not running or not yet healthy.",
            "Wrong hostname or port in spring.rabbitmq.host / spring.rabbitmq.port.",
            "Firewall or network policy blocking port 5672.",
            "RabbitMQ is running but bound to 127.0.0.1 only.",
        ],
        "fix_steps": [
            "Check RabbitMQ is running: rabbitmqctl status or docker ps",
            "Test connectivity: telnet <host> 5672 or nc -zv <host> 5672",
            "Verify spring.rabbitmq.host, spring.rabbitmq.port, spring.rabbitmq.username, spring.rabbitmq.password.",
            "Check RabbitMQ listeners: rabbitmqctl list_listeners",
        ],
        "see_also": ["rmq-002"],
    },
    {
        "id": "rmq-002",
        "category": "RabbitMQ",
        "severity": "high",
        "pattern": r"ACCESS_REFUSED|authentication failure.*rabbit|PossibleAuthenticationFailureException",
        "title": "RabbitMQ authentication refused",
        "plain_english": "The username or password used to connect to RabbitMQ is incorrect, or the user lacks permission on the vhost.",
        "causes": [
            "Wrong username or password in configuration.",
            "User exists but does not have access to the configured virtual host.",
            "User account has been locked or deleted.",
        ],
        "fix_steps": [
            "Verify credentials: rabbitmqctl list_users",
            "Check vhost permissions: rabbitmqctl list_permissions -p <vhost>",
            "Grant permissions: rabbitmqctl set_permissions -p <vhost> <user> '.*' '.*' '.*'",
            "Reset password: rabbitmqctl change_password <user> <newpassword>",
        ],
        "see_also": ["rmq-001"],
    },
    {
        "id": "rmq-003",
        "category": "RabbitMQ",
        "severity": "high",
        "pattern": r"Channel.*closed|NOT_FOUND.*queue|queue.*not found|RESOURCE_LOCKED",
        "title": "RabbitMQ queue or exchange not found / channel closed",
        "plain_english": "The application tried to use a queue or exchange that does not exist, or the channel was closed by the broker.",
        "causes": [
            "Queue/exchange not declared before use and auto-declare is disabled.",
            "Queue declared with different durability/exclusivity settings than what exists.",
            "Queue deleted externally while the application was running.",
        ],
        "fix_steps": [
            "Enable queue/exchange auto-declaration in the Spring AMQP config (@Bean Queue, Exchange, Binding).",
            "Check existing queues: rabbitmqctl list_queues name durable",
            "Delete and re-declare if settings conflict: rabbitmqctl delete_queue <name>",
            "Use the RabbitMQ management UI (port 15672) to inspect topology.",
        ],
        "see_also": ["rmq-001"],
    },
    {
        "id": "rmq-004",
        "category": "RabbitMQ",
        "severity": "medium",
        "pattern": r"ListenerExecutionFailedException|message.*rejected|basicNack|basicReject",
        "title": "RabbitMQ message listener threw an exception",
        "plain_english": "A message consumer threw an unhandled exception, causing the message to be rejected or dead-lettered.",
        "causes": [
            "Deserialization failure — message format does not match the expected DTO.",
            "Business logic exception in the @RabbitListener method.",
            "Downstream dependency (DB, external service) unavailable during processing.",
        ],
        "fix_steps": [
            "Check application logs for the full stack trace from the listener.",
            "Inspect the dead-letter queue for rejected messages.",
            "Add error handling / retry logic with @RabbitListener and a custom error handler.",
            "Validate message schema matches the consumer's expected DTO.",
        ],
        "see_also": ["rmq-003"],
    },

    # ── Database / Flyway ────────────────────────────────────────────────────
    {
        "id": "db-001",
        "category": "Database/Flyway",
        "severity": "critical",
        "pattern": r"Unable to acquire JDBC Connection|HikariPool.*Connection is not available|Cannot get a connection",
        "title": "Database connection pool exhausted or DB unreachable",
        "plain_english": "The application cannot get a database connection — either the DB is down or all connections in the pool are in use.",
        "causes": [
            "Database server is not running or not reachable.",
            "Connection pool size too small for the load.",
            "Connection leak — connections not being returned to the pool.",
            "Wrong JDBC URL, username, or password.",
        ],
        "fix_steps": [
            "Check DB is running and reachable: ping <db-host> and telnet <db-host> <port>",
            "Verify spring.datasource.url, username, password.",
            "Increase pool size: spring.datasource.hikari.maximum-pool-size=20",
            "Enable HikariCP leak detection: spring.datasource.hikari.leak-detection-threshold=30000",
        ],
        "see_also": ["db-002"],
    },
    {
        "id": "db-002",
        "category": "Database/Flyway",
        "severity": "critical",
        "pattern": r"FlywayException|Migration.*failed|Validate failed.*migration|checksum mismatch",
        "title": "Flyway migration failed or checksum mismatch",
        "plain_english": "Flyway could not apply a database migration — either a script failed or a previously-applied script has been modified.",
        "causes": [
            "SQL error in a migration script.",
            "A migration script was edited after it was already applied (checksum mismatch).",
            "Migration applied out of order.",
            "Database user lacks DDL permissions (CREATE TABLE, ALTER, etc.).",
        ],
        "fix_steps": [
            "Check the Flyway schema_version / flyway_schema_history table for the failed version.",
            "Fix the SQL error and repair: flyway repair (resets failed migration checksum).",
            "Never edit applied migration scripts — create a new migration instead.",
            "Grant DDL permissions to the DB user used by the application.",
        ],
        "see_also": ["db-001", "db-003"],
    },
    {
        "id": "db-003",
        "category": "Database/Flyway",
        "severity": "high",
        "pattern": r"Table.*doesn.t exist|relation.*does not exist|ORA-00942|1146.*Table.*doesn.t exist",
        "title": "Table does not exist",
        "plain_english": "A query references a table that has not been created in the database.",
        "causes": [
            "Flyway migrations have not been run or failed partway through.",
            "Application is pointing at the wrong database/schema.",
            "Migration script for this table was not included in the deployment.",
        ],
        "fix_steps": [
            "Run pending migrations: flyway migrate",
            "Check the target schema: SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
            "Verify spring.datasource.url points to the correct database.",
            "Check Flyway baseline version if migrating an existing database.",
        ],
        "see_also": ["db-002"],
    },
    {
        "id": "db-004",
        "category": "Database/Flyway",
        "severity": "high",
        "pattern": r"Deadlock found|deadlock detected|LockAcquisitionException|could not serialize access",
        "title": "Database deadlock detected",
        "plain_english": "Two or more transactions are waiting on each other's locks, causing a deadlock. One transaction was rolled back.",
        "causes": [
            "Multiple threads/services updating the same rows in different orders.",
            "Long-running transactions holding locks.",
            "Missing indexes causing full table scans that lock too many rows.",
        ],
        "fix_steps": [
            "Implement retry logic for deadlock exceptions (Spring @Retryable).",
            "Ensure all code acquires locks in a consistent order.",
            "Add indexes to reduce lock scope.",
            "Reduce transaction scope — commit earlier, hold locks for less time.",
        ],
        "see_also": ["db-001"],
    },
    {
        "id": "db-005",
        "category": "Database/Flyway",
        "severity": "medium",
        "pattern": r"DataIntegrityViolationException|Duplicate entry|unique constraint|violates unique constraint|ORA-00001",
        "title": "Unique constraint violation",
        "plain_english": "An INSERT or UPDATE tried to create a duplicate value in a column that requires unique values.",
        "causes": [
            "Duplicate data being inserted (race condition or retry without idempotency check).",
            "Bulk import containing duplicate records.",
            "Missing upsert logic — should be INSERT ... ON CONFLICT DO UPDATE.",
        ],
        "fix_steps": [
            "Add an existence check before insert, or use upsert semantics.",
            "For bulk imports, deduplicate the source data first.",
            "Use database-level ON CONFLICT / INSERT IGNORE / MERGE to handle duplicates gracefully.",
        ],
        "see_also": [],
    },
    {
        "id": "db-007",
        "category": "Database/Flyway",
        "severity": "high",
        "pattern": r"SQLIntegrityConstraintViolationException|Cannot delete or update a parent row|a foreign key constraint fails|FOREIGN KEY constraint failed|ORA-02292|ERROR 1451|DataIntegrityException",
        "title": "Foreign key constraint violation",
        "plain_english": "A DELETE or UPDATE was blocked because child records in another table still reference the row you are trying to remove or change.",
        "causes": [
            "Attempting to delete a parent record (e.g. a department) while dependent child records (e.g. employees) still reference it.",
            "Inserting a child record with a foreign key value that does not exist in the parent table.",
            "Multiple threads performing deletions concurrently — one thread deletes the parent while another is still using it.",
            "Missing ON DELETE CASCADE / ON DELETE SET NULL on the foreign key definition.",
        ],
        "fix_steps": [
            "Before deleting, query for dependents: SELECT * FROM <child_table> WHERE <fk_column> = <id>.",
            "Delete or reassign child records first, then delete the parent.",
            "Add ON DELETE CASCADE to the foreign key if automatic child deletion is the desired behaviour.",
            "Add a pre-delete check in the service layer and throw a descriptive business exception if dependents exist.",
            "If concurrent deletions are possible, use a database transaction with SELECT ... FOR UPDATE to lock the parent row before checking dependents.",
        ],
        "see_also": ["db-004", "db-005"],
    },
    {
        "id": "db-008",
        "category": "Database/Flyway",
        "severity": "high",
        "pattern": r"org\.hibernate\.exception\.ConstraintViolationException|ConstraintViolationException.*Hibernate|could not execute statement.*ConstraintViolation",
        "title": "Hibernate ConstraintViolationException — database constraint violated",
        "plain_english": "Hibernate wrapped a database constraint error (unique, foreign key, not-null, or check constraint). The underlying SQL error contains the specific constraint name.",
        "causes": [
            "Unique constraint: duplicate value inserted into a unique column.",
            "Foreign key constraint: parent record missing or child records still exist.",
            "Not-null constraint: a required column was left null.",
            "Check constraint: a column value failed a database-level validation rule.",
        ],
        "fix_steps": [
            "Read the 'Caused by: java.sql.SQLIntegrityConstraintViolationException' message — it names the constraint and the offending value.",
            "For FK violations: check for dependent child records before deleting the parent (see db-007).",
            "For unique violations: add an existence check or use upsert semantics (see db-005).",
            "For not-null: ensure all required fields are populated before calling save().",
            "Enable SQL logging to see the exact statement: spring.jpa.show-sql=true",
        ],
        "see_also": ["db-007", "db-005"],
    },
    {
        "id": "db-006",
        "category": "Database/Flyway",
        "severity": "medium",
        "pattern": r"LazyInitializationException|could not initialize proxy|no Session|failed to lazily initialize",
        "title": "Hibernate LazyInitializationException — no session",
        "plain_english": "Code tried to access a lazily-loaded JPA relationship after the Hibernate session was closed.",
        "causes": [
            "Accessing a @OneToMany / @ManyToMany collection outside of a transaction.",
            "Entity returned from a @Transactional method and then accessed in a non-transactional context.",
            "Open-Session-In-View disabled (correct) but lazy access not refactored.",
        ],
        "fix_steps": [
            "Use @Transactional on the service method that accesses the lazy collection.",
            "Use JOIN FETCH in the JPQL query to eagerly load the needed association.",
            "Use a DTO projection to fetch only the required fields without lazy loading.",
            "Enable spring.jpa.open-in-view=false (recommended) and fix access patterns.",
        ],
        "see_also": ["db-001"],
    },

    # ── MySQL ─────────────────────────────────────────────────────────────────
    {
        "id": "mysql-001",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"Access denied for user",
        "title": "MySQL access denied — wrong credentials or missing grant",
        "plain_english": "The MySQL server rejected the connection because the username/password is wrong or the account lacks permission on the database.",
        "causes": [
            "Wrong username or password in the application datasource config.",
            "Account exists but has no GRANT on the target database.",
            "Account is locked (account_locked = Y).",
            "Connecting from a host not covered by the account's host pattern.",
        ],
        "fix_steps": [
            "Verify credentials: mysql -u <user> -p -h <host>",
            "Check grants: SHOW GRANTS FOR '<user>'@'<host>';",
            "Grant access: GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* TO '<user>'@'<host>';",
            "Check account lock: SELECT account_locked FROM mysql.user WHERE user='<user>';",
        ],
        "see_also": ["mysql-003"],
    },
    {
        "id": "mysql-002",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"SSL connection error|SSL_CTX_set_default_verify_paths",
        "title": "MySQL SSL connection error",
        "plain_english": "The MySQL server or client encountered an SSL/TLS error when establishing the connection.",
        "causes": [
            "MySQL SSL is disabled on the server (have_ssl = DISABLED).",
            "SSL certificate paths are not configured in my.cnf.",
            "Certificate has expired or the CA is not trusted by the client.",
            "Client requires SSL but server does not support it.",
        ],
        "fix_steps": [
            "Check SSL status: SHOW VARIABLES LIKE '%ssl%';",
            "Enable SSL in /etc/mysql/my.cnf: ssl_cert, ssl_key, ssl_ca under [mysqld].",
            "Restart MySQL after config changes: systemctl restart mysql",
            "Verify certificate: openssl x509 -in /etc/mysql/ssl/server-cert.pem -noout -dates",
        ],
        "see_also": ["ssl-001", "ssl-003"],
    },
    {
        "id": "mysql-003",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"Too many connections",
        "title": "MySQL max connections exceeded",
        "plain_english": "The MySQL server has reached its maximum number of simultaneous connections and is refusing new ones.",
        "causes": [
            "max_connections is set too low for the current load.",
            "Connection leak — application not returning connections to the pool.",
            "Too many application instances connecting simultaneously.",
        ],
        "fix_steps": [
            "Check current usage: SHOW STATUS LIKE 'Threads_connected';",
            "Increase limit: SET GLOBAL max_connections = 500; (also set in my.cnf for persistence)",
            "Enable HikariCP leak detection: spring.datasource.hikari.leak-detection-threshold=30000",
            "Review connection pool size: spring.datasource.hikari.maximum-pool-size",
        ],
        "see_also": ["mysql-001"],
    },
    {
        "id": "mysql-004",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"caching_sha2_password.*Authentication plugin|Public Key Retrieval is not allowed",
        "title": "MySQL caching_sha2_password plugin incompatibility",
        "plain_english": "The MySQL 8.x default authentication plugin (caching_sha2_password) is not supported by older JDBC connectors without additional configuration.",
        "causes": [
            "MySQL 8.x uses caching_sha2_password by default; older mysql-connector-java requires mysql_native_password.",
            "JDBC URL missing allowPublicKeyRetrieval=true for caching_sha2_password over non-SSL connections.",
        ],
        "fix_steps": [
            "Option 1 — change the account plugin: ALTER USER '<user>'@'<host>' IDENTIFIED WITH mysql_native_password BY '<password>';",
            "Option 2 — update the JDBC URL: jdbc:mysql://<host>/<db>?allowPublicKeyRetrieval=true&useSSL=true",
            "Option 3 — upgrade mysql-connector-java to 8.x which supports caching_sha2_password natively.",
        ],
        "see_also": ["mysql-001"],
    },
    {
        "id": "mysql-005",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"DeadlockFoundException|Deadlock found when trying to get lock|Error 1213|ER_LOCK_DEADLOCK",
        "title": "MySQL deadlock — Error 1213: try restarting transaction",
        "plain_english": "MySQL detected a circular lock dependency between two transactions and rolled one back. The rolled-back transaction must be retried by the application.",
        "causes": [
            "Two transactions updating the same rows in opposite order (e.g. Thread A locks orders then payments; Thread B locks payments then orders).",
            "Missing indexes causing InnoDB to lock entire ranges instead of individual rows.",
            "Long-running transactions holding row locks while waiting for others.",
            "Batch operations interleaving with concurrent single-row updates on the same table.",
        ],
        "fix_steps": [
            "Add @Retryable to the service method: @Retryable(value = {DeadlockLoserDataAccessException.class}, maxAttempts = 3, backoff = @Backoff(delay = 100))",
            "Analyse the deadlock: SHOW ENGINE INNODB STATUS; — look for the LATEST DETECTED DEADLOCK section.",
            "Ensure all transactions acquire locks in the same order across all code paths.",
            "Add indexes on the columns used in WHERE / JOIN clauses to reduce lock scope.",
            "Use SELECT ... FOR UPDATE NOWAIT to fail fast rather than waiting and deadlocking.",
            "Shorten transactions — commit as early as possible to release locks sooner.",
        ],
        "see_also": ["db-004", "mysql-006", "thread-001"],
    },
    {
        "id": "mysql-006",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"JDBCConnectionException|Unable to acquire JDBC Connection|org\.hibernate\.exception\.JDBCConnectionException",
        "title": "Hibernate JDBCConnectionException — cannot acquire JDBC connection",
        "plain_english": "Hibernate could not obtain a database connection from the pool. This often wraps a deadlock rollback, pool exhaustion, or a dropped connection.",
        "causes": [
            "HikariCP connection pool exhausted — all connections in use or waiting.",
            "MySQL server closed the connection (wait_timeout / interactive_timeout exceeded).",
            "Deadlock caused the transaction to be rolled back and the connection returned in a bad state.",
            "MySQL max_connections limit reached.",
        ],
        "fix_steps": [
            "Check pool metrics: spring.datasource.hikari.maximum-pool-size and leak-detection-threshold.",
            "Increase MySQL max_connections: SET GLOBAL max_connections = 500;",
            "Set keepalive: spring.datasource.hikari.keepalive-time=30000 to prevent idle connection drops.",
            "Check for the root cause in the 'Caused by' chain — often a DeadlockFoundException or connection timeout.",
            "Enable HikariCP connection leak detection: spring.datasource.hikari.leak-detection-threshold=30000",
        ],
        "see_also": ["db-001", "mysql-005", "mysql-003"],
    },
    {
        "id": "mysql-007",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"CannotCreateTransactionException|Could not open JPA EntityManager|Could not open Hibernate Session",
        "title": "Spring CannotCreateTransactionException — transaction could not be started",
        "plain_english": "Spring could not open a database transaction. This is always a wrapper — the real cause is in the 'Caused by' chain (typically a deadlock, connection failure, or pool exhaustion).",
        "causes": [
            "Underlying DeadlockFoundException rolled back the connection before the transaction could start.",
            "JDBC connection pool exhausted — no connections available within the timeout.",
            "Database server unreachable or restarting.",
            "Transaction manager misconfigured (wrong DataSource wired).",
        ],
        "fix_steps": [
            "Always follow the 'Caused by' chain to the actual root exception — CannotCreateTransactionException is a wrapper.",
            "For deadlock root cause: add @Retryable on the @Transactional service method (see mysql-005).",
            "For pool exhaustion root cause: tune HikariCP settings (see mysql-006).",
            "Verify the transaction manager bean is wired to the correct DataSource.",
            "Check DB connectivity: can the app reach the DB host and port?",
        ],
        "see_also": ["mysql-005", "mysql-006", "db-001"],
    },
    {
        "id": "mysql-008",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"MySQLQueryInterruptedException|Query execution was interrupted|lock wait timeout exceeded|innodb_lock_wait_timeout",
        "title": "MySQL lock wait timeout — query interrupted",
        "plain_english": "A query waiting to acquire a row lock (e.g. SELECT ... FOR UPDATE) was killed by MySQL because it exceeded the lock wait timeout (default 50 s in InnoDB, often set lower in Hibernate).",
        "causes": [
            "High contention — multiple threads competing for the same row (e.g. Inventory#12345).",
            "A long-running transaction elsewhere is holding the lock.",
            "Lock timeout configured too short (hibernate.lock.timeout or innodb_lock_wait_timeout).",
            "Missing index on the locked column causing InnoDB to lock more rows than necessary.",
        ],
        "fix_steps": [
            "Increase lock timeout: spring.jpa.properties.hibernate.lock.timeout=10000 (ms) or SET GLOBAL innodb_lock_wait_timeout=30;",
            "Use FOR UPDATE NOWAIT to fail immediately instead of waiting: @QueryHints(@QueryHint(name=\"javax.persistence.lock.timeout\", value=\"0\"))",
            "Switch to optimistic locking with @Version on the entity — avoids row locks entirely and retries on version mismatch.",
            "Add @Retryable(value={LockAcquisitionException.class}, maxAttempts=3, backoff=@Backoff(delay=1000)) on the service method.",
            "Diagnose blocking queries: SHOW PROCESSLIST; and SELECT * FROM performance_schema.data_locks;",
            "Add an index on the locked column to reduce the number of rows InnoDB must lock.",
            "Reduce transaction scope — commit earlier to release locks sooner.",
        ],
        "see_also": ["mysql-009", "mysql-010", "mysql-011", "db-004"],
    },
    {
        "id": "mysql-009",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"org\.hibernate\.exception\.LockAcquisitionException|could not acquire lock on row|LockAcquisitionException",
        "title": "Hibernate LockAcquisitionException — row lock not acquired within timeout",
        "plain_english": "Hibernate could not acquire a pessimistic lock on the requested row within the configured timeout. This wraps a MySQL lock wait timeout or deadlock.",
        "causes": [
            "Another transaction holds a conflicting lock on the same row.",
            "Lock timeout too short for the current workload.",
            "Deadlock — two transactions waiting on each other's locks.",
        ],
        "fix_steps": [
            "Increase timeout: spring.jpa.properties.hibernate.lock.timeout=10000",
            "Use NOWAIT to fail fast: @QueryHint(name=\"javax.persistence.lock.timeout\", value=\"0\")",
            "Switch to optimistic locking (@Version) to avoid blocking entirely.",
            "Check for long-running transactions: SHOW PROCESSLIST; KILL <process_id>;",
        ],
        "see_also": ["mysql-008", "mysql-010", "db-004"],
    },
    {
        "id": "mysql-010",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"org\.hibernate\.PessimisticLockException|PessimisticLockException|could not obtain lock on row",
        "title": "Hibernate PessimisticLockException — SELECT FOR UPDATE failed",
        "plain_english": "A pessimistic lock (SELECT ... FOR UPDATE) could not be obtained. Another transaction holds a conflicting lock or the timeout was exceeded.",
        "causes": [
            "Another transaction holds a write lock on the same row.",
            "Lock wait timeout exceeded (wraps MySQLQueryInterruptedException).",
            "Concurrent @Async threads all trying to lock the same entity.",
        ],
        "fix_steps": [
            "Use FOR UPDATE NOWAIT to fail immediately and retry: @QueryHint(name=\"javax.persistence.lock.timeout\", value=\"0\")",
            "Replace pessimistic locking with optimistic locking (@Version) — better suited to high-concurrency @Async workloads.",
            "Serialise access to the hot row via an application-level lock (e.g. Redis distributed lock) rather than a DB row lock.",
            "Increase innodb_lock_wait_timeout if brief waits are acceptable.",
        ],
        "see_also": ["mysql-008", "mysql-009", "mysql-011"],
    },
    {
        "id": "mysql-011",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"TransactionTimedOutException|Transaction timed out.*deadline|transaction.*timed out",
        "title": "Spring TransactionTimedOutException — transaction deadline exceeded",
        "plain_english": "Spring's transaction manager cancelled the transaction because it exceeded the configured @Transactional(timeout=...) deadline. The underlying cause is usually a lock wait or slow query.",
        "causes": [
            "Underlying lock wait (MySQLQueryInterruptedException) consumed the transaction's time budget.",
            "@Transactional(timeout=...) set too short for the operation's normal duration.",
            "Slow query or missing index causing the transaction to run longer than expected.",
        ],
        "fix_steps": [
            "Follow the 'Caused by' chain — TransactionTimedOutException is a wrapper; fix the root cause first (see mysql-008).",
            "Increase the transaction timeout: @Transactional(timeout=30) or spring.transaction.default-timeout=30",
            "Reduce the work done inside the transaction — move non-DB operations outside @Transactional.",
            "Add @Retryable(value={TransactionTimedOutException.class}, maxAttempts=3) for transient timeouts.",
        ],
        "see_also": ["mysql-008", "mysql-009", "mysql-010"],
    },
    {
        "id": "mysql-012",
        "category": "MySQL",
        "severity": "critical",
        "pattern": r"reactor-http-nio|reactor-tcp|reactor.*deadlock|SQLTransactionRollbackException.*reactor|ReactiveException.*deadlock",
        "title": "Deadlock in reactive application (Project Reactor / Spring WebFlux)",
        "plain_english": "A database deadlock occurred on a Project Reactor event-loop thread. Reactive applications need non-blocking retry logic — @Retryable does not work here.",
        "causes": [
            "Multiple reactive streams contending for the same database rows.",
            "Blocking JDBC calls (JPA/Hibernate) on a reactor-http-nio thread — JDBC is inherently blocking.",
            "Long-running transactions in a high-concurrency reactive environment.",
            "Missing retry logic — the reactive pipeline fails instead of retrying the rolled-back transaction.",
        ],
        "fix_steps": [
            "Use retryWhen for non-blocking retry: Mono.fromCallable(() -> repo.findById(id)).retryWhen(Retry.backoff(3, Duration.ofSeconds(1)).filter(t -> t instanceof SQLTransactionRollbackException))",
            "Avoid Mono.block() / Flux.blockFirst() on reactor threads — offload blocking JDBC to a bounded elastic scheduler: Mono.fromCallable(() -> blockingCall()).subscribeOn(Schedulers.boundedElastic())",
            "Consider R2DBC (spring-boot-starter-data-r2dbc) for true non-blocking database access.",
            "Use onErrorResume for fallback: repo.findById(id).onErrorResume(SQLTransactionRollbackException.class, ex -> Mono.just(defaultValue()))",
            "Analyse the deadlock: SHOW ENGINE INNODB STATUS; — look for LATEST DETECTED DEADLOCK.",
        ],
        "see_also": ["mysql-005", "mysql-013", "thread-003"],
    },
    {
        "id": "mysql-013",
        "category": "MySQL",
        "severity": "high",
        "pattern": r"hibernate\.lock\.timeout|javax\.persistence\.lock\.timeout|innodb_lock_wait_timeout.*configure|lock timeout.*hibernate",
        "title": "Hibernate lock timeout configuration",
        "plain_english": "Hibernate's lock timeout is not configured or is set too short, causing lock wait failures before the database's own timeout fires.",
        "causes": [
            "Default Hibernate lock timeout (-1, meaning wait forever) or a very short value causing premature failures.",
            "Missing javax.persistence.lock.timeout query hint on pessimistic lock queries.",
            "innodb_lock_wait_timeout (default 50s) lower than the application's expected transaction duration.",
        ],
        "fix_steps": [
            "Set globally: spring.jpa.properties.hibernate.lock.timeout=10000 (milliseconds)",
            "Set per query: @QueryHints(@QueryHint(name=\"javax.persistence.lock.timeout\", value=\"10000\"))",
            "Use NOWAIT for immediate failure: @QueryHint(name=\"javax.persistence.lock.timeout\", value=\"0\")",
            "Set MySQL global timeout: SET GLOBAL innodb_lock_wait_timeout=30;",
            "Prefer @Version (optimistic locking) over pessimistic locks in high-concurrency scenarios.",
        ],
        "see_also": ["mysql-008", "mysql-009", "mysql-010"],
    },
    {
        "id": "webflux-001",
        "category": "Concurrency/Threading",
        "severity": "high",
        "pattern": r"block.*reactor|Mono\.block|Flux\.block|blockingCall.*reactor|reactor.*blocking|subscribeOn.*boundedElastic",
        "title": "Blocking call on Project Reactor event-loop thread",
        "plain_english": "A blocking operation (JDBC, Thread.sleep, Mono.block()) was called on a reactor-http-nio or parallel thread. This stalls the event loop and causes timeouts and deadlocks under load.",
        "causes": [
            "Mono.block() or Flux.blockFirst() called inside a reactive pipeline.",
            "JPA/JDBC repository called directly from a WebFlux controller without subscribeOn.",
            "Thread.sleep() or other blocking waits inside a flatMap or map operator.",
            "Synchronous RestTemplate used inside a reactive service instead of WebClient.",
        ],
        "fix_steps": [
            "Offload blocking calls to the bounded elastic scheduler: Mono.fromCallable(() -> blockingRepo.findById(id)).subscribeOn(Schedulers.boundedElastic())",
            "Replace RestTemplate with WebClient for non-blocking HTTP calls.",
            "Replace blocking JDBC with R2DBC for non-blocking database access.",
            "Never call Mono.block() inside a reactive pipeline — use flatMap, then, or zip instead.",
            "Use BlockHound in tests to detect accidental blocking calls: BlockHound.install();",
        ],
        "see_also": ["mysql-012", "thread-003"],
    },

    # ── Keystone ──────────────────────────────────────────────────────────────
    {
        "id": "ks-001",
        "category": "Keystone",
        "severity": "critical",
        "pattern": r"The request you have made requires authentication|Keystone.*401",
        "title": "Keystone 401 — authentication required",
        "plain_english": "The Keystone request was rejected because no valid token or credentials were provided.",
        "causes": [
            "Missing or expired token in the X-Auth-Token header.",
            "Service account credentials (username/password/project) are incorrect.",
            "Token has expired and was not refreshed.",
        ],
        "fix_steps": [
            "Re-authenticate: openstack token issue",
            "Verify service account credentials in the application config.",
            "Check token TTL and implement token refresh logic.",
        ],
        "see_also": ["ks-002", "ks-003"],
    },
    {
        "id": "ks-002",
        "category": "Keystone",
        "severity": "high",
        "pattern": r"You are not authorized to perform the requested action|Keystone.*403",
        "title": "Keystone 403 — insufficient role",
        "plain_english": "The authenticated user does not have the role required to perform the requested operation.",
        "causes": [
            "Service account is missing the required role on the project.",
            "Role assignment was removed or the project was changed.",
        ],
        "fix_steps": [
            "Check role assignments: openstack role assignment list --user <user> --project <project>",
            "Assign the required role: openstack role add --user <user> --project <project> <role>",
        ],
        "see_also": ["ks-001"],
    },
    {
        "id": "ks-003",
        "category": "Keystone",
        "severity": "high",
        "pattern": r"Could not find token|Token not found|404.*token",
        "title": "Keystone token not found or expired",
        "plain_english": "The token presented to Keystone does not exist or has already expired.",
        "causes": [
            "Token TTL has elapsed.",
            "Fernet key rotation invalidated existing tokens.",
            "Token was revoked.",
        ],
        "fix_steps": [
            "Re-authenticate to obtain a fresh token.",
            "Check fernet key rotation schedule: ls -la /etc/keystone/fernet-keys/",
            "Increase token TTL in keystone.conf if appropriate: [token] expiration = 3600",
        ],
        "see_also": ["ks-001", "ks-004"],
    },
    {
        "id": "ks-004",
        "category": "Keystone",
        "severity": "high",
        "pattern": r"Fernet.*decrypt|Invalid token|token is invalid",
        "title": "Keystone fernet token decryption failure",
        "plain_english": "Keystone cannot decrypt the token — the fernet keys used to create it are no longer present.",
        "causes": [
            "Fernet keys were rotated and old keys were removed before tokens expired.",
            "Fernet key directory is empty or missing.",
            "Token was issued by a different Keystone node with different keys (HA setup without shared keys).",
        ],
        "fix_steps": [
            "Check fernet keys: ls -la /etc/keystone/fernet-keys/",
            "Ensure all Keystone nodes share the same fernet keys in HA deployments.",
            "Re-issue tokens after key rotation: clients must re-authenticate.",
        ],
        "see_also": ["ks-003"],
    },
    {
        "id": "ks-005",
        "category": "Keystone",
        "severity": "critical",
        "pattern": r"No endpoint found.*identity|Endpoint not found|keystoneauth.*EndpointNotFound",
        "title": "Keystone endpoint not in catalogue",
        "plain_english": "The OpenStack client cannot find the identity service endpoint in the service catalogue.",
        "causes": [
            "Identity endpoint not registered in Keystone.",
            "Endpoint URL is wrong or the service is registered under a different region.",
            "Endpoint is disabled.",
        ],
        "fix_steps": [
            "List endpoints: openstack endpoint list --service identity",
            "Create the endpoint if missing: openstack endpoint create --region RegionOne identity public https://<host>:5000/v3",
            "Enable a disabled endpoint: openstack endpoint set --enable <endpoint_id>",
        ],
        "see_also": ["ks-001"],
    },

    # ── Java Standard Library ─────────────────────────────────────────────────
    {
        "id": "java-001",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"NullPointerException",
        "title": "NullPointerException — null reference dereferenced",
        "plain_english": "Code tried to call a method or access a field on an object reference that is null.",
        "causes": [
            "A method returned null and the caller did not check before using the result.",
            "An optional dependency or configuration value was not injected.",
            "A collection element or map value is null at the point of access.",
            "JPA entity relationship not loaded (see LazyInitializationException).",
        ],
        "fix_steps": [
            "Read the stack trace — the top application frame (non-framework) is where the null was dereferenced.",
            "Add a null check or use Optional<T> / Objects.requireNonNull() at the call site.",
            "In Java 14+, Helpful NullPointerExceptions (JEP 358) name the exact null variable — enable with -XX:+ShowCodeDetailsInExceptionMessages.",
            "Use @NonNull / @NotNull annotations and a static analyser (SpotBugs, NullAway) to catch these at compile time.",
        ],
        "see_also": ["java-002", "db-006"],
    },
    {
        "id": "java-002",
        "category": "Java Standard Library",
        "severity": "critical",
        "pattern": r"OutOfMemoryError|Java heap space|GC overhead limit exceeded|Metaspace",
        "title": "OutOfMemoryError — JVM heap or metaspace exhausted",
        "plain_english": "The JVM ran out of memory and could not allocate a new object. The application will likely crash or become unresponsive.",
        "causes": [
            "Heap too small for the workload — increase -Xmx.",
            "Memory leak — objects accumulating in a cache, static collection, or listener list.",
            "Processing very large datasets in memory (e.g. loading an entire DB table).",
            "Metaspace exhaustion from excessive dynamic class generation (reflection, proxies, Groovy scripts).",
        ],
        "fix_steps": [
            "Take a heap dump at the time of the OOM: -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/heap.hprof",
            "Analyse the heap dump with Eclipse MAT or VisualVM to find the largest retained objects.",
            "Increase heap: -Xmx2g (or appropriate value for your workload).",
            "For Metaspace: -XX:MaxMetaspaceSize=512m and investigate dynamic class generation.",
            "For GC overhead: profile GC logs with -Xlog:gc* and consider switching to G1GC or ZGC.",
        ],
        "see_also": ["java-003"],
    },
    {
        "id": "java-003",
        "category": "Java Standard Library",
        "severity": "critical",
        "pattern": r"StackOverflowError",
        "title": "StackOverflowError — infinite or excessively deep recursion",
        "plain_english": "A method called itself (directly or indirectly) so many times that the JVM call stack ran out of space.",
        "causes": [
            "Infinite recursion — a recursive method has no base case or the base case is never reached.",
            "Circular object graph serialization (Jackson, Gson, JPA toString).",
            "Proxy/AOP interception loop — a Spring proxy calling itself.",
            "Very deep but legitimate recursion on a large data structure.",
        ],
        "fix_steps": [
            "Check the stack trace for a repeating pattern of the same method — that is the recursive loop.",
            "Add or fix the base case in the recursive method.",
            "For circular serialization: use @JsonManagedReference / @JsonBackReference or @JsonIgnore on the back-reference.",
            "For deep-but-legitimate recursion: convert to an iterative algorithm using an explicit stack.",
        ],
        "see_also": ["java-002"],
    },
    {
        "id": "java-004",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"ConcurrentModificationException",
        "title": "ConcurrentModificationException — collection modified during iteration",
        "plain_english": "A collection (List, Map, Set) was modified while it was being iterated, which is not allowed by most Java collections.",
        "causes": [
            "Removing or adding elements inside a for-each loop over the same collection.",
            "Two threads accessing and modifying the same non-thread-safe collection concurrently.",
            "Modifying a collection inside a stream pipeline that is iterating it.",
        ],
        "fix_steps": [
            "Use Iterator.remove() instead of Collection.remove() inside a loop.",
            "Collect items to remove into a separate list, then remove after the loop.",
            "For concurrent access: use ConcurrentHashMap, CopyOnWriteArrayList, or synchronize access explicitly.",
            "Use removeIf() for conditional removal: list.removeIf(item -> item.shouldBeRemoved()).",
        ],
        "see_also": ["java-005"],
    },
    {
        "id": "java-005",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"ClassCastException",
        "title": "ClassCastException — incompatible type cast",
        "plain_english": "Code tried to cast an object to a type it is not an instance of.",
        "causes": [
            "Incorrect assumption about the runtime type of an object from a generic collection or API.",
            "Deserializing data into the wrong type.",
            "Multiple classloaders loading the same class — common in OSGi or hot-reload environments.",
            "Spring bean proxied by CGLIB being cast to a concrete class instead of an interface.",
        ],
        "fix_steps": [
            "Use instanceof before casting: if (obj instanceof MyType t) { ... }",
            "Check the actual runtime type: obj.getClass().getName() in a debug log.",
            "For Spring proxies: inject by interface, not concrete class.",
            "For classloader issues: ensure the same classloader loads the class on both sides of the cast.",
        ],
        "see_also": [],
    },
    {
        "id": "java-006",
        "category": "Java Standard Library",
        "severity": "medium",
        "pattern": r"IllegalStateException",
        "title": "IllegalStateException — object in wrong state for operation",
        "plain_english": "A method was called on an object that is not in the correct state to handle it.",
        "causes": [
            "Calling a method before required initialisation is complete.",
            "Reusing a single-use object (e.g. calling HttpURLConnection after disconnect).",
            "Spring context not fully started when a bean method is called.",
            "Transaction not active when a transactional operation is attempted.",
        ],
        "fix_steps": [
            "Read the exception message — it usually names the invalid state explicitly.",
            "Ensure initialisation order is correct (e.g. @PostConstruct, ApplicationReadyEvent).",
            "Check that @Transactional is applied at the correct layer and not self-invoked.",
        ],
        "see_also": ["java-007"],
    },
    {
        "id": "java-007",
        "category": "Java Standard Library",
        "severity": "medium",
        "pattern": r"IllegalArgumentException",
        "title": "IllegalArgumentException — invalid method argument",
        "plain_english": "A method received an argument value that it cannot accept.",
        "causes": [
            "Null passed to a method that requires a non-null value.",
            "Numeric value out of the accepted range.",
            "Empty string or blank value where content is required.",
            "Enum value not recognised.",
        ],
        "fix_steps": [
            "Read the exception message — it usually states which argument is invalid and why.",
            "Add input validation before calling the method.",
            "Use Spring's @Validated / @Valid on controller parameters to catch bad input at the API boundary.",
        ],
        "see_also": ["java-001"],
    },
    {
        "id": "java-008",
        "category": "Java Standard Library",
        "severity": "medium",
        "pattern": r"IndexOutOfBoundsException|ArrayIndexOutOfBoundsException|StringIndexOutOfBoundsException",
        "title": "IndexOutOfBoundsException — array or list index out of range",
        "plain_english": "Code tried to access an element at an index that does not exist in the array, list, or string.",
        "causes": [
            "Off-by-one error in a loop (using <= instead of <).",
            "Accessing a list that is shorter than expected (e.g. after a filter).",
            "Hardcoded index assumption that breaks when data changes.",
        ],
        "fix_steps": [
            "Check the index against the collection size before accessing: if (i < list.size()).",
            "Use list.get(0) only after checking list.isEmpty().",
            "Prefer enhanced for-each loops or streams over index-based loops where possible.",
        ],
        "see_also": [],
    },
    {
        "id": "java-009",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"ClassNotFoundException|NoClassDefFoundError",
        "title": "ClassNotFoundException / NoClassDefFoundError — missing class at runtime",
        "plain_english": "The JVM could not find a class that the application needs. The class is either missing from the classpath or failed to initialise.",
        "causes": [
            "A JAR dependency is missing from the classpath.",
            "Dependency version conflict — the class exists in a different version of the JAR.",
            "Class was present at compile time but excluded from the runtime artifact.",
            "For NoClassDefFoundError: the class was found but its static initialiser threw an exception.",
        ],
        "fix_steps": [
            "Check which JAR provides the missing class using the JAR Analyser.",
            "Add the missing dependency to pom.xml / build.gradle.",
            "Run mvn dependency:tree or gradle dependencies to find version conflicts.",
            "For NoClassDefFoundError: look for an earlier ExceptionInInitializerError in the logs.",
        ],
        "see_also": ["boot-001"],
    },
    {
        "id": "java-010",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"UnsupportedOperationException",
        "title": "UnsupportedOperationException — operation not supported by this collection or class",
        "plain_english": "A method was called that the object does not support — most commonly, trying to modify an unmodifiable collection.",
        "causes": [
            "Calling add/remove on a list returned by Arrays.asList() or List.of() (both are fixed-size/immutable).",
            "Calling a mutating method on Collections.unmodifiableList() / Map.copyOf().",
            "Abstract method not implemented in a subclass.",
        ],
        "fix_steps": [
            "Wrap in a mutable copy: new ArrayList<>(Arrays.asList(...)) before modifying.",
            "Use List.copyOf() only for truly read-only views; use new ArrayList<>() when mutation is needed.",
            "Check the collection's origin — if it came from a framework method, read its Javadoc for mutability.",
        ],
        "see_also": ["java-004"],
    },
    {
        "id": "java-011",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"NumberFormatException",
        "title": "NumberFormatException — string cannot be parsed as a number",
        "plain_english": "Integer.parseInt(), Long.parseLong(), or similar was called with a string that is not a valid number.",
        "causes": [
            "Empty string or null passed to parseInt.",
            "String contains whitespace, currency symbols, or commas.",
            "Configuration value is a placeholder (e.g. '${some.property}') that was not resolved.",
            "Locale-specific decimal separator (comma vs dot) mismatch.",
        ],
        "fix_steps": [
            "Validate the string before parsing: StringUtils.isNumeric() or a try/catch.",
            "Trim whitespace: Integer.parseInt(s.trim()).",
            "Check that all Spring property placeholders are resolved in the environment.",
            "Use NumberFormat with an explicit Locale for locale-aware parsing.",
        ],
        "see_also": ["java-007"],
    },
    {
        "id": "java-012",
        "category": "Java Standard Library",
        "severity": "high",
        "pattern": r"(?<!Query)(?<!MySQL)InterruptedException",
        "title": "InterruptedException — thread interrupted during blocking operation",
        "plain_english": "A thread was interrupted while waiting (sleep, wait, join, blocking queue take) — this is a signal to stop what it is doing.",
        "causes": [
            "Application shutdown signal interrupting worker threads.",
            "Thread pool shutdown interrupting in-flight tasks.",
            "Explicit Thread.interrupt() call from another thread.",
            "InterruptedException caught and swallowed — interrupt flag not restored.",
        ],
        "fix_steps": [
            "Never swallow InterruptedException silently — either re-throw it or restore the interrupt flag: Thread.currentThread().interrupt().",
            "On shutdown, handle InterruptedException as a clean-stop signal and exit the loop.",
            "Use ExecutorService.awaitTermination() with a timeout for graceful shutdown.",
        ],
        "see_also": ["java-013"],
    },
    {
        "id": "java-013",
        "category": "Java Standard Library",
        "severity": "critical",
        "pattern": r"deadlock|BLOCKED.*waiting.*lock|Thread.*waiting to lock|Found one Java-level deadlock",
        "title": "Thread deadlock detected",
        "plain_english": "Two or more threads are each waiting for a lock held by the other, so none can proceed.",
        "causes": [
            "Locks acquired in inconsistent order across threads.",
            "Nested synchronized blocks or ReentrantLock.lock() calls in different orders.",
            "Database deadlock propagated to application-level locking.",
            "Spring @Transactional methods calling each other with incompatible propagation levels.",
        ],
        "fix_steps": [
            "Take a thread dump: kill -3 <pid> or jstack <pid> — look for 'Found one Java-level deadlock'.",
            "Establish a global lock ordering and always acquire locks in that order.",
            "Use tryLock() with a timeout instead of lock() to detect and recover from deadlocks.",
            "Prefer higher-level concurrency utilities (java.util.concurrent) over raw synchronized.",
        ],
        "see_also": ["java-012", "db-004"],
    },
    {
        "id": "java-014",
        "category": "Java Standard Library",
        "severity": "medium",
        "pattern": r"FileNotFoundException|NoSuchFileException",
        "title": "FileNotFoundException — file or directory does not exist",
        "plain_english": "The application tried to open a file that does not exist at the specified path.",
        "causes": [
            "Hardcoded path that differs between environments (dev vs container vs production).",
            "File not included in the Docker image or deployment artifact.",
            "Relative path resolved against the wrong working directory.",
            "File was deleted or moved externally.",
        ],
        "fix_steps": [
            "Use classpath resources (ClassPathResource) instead of filesystem paths where possible.",
            "Externalise the path as a configuration property and verify it in each environment.",
            "In Docker: verify the file is COPY'd into the image and the path matches.",
            "Log the absolute path at startup: new File(path).getAbsolutePath().",
        ],
        "see_also": [],
    },
    {
        "id": "java-015",
        "category": "Java Standard Library",
        "severity": "medium",
        "pattern": r"ParseException|DateTimeParseException|UnparsableDateException",
        "title": "Date/time parse exception — unrecognised format",
        "plain_english": "A date or time string could not be parsed because its format does not match the expected pattern.",
        "causes": [
            "Date format mismatch between producer and consumer (e.g. 'dd/MM/yyyy' vs 'yyyy-MM-dd').",
            "Timezone offset present in the string but not in the format pattern.",
            "Locale-specific month names in a string parsed with a different locale.",
            "ISO-8601 string with milliseconds parsed by a formatter without the .SSS part.",
        ],
        "fix_steps": [
            "Use ISO-8601 (yyyy-MM-dd'T'HH:mm:ss.SSSZ) as the canonical format across all services.",
            "Configure Jackson globally: spring.jackson.date-format and spring.jackson.time-zone.",
            "Use java.time (DateTimeFormatter) rather than the legacy SimpleDateFormat.",
            "Log the raw string value before parsing to confirm what format is actually arriving.",
        ],
        "see_also": ["java-007"],
    },

    # ── Concurrency / Threading ───────────────────────────────────────────────
    {
        "id": "thread-001",
        "category": "Concurrency/Threading",
        "severity": "critical",
        "pattern": r"RejectedExecutionException|Task.*rejected.*ThreadPoolExecutor|executor.*shut down",
        "title": "Thread pool rejected task — pool full or shut down",
        "plain_english": "A task submitted to a thread pool was rejected because the pool's queue is full, all threads are busy, or the executor has been shut down.",
        "causes": [
            "Thread pool queue capacity exceeded under high load.",
            "Submitting tasks after ExecutorService.shutdown() was called.",
            "Spring @Async executor not sized for the workload.",
            "Burst of requests overwhelming a fixed-size pool.",
        ],
        "fix_steps": [
            "Increase the thread pool queue capacity or core/max thread count.",
            "Implement a RejectedExecutionHandler to handle overflow gracefully (e.g. CallerRunsPolicy).",
            "For Spring @Async: configure a ThreadPoolTaskExecutor bean with appropriate sizes.",
            "Add backpressure — slow down producers when the pool is saturated.",
        ],
        "see_also": ["java-013", "java-012"],
    },
    {
        "id": "thread-002",
        "category": "Concurrency/Threading",
        "severity": "high",
        "pattern": r"race condition|visibility.*issue|stale.*value|happens-before|volatile.*missing",
        "title": "Potential race condition — shared state without synchronisation",
        "plain_english": "Multiple threads are reading and writing shared state without proper synchronisation, leading to unpredictable behaviour.",
        "causes": [
            "Shared mutable field not declared volatile or accessed without synchronization.",
            "Check-then-act pattern (if !map.containsKey → map.put) not atomic.",
            "Singleton bean with mutable instance fields accessed by multiple request threads.",
            "Static mutable state modified from multiple threads.",
        ],
        "fix_steps": [
            "Use AtomicInteger, AtomicReference, or ConcurrentHashMap for shared counters/maps.",
            "Replace check-then-act with atomic operations: ConcurrentHashMap.computeIfAbsent().",
            "Declare shared flags volatile if only one thread writes and others read.",
            "Make Spring beans stateless — move mutable state to method-local variables or ThreadLocal.",
            "Use synchronized blocks or ReentrantReadWriteLock for complex invariants.",
        ],
        "see_also": ["java-013", "java-004"],
    },
    {
        "id": "thread-003",
        "category": "Concurrency/Threading",
        "severity": "high",
        "pattern": r"TimeoutException|await.*timed out|CountDownLatch.*timeout|CompletableFuture.*timeout",
        "title": "Concurrent operation timed out waiting for completion",
        "plain_english": "A thread waited for another thread or async operation to complete but it did not finish within the allowed time.",
        "causes": [
            "Downstream service or DB call taking longer than expected.",
            "Thread pool exhaustion causing tasks to queue rather than execute.",
            "Deadlock preventing the awaited thread from making progress.",
            "Timeout value too aggressive for the operation's normal duration.",
        ],
        "fix_steps": [
            "Check logs for the thread that was supposed to complete — it may itself be blocked.",
            "Take a thread dump to identify blocked/waiting threads.",
            "Increase the timeout if the operation is legitimately slow.",
            "Add monitoring on thread pool queue depth to detect saturation early.",
        ],
        "see_also": ["java-013", "thread-001"],
    },

    # ── HTTP Client ──────────────────────────────────────────────────────────
    {
        "id": "redis-001",
        "category": "Redis",
        "severity": "critical",
        "pattern": r"RedisConnectionException|RedisConnectionFailureException|Unable to connect to Redis|Connection refused.*6379|ConnectException.*[Rr]edis|LettuceConnectionFactory|RedisClient|lettuce\.core|spring\.redis",
        "title": "Redis connection refused — server unreachable",
        "plain_english": "The application cannot connect to Redis. This is a cache-layer failure — if Redis is used as a session store or primary cache, this will cascade into application errors.",
        "causes": [
            "Redis server is not running or has crashed.",
            "Wrong host or port in spring.redis.host / spring.redis.port.",
            "Firewall or network policy blocking port 6379.",
            "Redis max connections or memory limit reached, causing it to refuse new connections.",
            "Redis bound to 127.0.0.1 only — not reachable from the application container.",
        ],
        "fix_steps": [
            "Check Redis is running: redis-cli -h <host> -p 6379 ping — should return PONG.",
            "Start Redis if down: redis-server (or systemctl start redis / docker start redis).",
            "Verify config: spring.redis.host=<host> spring.redis.port=6379 in application.properties.",
            "Test network path: telnet <host> 6379",
            "Increase Lettuce connection pool: spring.redis.lettuce.pool.max-active=50 spring.redis.lettuce.pool.max-idle=10",
            "Add fallback with onErrorResume: redisTemplate.opsForValue().get(key).onErrorResume(RedisConnectionException.class, ex -> Mono.just(getFromDatabase()))",
            "Add a circuit breaker (Resilience4j @CircuitBreaker) so Redis failures degrade gracefully instead of cascading.",
            "Check Redis logs: tail -f /var/log/redis/redis-server.log",
        ],
        "see_also": ["http-001", "webflux-001"],
    },
    {
        "id": "http-001",
        "category": "HTTP Client",
        "severity": "high",
        "pattern": r"Connection refused|ConnectException|Failed to connect|connection timed out",
        "title": "HTTP connection refused or timed out",
        "plain_english": "The application tried to make an outbound HTTP call but the target service is not accepting connections.",
        "causes": [
            "Target service is down or not yet started.",
            "Wrong host or port in the service URL configuration.",
            "Firewall or network policy blocking the connection.",
            "Service is overloaded and not accepting new connections.",
        ],
        "fix_steps": [
            "Verify the target service is running and healthy.",
            "Check the configured URL: curl -v <url>",
            "Test network path: telnet <host> <port>",
            "Add circuit breaker / retry logic (Resilience4j) to handle transient failures.",
        ],
        "see_also": ["http-002"],
    },
    {
        "id": "http-002",
        "category": "HTTP Client",
        "severity": "high",
        "pattern": r"Read timed out|SocketTimeoutException|ReadTimeoutException|timeout.*after \d+ms",
        "title": "HTTP read timeout",
        "plain_english": "The HTTP request was sent successfully but the server did not respond within the configured timeout period.",
        "causes": [
            "Target service is slow or overloaded.",
            "Long-running operation that exceeds the client timeout.",
            "Network latency or packet loss.",
            "Timeout configured too aggressively.",
        ],
        "fix_steps": [
            "Increase read timeout if the operation is legitimately slow.",
            "Investigate target service performance — check its logs and metrics.",
            "Add async processing for long-running operations instead of synchronous HTTP.",
            "Implement retry with exponential backoff for transient timeouts.",
        ],
        "see_also": ["http-001"],
    },
    {
        "id": "http-003",
        "category": "HTTP Client",
        "severity": "medium",
        "pattern": r"404 Not Found|No handler found|RequestMapping.*not found|WhitelabelErrorPage",
        "title": "404 Not Found — endpoint does not exist",
        "plain_english": "The HTTP request reached the server but no handler was found for the requested path.",
        "causes": [
            "Wrong URL path in the client configuration.",
            "API version mismatch (e.g. calling /v1/ when server is on /v2/).",
            "Controller mapping changed after a deployment.",
            "Context path not included in the URL.",
        ],
        "fix_steps": [
            "Check the server's API documentation or Swagger UI for the correct path.",
            "Verify server.servlet.context-path in the target service's config.",
            "Check recent deployments for endpoint renames or removals.",
        ],
        "see_also": [],
    },
    {
        "id": "http-004",
        "category": "HTTP Client",
        "severity": "medium",
        "pattern": r"HttpMessageNotReadableException|JSON parse error|MismatchedInputException|Cannot deserialize",
        "title": "HTTP request/response deserialization failed",
        "plain_english": "Jackson (or another JSON library) could not parse the HTTP request body or response into the expected Java type.",
        "causes": [
            "API contract mismatch — sender and receiver have different DTO definitions.",
            "Null value in a field annotated @NonNull or mapped to a primitive.",
            "Date/time format mismatch.",
            "Unexpected JSON structure (array vs object, extra/missing fields).",
        ],
        "fix_steps": [
            "Compare the actual JSON payload with the expected DTO class.",
            "Use @JsonIgnoreProperties(ignoreUnknown=true) to tolerate extra fields.",
            "Standardise date formats with @JsonFormat or a global ObjectMapper config.",
            "Use the JAR Analyser DTO Conflicts tab to detect schema mismatches across services.",
        ],
        "see_also": ["http-003"],
    },
    {
        "id": "http-005",
        "category": "HTTP Client",
        "severity": "medium",
        "pattern": r"503 Service Unavailable|CircuitBreakerOpenException|circuit.*open|Upstream.*unavailable",
        "title": "503 Service Unavailable / circuit breaker open",
        "plain_english": "The target service is temporarily unavailable, or a circuit breaker has tripped after repeated failures.",
        "causes": [
            "Target service is down or being restarted.",
            "Circuit breaker opened after failure threshold exceeded.",
            "Load balancer has no healthy instances.",
            "Rate limit exceeded.",
        ],
        "fix_steps": [
            "Check target service health and logs.",
            "Wait for circuit breaker half-open state and retry.",
            "Review Resilience4j / Hystrix configuration — failure rate threshold, wait duration.",
            "Check load balancer health check configuration.",
        ],
        "see_also": ["http-001", "http-002"],
    },
]

# `KB` above is now purely a seed fixture consumed once by scripts/seed_static_kb.py
# — all 40 entries live in jar_kb_entries (origin='builtin') alongside user-created
# ones, so search_kb() reads exclusively from the DB rows the caller passes in.


def search_kb(query: str, db_entries: list[dict] | None = None, limit: int = 10) -> list[dict]:
    """Return KB entries whose pattern matches the query text.

    Three-pass strategy — broadens progressively so a narrow exception
    class+message that misses every pattern still surfaces relevant entries
    via token overlap rather than returning nothing:

    Pass 1 — regex pattern match against the full query string (existing
             behaviour, highest confidence). Results are sorted by
             specificity: entries whose pattern matches the exception class
             or a distinctive frame token rank above generic ones that only
             match on common words like "Connection refused".
    Pass 2 — regex pattern match against each individual token extracted
             from the query (short class name, individual message words).
             Catches cases where the full string doesn't match but a key
             token like "ConnectException" or "Deadlock" does.
    Pass 3 — keyword overlap: score each entry by how many of the query
             tokens appear in its title + plain_english + causes + fix_steps.
             Only entries with at least 2 token hits are included (threshold
             raised from 1 to reduce noise), ranked by hit count descending.
             Only fills remaining slots up to limit after passes 1 and 2.
    """
    if not query or not query.strip():
        return []

    entries = db_entries or []
    results: list[dict] = []
    seen: set[str] = set()

    # Extract tokens up-front — used by all three passes
    colon_idx = query.find(":")
    class_part = query[:colon_idx].strip() if colon_idx != -1 else query.strip()
    msg_part = query[colon_idx + 1:].strip() if colon_idx != -1 else ""

    short_class = class_part.split(".")[-1] if "." in class_part else class_part
    tokens: list[str] = []
    if short_class:
        tokens.append(short_class)
        tokens.extend(t for t in re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+", short_class) if len(t) > 3)
    _STOP = {"the", "and", "for", "not", "was", "with", "from", "that", "this", "when", "could"}
    tokens.extend(
        w for w in re.findall(r"[A-Za-z]{4,}", msg_part)
        if w.lower() not in _STOP
    )
    tokens = list(dict.fromkeys(t for t in tokens if t))

    # Pass 1 — full query against each entry's pattern, with specificity sort.
    # An entry is "specific" if its pattern matches the short exception class
    # name or a distinctive frame token (not just a generic word like
    # "Connection"). Specific matches rank first so redis-001 beats http-001
    # when Lettuce/RedisClient frames are present in the query.
    pass1_specific: list[dict] = []
    pass1_generic: list[dict] = []
    for entry in entries:
        if entry["id"] not in seen:
            try:
                if re.search(entry["pattern"], query, re.IGNORECASE):
                    seen.add(entry["id"])
                    # Specific = pattern matches the short class name or a
                    # frame token (something more distinctive than the message)
                    is_specific = bool(
                        re.search(entry["pattern"], short_class, re.IGNORECASE)
                        or any(
                            re.search(entry["pattern"], tok, re.IGNORECASE)
                            for tok in tokens
                            if tok != short_class and len(tok) > 5
                        )
                    )
                    if is_specific:
                        pass1_specific.append(entry)
                    else:
                        pass1_generic.append(entry)
            except re.error:
                pass
    results = pass1_specific + pass1_generic

    # Pass 2 — each token against each entry's pattern
    if tokens:
        for entry in entries:
            if entry["id"] not in seen:
                try:
                    if any(re.search(entry["pattern"], tok, re.IGNORECASE) for tok in tokens):
                        results.append(entry)
                        seen.add(entry["id"])
                except re.error:
                    pass

    # Pass 3 — token overlap scoring, only fills remaining slots, min 2 hits
    if tokens and len(results) < limit:
        tl = [t.lower() for t in tokens]
        scored: list[tuple[int, dict]] = []
        for entry in entries:
            if entry["id"] in seen:
                continue
            haystack = " ".join(filter(None, [
                entry.get("title", ""),
                entry.get("plain_english", ""),
                " ".join(entry.get("causes", [])),
                " ".join(entry.get("fix_steps", [])),
            ])).lower()
            hits = sum(1 for t in tl if t in haystack)
            if hits >= 2:  # raised from 1 to reduce noise
                scored.append((hits, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        for _, entry in scored:
            if len(results) >= limit:
                break
            results.append(entry)
            seen.add(entry["id"])

    return results[:limit]
