"""On-demand Java decompilation via CFR and Vineflower.

classfile.py's hand-rolled parser reads structural metadata (classes, methods,
fields, annotations) but never decodes the Code attribute (actual bytecode)
— by design, that's a different problem. Reconstructing real, readable Java
from bytecode is a research-grade problem in its own right (years of
edge-case handling in any real decompiler), so this shells out to two
independent, mature decompilers (both bundled into the image — see
docker/Dockerfile) rather than attempting it in Python, and runs both on
every decompile: CFR and Vineflower use different internal heuristics, so a
class that comes out thin or wrong from one is often fine from the other —
running only one engine means silently trusting whichever one happens to
struggle on a given class.

Nested jar bytes aren't durable: AnalysisJob.run() extracts nested jars into
a temp work_dir and deletes it (NestedJarExtractor.cleanup) once the initial
analysis finishes, so a SubReport row only ever remembers structural facts
(filename, installer_jar, depth), never a live path to the jar's own bytes.
An on-demand decompile run has to re-derive those bytes from the original
uploaded bundle (JarUpload.stored_path, which *is* kept permanently) using
the exact same resolution rules the initial analysis used.
"""
from __future__ import annotations

import asyncio
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

_DEFAULT_CFR_JAR = Path("/opt/certmanager/tools/cfr.jar")
_DEFAULT_VINEFLOWER_JAR = Path("/opt/certmanager/tools/vineflower.jar")

# Tracks in-flight decompiler subprocesses by "{run_id}:{sub_id}:{engine}" —
# mirrors build_manager/ansible_runner.py's _running_jobs, same rationale
# (lets a future cancel/inspect endpoint reach the live process if needed).
_running_decompiles: dict[str, asyncio.subprocess.Process] = {}

# Caps total concurrent decompiler JVMs across every in-flight run, for every
# user/tenant sharing this container — a single run already fans out 2 (CFR +
# Vineflower) per jar; this bounds the container's total, not just one run's,
# so a burst of simultaneous "Decompile All Jars" clicks can't starve it.
# Conservative default (two jars' worth of engine pairs) — revisit against
# real container CPU/memory sizing if usage patterns call for it.
_DECOMPILE_SEMAPHORE = asyncio.Semaphore(4)

ENGINES = ("cfr", "vineflower")


def find_cfr_jar() -> Path | None:
    """Settings override first, then the image's bundled default location."""
    if settings.CFR_JAR_PATH and Path(settings.CFR_JAR_PATH).exists():
        return Path(settings.CFR_JAR_PATH)
    if _DEFAULT_CFR_JAR.exists():
        return _DEFAULT_CFR_JAR
    return None


def find_vineflower_jar() -> Path | None:
    """Settings override first, then the image's bundled default location."""
    if settings.VINEFLOWER_JAR_PATH and Path(settings.VINEFLOWER_JAR_PATH).exists():
        return Path(settings.VINEFLOWER_JAR_PATH)
    if _DEFAULT_VINEFLOWER_JAR.exists():
        return _DEFAULT_VINEFLOWER_JAR
    return None


@dataclass
class DecompileResult:
    success: bool
    timed_out: bool = False
    error: str | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""


def _build_command(engine: str, jar_path: Path, output_dir: Path) -> list[str] | None:
    """Each engine takes its output location differently: CFR wants an
    explicit --outputdir flag, Vineflower takes source/destination as plain
    positional arguments."""
    if engine == "cfr":
        cfr_jar = find_cfr_jar()
        if not cfr_jar:
            return None
        return ["java", "-jar", str(cfr_jar), str(jar_path), "--outputdir", str(output_dir)]
    if engine == "vineflower":
        vf_jar = find_vineflower_jar()
        if not vf_jar:
            return None
        return ["java", "-jar", str(vf_jar), str(jar_path), str(output_dir)]
    raise ValueError(f"Unknown decompiler engine: {engine}")


