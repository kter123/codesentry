"""代码图抽取层：统一的节点/边模型与语言注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

NODE_KINDS = {
    "repo", "package", "file", "class", "function", "method",
    "route", "endpoint", "source", "sink", "module", "external", "dependency",
}
EDGE_KINDS = {
    "contains", "imports", "calls", "inherits", "implements",
    "routes_to", "exposes", "reads", "writes", "taints_to", "dataflow", "depends_on",
}


@dataclass
class CodeNode:
    key: str
    kind: str
    name: str
    path: str = ""
    start_line: int = 0
    end_line: int = 0
    qualified_name: str = ""
    lang: str = ""
    attrs: dict = field(default_factory=dict)


@dataclass
class CodeEdge:
    src_key: str
    dst_key: str
    kind: str
    provenance: str = "tree_sitter"
    confidence: float = 1.0
    attrs: dict = field(default_factory=dict)


@dataclass
class ExtractResult:
    nodes: list[CodeNode] = field(default_factory=list)
    edges: list[CodeEdge] = field(default_factory=list)
    endpoints: list[dict] = field(default_factory=list)
    unresolved_calls: int = 0

    def add_node(self, node: CodeNode) -> CodeNode:
        self.nodes.append(node)
        return node

    def add_edge(self, edge: CodeEdge) -> None:
        self.edges.append(edge)

    def merge(self, other: ExtractResult) -> None:
        self.nodes.extend(other.nodes)
        self.edges.extend(other.edges)
        self.endpoints.extend(other.endpoints)
        self.unresolved_calls += other.unresolved_calls


class Extractor(Protocol):
    lang: str

    def extract(self, path: str, source: str) -> ExtractResult: ...


_REGISTRY: dict[str, Extractor] = {}


def register(extractor: Extractor) -> Extractor:
    _REGISTRY[extractor.lang] = extractor
    return extractor


def get_extractor(lang: str) -> Extractor | None:
    return _REGISTRY.get(lang)


def file_key(path: str) -> str:
    return f"file:{path}"


def node_key(kind: str, path: str, qualname: str) -> str:
    return f"{kind}:{path}#{qualname}"


def endpoint_key(method: str, route: str) -> str:
    return f"endpoint:{(method or 'ANY').upper()}:{route}"


def normalize_route(route: str) -> str:
    route = (route or "/").strip()
    if not route.startswith("/"):
        route = "/" + route
    while "//" in route:
        route = route.replace("//", "/")
    return route.rstrip("/") or "/"


def text_of(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
