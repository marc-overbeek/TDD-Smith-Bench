#!/usr/bin/env python3
"""Compute patch-level LOC and complexity deltas for LM regeneration patches.

This script reads generated patch manifests from logs/bug_gen/<repo>/<model>,
links each patch to function metadata in logs/change_logs/<repo>, optionally
joins validation reports from logs/run_validation/<repo>/<model>, and writes one
JSON output per repo/model in results.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import tempfile
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_EXTS = {".py"}


ROOT = Path(__file__).resolve().parents[1]
BUG_ROOT = ROOT / "logs" / "bug_gen"
CHANGE_ROOT = ROOT / "logs" / "change_logs"
VAL_ROOT = ROOT / "logs" / "run_validation"
RESULTS_ROOT = ROOT / "results/metrics"


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
ATTEMPT_RE = re.compile(r"__attempt_(\d+)$")


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass
class FilePatch:
    old_path: str
    new_path: str
    hunks: list[Hunk]


@dataclass
class SimpleEntity:
    name: str
    line_start: int
    complexity: int


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _discover_repos() -> list[str]:
    if not BUG_ROOT.exists() or not CHANGE_ROOT.exists():
        return []
    bug_repos = {p.name for p in BUG_ROOT.iterdir() if p.is_dir()}
    change_repos = {p.name for p in CHANGE_ROOT.iterdir() if p.is_dir()}
    return sorted(bug_repos.intersection(change_repos))


def _discover_models(repo: str) -> list[str]:
    repo_dir = BUG_ROOT / repo
    if not repo_dir.exists():
        return []
    return sorted([p.name for p in repo_dir.iterdir() if p.is_dir()])


def _extract_attempt(instance_id: str) -> int | None:
    match = ATTEMPT_RE.search(instance_id)
    return int(match.group(1)) if match else None


def _base_empty_instance_id(repo: str, instance_id: str) -> str | None:
    marker = ".lm_regen_from_tests__"
    if marker not in instance_id:
        return None

    tail = instance_id.split(marker, 1)[1]
    tail = tail.split("__model_", 1)[0]
    tail = tail.split("__attempt_", 1)[0]
    return f"{repo}.{tail}"


def _model_scoped_instance_id(instance_id: str, model: str) -> str:
    if "__model_" in instance_id:
        return instance_id
    if "__attempt_" not in instance_id:
        return instance_id
    prefix, attempt = instance_id.rsplit("__attempt_", 1)
    return f"{prefix}__model_{model}__attempt_{attempt}"


def _parse_unified_diff(patch_text: str) -> list[FilePatch]:
    lines = patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    parsed: list[FilePatch] = []

    while i < len(lines):
        line = lines[i]
        if not line.startswith("--- "):
            i += 1
            continue

        old_path = line[4:].strip()
        old_path = old_path[2:] if old_path.startswith("a/") else old_path

        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            continue

        new_path = lines[i][4:].strip()
        new_path = new_path[2:] if new_path.startswith("b/") else new_path
        i += 1

        hunks: list[Hunk] = []
        while i < len(lines):
            if lines[i].startswith("--- "):
                break

            header = lines[i]
            match = HUNK_RE.match(header)
            if not match:
                i += 1
                continue

            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            i += 1

            hunk_lines: list[str] = []
            while i < len(lines):
                next_line = lines[i]
                if next_line.startswith("@@ ") or next_line.startswith("--- "):
                    break
                if next_line.startswith("\\ No newline at end of file"):
                    i += 1
                    continue
                hunk_lines.append(next_line)
                i += 1

            hunks.append(Hunk(old_start, old_count, new_start, new_count, hunk_lines))

        parsed.append(FilePatch(old_path=old_path, new_path=new_path, hunks=hunks))

    return parsed


def _line_has_python_code(line: str) -> bool:
    """Return True when a single logical line contains non-comment Python code."""
    if not line.strip():
        return False

    try:
        tokens = tokenize.generate_tokens(io.StringIO(line + "\n").readline)
        for tok_type, tok_str, _, _, _ in tokens:
            if tok_type in {
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
                tokenize.ENDMARKER,
            }:
                continue
            if tok_str.strip():
                return True
    except (tokenize.TokenError, IndentationError, SyntaxError):
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("#")
    except Exception:
        stripped = line.strip()
        return bool(stripped) and not stripped.startswith("#")

    return False


def _update_py_comment_block_state(line: str, in_block_comment: bool) -> tuple[str, bool]:
    """Track triple-quoted standalone comment/docstring blocks across diff hunk lines."""
    stripped = line.lstrip()

    if in_block_comment:
        if '"""' in stripped or "'''" in stripped:
            quote = '"""' if '"""' in stripped else "'''"
            _, _, after = stripped.partition(quote)
            return after, False
        return "", True

    if stripped.startswith('"""') or stripped.startswith("'''"):
        quote = stripped[:3]
        after = stripped[3:]
        if quote in after:
            _, _, tail = after.partition(quote)
            return tail, False
        return "", True

    return line, False


