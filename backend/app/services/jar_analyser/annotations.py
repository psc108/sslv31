"""Spring + JAX-RS annotation scanner.

Scans .class files inside a JAR (or extracted directory) and identifies
Spring MVC and JAX-RS annotations on classes and methods.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .classfile import ClassFileParser, ClassInfo, AnnotationInfo

# ---------------------------------------------------------------------------
# Spring MVC
# ---------------------------------------------------------------------------
REST_CONTROLLER   = "Lorg/springframework/web/bind/annotation/RestController;"
CONTROLLER        = "Lorg/springframework/web/bind/annotation/Controller;"
REQUEST_MAPPING   = "Lorg/springframework/web/bind/annotation/RequestMapping;"
GET_MAPPING       = "Lorg/springframework/web/bind/annotation/GetMapping;"
POST_MAPPING      = "Lorg/springframework/web/bind/annotation/PostMapping;"
PUT_MAPPING       = "Lorg/springframework/web/bind/annotation/PutMapping;"
PATCH_MAPPING     = "Lorg/springframework/web/bind/annotation/PatchMapping;"
DELETE_MAPPING    = "Lorg/springframework/web/bind/annotation/DeleteMapping;"

# Spring parameter
PATH_VARIABLE  = "Lorg/springframework/web/bind/annotation/PathVariable;"
REQUEST_PARAM  = "Lorg/springframework/web/bind/annotation/RequestParam;"
REQUEST_BODY   = "Lorg/springframework/web/bind/annotation/RequestBody;"
REQUEST_HEADER = "Lorg/springframework/web/bind/annotation/RequestHeader;"

# Spring security
PRE_AUTHORIZE  = "Lorg/springframework/security/access/prepost/PreAuthorize;"
SECURED        = "Lorg/springframework/security/access/annotation/Secured;"

# Deprecation
DEPRECATED = "Ljava/lang/Deprecated;"

# ---------------------------------------------------------------------------
# OpenAPI 3 / springdoc — the only source of developer-authored explanation
# text available from bytecode (annotation element values survive
# compilation; Javadoc/comments don't). See Stage 4 of the accuracy plan.
# Old-style Swagger 2 (@ApiOperation/@ApiModel, springfox) is deliberately
# not supported — confirmed absent (0 occurrences) in real analysed JARs,
# vs. 218 @Operation and 442 @Schema occurrences for the OpenAPI 3 style.
# ---------------------------------------------------------------------------
OPERATION      = "Lio/swagger/v3/oas/annotations/Operation;"
SCHEMA         = "Lio/swagger/v3/oas/annotations/media/Schema;"

# ---------------------------------------------------------------------------
# JAX-RS (jakarta + javax namespaces)
# ---------------------------------------------------------------------------
JAXRS_PATH         = "Ljakarta/ws/rs/Path;"
JAXRS_PATH_JAVAX   = "Ljavax/ws/rs/Path;"
JAXRS_GET          = "Ljakarta/ws/rs/GET;"
JAXRS_GET_JAVAX    = "Ljavax/ws/rs/GET;"
JAXRS_POST         = "Ljakarta/ws/rs/POST;"
JAXRS_POST_JAVAX   = "Ljavax/ws/rs/POST;"
JAXRS_PUT          = "Ljakarta/ws/rs/PUT;"
JAXRS_PUT_JAVAX    = "Ljavax/ws/rs/PUT;"
JAXRS_DELETE       = "Ljakarta/ws/rs/DELETE;"
JAXRS_DELETE_JAVAX = "Ljavax/ws/rs/DELETE;"
JAXRS_PATCH        = "Ljakarta/ws/rs/PATCH;"
JAXRS_PATCH_JAVAX  = "Ljavax/ws/rs/PATCH;"

JAXRS_PATH_ANNOTATIONS = {JAXRS_PATH, JAXRS_PATH_JAVAX}
JAXRS_METHOD_ANNOTATIONS = {
    JAXRS_GET, JAXRS_GET_JAVAX, JAXRS_POST, JAXRS_POST_JAVAX,
    JAXRS_PUT, JAXRS_PUT_JAVAX, JAXRS_DELETE, JAXRS_DELETE_JAVAX,
    JAXRS_PATCH, JAXRS_PATCH_JAVAX,
}

# JAX-RS parameter annotations. Unlike Spring (explicit @RequestBody only),
# JAX-RS's convention is inverted: a parameter with none of these is the
# implicit request entity/body — see _extract_parameters in endpoints.py.
JAXRS_PATH_PARAM      = "Ljakarta/ws/rs/PathParam;"
JAXRS_PATH_PARAM_JAVAX = "Ljavax/ws/rs/PathParam;"
JAXRS_QUERY_PARAM     = "Ljakarta/ws/rs/QueryParam;"
JAXRS_QUERY_PARAM_JAVAX = "Ljavax/ws/rs/QueryParam;"
JAXRS_HEADER_PARAM    = "Ljakarta/ws/rs/HeaderParam;"
JAXRS_HEADER_PARAM_JAVAX = "Ljavax/ws/rs/HeaderParam;"
JAXRS_COOKIE_PARAM    = "Ljakarta/ws/rs/CookieParam;"
JAXRS_COOKIE_PARAM_JAVAX = "Ljavax/ws/rs/CookieParam;"
JAXRS_MATRIX_PARAM    = "Ljakarta/ws/rs/MatrixParam;"
JAXRS_MATRIX_PARAM_JAVAX = "Ljavax/ws/rs/MatrixParam;"
JAXRS_FORM_PARAM      = "Ljakarta/ws/rs/FormParam;"
JAXRS_FORM_PARAM_JAVAX = "Ljavax/ws/rs/FormParam;"
# Framework-injected, not a request parameter at all (UriInfo, SecurityContext,
# AsyncResponse, an aggregate @BeanParam holder) — recognized so it's excluded
# from the implicit-body fallback without being surfaced as a param either.
JAXRS_CONTEXT         = "Ljakarta/ws/rs/core/Context;"
JAXRS_CONTEXT_JAVAX   = "Ljavax/ws/rs/core/Context;"
JAXRS_SUSPENDED       = "Ljakarta/ws/rs/container/Suspended;"
JAXRS_SUSPENDED_JAVAX = "Ljavax/ws/rs/container/Suspended;"
JAXRS_BEAN_PARAM      = "Ljakarta/ws/rs/BeanParam;"
JAXRS_BEAN_PARAM_JAVAX = "Ljavax/ws/rs/BeanParam;"

JAXRS_PARAM_ANNOTATIONS = {
    JAXRS_PATH_PARAM, JAXRS_PATH_PARAM_JAVAX,
    JAXRS_QUERY_PARAM, JAXRS_QUERY_PARAM_JAVAX,
    JAXRS_HEADER_PARAM, JAXRS_HEADER_PARAM_JAVAX,
    JAXRS_COOKIE_PARAM, JAXRS_COOKIE_PARAM_JAVAX,
    JAXRS_MATRIX_PARAM, JAXRS_MATRIX_PARAM_JAVAX,
    JAXRS_FORM_PARAM, JAXRS_FORM_PARAM_JAVAX,
    JAXRS_CONTEXT, JAXRS_CONTEXT_JAVAX,
    JAXRS_SUSPENDED, JAXRS_SUSPENDED_JAVAX,
    JAXRS_BEAN_PARAM, JAXRS_BEAN_PARAM_JAVAX,
}

# Security (JSR-250 — used by both Spring and JAX-RS)
ROLES_ALLOWED          = "Ljavax/annotation/security/RolesAllowed;"
ROLES_ALLOWED_JAKARTA  = "Ljakarta/annotation/security/RolesAllowed;"
PERMIT_ALL             = "Ljavax/annotation/security/PermitAll;"
PERMIT_ALL_JAKARTA     = "Ljakarta/annotation/security/PermitAll;"
DENY_ALL               = "Ljavax/annotation/security/DenyAll;"
DENY_ALL_JAKARTA       = "Ljakarta/annotation/security/DenyAll;"

# ---------------------------------------------------------------------------
# Combined sets
# ---------------------------------------------------------------------------
CONTROLLER_ANNOTATIONS = {REST_CONTROLLER, CONTROLLER} | JAXRS_PATH_ANNOTATIONS

MAPPING_ANNOTATIONS = {
    GET_MAPPING, POST_MAPPING, PUT_MAPPING, PATCH_MAPPING, DELETE_MAPPING,
    REQUEST_MAPPING,
} | JAXRS_METHOD_ANNOTATIONS

SECURITY_ANNOTATIONS = {
    PRE_AUTHORIZE, SECURED,
    ROLES_ALLOWED, ROLES_ALLOWED_JAKARTA,
    PERMIT_ALL, PERMIT_ALL_JAKARTA,
    DENY_ALL, DENY_ALL_JAKARTA,
}

# Component
SERVICE         = "Lorg/springframework/stereotype/Service;"
REPOSITORY      = "Lorg/springframework/stereotype/Repository;"
COMPONENT       = "Lorg/springframework/stereotype/Component;"
CONFIGURATION   = "Lorg/springframework/context/annotation/Configuration;"
BEAN            = "Lorg/springframework/context/annotation/Bean;"
ENTITY          = "Ljavax/persistence/Entity;"
ENTITY_JK       = "Ljakarta/persistence/Entity;"
TABLE           = "Ljavax/persistence/Table;"
TABLE_JK        = "Ljakarta/persistence/Table;"
RABBIT_LISTENER = "Lorg/springframework/amqp/rabbit/annotation/RabbitListener;"
SCHEDULED       = "Lorg/springframework/scheduling/annotation/Scheduled;"
# Repeatable-annotation container for multiple @Scheduled on one method
# (e.g. @Schedules({@Scheduled(cron=...), @Scheduled(fixedRate=...)})).
SCHEDULES       = "Lorg/springframework/scheduling/annotation/Schedules;"
FEIGN_CLIENT    = "Lorg/springframework/cloud/openfeign/FeignClient;"

# Error handling
CONTROLLER_ADVICE   = "Lorg/springframework/web/bind/annotation/ControllerAdvice;"
REST_CONTROLLER_ADVICE = "Lorg/springframework/web/bind/annotation/RestControllerAdvice;"
EXCEPTION_HANDLER  = "Lorg/springframework/web/bind/annotation/ExceptionHandler;"
RESPONSE_STATUS    = "Lorg/springframework/web/bind/annotation/ResponseStatus;"

CONTROLLER_ADVICE_ANNOTATIONS = {CONTROLLER_ADVICE, REST_CONTROLLER_ADVICE}

COMPONENT_ANNOTATIONS = {
    SERVICE, REPOSITORY, COMPONENT, CONFIGURATION, BEAN,
    ENTITY, ENTITY_JK, TABLE, TABLE_JK, RABBIT_LISTENER, SCHEDULED, FEIGN_CLIENT,
}

# Packages to skip (framework / library code)
_SKIP_PREFIXES = (
    "org/springframework/boot/loader/",  # embedded launcher — always skip
    "org/springframework/", "com/google/", "org/apache/", "io/netty/",
    "com/fasterxml/", "org/hibernate/", "ch/qos/", "org/slf4j/",
    "org/bouncycastle/", "io/micrometer/", "com/zaxxer/", "org/flywaydb/",
    "com/rabbitmq/", "org/junit/", "org/mockito/", "software/amazon/",
    "com/azure/", "com/oracle/", "reactor/", "io/r2dbc/",
)


@dataclass
class ScanResult:
    controllers: list[ClassInfo] = field(default_factory=list)
    components: list[ClassInfo] = field(default_factory=list)
    all_classes: list[ClassInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    class_file_versions: list[int] = field(default_factory=list)

    @property
    def min_class_version(self) -> int | None:
        return min(self.class_file_versions) if self.class_file_versions else None

    @property
    def max_class_version(self) -> int | None:
        return max(self.class_file_versions) if self.class_file_versions else None


class AnnotationScanner:
    """Scan .class files in a JAR or directory for Spring/JAX-RS annotations."""

    @classmethod
    def scan_jar(cls, jar_path: Path, app_packages: list[str] | None = None) -> ScanResult:
        result = ScanResult()
        try:
            with zipfile.ZipFile(jar_path, "r") as zf:
                entries = [
                    n for n in zf.namelist()
                    if n.endswith(".class") and not n.endswith("module-info.class")
                    and _should_scan(n, app_packages)
                ]
                for entry in entries:
                    try:
                        cls._process_class(zf.read(entry), result)
                    except Exception as e:
                        result.warnings.append(f"Failed to parse {entry}: {e}")
        except zipfile.BadZipFile:
            result.warnings.append(f"Not a valid ZIP: {jar_path}")
        return result

    @classmethod
    def scan_directory(cls, directory: Path, app_packages: list[str] | None = None) -> ScanResult:
        result = ScanResult()
        for class_file in directory.rglob("*.class"):
            if class_file.name == "module-info.class":
                continue
            rel = class_file.relative_to(directory).as_posix()
            if not _should_scan(rel, app_packages):
                continue
            try:
                cls._process_class(class_file.read_bytes(), result)
            except Exception as e:
                result.warnings.append(f"Failed to parse {rel}: {e}")
        return result

    @classmethod
    def _process_class(cls, data: bytes, result: ScanResult) -> None:
        info = ClassFileParser.parse(data)
        result.class_file_versions.append(info.class_file_version)
        result.all_classes.append(info)
        ann_descs = {a.descriptor for a in info.annotations}
        if ann_descs & CONTROLLER_ANNOTATIONS:
            result.controllers.append(info)
        elif ann_descs & COMPONENT_ANNOTATIONS:
            result.components.append(info)


def _should_scan(entry_path: str, app_packages: list[str] | None) -> bool:
    path = entry_path
    for prefix in (
        "content/lib/BOOT-INF/classes/",
        "BOOT-INF/classes/",
        "WEB-INF/classes/",
        "content/lib/",
    ):
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    if app_packages:
        return any(path.startswith(pkg.replace(".", "/")) for pkg in app_packages)
    return not any(path.startswith(skip) for skip in _SKIP_PREFIXES)
