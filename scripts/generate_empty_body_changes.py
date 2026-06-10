"""Generate empty-body function patches from scratch.

Pipeline:
1) Clone repo profile and extract function entities.
2) Generate one empty-body patch per function.
3) Run validation on generated patches.

Usage:
  uv run python scripts/generate_empty_body_changes.py \
      Instagram__MonkeyType.70c3acf6
"""

import argparse
import ast
import astor
import difflib
import json
import subprocess
import hashlib
from pathlib import Path
from collections import defaultdict
from swebench.harness.constants import FAIL_TO_PASS, KEY_INSTANCE_ID
from swesmith.bug_gen.utils import generate_patch_fast
from swesmith.constants import LOG_DIR_BUG_GEN
from swesmith.profiles import registry


def _empty_body_rewrite(src_code: str) -> str | None:
    """Rewrite top-level function body to `pass` while keeping signature untouched."""
    try:
        tree = ast.parse(src_code)
    except SyntaxError:
        return None

    if len(tree.body) == 0:
        return None

    node = tree.body[0]
    if not isinstance(node, ast.FunctionDef):
        return None

    node.body = [ast.Pass()]
    ast.fix_missing_locations(tree)
    return astor.to_source(tree).strip()


def _signature_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def _test_hash(test_id: str) -> str:
    return hashlib.sha256(test_id.encode()).hexdigest()[:10]


def _patch_lines(rewrite: str, candidate) -> list[str]:
    lines = [
        f"{' ' * candidate.indent_level * candidate.indent_size}{x}"
        if len(x.strip()) > 0
        else x
        for x in rewrite.splitlines(keepends=True)
    ]
    if not lines:
        return []
    return lines