def _loc_from_patch(file_patches: list[FilePatch]) -> tuple[int, int, int]:
    added = 0
    removed = 0

    for fp in file_patches:
        rel_path = fp.new_path or fp.old_path
        is_python = Path(rel_path).suffix.lower() == ".py" if rel_path else False

        old_in_block_comment = False
        new_in_block_comment = False

        for hunk in fp.hunks:
            for raw in hunk.lines:
                prefix = raw[0] if raw else " "
                payload = raw[1:] if raw else ""

                if not is_python:
                    if prefix == "+":
                        added += 1
                    elif prefix == "-":
                        removed += 1
                    continue

                if prefix in {" ", "-"}:
                    old_payload, old_in_block_comment = _update_py_comment_block_state(
                        payload, old_in_block_comment
                    )
                    if prefix == "-" and not old_in_block_comment and _line_has_python_code(old_payload):
                        removed += 1

                if prefix in {" ", "+"}:
                    new_payload, new_in_block_comment = _update_py_comment_block_state(
                        payload, new_in_block_comment
                    )
                    if prefix == "+" and not new_in_block_comment and _line_has_python_code(new_payload):
                        added += 1

    return added, removed, added - removed


def _apply_file_patch(original_text: str, file_patch: FilePatch) -> str:
    original_lines = original_text.splitlines(keepends=True)
    rebuilt: list[str] = []
    original_idx = 0

    for hunk in file_patch.hunks:
        target_idx = max(hunk.old_start - 1, 0)
        rebuilt.extend(original_lines[original_idx:target_idx])
        idx = target_idx

        for raw in hunk.lines:
            if not raw:
                prefix = " "
                payload = ""
            else:
                prefix = raw[0]
                payload = raw[1:]

            if prefix == " ":
                if idx < len(original_lines):
                    rebuilt.append(original_lines[idx])
                    idx += 1
                else:
                    rebuilt.append(payload + "\n")
            elif prefix == "-":
                if idx < len(original_lines):
                    idx += 1
            elif prefix == "+":
                rebuilt.append(payload + "\n")

        original_idx = idx

    rebuilt.extend(original_lines[original_idx:])
    return "".join(rebuilt)


def _extract_targets(
    base_id: str,
    function_map: dict[str, dict[str, Any]],
    test_case_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if base_id in function_map:
        entry = function_map[base_id]
        return [{"instance_id": base_id, **entry}]

    if base_id in test_case_map:
        targets: list[dict[str, Any]] = []
        for member_id in test_case_map[base_id].get("instance_ids", []):
            if member_id in function_map:
                targets.append({"instance_id": member_id, **function_map[member_id]})
        return targets

    return []


def _parse_entities(file_path: Path) -> tuple[list[Any], str | None]:
    ext = file_path.suffix.lower()
    if ext != ".py":
        return [], "unsupported_extension"

    try:
        text = file_path.read_text()
    except Exception as exc:
        return [], f"read_error:{exc.__class__.__name__}"

    return _parse_python_entities(text)


def _python_complexity(node: ast.AST) -> int:
    complexity = 1
    for n in ast.walk(node):
        if isinstance(n, (ast.If, ast.While, ast.For)):
            complexity += 1
        elif isinstance(n, ast.BoolOp):
            complexity += len(n.values) - 1
        elif isinstance(n, ast.Try):
            complexity += len(n.handlers)
        elif isinstance(n, ast.Compare):
            complexity += len(n.ops)
    return complexity


def _parse_python_entities(text: str) -> tuple[list[Any], str | None]:
    entities: list[Any] = []
    try:
        tree = ast.parse(text)
    except Exception as exc:
        return [], f"parse_error:{exc.__class__.__name__}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            entities.append(
                SimpleEntity(
                    name=node.name,
                    line_start=getattr(node, "lineno", -1),
                    complexity=_python_complexity(node),
                )
            )

    return entities, None


def _closest_entity(entities: list[Any], name: str, line_start: int) -> Any | None:
    candidates = [e for e in entities if getattr(e, "name", None) == name]
    if not candidates:
        return None
    return min(candidates, key=lambda e: abs(getattr(e, "line_start", 10**9) - line_start))


