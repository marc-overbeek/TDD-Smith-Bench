"""Regenerate function bodies from failing empty-body tests using an LLM.

Pipeline:
1) Load pre-existing empty-body validation instances from `_function_map.json` and `report.json`.
2) Filter for instances with failing tests (FAIL_TO_PASS).
3) Prompt an LLM with the failing tests, function signature, and empty-body file context.
4) Reconstruct the patch with the LLM's generated AST.
5) Save the diffs to `logs/bug_gen/<repo>`.

Usage:
  uv run python scripts/generate_regen_from_tests.py \
      Instagram__MonkeyType.70c3acf6 \
      --model ollama/gpt-oss:120b
"""

import argparse
import ast
import astor
import difflib
import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
import yaml
from typing import Any

import litellm
from litellm import completion
from litellm.cost_calculator import completion_cost
from tqdm import tqdm

from swesmith.bug_gen.llm.utils import PROMPT_KEYS, extract_code_block
from swesmith.bug_gen.utils import generate_patch_fast
from swesmith.constants import LOG_DIR_BUG_GEN, PREFIX_BUG, PREFIX_METADATA, BugRewrite, CodeEntity, KEY_PATCH
from swesmith.profiles import registry
from swebench.harness.constants import FAIL_TO_PASS, KEY_INSTANCE_ID


def _get_model_id(model: str) -> str:
    """Extract a filesystem-safe model identifier from a model string.
    
    Examples:
      'gpt-4' -> 'gpt-4'
      'ollama/gpt-oss:120b' -> 'ollama_gpt-oss_120b'
      'claude-3-opus' -> 'claude-3-opus'
    """
    # Replace special characters with underscores to make it filesystem-safe
    model_id = model.replace("/", "_").replace(":", "_").replace("-", "_")
    return model_id


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


