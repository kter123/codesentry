"""Python 抽取器：函数/类/方法、导入、调用、路由、source/sink。"""

from __future__ import annotations

import re

import tree_sitter_python
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

_LANG = Language(tree_sitter_python.language())

_ROUTE_RE = re.compile(
    r"@\s*[\w.]*\.?(route|get|post|put|delete|patch|api_route)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_METHODS_RE = re.compile(r"methods\s*=\s*\[([^\]]*)\]", re.IGNORECASE)

_SOURCE_CALLS = {
    "input",
    "get_json",
    "getlist",
    "getvalue",
    "request.args.get",
    "request.form.get",
    "request.json",
    "request.get_json",
}
_SINK_CALLS = {
    "eval", "exec", "compile", "os.system", "os.popen", "subprocess.run",
    "subprocess.call", "subprocess.check_output", "subprocess.Popen",
    "pickle.load", "pickle.loads", "yaml.load", "yaml.unsafe_load",
    "cursor.execute", "connection.execute", "conn.execute", "session.execute",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "httpx.get", "httpx.post", "urllib.request.urlopen", "open",
    "render_template_string", "send_file", "send_from_directory",
}


class PythonExtractor:
    lang = "python"

    def extract(self, path: str, source: str) -> ExtractResult:
        raw = source.encode("utf-8")
        tree = Parser(_LANG).parse(raw)
        result = ExtractResult()
        file_node = CodeNode(
            key=file_key(path), kind="file", name=path.rsplit("/", 1)[-1],
            path=path, start_line=1, end_line=max(1, source.count("\n") + 1), lang="python",
            attrs={"imports": []},
        )
        result.add_node(file_node)
        self._walk(tree.root_node, raw, path, result, file_node, [], [])

        imports = file_node.attrs.get("imports") or []
        for module in sorted(set(imports)):
            result.add_edge(CodeEdge(file_node.key, f"module:{module}", "imports"))
        return result

    def _walk(self, node, raw, path, result, parent, class_stack, func_stack):
        for child in node.children:
            if child.type == "decorated_definition":
                decorators = [c for c in child.children if c.type == "decorator"]
                definition = child.child_by_field_name("definition")
                if definition is not None:
                    self._definition(
                        definition, raw, path, result, parent, class_stack, func_stack, decorators
                    )
            elif child.type in ("function_definition", "class_definition"):
                self._definition(
                    child, raw, path, result, parent, class_stack, func_stack, []
                )
            elif child.type in ("import_statement", "import_from_statement"):
                self._import(child, raw, parent)
            else:
                self._walk(child, raw, path, result, parent, class_stack, func_stack)

    def _definition(self, node, raw, path, result, parent, class_stack, func_stack, decorators):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = text_of(raw, name_node)
        if node.type == "class_definition":
            qual = ".".join([*class_stack, name])
            key = node_key("class", path, qual)
            result.add_node(CodeNode(
                key=key, kind="class", name=name, path=path,
                start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
                qualified_name=qual, lang="python",
            ))
            result.add_edge(CodeEdge(parent.key, key, "contains"))
            body = node.child_by_field_name("body")
            if body is not None:
                self._walk(body, raw, path, result, _NodeRef(key), [*class_stack, name], func_stack)
            return

        if node.type != "function_definition":
            return
        qual = ".".join([*class_stack, *func_stack, name])
        kind = "method" if class_stack else "function"
        key = node_key("function", path, qual)
        sources, sinks = self._sources_sinks(node, raw, bool(decorators))
        result.add_node(CodeNode(
            key=key, kind=kind, name=name, path=path,
            start_line=node.start_point[0] + 1, end_line=node.end_point[0] + 1,
            qualified_name=qual, lang="python",
            attrs={
                "calls": self._calls(node, raw),
                "sources": sources,
                "sinks": sinks,
                "params": self._params(node, raw),
            },
        ))
        result.add_edge(CodeEdge(parent.key, key, "contains"))
        self._routes(decorators, raw, path, result, key, name)
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk(
                body, raw, path, result, _NodeRef(key), class_stack, [*func_stack, name]
            )

    def _routes(self, decorators, raw, path, result, func_key, func_name):
        for dec in decorators:
            text = text_of(raw, dec)
            match = _ROUTE_RE.search(text)
            if not match:
                continue
            route = normalize_route(match.group(2))
            methods_match = _METHODS_RE.search(text)
            if methods_match:
                methods = re.findall(r"[\"']([A-Za-z]+)[\"']", methods_match.group(1))
            else:
                methods = ["GET"]
            for method in methods or ["GET"]:
                method = method.upper()
                route_key = f"route:{path}#{method}:{route}"
                ep_key = endpoint_key(method, route)
                result.add_node(CodeNode(
                    key=route_key, kind="route", name=f"{method} {route}", path=path,
                    start_line=dec.start_point[0] + 1, end_line=dec.end_point[0] + 1,
                    lang="python", attrs={"method": method, "route": route},
                ))
                result.add_edge(CodeEdge(route_key, func_key, "routes_to"))
                result.add_node(CodeNode(
                    key=ep_key, kind="endpoint", name=f"{method} {route}", path=path,
                    lang="python",
                    attrs={"method": method, "route": route, "permission": "其他",
                           "evidence": f"{path}:{dec.start_point[0] + 1}", "mismatch": False},
                ))
                result.add_edge(CodeEdge(func_key, ep_key, "exposes"))
                result.endpoints.append({
                    "key": ep_key, "method": method, "route": route,
                    "permission": "其他", "path": path,
                    "line": dec.start_point[0] + 1, "mismatch": False,
                })

    def _import(self, node, raw, file_node):
        text = text_of(raw, node).strip()
        imports = file_node.attrs.setdefault("imports", [])
        if text.startswith("import "):
            for part in text[7:].split(","):
                name = part.strip().split(" as ")[0].strip()
                if name:
                    imports.append(name)
        else:
            match = re.match(r"from\s+([\w.]+)\s+import\s+(.+)", text)
            if match:
                imports.append(match.group(1))
                for part in match.group(2).split(","):
                    alias = part.strip().split(" as ")[0].strip()
                    if alias and alias != "*":
                        imports.append(f"{match.group(1)}.{alias}")

    def _params(self, node, raw) -> list[str]:
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            return []
        out = []
        for child in params_node.named_children:
            if child.type in ("identifier", "typed_parameter", "default_parameter"):
                name_node = child.child_by_field_name("name") or child
                name = text_of(raw, name_node).split(":")[0].strip()
                if name and name not in ("self", "cls"):
                    out.append(name)
        return out

    def _sources_sinks(self, node, raw, is_route: bool) -> tuple[list[dict], list[dict]]:
        sources: list[dict] = []
        sinks: list[dict] = []
        for name in self._params(node, raw):
            sources.append({"name": name, "line": node.start_point[0] + 1, "kind": "param"})
        for call in self._iter_calls(node):
            callee = self._callee(call, raw)
            line = call.start_point[0] + 1
            if callee in _SOURCE_CALLS or callee.split(".")[-1] in _SOURCE_CALLS:
                sources.append({"name": callee.split(".")[-1], "line": line, "kind": "call"})
            if callee in _SINK_CALLS or callee.split(".")[-1] in _SINK_CALLS:
                args = call.child_by_field_name("arguments")
                sinks.append({
                    "callee": callee, "line": line,
                    "arg_text": text_of(raw, args)[:500] if args is not None else "",
                })
        return _dedupe(sources), _dedupe(sinks)

    def _calls(self, node, raw) -> list[dict]:
        out = []
        seen = set()
        for call in self._iter_calls(node):
            callee = self._callee(call, raw)
            line = call.start_point[0] + 1
            key = (callee, line)
            if not callee or key in seen:
                continue
            seen.add(key)
            out.append({"callee": callee, "name": callee.split(".")[-1], "line": line})
        return out

    def _iter_calls(self, node):
        for child in node.children:
            if child.type in ("function_definition", "class_definition", "decorated_definition"):
                continue
            if child.type == "call":
                yield child
            yield from self._iter_calls(child)

    @staticmethod
    def _callee(call, raw) -> str:
        fn = call.child_by_field_name("function")
        return text_of(raw, fn).strip() if fn is not None else ""


class _NodeRef:
    def __init__(self, key: str):
        self.key = key


def _dedupe(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for item in items:
        key = (item.get("name") or item.get("callee"), item.get("line"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