def _generate_combined_patch(repo_dir: Path, candidate_rewrites: list[tuple], repo: str) -> str | None:
    by_file = {}
    originals = {}

    for candidate, rewrite in sorted(candidate_rewrites, key=lambda item: (item[0].file_path, -item[0].line_start)):
        file_path = Path(candidate.file_path)
        if file_path not in originals:
            original_text = file_path.read_text()
            original_lines = original_text.splitlines(keepends=True)
            originals[file_path] = original_lines
            by_file[file_path] = original_lines.copy()

        modified_lines = by_file[file_path]
        change = _patch_lines(rewrite, candidate)
        if not change:
            return None

        curr_last_line = modified_lines[candidate.line_end - 1]
        num_newlines = len(curr_last_line) - len(curr_last_line.rstrip("\n"))
        change[-1] = change[-1].rstrip("\n") + "\n" * num_newlines

        modified_lines = (
            modified_lines[: candidate.line_start - 1]
            + change
            + modified_lines[candidate.line_end :]
        )
        by_file[file_path] = modified_lines

    diffs = []
    for file_path, original_lines in originals.items():
        modified_lines = by_file[file_path]
        if original_lines == modified_lines:
            continue

        rel_path = file_path.relative_to(repo_dir)
        original_stripped = [line.rstrip("\n") for line in original_lines]
        modified_stripped = [line.rstrip("\n") for line in modified_lines]
        diff = difflib.unified_diff(
            original_stripped,
            modified_stripped,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
        diff_text = "\n".join(diff)
        if diff_text and not diff_text.endswith("\n"):
            diff_text += "\n"
        if diff_text:
            diffs.append(diff_text)

    if not diffs:
        return None
    return "".join(diffs)


def _instance_id_for_test(repo: str, test_id: str, index: int) -> str:
    test_hash = _test_hash(test_id)
    return f"{repo}.empty_body_test_case_{index:05d}_{test_hash}"


def _load_initial_validation(repo: str, fn_map: dict) -> dict[str, list[str]]:
    validation_dir = Path("logs/run_validation") / repo
    test_to_instances = defaultdict(list)
    for instance_id in fn_map:
        report_path = validation_dir / instance_id / "report.json"
        if not report_path.exists():
            continue
        report = json.loads(report_path.read_text())
        for test in report.get(FAIL_TO_PASS, []):
            test_to_instances[test].append(instance_id)
    return test_to_instances


def main(repo: str, workers: int, max_functions: int):
    rp = registry.get(repo)
    repo_dir, _ = rp.clone()

    entities = rp.extract_entities(exclude_tests=True)
    functions = [x for x in entities if getattr(x, "is_function", False)]
    if max_functions != -1:
        functions = functions[:max_functions]

    out_dir = Path("logs/change_logs") / repo
    out_dir.mkdir(parents=True, exist_ok=True)

    patches_path = Path(LOG_DIR_BUG_GEN) / f"{repo}_empty_body_from_scratch_patches.json"
    metadata_path = out_dir / "_function_map.json"

    patches = []
    fn_map = {}
    instance_to_candidate = {}

    for idx, fn in enumerate(functions):
        rewrite = _empty_body_rewrite(fn.src_code)
        if not rewrite:
            continue

        bug = type("Bug", (), {"rewrite": rewrite})
        patch = generate_patch_fast(fn, bug, repo_dir)
        if not patch:
            continue

        sig_hash = _signature_hash(fn.signature)
        inst_suffix = f"empty_body_from_scratch_{idx:05d}_{sig_hash}"
        instance_id = f"{repo}.{inst_suffix}"

        patches.append({KEY_INSTANCE_ID: instance_id, "repo": repo, "patch": patch})
        fn_map[instance_id] = {
            "file_path": str(Path(fn.file_path).resolve().relative_to(Path(repo_dir).resolve())),
            "function_name": fn.name,
            "signature": fn.signature,
            "line_start": fn.line_start,
            "line_end": fn.line_end,
        }
        instance_to_candidate[instance_id] = fn

    patches_path.parent.mkdir(parents=True, exist_ok=True)
    patches_path.write_text(json.dumps(patches, indent=2))
    metadata_path.write_text(json.dumps(fn_map, indent=2))

    print(f"Generated {len(patches)} empty-body patches: {patches_path}")

    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "swesmith.harness.valid",
        str(patches_path),
        "--workers",
        str(workers),
        "--redo_existing",
    ]
    subprocess.run(cmd, check=True)

    test_to_instances = _load_initial_validation(repo, fn_map)
    combined_patches = []
    combined_map = {}
    seen_instance_ids = set()  # Track unique instance_ids combinations

    for idx, (test_id, instances) in enumerate(sorted(test_to_instances.items()), start=1):
        candidate_rewrites = []
        for instance_id in instances:
            fn = instance_to_candidate.get(instance_id)
            if not fn:
                continue
            rewrite = _empty_body_rewrite(fn.src_code)
            if rewrite:
                candidate_rewrites.append((fn, rewrite))

        if len(candidate_rewrites) <= 1:
            continue

        # Check if we've already seen this exact set of instance_ids
        instances_key = frozenset(instances)
        if instances_key in seen_instance_ids:
            continue
        seen_instance_ids.add(instances_key)

        instance_id = _instance_id_for_test(repo, test_id, idx)
        patch = _generate_combined_patch(repo_dir, candidate_rewrites, repo)
        if not patch:
            continue

        combined_patches.append({KEY_INSTANCE_ID: instance_id, "repo": repo, "patch": patch})
        combined_map[instance_id] = {
            "test_case": test_id,
            "broken_functions": [fn.name for fn, _ in candidate_rewrites],
            "instance_count": len(candidate_rewrites),
            "instance_ids": instances,
        }

    combined_patches_path = Path(LOG_DIR_BUG_GEN) / f"{repo}_empty_body_from_test_case_patches.json"
    combined_metadata_path = out_dir / "_test_case_map.json"
    combined_patches_path.write_text(json.dumps(combined_patches, indent=2))
    combined_metadata_path.write_text(json.dumps(combined_map, indent=2))

    print(f"Generated {len(combined_patches)} combined test-case patches: {combined_patches_path}")

    if combined_patches:
        cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "swesmith.harness.valid",
            str(combined_patches_path),
            "--workers",
            str(workers),
            "--redo_existing",
        ]
        subprocess.run(cmd, check=True)

    summary = {
        "repo": repo,
        "functions_considered": len(functions),
        "patches_generated": len(patches),
        "combined_patches_generated": len(combined_patches),
        "patches_json": str(patches_path),
        "combined_patches_json": str(combined_patches_path),
        "change_dir": str(out_dir),
    }
    (out_dir / "_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate empty-body patches from scratch."
    )
    parser.add_argument("repo", type=str, help="Repo key, e.g. Instagram__MonkeyType.70c3acf6")
    parser.add_argument("--workers", type=int, default=4, help="Validation worker count.")
    parser.add_argument(
        "--max_functions",
        type=int,
        default=-1,
        help="Limit number of functions for faster runs (-1 = all).",
    )
    args = parser.parse_args()
    main(**vars(args))