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

        # Clamp indices to the current modified_lines bounds to avoid IndexError
        start_idx = max(0, candidate.line_start - 1)
        last_idx = min(candidate.line_end - 1, len(modified_lines) - 1)
        end_idx = min(candidate.line_end, len(modified_lines))

        curr_last_line = modified_lines[last_idx]
        num_newlines = len(curr_last_line) - len(curr_last_line.rstrip("\n"))
        change[-1] = change[-1].rstrip("\n") + "\n" * num_newlines

        modified_lines = (
            modified_lines[:start_idx]
            + change
            + modified_lines[end_idx:]
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


def _group_candidate_rewrites_by_file(candidate_rewrites: list[tuple[str, object, str]]) -> dict[Path, list[tuple[str, object, str]]]:
    groups: dict[Path, list[tuple[str, object, str]]] = defaultdict(list)
    for instance_id, candidate, rewrite in candidate_rewrites:
        groups[Path(candidate.file_path)].append((instance_id, candidate, rewrite))
    return groups


def _generate_same_file_combined_patches(
    repo_dir: Path,
    repo: str,
    test_id: str,
    candidate_rewrites: list[tuple[str, object, str]],
    seen_instance_ids: set[frozenset],
    next_group_index: int,
):
    combined_patches = []
    combined_map = {}

    for file_path, grouped_rewrites in sorted(
        _group_candidate_rewrites_by_file(candidate_rewrites).items(),
        key=lambda item: str(item[0]),
    ):
        if len(grouped_rewrites) <= 1:
            continue

        group_instance_ids = [instance_id for instance_id, _, _ in grouped_rewrites]
        group_key = frozenset(group_instance_ids)
        if group_key in seen_instance_ids:
            continue
        seen_instance_ids.add(group_key)

        next_group_index += 1
        instance_id = _instance_id_for_test(repo, test_id, next_group_index)
        patch = _generate_combined_patch(
            repo_dir,
            [(candidate, rewrite) for _, candidate, rewrite in grouped_rewrites],
            repo,
        )
        if not patch:
            continue

        try:
            rel_file_path = str(Path(file_path).resolve().relative_to(repo_dir.resolve()))
        except Exception:
            rel_file_path = str(file_path)

        combined_patches.append({KEY_INSTANCE_ID: instance_id, "repo": repo, "patch": patch})
        combined_map[instance_id] = {
            "test_case": test_id,
            "broken_functions": [candidate.name for _, candidate, _ in grouped_rewrites],
            "instance_count": len(grouped_rewrites),
            "instance_ids": group_instance_ids,
            "file_path": rel_file_path,
        }

    return combined_patches, combined_map, next_group_index


def _instance_id_for_test(repo: str, test_id: str, index: int) -> str:
    test_hash = _test_hash(test_id)
    return f"{repo}.empty_body_test_case_{index:05d}_{test_hash}"


def _load_initial_validation(repo: str, fn_map: dict, max_tests_per_line: float | None = None) -> tuple[dict[str, list[str]], list[str]]:
    validation_dir = Path("logs/run_validation") / repo
    test_to_instances = defaultdict(list)
    pruned_instances: list[str] = []

    for instance_id, fn_info in fn_map.items():
        report_path = validation_dir / instance_id / "report.json"
        if not report_path.exists():
            continue

        report = json.loads(report_path.read_text())
        failed_tests = report.get(FAIL_TO_PASS, [])
        if max_tests_per_line is not None and failed_tests:
            line_count = max(1, fn_info.get("line_end", 0) - fn_info.get("line_start", 0) + 1)
            density = len(failed_tests) / line_count
            if density > max_tests_per_line:
                pruned_instances.append(instance_id)
                continue

        for test in failed_tests:
            test_to_instances[test].append(instance_id)

    return test_to_instances, pruned_instances


def main(repo: str, workers: int, max_functions: int, max_tests_per_line: float | None):
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

    test_to_instances, pruned_instances = _load_initial_validation(repo, fn_map, max_tests_per_line)
    if pruned_instances:
        for instance_id in pruned_instances:
            fn_map.pop(instance_id, None)
        print(
            f"Pruned {len(pruned_instances)} instances with > {max_tests_per_line} tests/line: {pruned_instances}"
        )

    metadata_path.write_text(json.dumps(fn_map, indent=2))

    combined_patches = []
    combined_map = {}
    seen_instance_ids = set()  # Track unique instance_ids combinations
    next_group_index = 0

    for test_id, instances in sorted(test_to_instances.items()):
        candidate_rewrites = []
        for instance_id in instances:
            fn = instance_to_candidate.get(instance_id)
            if not fn:
                continue
            rewrite = _empty_body_rewrite(fn.src_code)
            if rewrite:
                candidate_rewrites.append((instance_id, fn, rewrite))

        if len(candidate_rewrites) <= 1:
            continue

        patches, map_entries, next_group_index = _generate_same_file_combined_patches(
            repo_dir,
            repo,
            test_id,
            candidate_rewrites,
            seen_instance_ids,
            next_group_index,
        )
        combined_patches.extend(patches)
        combined_map.update(map_entries)

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
        "pruned_instances": len(pruned_instances),
        "max_tests_per_line": max_tests_per_line,
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
    parser.add_argument(
        "--max_tests_per_line",
        type=float,
        default=3,
        help="Prune instances where failing tests / function line count exceeds this threshold.",
    )
    args = parser.parse_args()
    main(**vars(args))