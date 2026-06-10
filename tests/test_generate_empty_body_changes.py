import sys
from pathlib import Path
from types import ModuleType


def _inject_stub_modules() -> None:
    swebench = ModuleType("swebench")
    swebench_harness = ModuleType("swebench.harness")
    swebench_constants = ModuleType("swebench.harness.constants")
    swebench_constants.FAIL_TO_PASS = "fail_to_pass"
    swebench_constants.KEY_INSTANCE_ID = "instance_id"
    swebench_harness.constants = swebench_constants
    swebench.harness = swebench_harness

    swesmith = ModuleType("swesmith")
    swebug_gen = ModuleType("swesmith.bug_gen")
    swebug_gen_utils = ModuleType("swesmith.bug_gen.utils")
    swebug_gen_utils.generate_patch_fast = lambda *args, **kwargs: None
    swebug_gen.utils = swebug_gen_utils
    swesmith.bug_gen = swebug_gen

    swesmith_constants = ModuleType("swesmith.constants")
    swesmith_constants.LOG_DIR_BUG_GEN = Path("/tmp")
    swesmith.constants = swesmith_constants

    swesmith_profiles = ModuleType("swesmith.profiles")
    swesmith_profiles.registry = {}
    swesmith.profiles = swesmith_profiles

    sys.modules["swebench"] = swebench
    sys.modules["swebench.harness"] = swebench_harness
    sys.modules["swebench.harness.constants"] = swebench_constants
    sys.modules["swesmith"] = swesmith
    sys.modules["swesmith.bug_gen"] = swebug_gen
    sys.modules["swesmith.bug_gen.utils"] = swebug_gen_utils
    sys.modules["swesmith.constants"] = swesmith_constants
    sys.modules["swesmith.profiles"] = swesmith_profiles


_inject_stub_modules()

from scripts import generate_empty_body_changes as gebc


class DummyCandidate:
    def __init__(
        self,
        file_path,
        name,
        signature,
        line_start,
        line_end,
        indent_level=0,
        indent_size=4,
    ):
        self.file_path = str(file_path)
        self.name = name
        self.signature = signature
        self.line_start = line_start
        self.line_end = line_end
        self.indent_level = indent_level
        self.indent_size = indent_size


def test_group_candidate_rewrites_by_file(tmp_path: Path):
    file_a = tmp_path / "a.py"
    file_a.write_text("def foo():\n    x = 1\n\n\ndef bar():\n    y = 2\n")
    file_b = tmp_path / "b.py"
    file_b.write_text("def baz():\n    z = 3\n")

    c1 = DummyCandidate(file_a, "foo", "foo()", 1, 2)
    c2 = DummyCandidate(file_a, "bar", "bar()", 5, 6)
    c3 = DummyCandidate(file_b, "baz", "baz()", 1, 2)

    grouped = gebc._group_candidate_rewrites_by_file(
        [
            ("id1", c1, "def foo():\n    pass\n"),
            ("id2", c2, "def bar():\n    pass\n"),
            ("id3", c3, "def baz():\n    pass\n"),
        ]
    )

    assert len(grouped) == 2
    assert set(str(path) for path in grouped) == {str(file_a), str(file_b)}
    assert len(grouped[file_a]) == 2
    assert len(grouped[file_b]) == 1


def test_generate_same_file_combined_patches(tmp_path: Path):
    file_a = tmp_path / "a.py"
    file_a.write_text(
        "def foo():\n    x = 1\n\n\ndef bar():\n    y = 2\n"
    )
    file_b = tmp_path / "b.py"
    file_b.write_text("def baz():\n    z = 3\n")

    c1 = DummyCandidate(file_a, "foo", "foo()", 1, 2)
    c2 = DummyCandidate(file_a, "bar", "bar()", 5, 6)
    c3 = DummyCandidate(file_b, "baz", "baz()", 1, 2)

    candidate_rewrites = [
        ("id1", c1, "def foo():\n    pass\n"),
        ("id2", c2, "def bar():\n    pass\n"),
        ("id3", c3, "def baz():\n    pass\n"),
    ]

    combined_patches, combined_map, next_group_index = gebc._generate_same_file_combined_patches(
        tmp_path,
        "repo",
        "test_case_1",
        candidate_rewrites,
        set(),
        0,
    )

    assert len(combined_patches) == 1
    assert len(combined_map) == 1
    assert next_group_index == 1

    instance_id = combined_patches[0][gebc.KEY_INSTANCE_ID]
    assert instance_id in combined_map
    assert combined_map[instance_id]["file_path"] == "a.py"
    assert combined_map[instance_id]["instance_ids"] == ["id1", "id2"]
    assert combined_map[instance_id]["broken_functions"] == ["foo", "bar"]