def _get_test_source(repo_dir: str, test_id: str) -> str:
    """Attempt to extract the source code of a failing test function."""
    parts = test_id.split("::")
    if len(parts) < 2:
        return test_id
    
    file_path = Path(repo_dir) / parts[0]
    if not file_path.exists() or file_path.suffix != ".py":
        return test_id

    func_name = parts[-1]
    try:
        tree = ast.parse(file_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return astor.to_source(node).strip()
    except Exception:
        pass
    return test_id


def _get_base_hash(repo: str, instance_id: str) -> str:
    prefix = f"{repo}."
    if instance_id.startswith(prefix):
        return instance_id[len(prefix):]
    return instance_id


def _regen_instance_id(repo: str, base_hash: str, attempt: int) -> str:
    return f"{repo}.lm_regen_from_tests__{base_hash}__attempt_{attempt}"


def _load_previous_rewrite(
    func_dir: Path, configs_name: str, base_hash: str, attempt: int
) -> str | None:
    if attempt <= 1:
        return None

    # func_dir structure: log_dir/file__path.py/attemptN/function_name_hash
    # Navigate to previous attempt: log_dir/file__path.py/attempt(N-1)/function_name_hash
    prev_attempt_dir = func_dir.parent.parent / f"attempt{attempt - 1}"
    prev_func_dir = prev_attempt_dir / func_dir.name
    
    if not prev_func_dir.exists():
        return None

    meta_path = prev_func_dir / f"{PREFIX_METADATA}__{configs_name}__{base_hash}.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text())
            return data.get("rewrite")
        except Exception:
            pass

    # Fallback: check if rewrite exists in any .json in previous attempt
    for meta_file in prev_func_dir.glob(f"{PREFIX_METADATA}__*.json"):
        try:
            data = json.loads(meta_file.read_text())
            return data.get("rewrite")
        except Exception:
            pass

    return None


def _load_test_case_map(repo: str) -> dict[str, dict]:
    test_case_map_path = Path("logs/change_logs") / repo / "_test_case_map.json"
    if not test_case_map_path.exists():
        print(f"Test case map not found at {test_case_map_path}. Cannot load combined instance mappings.")
        return {}
    return json.loads(test_case_map_path.read_text())


def _build_combined_file_sources(repo_dir: Path, candidates: list, rewrites: dict[tuple[str, str, int], str]) -> str:
    file_sources: dict[Path, str] = {}
    file_groups: dict[Path, list] = {}
    for candidate in candidates:
        file_path = Path(candidate.file_path)
        file_groups.setdefault(file_path, []).append(candidate)
        if file_path not in file_sources:
            file_sources[file_path] = file_path.read_text()

    for file_path, group in file_groups.items():
        modified = file_sources[file_path]
        for candidate in sorted(group, key=lambda c: c.line_start, reverse=True):
            key = (candidate.file_path, candidate.name, candidate.line_start)
            rewrite = rewrites.get(key)
            if not rewrite:
                continue
            modified = modified.replace(candidate.src_code, rewrite, 1)
        file_sources[file_path] = modified

    output = []
    for file_path in sorted(file_sources):
        rel_path = file_path.relative_to(repo_dir)
        output.append(f"--- file: {rel_path} ---")
        output.append(file_sources[file_path])
    return "\n".join(output)


def _save_llm_issue(log_dir: Path, repo: str, regen_instance_id: str, attempt: int, mode: str, message_content: str, prompt_messages: list[dict], error: str) -> Path:
    issue_dir = log_dir / "issues"
    issue_dir.mkdir(parents=True, exist_ok=True)
    issue_path = issue_dir / f"{regen_instance_id}__attempt_{attempt}__{mode}.json"
    issue_data = {
        "repo": repo,
        "instance_id": regen_instance_id,
        "attempt": attempt,
        "mode": mode,
        "error": error,
        "prompt_messages": prompt_messages,
        "response_content": message_content,
    }
    issue_path.write_text(json.dumps(issue_data, indent=2))
    return issue_path


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


def _extract_function_rewrites_from_code_block(code_block: str, candidates: list):
    def parse_with_ast(text: str):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        entries = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                src = ast.get_source_segment(text, node)
                if src:
                    entries.append((node.name, src))
        return entries if entries else None

    def normalize_code_block(text: str) -> str:
        if '```' not in text:
            return text
        blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        return "\n\n".join(blocks)

    def parse_with_regex(text: str):
        cleaned = normalize_code_block(text)

        pattern = re.compile(
            r"(?ms)^(?:@.*\n)*\s*(?:async\s+)?def\s+(\w+)\s*\(.*?(?=^(?:@.*\n)*\s*(?:async\s+)?def\s+\w+\s*\(|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        entries = []
        for match in pattern.finditer(cleaned):
            func_name = match.group(1)
            entries.append((func_name, match.group(0).rstrip()))
        return entries

    def extract_signature(src: str) -> str | None:
        match = re.search(
            r"^\s*(?:@.*\n\s*)*(?:async\s+)?(def\s+[^(\s]+\s*\(.*?\))\s*:",
            src,
            re.MULTILINE | re.DOTALL,
        )
        if not match:
            return None
        return re.sub(r"\s+", " ", match.group(1).strip())

    def normalize_signature(sig: str | None) -> str | None:
        if sig is None:
            return None
        return re.sub(r"\s+", " ", sig.strip())

    def find_entries():
        cleaned = normalize_code_block(code_block)
        entries = parse_with_ast(cleaned)
        if entries is not None:
            return entries

        match = re.search(r"(^\s*(?:@.*\n)*\s*(?:async\s+)?def\s+\w+\s*\()", cleaned, re.M)
        if match:
            start = match.start()
            entries = parse_with_ast(cleaned[start:])
            if entries is not None:
                return entries

        return parse_with_regex(cleaned)

    entries = find_entries()
    if entries is None:
        return None

    candidates_by_name: dict[str, list] = {}
    for candidate in sorted(
        candidates,
        key=lambda c: (getattr(c, "file_path", ""), getattr(c, "line_start", 0)),
    ):
        candidates_by_name.setdefault(candidate.name, []).append(candidate)

    result = []
    for name, src in entries:
        if name not in candidates_by_name or not candidates_by_name[name]:
            return None

        signature = extract_signature(src)
        chosen_candidate = None

        if signature is not None:
            normalized_signature = normalize_signature(signature)
            for candidate in candidates_by_name[name]:
                candidate_signature = normalize_signature(getattr(candidate, "signature", None))
                if candidate_signature and candidate_signature.endswith(normalized_signature):
                    chosen_candidate = candidate
                    break

        if chosen_candidate is None:
            chosen_candidate = candidates_by_name[name][0]

        result.append((chosen_candidate, src))
        candidates_by_name[name].remove(chosen_candidate)

    return result


def _annotate_exact_match(rewrite: str) -> str:
    lines = rewrite.rstrip().splitlines()
    if not lines:
        return rewrite

    indent = None
    for line in lines[1:]:
        stripped = line.lstrip(" ")
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            break
    if indent is None:
        indent = 4

    comment_line = " " * indent + "# this is an exact match"
    if lines[-1].strip() == "":
        return rewrite.rstrip() + "\n" + comment_line
    return rewrite.rstrip() + "\n" + comment_line


def _load_previous_combined_rewrite(log_dir: Path, configs_name: str, base_hash: str, attempt: int) -> str | None:
    if attempt <= 1:
        return None

    prev_meta_path = (
        log_dir
        / "combined"
        / f"attempt{attempt - 1}"
        / base_hash
        / f"{PREFIX_METADATA}__{configs_name}__{base_hash}.json"
    )
    if not prev_meta_path.exists():
        return None

    try:
        data = json.loads(prev_meta_path.read_text())
        return data.get("rewrite")
    except Exception:
        return None


def _write_patches_json(patches: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(patches, f, indent=4)


def _validate_patches(patches_file: Path, workers: int) -> None:
    subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "swesmith.harness.valid",
            str(patches_file),
            "--workers",
            str(workers),
            "--redo_existing",
        ],
        check=True,
    )


def main(
    repo: str,
    config_file: str,
    model: str,
    max_bugs: int = -1,
    max_attempts: int = 1,
    workers: int = 4,
    include_combined: bool = False,
    combined_only: bool = False,
    combined_config_file: str = "configs/bug_gen/lm_regen_from_tests_combined.yml",
    **kwargs,
):
    # Extract model ID for directory organization
    model_id = _get_model_id(model)
    
    # 1. Load config
    with open(config_file) as f:
        configs = yaml.safe_load(f)

    combined_configs = {}
    if include_combined or combined_only:
        combined_config_path = Path(combined_config_file)
        if not combined_config_path.exists():
            print(f"Combined config file not found: {combined_config_path}")
            return
        with open(combined_config_path) as f:
            combined_configs = yaml.safe_load(f)

    # 2. Get original repo entities
    print(f"Extracting entities from {repo}...")
    rp = registry.get(repo)
    repo_dir, _ = rp.clone()
    entities = rp.extract_entities(exclude_tests=True)
    
    # Map candidates by relative file_path + function_name + line_start for exact lookup
    entity_map = {}
    for e in entities:
        if getattr(e, "is_function", False):
            rel_path = str(Path(e.file_path).resolve().relative_to(Path(repo_dir).resolve()))
            entity_map[(rel_path, e.name, e.line_start)] = e

    # 3. Read function map and run validation reports
    change_logs_dir = Path("logs/change_logs") / repo
    map_path = change_logs_dir / "_function_map.json"
    
    if not map_path.exists():
        print(f"Function map {map_path} not found. Run generate_empty_body_changes.py first.")
        return

    fn_map = json.loads(map_path.read_text())
    run_val_dir = Path("logs/run_validation") / repo

    log_dir = LOG_DIR_BUG_GEN / repo / model_id
    log_dir.mkdir(parents=True, exist_ok=True)

    combined_map = {}
    if combined_only or include_combined:
        combined_map = _load_test_case_map(repo)
        if combined_only and not combined_map:
            print(
                f"Combined test case map not found at {Path('logs/change_logs') / repo / '_test_case_map.json'}."
            )
            return

    broken_candidates = []
    if not combined_only:
        for instance_id, fn_info in tqdm(fn_map.items(), desc="Collecting broken instances", unit="instance"):
            report_path = run_val_dir / instance_id / "report.json"
            if not report_path.exists():
                continue

            report = json.loads(report_path.read_text())
            broken = report.get(FAIL_TO_PASS, [])
            if len(broken) == 0:
                continue

            rel_file_path = fn_info["file_path"]
            candidate = entity_map.get(
                (rel_file_path, fn_info["function_name"], fn_info["line_start"])
            )
            if not candidate:
                fallback = [
                    v
                    for k, v in entity_map.items()
                    if k[0] == rel_file_path and k[1] == fn_info["function_name"]
                ]
                if fallback:
                    candidate = fallback[0]
                else:
                    tqdm.write(
                        f"Candidate not found for {fn_info['file_path']}::{fn_info['function_name']}"
                    )
                    continue

            empty_func_src = _empty_body_rewrite(candidate.src_code)
            if not empty_func_src:
                tqdm.write(
                    f"Could not parse AST for empty body replacement in {instance_id}"
                )
                continue

            original_file_content = open(candidate.file_path).read()
            broken_test_details = []
            for test in broken:
                src = _get_test_source(repo_dir, test)
                if src and src != test:
                    broken_test_details.append(f"--- {test} ---\n```python\n{src}\n```")
                else:
                    broken_test_details.append(f"--- {test} ---")

            broken_candidates.append(
                {
                    "mode": "individual",
                    "instance_id": instance_id,
                    "base_hash": _get_base_hash(repo, instance_id),
                    "fn_info": fn_info,
                    "candidate": candidate,
                    "empty_func_src": empty_func_src,
                    "original_file_content": original_file_content,
                    "broken_tests": broken_test_details,
                }
            )

    if include_combined or combined_only:
        for instance_id, combined_info in sorted(combined_map.items()):
            instance_ids = combined_info.get("instance_ids", [])
            if not instance_ids:
                continue

            file_candidates = []
            instance_fns = []
            for original_id in instance_ids:
                fn_info = fn_map.get(original_id)
                if not fn_info:
                    continue

                rel_file_path = fn_info["file_path"]
                candidate = entity_map.get(
                    (rel_file_path, fn_info["function_name"], fn_info["line_start"])
                )
                if not candidate:
                    fallback = [
                        v
                        for k, v in entity_map.items()
                        if k[0] == rel_file_path and k[1] == fn_info["function_name"]
                    ]
                    if fallback:
                        candidate = fallback[0]
                    else:
                        tqdm.write(
                            f"Candidate not found for combined instance {original_id}"
                        )
                        continue

                empty_func_src = _empty_body_rewrite(candidate.src_code)
                if not empty_func_src:
                    tqdm.write(
                        f"Could not parse AST for empty body replacement in combined instance {instance_id}"
                    )
                    continue

                file_candidates.append(candidate)
                instance_fns.append(fn_info)

            if not file_candidates:
                continue

            report_path = run_val_dir / instance_id / "report.json"
            if not report_path.exists():
                continue
            report = json.loads(report_path.read_text())
            broken = report.get(FAIL_TO_PASS, [])
            if len(broken) == 0:
                continue

            broken_test_details = []
            for test in broken:
                src = _get_test_source(repo_dir, test)
                if src and src != test:
                    broken_test_details.append(f"--- {test} ---\n```python\n{src}\n```")
                else:
                    broken_test_details.append(f"--- {test} ---")

            broken_candidates.append(
                {
                    "mode": "combined",
                    "instance_id": instance_id,
                    "base_hash": _get_base_hash(repo, instance_id),
                    "fn_infos": instance_fns,
                    "candidates": file_candidates,
                    "broken_tests": broken_test_details,
                }
            )

    if len(broken_candidates) == 0:
        print("No failing functions found for regeneration.")
        return

    attempt = 1
    total_generated = 0
    while attempt <= max_attempts and broken_candidates:
        tqdm.write(
            f"Attempt {attempt}/{max_attempts}: regenerating {len(broken_candidates)} broken functions"
        )
        current_patches = []
        patches_file = log_dir / f"{repo}_lm_regen_from_tests_attempt_{attempt}_patches.json"

        for broken_info in tqdm(
            broken_candidates,
            desc=f"Generating attempt {attempt}",
            unit="function",
        ):
            instance_id = broken_info["instance_id"]
            base_hash = broken_info["base_hash"]
            broken_test_details = broken_info["broken_tests"]
            mode = broken_info["mode"]

            if mode == "individual":
                fn_info = broken_info["fn_info"]
                candidate = broken_info["candidate"]
                empty_func_src = broken_info["empty_func_src"]
                original_file_content = broken_info["original_file_content"]

                file_dir = log_dir / candidate.file_path.replace("/", "__")
                attempt_dir = file_dir / f"attempt{attempt}"
                signature_hash = hashlib.sha256(candidate.signature.encode()).hexdigest()[:8]
                func_dir = attempt_dir / f"{candidate.name}_{signature_hash}"

                prev_rewrite = _load_previous_rewrite(
                    func_dir,
                    configs["name"],
                    base_hash,
                    attempt,
                )

                if attempt == 1 or not prev_rewrite:
                    func_src_code = empty_func_src
                    file_src_code = original_file_content.replace(
                        candidate.src_code, empty_func_src
                    )
                    previous_attempt = ""
                else:
                    func_src_code = prev_rewrite
                    file_src_code = original_file_content.replace(
                        candidate.src_code, prev_rewrite
                    )
                    previous_attempt = (
                        f"Previous generation attempt #{attempt - 1}:\n"
                        "```python\n"
                        f"{prev_rewrite}\n"
                        "```\n"
                    )

                prompt_content = {
                    "instance_id": instance_id,
                    "broken_tests": "\n\n".join(broken_test_details),
                    "func_signature": candidate.signature,
                    "func_src_code": func_src_code,
                    "file_src_code": file_src_code,
                    "previous_attempt": previous_attempt,
                }
            else:
                candidates = broken_info["candidates"]
                file_dir = log_dir / "combined" / f"attempt{attempt}" / base_hash
                func_dir = file_dir

                prev_rewrite = _load_previous_combined_rewrite(
                    log_dir,
                    combined_configs.get("name", configs["name"]),
                    base_hash,
                    attempt,
                )

                current_rewrites = {}
                if attempt == 1 or not prev_rewrite:
                    rewritten_blocks = []
                    for candidate in candidates:
                        empty_code = _empty_body_rewrite(candidate.src_code)
                        if not empty_code:
                            empty_code = candidate.src_code
                        rewritten_blocks.append(empty_code)
                        current_rewrites[(candidate.file_path, candidate.name, candidate.line_start)] = empty_code
                    func_src_code = "\n\n".join(rewritten_blocks)
                    file_src_code = _build_combined_file_sources(repo_dir, candidates, current_rewrites)
                    previous_attempt = ""
                else:
                    func_src_code = prev_rewrite
                    extracted = _extract_function_rewrites_from_code_block(prev_rewrite, candidates)
                    if extracted is None:
                        file_rewrites = {}
                    else:
                        file_rewrites = {
                            (c.file_path, c.name, c.line_start): rewrite
                            for c, rewrite in extracted
                        }
                    file_src_code = _build_combined_file_sources(repo_dir, candidates, file_rewrites)
                    previous_attempt = (
                        f"Previous generation attempt #{attempt - 1}:\n"
                        "```python\n"
                        f"{prev_rewrite}\n"
                        "```\n"
                    )

                prompt_content = {
                    "instance_id": instance_id,
                    "broken_tests": "\n\n".join(broken_test_details),
                    "func_signatures": "\n\n".join([c.signature for c in candidates]),
                    "func_src_code": func_src_code,
                    "file_src_code": file_src_code,
                    "previous_attempt": previous_attempt,
                }

            prompt_configs = combined_configs if mode == "combined" else configs
            messages = [
                {
                    "content": prompt_configs[k].format(**prompt_content),
                    "role": "system" if k == "system" else "user",
                }
                for k in PROMPT_KEYS
                if k in prompt_configs
            ]

            regen_instance_id = _regen_instance_id(repo, base_hash, attempt)
            tqdm.write(
                f"Generating fix for {regen_instance_id} with {len(broken_test_details)} broken tests..."
            )

            # Check if patch already exists for this instance
            if mode == "individual":
                candidate = broken_info["candidate"]
                file_dir = log_dir / candidate.file_path.replace("/", "__")
                attempt_dir = file_dir / f"attempt{attempt}"
                signature_hash = hashlib.sha256(candidate.signature.encode()).hexdigest()[:8]
                func_dir = attempt_dir / f"{candidate.name}_{signature_hash}"
                strategy_name = configs["name"]
            else:
                candidates = broken_info["candidates"]
                file_dir = log_dir / "combined" / f"attempt{attempt}" / base_hash
                func_dir = file_dir
                strategy_name = combined_configs.get("name", configs["name"])

            uuid_str = f"{strategy_name}__{base_hash}"
            expected_patch_path = func_dir / f"{PREFIX_BUG}__{uuid_str}.diff"
            if expected_patch_path.exists():
                tqdm.write(f"Skipping {regen_instance_id}, patch already exists at {expected_patch_path}")
                continue

            try:
                response: Any = completion(
                    model=model, messages=messages, n=1, temperature=0.0
                )
            except Exception as e:
                tqdm.write(f"Failed LLM generation for {regen_instance_id}: {e}")
                continue

            choice = response.choices[0]
            message = choice.message
            code_block = extract_code_block(message.content)

            explanation = ""
            if "Explanation:" in message.content:
                explanation = message.content.split("Explanation:")[-1].split("```")[0].strip()
            else:
                explanation = message.content.split("```", 1)[0].strip()

            try:
                cost = completion_cost(completion_response=response)
            except Exception:
                cost = 0.0

            if mode == "individual":
                rewrite_obj = BugRewrite(
                    rewrite=code_block,
                    explanation=explanation,
                    strategy=configs["name"],
                    cost=cost,
                    output=message.content,
                    model=model,
                )

                patch = generate_patch_fast(candidate, rewrite_obj, repo_dir)
                if not patch or len(patch.strip()) == 0:
                    code_block = _annotate_exact_match(code_block)
                    rewrite_obj = BugRewrite(
                        rewrite=code_block,
                        explanation=explanation,
                        strategy=configs["name"],
                        cost=cost,
                        output=message.content,
                        model=model,
                    )
                    patch = generate_patch_fast(candidate, rewrite_obj, repo_dir)
                    if not patch or len(patch.strip()) == 0:
                        tqdm.write(
                            f"Skipping {regen_instance_id}, generated exact matching diff or unable to format."
                        )
                        continue
                    tqdm.write(
                        f"Created an exact-match annotated patch for {regen_instance_id}."
                    )
            else:
                candidates = broken_info["candidates"]
                extracted = _extract_function_rewrites_from_code_block(code_block, candidates)
                if extracted is None:
                    issue_path = _save_llm_issue(
                        log_dir,
                        repo,
                        regen_instance_id,
                        attempt,
                        "combined",
                        message.content,
                        messages,
                        "unable to parse combined function rewrites",
                    )
                    tqdm.write(
                        f"Skipping {regen_instance_id}, unable to parse combined function rewrites. Saved issue to {issue_path}"
                    )
                    tqdm.write(f"Generated content:\n{code_block}")
                    continue

                patch = _generate_combined_patch(repo_dir, extracted, repo)
                if not patch or len(patch.strip()) == 0:
                    extracted = [
                        (candidate, _annotate_exact_match(rewrite))
                        for candidate, rewrite in extracted
                    ]
                    patch = _generate_combined_patch(repo_dir, extracted, repo)
                    if not patch or len(patch.strip()) == 0:
                        tqdm.write(
                            f"Skipping {regen_instance_id}, generated exact matching combined diff or unable to format."
                        )
                        continue
                    tqdm.write(
                        f"Created an exact-match annotated combined patch for {regen_instance_id}."
                    )

                rewrite_obj = BugRewrite(
                    rewrite=code_block,
                    explanation=explanation,
                    strategy=combined_configs.get("name", configs["name"]),
                    cost=cost,
                    output=message.content,
                    model=model,
                )

            func_dir.mkdir(parents=True, exist_ok=True)

            meta_path = func_dir / f"{PREFIX_METADATA}__{uuid_str}.json"
            patch_path = func_dir / f"{PREFIX_BUG}__{uuid_str}.diff"

            with open(meta_path, "w") as f:
                json.dump(rewrite_obj.to_dict(), f, indent=2)
            with open(patch_path, "w") as f:
                f.write(patch)

            current_patches.append(
                {
                    KEY_INSTANCE_ID: regen_instance_id,
                    KEY_PATCH: patch,
                    "repo": repo,
                }
            )
            tqdm.write(f"Saved generated patch to {patch_path}")
            total_generated += 1

            if max_bugs != -1 and total_generated >= max_bugs:
                break

        if len(current_patches) == 0:
            print(f"No regenerated patches were produced in attempt {attempt}.")
            break

        _write_patches_json(current_patches, patches_file)
        _validate_patches(patches_file, workers)

        remaining = []
        for broken_info in broken_candidates:
            base_hash = broken_info["base_hash"]
            regen_instance_id = _regen_instance_id(repo, base_hash, attempt)
            report_path = run_val_dir / regen_instance_id / "report.json"
            if not report_path.exists():
                remaining.append(broken_info)
                continue
            report = json.loads(report_path.read_text())
            if len(report.get(FAIL_TO_PASS, [])) > 0:
                remaining.append(broken_info)

        if not remaining:
            print(
                f"All regenerated functions passed by attempt {attempt}."
            )
            break

        print(
            f"{len(remaining)} functions still failing after attempt {attempt}."
        )
        broken_candidates = remaining
        attempt += 1

    print(f"Done! Generated patches for {total_generated} attempts across functions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerate functions from from-scratch failing tests.")
    parser.add_argument("repo", type=str, help="Repository to generate bug patches for.")
    parser.add_argument(
        "--config_file", 
        type=str, 
        default="configs/bug_gen/lm_regen_from_tests.yml",
        help="Path to the system prompt configuration YAML."
    )
    parser.add_argument(
        "--model", 
        type=str, 
        default="ollama/gpt-oss:120b",
        help="Model string to use via litellm."
    )
    parser.add_argument(
        "--max_bugs",
        type=int,
        default=-1,
        help="Limit number of bugs to regenerate (-1 for unlimited)."
    )
    parser.add_argument(
        "--max_attempts",
        type=int,
        default=2,
        help="Maximum number of regeneration attempts for still-failing functions."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Worker count to use for validation runs."
    )
    parser.add_argument(
        "--include_combined",
        action="store_true",
        help="Include combined test-case regeneration alongside individual function regeneration."
    )
    parser.add_argument(
        "--combined_only",
        action="store_true",
        help="Regenerate only combined test-case patches."
    )
    parser.add_argument(
        "--combined_config_file",
        type=str,
        default="configs/bug_gen/lm_regen_from_tests_combined.yml",
        help="Path to the combined prompt configuration YAML."
    )
    args = parser.parse_args()
    main(**vars(args))