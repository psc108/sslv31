"""Outbound call response-shape / error-handling analysis — the follow-up
to outbound_integrations.py, closing the gap that module's docstring
explicitly flags: knowing a class calls out to an external system doesn't
say what response it expects back or how it handles errors, and answering
that needs to read inside a method body — the one thing this tool's
structural bytecode parser (classfile.py) deliberately never does.

The practical way to get there without building a real bytecode-instruction
decoder: scan already-decompiled Java *source text* (CFR/Vineflower output,
see decompiler.py) for known outbound-call patterns with plain regexes.
This is why the feature hangs off Decompilation (Section 36) rather than
running automatically on every analysis like outbound_integrations.py does
— it only exists for jars someone has actually chosen to decompile, and it
runs as a free-ish post-processing pass over source text already in hand
(no extra JVM invocation), triggered from _run_decompile() right after a
class's source is collected.

Patterns detected — grounded in this tool's own real fixture jar, not
assumed generically, since a first design pass here guessed Spring's
RestTemplate/WebClient and turned out to be wrong for this codebase, which
actually uses JAX-RS's jakarta.ws.rs.client.WebTarget throughout (e.g.
CatalogClient.getRateCard(): `this.rateCardWebTarget.path(...).request(...)
.get()`, then `response.readEntity(RateCardDto.class)`, with inline
`response.getStatus() == Response.Status.NOT_FOUND.getStatusCode()` branches
rather than try/catch). All three shapes are matched — JAX-RS Client,
RestTemplate, WebClient — since different services in the same bundle (or
a jar this tool has never seen) may use any of them.

Everything here is a best-effort text scan, not a real Java parser:
- "Enclosing method" is found by scanning backward for the nearest method
  signature and forward-counting braces from its own opening brace — this
  can misattribute boundaries around string/comment literals containing
  braces, or unusually formatted decompiler output. Good enough to
  correlate a call site with its own error handling; not a guarantee.
- A `catch`/`throw new`/status-check found "in the enclosing method" isn't
  proof it's handling *this particular* call, just the most useful signal
  obtainable without real control-flow analysis, for methods (the common
  case observed here) that make one outbound call per method.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_JAXRS_TERMINAL_RE = re.compile(r"\.request\([^)]*\)\s*\.\s*(get|post|put|delete|head|options)\s*\(", re.DOTALL)
_RESTTEMPLATE_RE = re.compile(r"\b\w*[Rr]est[Tt]emplate\w*\s*\.\s*(exchange|getForObject|getForEntity|postForObject|postForEntity)\s*\(", re.DOTALL)
_WEBCLIENT_TERMINAL_RE = re.compile(r"\.\s*(bodyToMono|bodyToFlux)\s*\(")

_READ_ENTITY_RE = re.compile(r"\.readEntity\(\s*([\w.]+)\.class\s*\)")
_CLASS_LITERAL_RE = re.compile(r"\b([\w.]+)\.class\b")
_PARAM_TYPE_REF_RE = re.compile(r"ParameterizedTypeReference<\s*([\w<>,.\s\[\]]+?)\s*>\s*\(\)\s*\{\s*\}")
_GENERIC_TYPE_RE = re.compile(r"GenericType<\s*([\w<>,.\s\[\]]+?)\s*>\s*\(\)\s*\{\s*\}")
_CATCH_RE = re.compile(r"catch\s*\(\s*([\w.]+(?:\s*\|\s*[\w.]+)*)\s+\w+\s*\)")
_THROW_NEW_RE = re.compile(r"throw\s+new\s+([\w.]+)\s*\(")
_STATUS_CHECK_RE = re.compile(r"getStatus(?:Code)?\(\)\s*(==|!=)\s*(?:Response\.Status\.(\w+)\.getStatusCode\(\)|(\d{3}))")

_METHOD_SIG_RE = re.compile(
    r"(?:public|private|protected|static|final|synchronized|\s)+[\w<>\[\],.\s]+?\s(\w+)\s*\([^)]*\)\s*"
    r"(?:throws\s+[\w.,\s]+)?\s*\{"
)


@dataclass
class OutboundCallSite:
    call_type: str  # "jaxrs_client" | "resttemplate" | "webclient"
    method_name: str | None
    call_snippet: str
    response_type: str | None
    caught_exceptions: list[str] = field(default_factory=list)
    thrown_exceptions: list[str] = field(default_factory=list)
    status_checks: list[str] = field(default_factory=list)


def _find_enclosing_method(source: str, pos: int) -> tuple[str | None, str]:
    """Nearest method signature before `pos`, then its matching closing
    brace by depth-counting — see module docstring for the caveats."""
    last_match = None
    for m in _METHOD_SIG_RE.finditer(source, 0, pos):
        last_match = m
    if not last_match:
        window_start = max(0, pos - 500)
        return None, source[window_start:pos + 500]

    brace_start = last_match.end() - 1
    depth = 0
    for i in range(brace_start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return last_match.group(1), source[last_match.start():i + 1]
    return last_match.group(1), source[last_match.start():]


def extract_outbound_call_sites(source: str) -> list[OutboundCallSite]:
    sites: list[OutboundCallSite] = []
    for pattern, call_type in (
        (_JAXRS_TERMINAL_RE, "jaxrs_client"),
        (_RESTTEMPLATE_RE, "resttemplate"),
        (_WEBCLIENT_TERMINAL_RE, "webclient"),
    ):
        for m in pattern.finditer(source):
            method_name, method_text = _find_enclosing_method(source, m.start())

            response_type = None
            rt_m = _READ_ENTITY_RE.search(method_text) or _PARAM_TYPE_REF_RE.search(method_text) or _GENERIC_TYPE_RE.search(method_text)
            if rt_m:
                response_type = rt_m.group(1)
            else:
                # A bare trailing X.class argument on the call itself
                # (RestTemplate/WebClient's own convention) — searched near
                # the call site, not the whole method, to avoid picking up
                # an unrelated cast elsewhere in a larger method.
                near = source[m.start():m.start() + 400]
                cls_m = _CLASS_LITERAL_RE.search(near)
                if cls_m:
                    response_type = cls_m.group(1)

            caught = list(dict.fromkeys(
                exc.strip() for grp in _CATCH_RE.findall(method_text) for exc in grp.split("|")
            ))
            thrown = list(dict.fromkeys(_THROW_NEW_RE.findall(method_text)))
            status_checks = list(dict.fromkeys(
                f"{op} {name or code}" for op, name, code in _STATUS_CHECK_RE.findall(method_text)
            ))

            snippet = source[max(0, m.start() - 60):m.start() + 120].strip()
            sites.append(OutboundCallSite(
                call_type=call_type, method_name=method_name, call_snippet=snippet,
                response_type=response_type, caught_exceptions=caught,
                thrown_exceptions=thrown, status_checks=status_checks,
            ))
    return sites