async def run_decompiler(engine: str, jar_path: Path, output_dir: Path, timeout_seconds: int, run_id: str) -> DecompileResult:
    """Run one decompiler engine ("cfr" or "vineflower") against one jar,
    writing reconstructed .java sources (mirroring the jar's own package
    structure) into output_dir. One JVM invocation covers every class in the
    jar — neither engine needs to be run per-class.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_command(engine, jar_path, output_dir)
    if not cmd:
        return DecompileResult(success=False, error=f"{engine} jar not found ({engine.upper()}_JAR_PATH not set and default bundled path missing)")

    # Held for the JVM's entire lifetime, not just while spawning it — a
    # queued caller waits here rather than piling more concurrent JVMs onto
    # the container than _DECOMPILE_SEMAPHORE allows.
    async with _DECOMPILE_SEMAPHORE:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return DecompileResult(success=False, error=f"Failed to start {engine}: {e}")

        _running_decompiles[run_id] = proc
        try:
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                return DecompileResult(success=False, timed_out=True, error=f"Timed out after {timeout_seconds}s")

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            # Both engines can return non-zero on some partial-failure cases even
            # when they still emitted usable output for most classes — check for
            # actual output rather than trusting the exit code alone.
            has_output = any(output_dir.rglob("*.java"))
            if proc.returncode != 0 and not has_output:
                return DecompileResult(
                    success=False,
                    error=f"{engine} exited {proc.returncode}",
                    stdout_tail=stdout_text[-2000:],
                    stderr_tail=stderr_text[-2000:],
                )
            return DecompileResult(success=True, stdout_tail=stdout_text[-2000:], stderr_tail=stderr_text[-2000:])
        finally:
            _running_decompiles.pop(run_id, None)


async def cancel_run(run_id: str) -> int:
    """Terminate every live subprocess registered for this decompile run —
    at most two at once (CFR + Vineflower for whichever jar is currently
    in flight; "decompile all" processes jars one at a time, so there's
    never more than one jar's pair running concurrently for a given run).
    Same terminate-then-kill-on-timeout fallback run_decompiler itself uses
    when a run hits its own timeout. Returns how many processes were
    actually live and terminated (0 if the run had already finished)."""
    prefix = f"{run_id}:"
    matching = [key for key in _running_decompiles if key.startswith(prefix)]
    count = 0
    for key in matching:
        proc = _running_decompiles.get(key)
        if not proc:
            continue
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        count += 1
    return count


def _strip_fat_jar_wrapper(rel: Path) -> Path:
    """CFR auto-detects a Spring Boot / WAR fat-jar layout and normalizes its
    output to bare package paths (com/foo/Bar.java). Vineflower doesn't do
    this for a jar-of-jars (an installer jar whose content/lib/*.jar is
    itself a fat jar) — it preserves the whole literal path, wrapper
    directories and all (content/lib/BOOT-INF/classes/com/foo/Bar.java).
    Left alone, the same class gets a different class_name per engine,
    which breaks both the tree's cross-engine dedup and the per-class
    engine toggle (a lookup by CFR's class_name would never find
    Vineflower's row for the same class). Strip up to and including the
    rightmost BOOT-INF/classes or WEB-INF/classes marker so every engine
    agrees on the same class_name for the same class; a no-op for CFR,
    whose output never contains these markers in the first place."""
    parts = rel.parts
    strip_after = None
    for i in range(len(parts) - 1):
        if parts[i] in ("BOOT-INF", "WEB-INF") and parts[i + 1] == "classes":
            strip_after = i + 2
    return Path(*parts[strip_after:]) if strip_after is not None else rel


def collect_decompiled_sources(output_dir: Path) -> list[tuple[str, str, str, str]]:
    """Walk a decompiler's output tree and return (class_name, package_name,
    simple_name, source) tuples — one per .java file, package path taken
    from the file's directory structure (matches the engine's own layout,
    which mirrors the original jar's package tree), normalized so every
    engine produces the same class_name for the same class."""
    results: list[tuple[str, str, str, str]] = []
    for java_file in output_dir.rglob("*.java"):
        rel = _strip_fat_jar_wrapper(java_file.relative_to(output_dir))
        simple_name = java_file.stem
        package_parts = rel.parts[:-1]
        package_name = ".".join(package_parts)
        class_name = "/".join(package_parts + (simple_name,))
        try:
            source = java_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        results.append((class_name, package_name, simple_name, source))
    return results


def resolve_jar_path_for_sub_report(upload_stored_path: Path, sub_report, work_dir: Path) -> Path | None:
    """Re-derive the actual jar bytes for a SubReport, since they aren't kept
    around after the initial analysis. Mirrors AnalysisJob's own extraction
    logic exactly (see job.py's _run_sync/_run_zip_bundle/_analyse_installer_entry)
    so the jar decompiled here is the same one that was originally analysed."""
    if sub_report.depth == 0:
        # Top-level single jar/war — the stored upload *is* the jar, no
        # extraction step ever happened for it.
        return upload_stored_path

    if upload_stored_path.suffix.lower() == ".zip":
        # Matches AnalysisJob._run_zip_bundle: each contained .jar/.war is
        # written to disk directly, no further installer/fat-jar unwrapping.
        with zipfile.ZipFile(upload_stored_path) as zf:
            for name in zf.namelist():
                if name.lower().endswith((".jar", ".war")) and Path(name).name == sub_report.filename:
                    dest = work_dir / Path(name).name
                    dest.write_bytes(zf.read(name))
                    return dest
        return None

    # "Jar of jars" — re-run the same NestedJarExtractor walk and match by
    # filename + depth (both persisted on SubReport), then apply the same
    # fat_jar_path-or-extracted_path rule AnalysisJob._analyse_installer_entry
    # uses, so an installer wrapper resolves to its real application jar.
    from app.services.jar_analyser.extractor import NestedJarExtractor
    entries = NestedJarExtractor.extract(upload_stored_path, work_dir)
    for entry in entries:
        if entry.filename == sub_report.filename and entry.depth == sub_report.depth:
            return entry.fat_jar_path or entry.extracted_path
    return None
