"""Java 抽取器：类/方法、导入、调用、Spring 路由与权限判定。"""

from __future__ import annotations

import re

import tree_sitter_java
from tree_sitter import Language, Parser

from codesentry.rag.extractors.base import (
    CodeEdge,
    CodeNode,
    ExtractResult,
    endpoint_key,
    file_key,
    node_key,
    normalize_route,
    text_of,
)

_LANG = Language(tree_sitter_java.language())

_ROUTE_ANN = re.compile(
    r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_ROUTE_ANN_BARE = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\b", re.IGNORECASE)
_REQUEST_METHOD = re.compile(r"RequestMethod\.([A-Z]+)", re.IGNORECASE)

_SINK_NAMES = {
    "exec", "start", "execute", "executeQuery", "executeUpdate", "executeBatch",
    "readObject", "eval", "openConnection", "getForObject", "getForEntity",
    "postForObject", "postForEntity", "exchange", "write", "transferTo",
    "writeString", "writeBytes", "newOutputStream", "getInputStream",
}
_SOURCE_ANNOTATIONS = {
    "RequestParam", "PathVariable", "RequestBody", "RequestHeader",
    "CookieValue", "ModelAttribute", "RequestPart",
}
_SOURCE_TYPES = {"HttpServletRequest", "MultipartFile", "Part"}


class JavaExtractor:
    lang = "java"

    def extract(self, path: str, source: str) -> ExtractResult:
        raw = source.encode("utf-8")
        tree = Parser(_LANG).parse(raw)
        result = ExtractResult()
        file_node = CodeNode(
            key=file_key(path), kind="file", name=path.rsplit("/", 1)[-1],
            path=path, start_line=1, end_line=max(1, source.count("\n") + 1), lang="java",
            attrs={"imports": []},
        )
        result.add_node(file_node)
        package = self._package(tree.root_node, raw)
        if package:
            pkg_key = f"package:{package}"
            result.add_node(CodeNode(key=pkg_key, kind="package", name=package, lang="java"))
            result.add_edge(CodeEdge(pkg_key, file_node.key, "contains"))
        self._walk(tree.root_node, raw, path, result, file_node, package, [])
        for module in sorted(set(file_node.attrs.get("imports") or [])):
            result.add_edge(CodeEdge(file_node.key, f"module:{module}", "imports"))
        return result

    def _walk(self, node, raw, path, result, parent, package, class_stack):
        for child in node.children:
            t = child.type
            if t == "import_declaration":
                text = text_of(raw, child).replace("import", "", 1).strip().rstrip(";")
                if text and not text.startswith("static"):
                    parent.attrs.setdefault("imports", []).append(text)
            elif t in ("class_declaration", "interface_declaration", "enum_declaration",
                       "record_declaration"):
                self._class(child, raw, path, result, parent, package, class_stack)
            elif t in ("method_declaration", "constructor_declaration"):
                self._method(child, raw, path, result, parent, class_stack)
            else:
                self._walk(child, raw, path, result, parent, package, class_stack)

    def _class(self, node, raw, path, result, parent, package, class_stack):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = text_of(raw, name_node)
        qual = class_stack[-1][0] + "." + name if class_stack else ".".join(
            [p for p in (package, name) if p]
        )
        key = node_key("class", path, qual)
        annotations, _ = self._annotations(node, raw)
        prefix = self._class_route_prefix(annotations)
        permission, evidence = self._permission(annotations, raw, node, inherited=None)
        result.add_node(CodeNode(
            key=key, kind="class", name=name, path=path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            qualified_name=qual, lang="java",
            attrs={"route_prefix": prefix, "permission": permission, "evidence": evidence},
        ))
        result.add_edge(CodeEdge(parent.key, key, "contains"))
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk(
                body, raw, path, result, _Ref(key), package,
                [*class_stack, (qual, prefix, permission)],
            )

    def _method(self, node, raw, path, result, parent, class_stack):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = text_of(raw, name_node)
        class_name = class_stack[-1][0].rsplit(".", 1)[-1] if class_stack else ""
        qual = ".".join([c[0] for c in class_stack] + [name])
        key = node_key("function", path, qual)
        annotations, _ = self._annotations(node, raw)
        method_perm, method_ev = self._permission(annotations, raw, node, inherited=None)
        class_perm = class_stack[-1][2] if class_stack else "内部接口"
        permission = method_perm if method_perm != "内部接口" else class_perm
        evidence = method_ev or (class_stack[-1][2] if class_stack and class_stack[-1][2] else "")
        sources = self._sources(node, raw)
        result.add_node(CodeNode(
            key=key, kind="method", name=name, path=path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            qualified_name=qual, lang="java",
            attrs={
                "calls": self._calls(node, raw),
                "sources": sources,
                "sinks": self._sinks(node, raw),
                "permission": permission,
                "evidence": evidence,
                "class": class_name,
            },
        ))
        result.add_edge(CodeEdge(parent.key, key, "contains"))
        self._routes(
            annotations, raw, path, result, key, permission, evidence,
            class_stack[-1][1] if class_stack else "", node.start_point[0] + 1,
        )

    def _routes(self, annotations, raw, path, result, func_key, permission, evidence, prefix, line):
        texts = [a if isinstance(a, str) else text_of(raw, a) for a in annotations]
        for text in texts:
            match = _ROUTE_ANN.search(text)
            if not match:
                if not _ROUTE_ANN_BARE.search(text):
                    continue
                ann = _ROUTE_ANN_BARE.search(text)
                kind = ann.group(1).upper() if ann else "REQUEST"
                route = ""
            else:
                kind = match.group(1).upper()
                route = match.group(2)
            if kind == "REQUEST":
                methods = _REQUEST_METHOD.findall(text) or ["ANY"]
            else:
                methods = [kind]
            full = normalize_route((prefix or "") + "/" + route)
            for method in methods:
                method = method.upper()
                route_key = f"route:{path}#{method}:{full}"
                ep_key = endpoint_key(method, full)
                result.add_node(CodeNode(
                    key=route_key, kind="route", name=f"{method} {full}", path=path,
                    lang="java", attrs={"method": method, "route": full, "annotation": text[:300]},
                ))
                result.add_edge(CodeEdge(route_key, func_key, "routes_to"))
                result.add_node(CodeNode(
                    key=ep_key, kind="endpoint", name=f"{method} {full}", path=path,
                    lang="java",
                    attrs={"method": method, "route": full, "permission": permission,
                           "evidence": evidence or f"{path}:1", "mismatch": False},
                ))
                result.add_edge(CodeEdge(func_key, ep_key, "exposes"))
                result.endpoints.append({
                    "key": ep_key, "method": method, "route": full,
                    "permission": permission, "path": path,
                    "line": line,
                    "mismatch": False,
                })

    @staticmethod
    def _class_route_prefix(annotations) -> str:
        for ann in annotations:
            text = ann
            if "RequestMapping" not in text:
                continue
            match = _ROUTE_ANN.search(text)
            if match:
                return match.group(2)
        return ""

    def _annotations(self, node, raw) -> tuple[list[str], list[int]]:
        mods = next((c for c in node.children if c.type == "modifiers"), None)
        if mods is None:
            return [], []
        texts, lines = [], []
        for child in mods.children:
            if child.type in ("annotation", "marker_annotation"):
                texts.append(text_of(raw, child))
                lines.append(child.start_point[0] + 1)
        return texts, lines

    def _permission(self, annotations, raw, node, inherited) -> tuple[str, str]:
        joined = " ".join(annotations)
        line = node.start_point[0] + 1
        evidence = f"{line}: {joined[:240]}" if joined else ""
        low = joined.lower()
        if "permitall" in low or "rolevance_anonymous" in low or "role_anonymous" in low:
            return "公开", evidence
        if any(x in low for x in (
            "hasrole", "hasauthority", "preauthorize", "secuRed".lower(),
            "requiresroles", "requirespermissions", "role_admin", "role_super",
        )):
            return "管理员权限", evidence
        if "isauthenticated" in low or "role_user" in low or "hasanyrole" in low:
            return "登录用户", evidence
        if inherited:
            return inherited, evidence
        return "内部接口", evidence

    def _params(self, node, raw) -> list[dict]:
        params = node.child_by_field_name("parameters")
        if params is None:
            return []
        out = []
        for child in params.named_children:
            if child.type not in ("formal_parameter", "spread_parameter"):
                continue
            name_node = child.child_by_field_name("name")
            type_node = child.child_by_field_name("type")
            anns, _ = self._annotations(child, raw)
            out.append({
                "name": text_of(raw, name_node) if name_node is not None else "",
                "type": text_of(raw, type_node) if type_node is not None else "",
                "annotations": anns,
                "line": child.start_point[0] + 1,
            })
        return out

    def _sources(self, node, raw) -> list[dict]:
        out = []
        for p in self._params(node, raw):
            ann_names = {re.sub(r"^@|\(.*$", "", a).strip() for a in p["annotations"]}
            if ann_names & _SOURCE_ANNOTATIONS or p["type"] in _SOURCE_TYPES or not ann_names:
                out.append({"name": p["name"], "line": p["line"], "kind": "param"})
        return out

    def _sinks(self, node, raw) -> list[dict]:
        out = []
        for call in self._iter_calls(node):
            name, full = self._callee(call, raw)
            if name not in _SINK_NAMES:
                continue
            args = call.child_by_field_name("arguments")
            out.append({"callee": full, "line": call.start_point[0] + 1,
                        "arg_text": text_of(raw, args)[:500] if args is not None else ""})
        return out

    def _calls(self, node, raw) -> list[dict]:
        out, seen = [], set()
        for call in self._iter_calls(node):
            name, full = self._callee(call, raw)
            if not name:
                continue
            key = (full, call.start_point[0] + 1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"callee": full, "name": name, "line": call.start_point[0] + 1})
        return out

    def _iter_calls(self, node):
        for child in node.children:
            if child.type in ("method_declaration", "constructor_declaration", "class_declaration"):
                continue
            if child.type == "method_invocation":
                yield child
            yield from self._iter_calls(child)

    @staticmethod
    def _callee(call, raw) -> tuple[str, str]:
        name_node = call.child_by_field_name("name")
        name = text_of(raw, name_node) if name_node is not None else ""
        obj = call.child_by_field_name("object")
        full = f"{text_of(raw, obj)}.{name}" if obj is not None else name
        return name, full

    @staticmethod
    def _package(root, raw) -> str:
        for child in root.children:
            if child.type == "package_declaration":
                return text_of(raw, child).replace("package", "").strip().rstrip(";")
        return ""


class _Ref:
    def __init__(self, key: str):
        self.key = key
