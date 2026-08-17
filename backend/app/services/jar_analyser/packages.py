"""Package structure analyser.

Builds a package tree from a list of ClassInfo records and detects
standard Spring application architectural layers from package names.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .classfile import ClassInfo

# ---------------------------------------------------------------------------
# Layer detection patterns
# ---------------------------------------------------------------------------

_LAYER_PATTERNS: list[tuple[str, list[str]]] = [
    ("controller", ["controller", "api", "rest", "web", "resource"]),
    ("service",    ["service", "business", "logic", "usecase"]),
    ("repository", ["repository", "dao", "persistence", "data"]),
    ("model",      ["model", "domain", "entity", "dto", "vo"]),
    ("config",     ["config", "configuration", "autoconfigure"]),
    ("event",      ["event", "messaging", "listener", "publisher"]),
    ("security",   ["security", "auth", "authentication", "authorization"]),
    ("util",       ["util", "utils", "helper", "common"]),
]


def _detect_layer(package: str) -> str:
    last = package.rsplit(".", 1)[-1].lower()
    for layer, patterns in _LAYER_PATTERNS:
        if any(p in last for p in patterns):
            return layer
    return "other"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PackageNode:
    package: str
    class_count: int = 0
    subpackage_count: int = 0
    dominant_annotation: str | None = None
    layer: str = "other"
    children: dict[str, "PackageNode"] = field(default_factory=dict, repr=False)


@dataclass
class LayerSummary:
    layer: str
    package: str
    class_count: int


@dataclass
class PackageStructure:
    root_packages: list[str]
    nodes: dict[str, PackageNode]          # package -> node
    layer_summary: list[LayerSummary]
    class_count: int
    package_count: int


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------

class PackageAnalyser:
    """Analyse package structure from a list of ClassInfo records."""

    @classmethod
    def analyse(cls, classes: list[ClassInfo]) -> PackageStructure:
        # Count classes per package and collect annotations
        pkg_classes: dict[str, list[ClassInfo]] = defaultdict(list)
        for ci in classes:
            pkg = ci.package_name
            if pkg:
                pkg_classes[pkg].append(ci)

        nodes: dict[str, PackageNode] = {}
        for pkg, cls_list in pkg_classes.items():
            dominant = _dominant_annotation(cls_list)
            node = PackageNode(
                package=pkg,
                class_count=len(cls_list),
                dominant_annotation=dominant,
                layer=_detect_layer(pkg),
            )
            nodes[pkg] = node

        # Count subpackages
        for pkg in list(nodes.keys()):
            parent = pkg.rsplit(".", 1)[0] if "." in pkg else None
            if parent and parent in nodes:
                nodes[parent].subpackage_count += 1

        # Root packages (no parent in nodes)
        root_packages = sorted({
            pkg for pkg in nodes
            if not any(pkg.startswith(other + ".") for other in nodes if other != pkg)
        })

        layer_summary = [
            LayerSummary(layer=n.layer, package=n.package, class_count=n.class_count)
            for n in sorted(nodes.values(), key=lambda x: (-x.class_count, x.package))
            if n.layer != "other" or n.class_count > 0
        ]

        return PackageStructure(
            root_packages=root_packages,
            nodes=nodes,
            layer_summary=layer_summary,
            class_count=sum(n.class_count for n in nodes.values()),
            package_count=len(nodes),
        )


def _dominant_annotation(classes: list[ClassInfo]) -> str | None:
    counts: dict[str, int] = defaultdict(int)
    for ci in classes:
        for ann in ci.annotations:
            counts[ann.simple_name] += 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])