def _validation_index(repo: str, model: str) -> dict[str, dict[str, Any]]:
    model_dir = VAL_ROOT / repo / model
    if not model_dir.exists():
        return {}

    out: dict[str, dict[str, Any]] = {}
    for child in model_dir.iterdir():
        if not child.is_dir():
            continue
        report_path = child / "report.json"
        if not report_path.exists():
            continue
        report = _load_json(report_path, {})
        if isinstance(report, dict):
            out[child.name] = report
    return out


def _build_rows_for_repo_model(
    repo: str,
    model: str,
    manifests: list[Path],
    function_map: dict[str, dict[str, Any]],
    test_case_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    repo_root = ROOT / repo
    validation = _validation_index(repo, model)

    original_entities_cache: dict[str, tuple[list[Any], str | None]] = {}
    original_text_cache: dict[str, str | None] = {}

    for manifest in manifests:
        entries = _load_json(manifest, [])
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            instance_id = entry.get("instance_id")
            patch_text = entry.get("patch")
            if not isinstance(instance_id, str) or not isinstance(patch_text, str):
                continue

            attempt = _extract_attempt(instance_id)
            base_id = _base_empty_instance_id(repo, instance_id)
            if base_id is None:
                continue

            targets = _extract_targets(base_id, function_map, test_case_map)
            target_by_file: dict[str, list[dict[str, Any]]] = {}
            for target in targets:
                target_by_file.setdefault(target["file_path"], []).append(target)

            file_patches = _parse_unified_diff(patch_text)
            lines_added, lines_removed, net_loc_change = _loc_from_patch(file_patches)

            baseline_sum = 0
            generated_sum = 0
            baseline_found = 0
            generated_found = 0
            complexity_supported = True
            parse_errors: list[str] = []

            for fp in file_patches:
                rel_path = fp.new_path or fp.old_path
                if not rel_path or rel_path not in target_by_file:
                    continue

                original_file_path = repo_root / rel_path
                ext = original_file_path.suffix.lower()
                if ext not in SUPPORTED_EXTS:
                    complexity_supported = False
                    continue

                if rel_path not in original_text_cache:
                    if original_file_path.exists():
                        original_text_cache[rel_path] = original_file_path.read_text()
                    else:
                        original_text_cache[rel_path] = None

                original_text = original_text_cache.get(rel_path)
                if original_text is None:
                    parse_errors.append(f"missing_source:{rel_path}")
                    continue

                if rel_path not in original_entities_cache:
                    original_entities_cache[rel_path] = _parse_entities(original_file_path)

                original_entities, original_err = original_entities_cache[rel_path]
                if original_err:
                    parse_errors.append(f"{rel_path}:{original_err}")
                    continue

                patched_text = _apply_file_patch(original_text, fp)
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=original_file_path.suffix, delete=True
                ) as tmp:
                    tmp.write(patched_text)
                    tmp.flush()
                    patched_entities, patched_err = _parse_entities(Path(tmp.name))

                if patched_err:
                    parse_errors.append(f"{rel_path}:{patched_err}")
                    continue

                for target in target_by_file.get(rel_path, []):
                    func_name = target.get("function_name")
                    line_start = int(target.get("line_start", -1))
                    if not isinstance(func_name, str) or line_start < 0:
                        continue

                    before = _closest_entity(original_entities, func_name, line_start)
                    after = _closest_entity(patched_entities, func_name, line_start)

                    if before is not None:
                        c_before = getattr(before, "complexity", -1)
                        if isinstance(c_before, int) and c_before >= 0:
                            baseline_sum += c_before
                            baseline_found += 1
                    if after is not None:
                        c_after = getattr(after, "complexity", -1)
                        if isinstance(c_after, int) and c_after >= 0:
                            generated_sum += c_after
                            generated_found += 1

            complexity_change = None
            if baseline_found > 0 and generated_found == baseline_found:
                complexity_change = generated_sum - baseline_sum

            validation_report = validation.get(instance_id)
            if validation_report is None:
                validation_report = validation.get(_model_scoped_instance_id(instance_id, model))

            fail_to_pass = []
            if isinstance(validation_report, dict):
                maybe_ftp = validation_report.get("FAIL_TO_PASS")
                if isinstance(maybe_ftp, list):
                    fail_to_pass = maybe_ftp

            target_functions = [
                f"{t.get('file_path', '<unknown>')}::{t.get('function_name', '<unknown>')}"
                for t in targets
            ]

            rows.append(
                {
                    "repo": repo,
                    "model": model,
                    "instance_id": instance_id,
                    "base_instance_id": base_id,
                    "attempt": attempt,
                    "manifest": str(manifest.relative_to(ROOT)),
                    "is_combined_patch": base_id in test_case_map,
                    "file_count": len(file_patches),
                    "target_function_count": len(target_functions),
                    "target_functions": target_functions,
                    "lines_added": lines_added,
                    "lines_removed": lines_removed,
                    "net_loc_change": net_loc_change,
                    "baseline_complexity_sum": baseline_sum if baseline_found > 0 else None,
                    "generated_complexity_sum": generated_sum if generated_found > 0 else None,
                    "complexity_change": complexity_change,
                    "baseline_found_count": baseline_found,
                    "generated_found_count": generated_found,
                    "complexity_supported": complexity_supported,
                    "parse_errors": sorted(set(parse_errors)),
                    "validation_report_found": validation_report is not None,
                    "fail_to_pass_count": len(fail_to_pass),
                }
            )

    rows.sort(
        key=lambda r: (
            r["repo"],
            r["model"],
            (r["attempt"] if r["attempt"] is not None else 999999),
            r["instance_id"],
        )
    )
    return rows


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "patch_count": 0,
            "avg_lines_added": 0.0,
            "avg_lines_removed": 0.0,
            "avg_net_loc_change": 0.0,
            "avg_complexity_change": None,
            "complexity_change_patch_count": 0,
            "validation_report_found_count": 0,
        }

    patch_count = len(rows)
    avg_added = sum(r["lines_added"] for r in rows) / patch_count
    avg_removed = sum(r["lines_removed"] for r in rows) / patch_count
    avg_net = sum(r["net_loc_change"] for r in rows) / patch_count

    complexity_values = [r["complexity_change"] for r in rows if isinstance(r["complexity_change"], int)]
    avg_complexity = None
    if complexity_values:
        avg_complexity = sum(complexity_values) / len(complexity_values)

    val_found = sum(1 for r in rows if r["validation_report_found"])

    return {
        "patch_count": patch_count,
        "avg_lines_added": avg_added,
        "avg_lines_removed": avg_removed,
        "avg_net_loc_change": avg_net,
        "avg_complexity_change": avg_complexity,
        "complexity_change_patch_count": len(complexity_values),
        "validation_report_found_count": val_found,
    }


