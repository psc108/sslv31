"""Parses a raw pasted Java/JVM log or stack-trace blob into a structured
chain of exceptions (root + "Caused by:"/"Suppressed:" links), each with its
own frames (class/method/file/line).

Grounded against a real example the user pasted from
/var/log/ecs/fulfillment/application.log - notably, that example had no
visible "ExceptionClass: message" header line before its "at ..." frames
(likely trimmed by whatever grep produced the paste), so this parser must
degrade gracefully to a headerless block of frames rather than requiring a
header to find anything at all. It also has to ignore ordinary log noise
(timestamp/level/logger-name lines) sitting between or around stack frames,
since a real pasted blob is rarely a clean, isolated trace.

Best-effort text parsing, not a real log/stacktrace grammar - same caveat
class as outbound_call_analysis.py. Frame lines also commonly carry a
Logback/Log4j2 "~[artifact:version]" classpath-origin suffix after the
closing paren; the frame regex doesn't require end-of-line so this is
simply ignored rather than causing a match failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# The optional `module/` (or `module//`, for an unnamed module) prefix is
# JPMS's own frame format, standard in every JDK 9+ trace for JDK-internal
# frames (e.g. "java.base/java.lang.reflect.Method.invoke(...)") - dropped
# rather than captured, since it names a module, not a class.
_FRAME_RE = re.compile(r"^\s*at\s+(?:[\w.]+/{1,2})?([\w.$]+)\.([\w$<>]+)\(([^)]*)\)")
_MORE_RE = re.compile(r"^\s*\.\.\.\s*\d+\s*more\s*$")
_CAUSED_BY_RE = re.compile(r"^\s*Caused by:\s*(.+)$")
_SUPPRESSED_RE = re.compile(r"^\s*Suppressed:\s*(.+)$")
_HEADER_RE = re.compile(r"^([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)(?::\s(.*))?$")
_THREAD_HEADER_RE = re.compile("Exception in thread [\"'].*?[\"']\\s+(.+)")
_LOC_RE = re.compile(r"^([^:]+):(\d+)$")

# Package prefixes that are JDK internals, framework plumbing, or generated
# proxy/reflection machinery rather than a service's own business logic —
# same category of "class scope" duplicated-per-file heuristic dto_scanner.py's
# own _SKIP_RECURSE_PREFIXES and events.py's _scan_entity_classes use, broadened
# here with the extra infrastructure (Tomcat/Netty/CGLIB proxies/reflection)
# that actually shows up in a *runtime* stack trace but never in bytecode
# scanned ahead of time. Used only to dim noise in the UI, not to drop frames
# outright — a real bug can technically live inside a framework class.
_FRAMEWORK_PREFIXES = (
    "java.", "javax.", "jakarta.", "jdk.", "sun.", "com.sun.",
    "org.springframework.", "org.hibernate.", "com.fasterxml.", "com.google.",
    "org.apache.", "io.netty.", "io.undertow.", "reactor.", "rx.",
    "org.eclipse.jetty.", "org.glassfish.", "com.zaxxer.hikari.",
    "org.jboss.", "kotlin.", "scala.", "net.sf.cglib.", "org.aspectj.",
    "com.rabbitmq.", "feign.", "okhttp3.", "okio.",
)


@dataclass
class StackFrame:
    class_name: str  # dot-separated fully-qualified, e.g. com.dxc.ecs.fulfillment.service.ServiceDesignService
    method_name: str
    file_name: str | None
    line_number: int | None
    is_native: bool = False

    @property
    def is_application_frame(self) -> bool:
        """False for JDK/framework/proxy plumbing (see _FRAMEWORK_PREFIXES) —
        a heuristic to let the UI visually separate "your code" from the
        noise most real traces are mostly made of, not proof either way."""
        return not self.class_name.startswith(_FRAMEWORK_PREFIXES)


@dataclass
class ExceptionBlock:
    kind: str  # "root" | "caused_by" | "suppressed"
    exception_class: str | None  # None if only frames were found, no header line
    message: str | None
    frames: list[StackFrame] = field(default_factory=list)
    # Set by _flag_root_causes() once the full chain is known - see its own
    # docstring for the "deepest link, not the outermost" reasoning.
    is_likely_root_cause: bool = False


def _parse_frame(m: re.Match) -> StackFrame:
    class_name, method_name, loc = m.group(1), m.group(2), m.group(3)
    if loc in ("Native Method",):
        return StackFrame(class_name, method_name, None, None, is_native=True)
    if loc == "Unknown Source":
        return StackFrame(class_name, method_name, None, None)
    loc_m = _LOC_RE.match(loc)
    if loc_m:
        return StackFrame(class_name, method_name, loc_m.group(1), int(loc_m.group(2)))
    return StackFrame(class_name, method_name, loc or None, None)


def _split_header(text: str) -> tuple[str | None, str | None]:
    hm = _HEADER_RE.fullmatch(text.strip())
    if hm:
        return hm.group(1), hm.group(2)
    return text.strip() or None, None


def extract_stack_traces(text: str) -> list[ExceptionBlock]:
    """Returns one ExceptionBlock per exception found in the text, in the
    order they appear (root first, then any Caused by:/Suppressed: chain
    links) - callers that only care about "what exceptions are present"
    can just read .exception_class off each block; callers that want
    "where in the code did this happen" use .frames."""
    blocks: list[ExceptionBlock] = []
    current: ExceptionBlock | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        m = _FRAME_RE.match(line)
        if m:
            if current is None:
                current = ExceptionBlock(kind="root", exception_class=None, message=None)
                blocks.append(current)
            current.frames.append(_parse_frame(m))
            continue

        if _MORE_RE.match(line):
            continue

        cb = _CAUSED_BY_RE.match(line)
        if cb:
            cls, msg = _split_header(cb.group(1))
            current = ExceptionBlock(kind="caused_by", exception_class=cls, message=msg)
            blocks.append(current)
            continue

        sp = _SUPPRESSED_RE.match(line)
        if sp:
            cls, msg = _split_header(sp.group(1))
            current = ExceptionBlock(kind="suppressed", exception_class=cls, message=msg)
            blocks.append(current)
            continue

        th = _THREAD_HEADER_RE.match(line.strip())
        if th:
            cls, msg = _split_header(th.group(1))
            current = ExceptionBlock(kind="root", exception_class=cls, message=msg)
            blocks.append(current)
            continue

        hm = _HEADER_RE.fullmatch(line.strip())
        if hm:
            current = ExceptionBlock(kind="root", exception_class=hm.group(1), message=hm.group(2))
            blocks.append(current)
            continue

        # Ordinary log noise (timestamp/level/logger-name lines, plain
        # messages) - not part of the trace structure, ignored.

    _flag_root_causes(blocks)
    return blocks


def _flag_root_causes(blocks: list[ExceptionBlock]) -> None:
    """Marks the deepest link of each independent incident's causal chain -
    the last root/caused_by block before the next "root" starts a new,
    unrelated incident (a single paste can contain several) - as the likely
    actual cause. Java's convention is to wrap and rethrow as an exception
    propagates up the call stack, so the outermost/first-seen exception is
    usually just packaging around the real one, not the cause itself.
    Suppressed exceptions are a sibling branch (e.g. a try-with-resources
    close() failure alongside the real exception, not a link in its causal
    chain), so they're never flagged even when they're a chain's last block."""
    run: list[ExceptionBlock] = []

    def flag_run() -> None:
        for b in reversed(run):
            if b.kind in ("root", "caused_by"):
                b.is_likely_root_cause = True
                return

    for block in blocks:
        if block.kind == "root":
            flag_run()
            run = [block]
        else:
            run.append(block)
    flag_run()
