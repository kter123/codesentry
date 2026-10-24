"""通用 tree-sitter 抽取器：JS/TS/Go/PHP/C/C++ 的函数、类、调用与路由。"""

from __future__ import annotations

import re

import tree_sitter_c
import tree_sitter_cpp
import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_php
import tree_sitter_typescript
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

_ROUTE_PATTERNS: dict[str, list[tuple[re.Pattern[str], int, int, str | None]]] = {
    "javascript": [
        (re.compile(r"\b(?:app|router|server|api)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*[\"'`]([^\"'`]+)", re.IGNORECASE), 1, 2, None),
        (re.compile(r"@(Get|Post|Put|Delete|Patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE), 1, 2, None),
    ],
    "typescript": [
        (re.compile(r"\b(?:app|router|server|api)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*[\"'`]([^\"'`]+)", re.IGNORECASE), 1, 2, None),
        (re.compile(r"@(Get|Post|Put|Delete|Patch)\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE), 1, 2, None),
    ],
    "tsx": [
        (re.compile(r"\b(?:app|router|server|api)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*[\"'`]([^\"'`]+)", re.IGNORECASE), 1, 2, None),
    ],
    "go": [
        (re.compile(r"\.\s*(GET|POST|PUT|DELETE|PATCH|Any)\s*\(\s*[\"']([^\"']+)[\"']"), 1, 2, None),
        (re.compile(r"(?:http\.)?HandleFunc\s*\(\s*[\"']([^\"']+)[\"']"), 0, 1, "ANY"),
    ],
    "php": [
        (re.compile(r"Route::(get|post|put|delete|patch|any)\s*\(\s*[\"']([^\"']+)[\"']", re.IGNORECASE), 1, 2, None),
    ],
    "c": [],
    "cpp": [],
}
_IMPORT_RES = {
    "javascript": re.compile(r"(?:from\s+|require\(\s*)[\"']([^\"']+)[\"']"),
    "typescript": re.compile(r"(?:from\s+|require\(\s*)[\"']([^\"']+)[\"']"),
    "tsx": re.compile(r"(?:from\s+|require\(\s*)[\"']([^\"']+)[\"']"),
    "go": re.compile(r"[\"']([\w./\-]+)[\"']"),
    "php": re.compile(r"(?:use\s+|require(?:_once)?\s*\(?\s*[\"'])([\\\w./\-]+)"),
    "c": re.compile(r"#\s*include\s*[<\"]([^>\"]+)[>\"]"),
    "cpp": re.compile(r"#\s*include\s*[<\"]([^>\"]+)[>\"]"),
}

_SOURCE_HINTS = ("req.", "request.", "ctx.", "r.URL", "r.Form", "$_GET", "$_POST", "$_REQUEST", "getParameter")
_SINK_NAMES = {
    "eval", "exec", "system", "popen", "strcpy", "strcat", "sprintf", "gets", "memcpy",
    "readObject", "execute", "query", "execSync", "spawn", "execFile", "Function",
    "include", "require", "unserialize", "shell_exec", "passthru", "assert",
}


class _Cfg:
    def __init__(self, lang, language, function_types, class_types, call_types,
                 import_types, params_field="parameters", name_field="name",
                 method_owner_field: str | None = None):
        self.lang = lang
        self.language = language
        self.function_types = function_types
        self.class_types = class_types
        self.call_types = call_types
        self.import_types = import_types
        self.params_field = params_field
        self.name_field = name_field
        self.method_owner_field = method_owner_field


_CFG = {
    "javascript": _Cfg(
        "javascript", Language(tree_sitter_javascript.language()),
        {"function_declaration", "generator_function_declaration", "method_definition",
         "function_expression", "arrow_function"},
        {"class_declaration", "class"},
        {"call_expression"}, {"import_statement"},
    ),
    "typescript": _Cfg(
        "typescript", Language(tree_sitter_typescript.language_typescript()),
        {"function_declaration", "generator_function_declaration", "method_definition",
         "function_expression", "arrow_function"},
        {"class_declaration", "class", "interface_declaration"},
        {"call_expression"}, {"import_statement"},
    ),
    "tsx": _Cfg(
        "tsx", Language(tree_sitter_typescript.language_tsx()),
        {"function_declaration", "generator_function_declaration", "method_definition",
         "function_expression", "arrow_function"},
        {"class_declaration", "class", "interface_declaration"},
        {"call_expression"}, {"import_statement"},
    ),
    "go": _Cfg(
        "go", Language(tree_sitter_go.language()),
        {"function_declaration", "method_declaration"},
        {"type_declaration"},
        {"call_expression"}, {"import_declaration"},
    ),
    "php": _Cfg(
        "php", Language(tree_sitter_php.language_php()),
        {"function_definition", "method_declaration"},
        {"class_declaration", "interface_declaration", "trait_declaration"},
        {"function_call_expression", "member_call_expression", "scoped_call_expression"},
        {"namespace_use_declaration"},
    ),
    "c": _Cfg(
        "c", Language(tree_sitter_c.language()),
        {"function_definition"}, {"struct_specifier"},
        {"call_expression"}, {"preproc_include"},
    ),
    "cpp": _Cfg(
        "cpp", Language(tree_sitter_cpp.language()),
        {"function_definition"}, {"class_specifier", "struct_specifier"},
        {"call_expression"}, {"preproc_include"},
    ),
}


class GenericExtractor:
    def __init__(self, lang: str):
        self.cfg = _CFG[lang]
        self.lang = lang
        self._parser = Parser(self.cfg.language)

    def extract(self, path: str, source: str) -> ExtractResult:
        raw = source.encode("utf-8")
        tree = self._parser.parse(raw)
        result = ExtractResult()
        file_node = CodeNode(
            key=file_key(path), kind="file", name=path.rsplit("/", 1)[-1],
            path=path, start_line=1, end_line=max(1, source.count("\n") + 1),
            lang=self.lang, attrs={"imports": []},
        )
        result.add_node(file_node)
        self._walk(tree.root_node, raw, path, result, file_node, [])
        self._routes(source, path, result)
        for module in sorted(set(file_node.attrs.get("imports") or [])):
            result.add_edge(CodeEdge(file_node.key, f"module:{module}", "imports"))
        return result

    def _walk(self, node, raw, path, result, parent, class_stack):
        cfg = self.cfg
        for child in node.children:
            t = child.type
            if t in cfg.import_types:
                text = text_of(raw, child)
                matches = _IMPORT_RES[self.lang].findall(text)
                for module in matches or [text.strip()[:160]]:
                    parent.attrs.setdefault("imports", []).append(str(module)[:300])
            elif t in cfg.class_types:
                self._class(child, raw, path, result, parent, class_stack)
            elif t in cfg.function_types:
                self._function(child, raw, path, result, parent, class_stack)
            elif t == "variable_declarator" and self.lang in ("javascript", "typescript", "tsx"):
                value = child.child_by_field_name("value")
                if value is not None and value.type in cfg.function_types:
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        self._add_function(
                            value, text_of(raw, name_node), raw, path, result,
                            parent, class_stack, is_arrow=True,
                        )
            else:
                self._walk(child, raw, path, result, parent, class_stack)

    def _class(self, node, raw, path, result, parent, class_stack):
        name = self._name(node, raw)
        if not name:
            self._walk(node, raw, path, result, parent, class_stack)
            return
        qual = ".".join([*(c[0] for c in class_stack), name])
        key = node_key("class", path, qual)
        result.add_node(CodeNode(
            key=key, kind="class", name=name, path=path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            qualified_name=qual, lang=self.lang,
        ))
        result.add_edge(CodeEdge(parent.key, key, "contains"))
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk(body, raw, path, result, _Ref(key), [*class_stack, (name, key)])
        else:
            self._walk(node, raw, path, result, _Ref(key), [*class_stack, (name, key)])

    def _function(self, node, raw, path, result, parent, class_stack):
        name = self._name(node, raw)
        if not name and self.cfg.method_owner_field:
            owner = node.child_by_field_name(self.cfg.method_owner_field)
            if owner is not None:
                name = text_of(raw, owner).split()[-1]
        if not name:
            self._walk(node, raw, path, result, parent, class_stack)
            return
        self._add_function(node, name, raw, path, result, parent, class_stack)

    def _add_function(self, node, name, raw, path, result, parent, class_stack, is_arrow=False):
        qual = ".".join([*(c[0] for c in class_stack), name])
        key = node_key("function", path, qual)
        params = self._params(node, raw)
        sources = [{"name": p, "line": node.start_point[0] + 1, "kind": "param"} for p in params]
        sinks = self._sinks(node, raw)
        result.add_node(CodeNode(
            key=key, kind="method" if class_stack else "function", name=name, path=path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            qualified_name=qual, lang=self.lang,
            attrs={"calls": self._calls(node, raw), "sources": sources,
                   "sinks": sinks, "params": params},
        ))
        result.add_edge(CodeEdge(parent.key, key, "contains"))
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk(body, raw, path, result, _Ref(key), class_stack)

    def _name(self, node, raw) -> str:
        name_node = node.child_by_field_name(self.cfg.name_field)
        if name_node is not None:
            return text_of(raw, name_node)
        if self.cfg.lang in ("c", "cpp"):
            decl = node.child_by_field_name("declarator")
            if decl is not None:
                return self._declarator_name(decl, raw)
        return ""

    def _declarator_name(self, node, raw) -> str:
        if node.type in ("identifier", "field_identifier", "qualified_identifier"):
            return text_of(raw, node).split("::")[-1]
        for child in node.children:
            name = self._declarator_name(child, raw)
            if name:
                return name
        return ""

    def _params(self, node, raw) -> list[str]:
        params = node.child_by_field_name(self.cfg.params_field)
        if params is None:
            return []
        out = []
        for child in params.named_children:
            if child.type in ("identifier", "variable_name"):
                out.append(text_of(raw, child))
                continue
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                out.append(text_of(raw, name_node))
                continue
            if child.type in ("parameter", "formal_parameter", "simple_parameter"):
                out.append(text_of(raw, child).split()[-1].strip("$&*"))
        return [n for n in out if n and n not in ("self", "this")]

    def _calls(self, node, raw) -> list[dict]:
        out, seen = [], set()
        for call in self._iter(node, self.cfg.call_types):
            callee = call.child_by_field_name("function")
            text = text_of(raw, callee) if callee is not None else ""
            if self.lang == "php":
                text = text_of(raw, call)
            if not text:
                continue
            name = re.split(r"[.>:\-]+", text)[-1].strip("$")
            key = (text, call.start_point[0] + 1)
            if key in seen:
                continue
            seen.add(key)
            out.append({"callee": text[-200:], "name": name, "line": call.start_point[0] + 1})
        return out

    def _sinks(self, node, raw) -> list[dict]:
        out = []
        for call in self._iter(node, self.cfg.call_types):
            callee = call.child_by_field_name("function")
            text = text_of(raw, callee) if callee is not None else text_of(raw, call)
            name = re.split(r"[.>:\-]+", text)[-1].strip("$")
            if name not in _SINK_NAMES:
                continue
            args = call.child_by_field_name("arguments")
            out.append({"callee": name, "line": call.start_point[0] + 1,
                        "arg_text": text_of(raw, args)[:500] if args is not None else ""})
        return out

    def _iter(self, node, types):
        for child in node.children:
            if child.type in self.cfg.function_types or child.type in self.cfg.class_types:
                continue
            if child.type in types:
                yield child
            yield from self._iter(child, types)

    def _routes(self, source: str, path: str, result: ExtractResult):
        functions = [n for n in result.nodes if n.kind in ("function", "method")]

        def owner(line: int):
            for fn in functions:
                if fn.start_line <= line <= fn.end_line:
                    return fn
            return None

        for pattern, method_group, route_group, default_method in _ROUTE_PATTERNS[self.lang]:
            for match in pattern.finditer(source):
                method = default_method or match.group(method_group).upper()
                route = normalize_route(match.group(route_group))
                if not route.startswith("/"):
                    continue
                line = source[: match.start()].count("\n") + 1
                fn = owner(line)
                route_key = f"route:{path}#{method}:{route}"
                ep_key = endpoint_key(method, route)
                result.add_node(CodeNode(
                    key=route_key, kind="route", name=f"{method} {route}", path=path,
                    start_line=line, end_line=line, lang=self.lang,
                    attrs={"method": method, "route": route},
                ))
                if fn is not None:
                    result.add_edge(CodeEdge(route_key, fn.key, "routes_to"))
                result.add_node(CodeNode(
                    key=ep_key, kind="endpoint", name=f"{method} {route}", path=path,
                    lang=self.lang,
                    attrs={"method": method, "route": route, "permission": "其他",
                           "evidence": f"{path}:{line}", "mismatch": False},
                ))
                if fn is not None:
                    result.add_edge(CodeEdge(fn.key, ep_key, "exposes"))
                result.endpoints.append({
                    "key": ep_key, "method": method, "route": route,
                    "permission": "其他", "path": path, "line": line, "mismatch": False,
                })


class _Ref:
    def __init__(self, key: str):
        self.key = key


def extractor_for(lang: str) -> GenericExtractor | None:
    if lang not in _CFG:
        return None
    return GenericExtractor(lang)
