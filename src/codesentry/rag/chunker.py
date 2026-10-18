"""tree-sitter AST 函数/类切块（agent.md D9，借鉴 RepoAgent 思路）。"""

from dataclasses import dataclass, field

import tree_sitter_python
from tree_sitter import Language, Parser


@dataclass
class Chunk:
    path: str
    lang: str
    symbol_name: str
    symbol_kind: str  # function | class
    start_line: int
    end_line: int
    signature: str
    docstring: str = ""
    call_refs: list[str] = field(default_factory=list)
    content: str = ""


def _language(lang: str) -> Language:
    if lang == "python":
        return Language(tree_sitter_python.language())
    raise ValueError(f"chunker: unsupported language: {lang}")  # 其余五语言 M1 后逐个接入


_LANGS = {"python"}


def chunk_code(path: str, lang: str, source: str) -> list[Chunk]:
    if lang not in _LANGS:
        raise ValueError(f"chunker: unsupported language: {lang}")
    if not source or not source.strip():
        return []
    parser = Parser(_language(lang))
    tree = parser.parse(source.encode("utf-8"))
    root = tree.root_node

    def node_text(n) -> str:
        return source.encode("utf-8")[n.start_byte : n.end_byte].decode("utf-8")

    chunks: list[Chunk] = []

    def walk(node):
        for child in node.children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = node_text(name_node)
                body = child.child_by_field_name("body")
                docstring = _py_docstring(body, node_text) if body else ""
                chunks.append(
                    Chunk(
                        path=path,
                        lang=lang,
                        symbol_name=name,
                        symbol_kind="function",
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        signature=f"def {name}(...)",
                        docstring=docstring,
                        call_refs=_py_calls(child, node_text),
                        content=node_text(child),
                    )
                )
            elif child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                chunks.append(
                    Chunk(
                        path=path,
                        lang=lang,
                        symbol_name=node_text(name_node),
                        symbol_kind="class",
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        signature=f"class {node_text(name_node)}(...)",
                        content=node_text(child),
                    )
                )
            walk(child)

    walk(root)
    return chunks


def _py_docstring(body, node_text) -> str:
    if body is None:
        return ""
    first = body.children[0] if body.children else None
    if first is not None and first.type == "expression_statement":
        inner = first.children[0] if first.children else None
        if inner is not None and inner.type == "string":
            text = node_text(inner)
            return text.strip("\"'")[:500]
    return ""


def _py_calls(fn_node, node_text) -> list[str]:
    refs: list[str] = []

    def walk(n):
        if n.type == "call":
            fn = n.child_by_field_name("function")
            if fn is not None:
                refs.append(node_text(fn))
        for c in n.children:
            walk(c)

    walk(fn_node)
    return sorted(set(refs))
