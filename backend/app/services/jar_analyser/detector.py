"""JAR type detection — classifies any JAR/WAR without executing it."""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class JarType(str, Enum):
    JAR_OF_JARS         = "jar_of_jars"         # Installer package with nested installer JARs
    SPRING_BOOT_FAT     = "spring_boot_fat"     # Spring Boot fat JAR (BOOT-INF/lib)
    SPRING_BOOT_WAR     = "spring_boot_war"     # Spring Boot WAR (WEB-INF/lib)
    FRONTEND_INSTALLER  = "frontend_installer"  # Node.js/UI installer (content/dist, no fat JAR)
    NGINX_INSTALLER     = "nginx_installer"     # Nginx config-only installer (bundle/etc/nginx)
    MONITORING_INSTALLER = "monitoring_installer" # Grafana/Prometheus config-only installer
    EXECUTABLE_JAR      = "executable_jar"      # Executable JAR, non-Spring main class
    WAR                 = "war"                 # Standard WAR file
    MULTI_RELEASE       = "multi_release"       # Multi-release JAR (META-INF/versions)
    LIBRARY             = "library"             # Plain library JAR


_SPRING_JAR_LAUNCHER = "org.springframework.boot.loader.JarLauncher"
_SPRING_WAR_LAUNCHER = "org.springframework.boot.loader.WarLauncher"


@dataclass
class DetectionResult:
    jar_type: JarType
    confidence: float                        # 0.0 – 1.0
    main_class: str | None = None
    start_class: str | None = None
    spring_boot_version: str | None = None
    has_boot_inf: bool = False
    has_web_inf: bool = False
    has_multi_release: bool = False
    nested_jar_names: list[str] = field(default_factory=list)   # root-level *.jar entries
    installer_jar_names: list[str] = field(default_factory=list) # nested JARs with part.yml
    warnings: list[str] = field(default_factory=list)