def _write_output(repo: str, model: str, rows: list[dict[str, Any]]) -> Path:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_ROOT / f"{repo}__{model}_patch_metrics.json"
    payload = {
        "repo": repo,
        "model": model,
        "summary": _summary(rows),
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute LOC and complexity deltas for LM-generated patch manifests."
    )
    parser.add_argument("--repo", type=str, default=None, help="Optional single repo filter.")
    parser.add_argument("--model", type=str, default=None, help="Optional single model filter.")
    args = parser.parse_args()

    repos = [args.repo] if args.repo else _discover_repos()
    if not repos:
        print("No repositories found under logs/bug_gen and logs/change_logs")
        return

    generated: list[Path] = []

    for repo in repos:
        models = _discover_models(repo)
        if args.model:
            models = [m for m in models if m == args.model]
        if not models:
            print(f"[{repo}] No matching model directories found.")
            continue

        function_map = _load_json(CHANGE_ROOT / repo / "_function_map.json", {})
        test_case_map = _load_json(CHANGE_ROOT / repo / "_test_case_map.json", {})
        if not isinstance(function_map, dict):
            print(f"[{repo}] Invalid or missing _function_map.json")
            continue
        if not isinstance(test_case_map, dict):
            test_case_map = {}

        for model in models:
            model_dir = BUG_ROOT / repo / model
            manifests = sorted(model_dir.glob("*_lm_regen_from_tests_attempt_*_patches.json"))
            if not manifests:
                print(f"[{repo} | {model}] No LM patch manifests found.")
                continue

            rows = _build_rows_for_repo_model(
                repo=repo,
                model=model,
                manifests=manifests,
                function_map=function_map,
                test_case_map=test_case_map,
            )
            out_path = _write_output(repo, model, rows)
            generated.append(out_path)

            summary = _summary(rows)
            print(
                f"[{repo} | {model}] patches={summary['patch_count']} "
                f"avg_net_loc_change={summary['avg_net_loc_change']:.2f} "
                f"complexity_rows={summary['complexity_change_patch_count']}"
            )
            print(f"[{repo} | {model}] wrote {out_path}")

    if generated:
        print("\nGenerated metric files:")
        for path in generated:
            print(f"- {path}")
    else:
        print("No output files generated.")


if __name__ == "__main__":
    main()
