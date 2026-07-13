from pathlib import Path
from types import SimpleNamespace

from scripts.generate_regen_from_tests import (
    _extract_function_rewrites_from_code_block,
    _generate_combined_patch,
)


class DummyCandidate:
    def __init__(self, name: str, qualified_name: str, signature: str | None = None):
        self.name = name
        self.qualified_name = qualified_name
        self.signature = signature or f"def {name}()"


def test_extract_function_rewrites_from_code_block_with_class_methods():
    code_block = """
class A:
    def __init__(self, x):
        return x

class B:
    def __init__(self, y):
        return y
"""
    candidates = [
        DummyCandidate("__init__", "A::__init__"),
        DummyCandidate("__init__", "B::__init__"),
    ]

    extracted = _extract_function_rewrites_from_code_block(code_block, candidates)

    assert extracted is not None
    assert len(extracted) == 2
    assert extracted[0][0].qualified_name == "A::__init__"
    assert extracted[1][0].qualified_name == "B::__init__"
    assert extracted[0][1].strip().startswith("def __init__(self, x)")
    assert extracted[1][1].strip().startswith("def __init__(self, y)")


def test_extract_function_rewrites_from_code_block_same_name_same_file():
    code_block = """

def foo(x):
    return x * 2


def foo(y):
    return y + 1
"""
    candidates = [
        DummyCandidate("foo", "foo(int)", signature="def foo(x)"),
        DummyCandidate("foo", "foo(str)", signature="def foo(y)"),
    ]

    extracted = _extract_function_rewrites_from_code_block(code_block, candidates)

    assert extracted is not None
    assert len(extracted) == 2
    assert extracted[0][0].qualified_name == "foo(int)"
    assert extracted[1][0].qualified_name == "foo(str)"
    assert "return x * 2" in extracted[0][1]
    assert "return y + 1" in extracted[1][1]


def test_generate_combined_patch_clamps_out_of_range_line_end(tmp_path: Path) -> None:
    repo_dir = tmp_path
    file_path = repo_dir / "sample.py"
    file_path.write_text("print('hello')\n")

    candidate = SimpleNamespace(
        file_path=str(file_path),
        line_start=2,
        line_end=3,
        indent_level=0,
        indent_size=4,
        src_code="print('hello')",
        name="sample",
    )

    patch = _generate_combined_patch(repo_dir, [(candidate, "print('bye')\n")], "repo")

    assert patch is not None
    assert "a/sample.py" in patch
    assert "b/sample.py" in patch