class JarTypeDetector:
    """Classify a JAR/WAR file without executing it.

    Usage::

        result = JarTypeDetector.detect(path)
        print(result.jar_type, result.confidence)
    """

    @staticmethod
    def detect(path: str | Path) -> DetectionResult:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        try:
            with zipfile.ZipFile(path, "r") as zf:
                return JarTypeDetector._classify(zf)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"Not a valid ZIP/JAR file: {path}") from exc

    @staticmethod
    def _classify(zf: zipfile.ZipFile) -> DetectionResult:
        names = set(zf.namelist())

        # --- Manifest ---
        manifest = JarTypeDetector._read_manifest(zf)
        main_class = manifest.get("Main-Class")
        start_class = manifest.get("Start-Class")
        sb_version = manifest.get("Spring-Boot-Version")
        multi_release = manifest.get("Multi-Release", "").lower() == "true"

        # --- Structural flags ---
        has_boot_inf = any(n.startswith("BOOT-INF/") for n in names)
        has_web_inf  = any(n.startswith("WEB-INF/")  for n in names)
        has_multi_rel = any(n.startswith("META-INF/versions/") for n in names) or multi_release

        # Root-level *.jar entries (direct children only)
        root_jars = [
            n for n in names
            if n.endswith(".jar") and "/" not in n.rstrip("/")
        ]

        # Installer JARs: nested JARs that contain a part.yml
        installer_jars = []
        if root_jars:
            installer_jars = JarTypeDetector._find_installer_jars(zf, root_jars)

        # --- Classification ---

        # 1. JAR-of-JARs installer (root-level JARs with part.yml metadata)
        if installer_jars:
            confidence = 1.0 if len(installer_jars) == len(root_jars) else 0.75
            return DetectionResult(
                jar_type=JarType.JAR_OF_JARS,
                confidence=confidence,
                main_class=main_class,
                start_class=start_class,
                spring_boot_version=sb_version,
                has_boot_inf=has_boot_inf,
                has_web_inf=has_web_inf,
                has_multi_release=has_multi_rel,
                nested_jar_names=root_jars,
                installer_jar_names=installer_jars,
            )

        # 2. Frontend/UI installer — part.yml + content/dist or node_modules, no fat JAR
        has_part_yml = "part.yml" in names
        has_content_dist = any(n.startswith("content/dist/") for n in names)
        has_node_modules = any(n.startswith("content/node_modules/") for n in names)
        has_content_lib_jar = any(n.startswith("content/lib/") and n.endswith(".jar") for n in names)
        if has_part_yml and (has_content_dist or has_node_modules) and not has_content_lib_jar:
            return DetectionResult(
                jar_type=JarType.FRONTEND_INSTALLER,
                confidence=0.95,
                main_class=main_class,
            )

        # 3. Nginx config-only installer — bundle/etc/nginx, no content/
        has_nginx = any("nginx" in n.lower() for n in names)
        has_content = any(n.startswith("content/") for n in names)
        if has_part_yml and has_nginx and not has_content:
            return DetectionResult(
                jar_type=JarType.NGINX_INSTALLER,
                confidence=0.95,
                main_class=main_class,
            )

        # 4. Monitoring config-only installer — grafana/prometheus bundle, no content/
        has_grafana = any("grafana" in n.lower() for n in names)
        has_prometheus = any("prometheus" in n.lower() for n in names)
        if has_part_yml and (has_grafana or has_prometheus) and not has_content:
            return DetectionResult(
                jar_type=JarType.MONITORING_INSTALLER,
                confidence=0.95,
                main_class=main_class,
            )

        # 5. JAR-of-JARs without part.yml (generic nested-JAR package)
        if root_jars and not has_boot_inf:
            return DetectionResult(
                jar_type=JarType.JAR_OF_JARS,
                confidence=0.65,
                main_class=main_class,
                start_class=start_class,
                spring_boot_version=sb_version,
                nested_jar_names=root_jars,
                warnings=["Root-level JARs found but no part.yml — may be a custom installer format"],
            )

        # 3. Spring Boot fat JAR
        if main_class == _SPRING_JAR_LAUNCHER or (has_boot_inf and start_class):
            confidence = 1.0 if (main_class == _SPRING_JAR_LAUNCHER and start_class and has_boot_inf) else 0.85
            return DetectionResult(
                jar_type=JarType.SPRING_BOOT_FAT,
                confidence=confidence,
                main_class=main_class,
                start_class=start_class,
                spring_boot_version=sb_version,
                has_boot_inf=True,
                has_multi_release=has_multi_rel,
            )

        # 4. Spring Boot WAR
        if main_class == _SPRING_WAR_LAUNCHER:
            return DetectionResult(
                jar_type=JarType.SPRING_BOOT_WAR,
                confidence=1.0,
                main_class=main_class,
                start_class=start_class,
                spring_boot_version=sb_version,
                has_web_inf=True,
                has_multi_release=has_multi_rel,
            )

        # 5. Standard WAR
        if has_web_inf:
            return DetectionResult(
                jar_type=JarType.WAR,
                confidence=0.95,
                main_class=main_class,
                has_web_inf=True,
            )

        # 6. Multi-release JAR
        if has_multi_rel:
            jar_type = JarType.EXECUTABLE_JAR if main_class else JarType.MULTI_RELEASE
            return DetectionResult(
                jar_type=jar_type,
                confidence=0.9,
                main_class=main_class,
                has_multi_release=True,
            )

        # 7. Executable JAR (non-Spring main class)
        if main_class:
            return DetectionResult(
                jar_type=JarType.EXECUTABLE_JAR,
                confidence=0.9,
                main_class=main_class,
            )

        # 8. Plain library JAR
        return DetectionResult(
            jar_type=JarType.LIBRARY,
            confidence=0.8,
        )

    @staticmethod
    def _read_manifest(zf: zipfile.ZipFile) -> dict[str, str]:
        """Parse META-INF/MANIFEST.MF into a key→value dict."""
        try:
            raw = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
        except KeyError:
            return {}
        result: dict[str, str] = {}
        current_key: str | None = None
        current_val: list[str] = []
        for line in raw.splitlines():
            if not line:
                if current_key:
                    result[current_key] = "".join(current_val)
                current_key = None
                current_val = []
            elif line.startswith(" ") and current_key:
                # Continuation line
                current_val.append(line[1:])
            elif ":" in line:
                if current_key:
                    result[current_key] = "".join(current_val)
                key, _, val = line.partition(":")
                current_key = key.strip()
                current_val = [val.strip()]
        if current_key:
            result[current_key] = "".join(current_val)
        return result

    @staticmethod
    def _find_installer_jars(zf: zipfile.ZipFile, root_jars: list[str]) -> list[str]:
        """Return the subset of root_jars whose contents include a part.yml."""
        installer_jars = []
        for jar_name in root_jars:
            try:
                nested_bytes = zf.read(jar_name)
                import io
                with zipfile.ZipFile(io.BytesIO(nested_bytes), "r") as nested_zf:
                    if "part.yml" in nested_zf.namelist():
                        installer_jars.append(jar_name)
            except Exception:
                pass
        return installer_jars
