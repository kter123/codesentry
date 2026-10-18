import pytest

from codesentry.rag.chunker import Chunk, chunk_code

PYTHON_SRC = '''\
def sink_call(url):
    resp = requests.get(url)
    return resp.text


class FileService:
    def read_report(self, name):
        return open(name)
'''


def test_python_chunks_functions_and_classes():
    chunks = chunk_code("app.py", "python", PYTHON_SRC)
    kinds = {(c.symbol_name, c.symbol_kind) for c in chunks}
    assert ("sink_call", "function") in kinds
    assert ("FileService", "class") in kinds
    assert ("read_report", "function") in kinds


def test_chunk_lines_and_content():
    chunks = chunk_code("app.py", "python", PYTHON_SRC)
    fn = next(c for c in chunks if c.symbol_name == "sink_call")
    assert fn.start_line >= 1 and fn.end_line > fn.start_line
    assert "requests.get(url)" in fn.content


def test_call_refs_extracted():
    chunks = chunk_code("app.py", "python", PYTHON_SRC)
    fn = next(c for c in chunks if c.symbol_name == "sink_call")
    assert any("requests.get" in ref for ref in fn.call_refs)


def test_unsupported_lang_raises():
    with pytest.raises(ValueError):
        chunk_code("x.rs", "rust", "fn main() {}")


def test_empty_source():
    assert chunk_code("a.py", "python", "") == []
