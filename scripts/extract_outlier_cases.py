#!/usr/bin/env python3
"""Select patch-metric outliers and map each case across models.

This script identifies the top N global outliers by absolute net LOC change and
absolute complexity change from results/metrics/*_patch_metrics.json, then maps
each selected outlier case to all available models.

For each model-case pair, the script attaches:
- metric deltas
- success/failure derived from results/*_test_comparison.json
- generated patch text extracted from the patch manifest referenced by the row
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

METRICS_SUFFIX = "_patch_metrics.json"
RESULT_SUFFIX = "_test_comparison.json"

MODEL_LABELS = {
    "wxnknl6gvktb": "Claude Haiku 4.5",
    "ql4mbrrqznnz": "Claude Sonnet 4.6",
    "gewiaj6mtzjm": "Qwen3 Coder 30B",
}


@dataclass(frozen=True)
class CaseKey:
    repo: str
    base_instance_id: str
    attempt: int


def parse_repo_model_filename(path: Path, suffix: str) -> tuple[str, str] | None:
    name = path.name
    if not name.endswith(suffix):
        return None

    stem = name[: -len(suffix)]
    parts = stem.split("__", 2)
    if len(parts) != 3:
        return None
    return f"{parts[0]}__{parts[1]}", parts[2]


def model_label(model_id: str) -> str:
    for suffix, label in MODEL_LABELS.items():
        if model_id.endswith(suffix):
            return label
    return model_id


def metric_join_key(row: dict[str, Any]) -> str | None:
    if row.get("is_combined_patch"):
        base_instance_id = row.get("base_instance_id")
        if isinstance(base_instance_id, str) and base_instance_id:
            return f"combined::{base_instance_id}"
        return None

    target_functions = row.get("target_functions")
    if not isinstance(target_functions, list) or len(target_functions) != 1:
        return None

    function_name = target_functions[0]
    return function_name if isinstance(function_name, str) and function_name else None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_success_lookup(results_dir: Path) -> dict[tuple[str, str, int, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, int, str], dict[str, Any]] = {}

    for path in sorted(results_dir.glob(f"*{RESULT_SUFFIX}")):
        parsed = parse_repo_model_filename(path, RESULT_SUFFIX)
        if not parsed:
            continue
        repo, model_id = parsed
        payload = load_json(path)
        if not isinstance(payload, list):
            continue

        for entry in payload:
            if not isinstance(entry, dict):
                continue
            function_name = entry.get("function")
            empty_fails_count = entry.get("empty_fails_count")
            attempts = entry.get("attempts")
            if not isinstance(function_name, str):
                continue
            if not isinstance(empty_fails_count, int):
                continue
            if not isinstance(attempts, list):
                continue

            for attempt_data in attempts:
                if not isinstance(attempt_data, dict):
                    continue
                attempt = attempt_data.get("attempt")
                fixed_count = attempt_data.get("fixed_count")
                if not isinstance(attempt, int) or not isinstance(fixed_count, int):
                    continue

                lookup[(repo, model_id, attempt, function_name)] = {
                    "full_success": fixed_count == empty_fails_count,
                    "fixed_count": fixed_count,
                    "empty_fails_count": empty_fails_count,
                    "still_broken_count": attempt_data.get("still_broken_count"),
                    "new_broken_count": attempt_data.get("new_broken_count"),
                }

    return lookup


def load_patch_text(manifest_path: Path, instance_id: str, cache: dict[str, dict[str, str]]) -> str | None:
    key = str(manifest_path)
    manifest_map = cache.get(key)
    if manifest_map is None:
        if not manifest_path.exists():
            cache[key] = {}
            return None
        try:
            payload = load_json(manifest_path)
        except Exception:
            cache[key] = {}
            return None

        parsed: dict[str, str] = {}
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                i = item.get("instance_id")
                p = item.get("patch")
                if isinstance(i, str) and isinstance(p, str):
                    parsed[i] = p
        cache[key] = parsed
        manifest_map = parsed

    return manifest_map.get(instance_id)


def collect_metric_rows(metrics_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    model_ids: set[str] = set()

    for path in sorted(metrics_dir.glob(f"*{METRICS_SUFFIX}")):
        parsed = parse_repo_model_filename(path, METRICS_SUFFIX)
        if not parsed:
            continue
        repo, model_id = parsed
        model_ids.add(model_id)

        payload = load_json(path)
        src_rows = payload.get("rows")
        if not isinstance(src_rows, list):
            continue

        for row in src_rows:
            if not isinstance(row, dict):
                continue
            attempt = row.get("attempt")
            base_instance_id = row.get("base_instance_id")
            instance_id = row.get("instance_id")
            net_loc_change = row.get("net_loc_change")
            join_key = metric_join_key(row)
            if not isinstance(attempt, int):
                continue
            if not isinstance(base_instance_id, str) or not base_instance_id:
                continue
            if not isinstance(instance_id, str) or not instance_id:
                continue

            enriched = {
                "repo": repo,
                "model_id": model_id,
                "model_label": model_label(model_id),
                "attempt": attempt,
                "instance_id": instance_id,
                "base_instance_id": base_instance_id,
                "manifest": row.get("manifest"),
                "target_functions": row.get("target_functions"),
                "join_key": join_key,
                "validation_report_found": bool(row.get("validation_report_found")),
                "lines_added": row.get("lines_added"),
                "lines_removed": row.get("lines_removed"),
                "net_loc_change": net_loc_change,
                "complexity_change": row.get("complexity_change"),
                "parse_errors": row.get("parse_errors") if isinstance(row.get("parse_errors"), list) else [],
                "is_combined_patch": bool(row.get("is_combined_patch")),
            }
            rows.append(enriched)

    return rows, sorted(model_ids)


def attach_success(rows: list[dict[str, Any]], success_lookup: dict[tuple[str, str, int, str], dict[str, Any]]) -> None:
    for row in rows:
        join_key = row.get("join_key")
        if not isinstance(join_key, str):
            row["success_status"] = "unknown"
            row["success_reason"] = "missing_join_key"
            continue

        key = (row["repo"], row["model_id"], row["attempt"], join_key)
        hit = success_lookup.get(key)
        if hit is None:
            if not row.get("validation_report_found"):
                row["success_status"] = "unknown"
                row["success_reason"] = "missing_validation_report"
            else:
                row["success_status"] = "unknown"
                row["success_reason"] = "missing_test_comparison_match"
            continue

        row["success_status"] = "success" if hit["full_success"] else "failure"
        row["success_reason"] = "matched"
        row["fixed_count"] = hit.get("fixed_count")
        row["empty_fails_count"] = hit.get("empty_fails_count")
        row["still_broken_count"] = hit.get("still_broken_count")
        row["new_broken_count"] = hit.get("new_broken_count")


def sort_key_abs(field: str):
    def _k(row: dict[str, Any]) -> tuple[float, int]:
        value = row.get(field)
        if isinstance(value, (int, float)):
            return (abs(float(value)), 1)
        return (-1.0, 0)

    return _k


def select_top_distinct_repo(rows: list[dict[str, Any]], field: str, top_n: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=sort_key_abs(field), reverse=True)

    selected: list[dict[str, Any]] = []
    seen_repos: set[str] = set()

    for row in ranked:
        repo = row.get("repo")
        if not isinstance(repo, str):
            continue
        if repo in seen_repos:
            continue
        selected.append(row)
        seen_repos.add(repo)
        if len(selected) >= top_n:
            return selected

    # Fallback: if there are fewer than top_n distinct repos, fill remaining by rank.
    for row in ranked:
        if row in selected:
            continue
        selected.append(row)
        if len(selected) >= top_n:
            break

    return selected


def case_key_from_row(row: dict[str, Any]) -> CaseKey:
    return CaseKey(
        repo=row["repo"],
        base_instance_id=row["base_instance_id"],
        attempt=row["attempt"],
    )


def select_outliers(rows: list[dict[str, Any]], top_n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    loc_candidates = [r for r in rows if isinstance(r.get("net_loc_change"), (int, float))]
    loc_outliers = select_top_distinct_repo(loc_candidates, "net_loc_change", top_n)

    complexity_candidates = [r for r in rows if isinstance(r.get("complexity_change"), (int, float))]
    complexity_outliers = select_top_distinct_repo(
        complexity_candidates, "complexity_change", top_n
    )

    return loc_outliers, complexity_outliers


def build_case_index(rows: list[dict[str, Any]]) -> dict[CaseKey, dict[str, dict[str, Any]]]:
    index: dict[CaseKey, dict[str, dict[str, Any]]] = {}
    for row in rows:
        ckey = case_key_from_row(row)
        per_model = index.setdefault(ckey, {})
        per_model[row["model_id"]] = row
    return index


def case_has_patch_for_all_models(
    case_rows: dict[str, dict[str, Any]],
    model_ids: list[str],
    root_dir: Path,
    patch_cache: dict[str, dict[str, str]],
) -> bool:
    for model_id in model_ids:
        row = case_rows.get(model_id)
        if row is None:
            return False

        manifest_value = row.get("manifest")
        instance_id = row.get("instance_id")
        if not isinstance(manifest_value, str) or not manifest_value:
            return False
        if not isinstance(instance_id, str) or not instance_id:
            return False

        patch_text = load_patch_text(root_dir / manifest_value, instance_id, patch_cache)
        if not isinstance(patch_text, str):
            return False

    return True


def eligible_case_keys_with_full_patch_coverage(
    case_index: dict[CaseKey, dict[str, dict[str, Any]]],
    model_ids: list[str],
    root_dir: Path,
) -> set[CaseKey]:
    eligible: set[CaseKey] = set()
    patch_cache: dict[str, dict[str, str]] = {}

    for ckey, case_rows in case_index.items():
        if case_has_patch_for_all_models(case_rows, model_ids, root_dir, patch_cache):
            eligible.add(ckey)

    return eligible


def case_has_full_success_for_all_models(
    case_rows: dict[str, dict[str, Any]],
    model_ids: list[str],
) -> bool:
    for model_id in model_ids:
        row = case_rows.get(model_id)
        if row is None:
            return False
        if row.get("success_status") != "success":
            return False

        fixed_count = row.get("fixed_count")
        empty_fails_count = row.get("empty_fails_count")
        if not isinstance(fixed_count, int) or not isinstance(empty_fails_count, int):
            return False
        if fixed_count != empty_fails_count:
            return False

    return True


def eligible_case_keys_with_full_success(
    case_index: dict[CaseKey, dict[str, dict[str, Any]]],
    model_ids: list[str],
) -> set[CaseKey]:
    eligible: set[CaseKey] = set()

    for ckey, case_rows in case_index.items():
        if case_has_full_success_for_all_models(case_rows, model_ids):
            eligible.add(ckey)

    return eligible


def render_case_id(case_key: CaseKey) -> str:
    return f"{case_key.repo}|{case_key.base_instance_id}|attempt_{case_key.attempt}"


def build_cross_model_records(
    selected_cases: list[tuple[str, dict[str, Any]]],
    case_index: dict[CaseKey, dict[str, dict[str, Any]]],
    model_ids: list[str],
    root_dir: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    patch_cache: dict[str, dict[str, str]] = {}

    for metric_type, selected in selected_cases:
        ckey = case_key_from_row(selected)
        case_id = render_case_id(ckey)
        per_model = case_index.get(ckey, {})

        for model_id in model_ids:
            row = per_model.get(model_id)
            if row is None:
                records.append(
                    {
                        "metric_type": metric_type,
                        "case_id": case_id,
                        "repo": ckey.repo,
                        "base_instance_id": ckey.base_instance_id,
                        "attempt": ckey.attempt,
                        "model_id": model_id,
                        "model_label": model_label(model_id),
                        "exists": False,
                    }
                )
                continue

            manifest_value = row.get("manifest")
            patch_text = None
            if isinstance(manifest_value, str) and manifest_value:
                manifest_path = root_dir / manifest_value
                patch_text = load_patch_text(manifest_path, row["instance_id"], patch_cache)

            records.append(
                {
                    "metric_type": metric_type,
                    "case_id": case_id,
                    "repo": ckey.repo,
                    "base_instance_id": ckey.base_instance_id,
                    "attempt": ckey.attempt,
                    "model_id": model_id,
                    "model_label": model_label(model_id),
                    "exists": True,
                    "instance_id": row.get("instance_id"),
                    "success_status": row.get("success_status"),
                    "success_reason": row.get("success_reason"),
                    "fixed_count": row.get("fixed_count"),
                    "empty_fails_count": row.get("empty_fails_count"),
                    "still_broken_count": row.get("still_broken_count"),
                    "new_broken_count": row.get("new_broken_count"),
                    "net_loc_change": row.get("net_loc_change"),
                    "complexity_change": row.get("complexity_change"),
                    "lines_added": row.get("lines_added"),
                    "lines_removed": row.get("lines_removed"),
                    "target_functions": row.get("target_functions"),
                    "is_combined_patch": row.get("is_combined_patch"),
                    "parse_errors": row.get("parse_errors"),
                    "manifest": row.get("manifest"),
                    "patch_text": patch_text,
                    "patch_found": isinstance(patch_text, str),
                }
            )

    return records


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_markdown_summary(
    path: Path,
    loc_outliers: list[dict[str, Any]],
    complexity_outliers: list[dict[str, Any]],
    cross_records: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# Outlier Comparison Summary")
    lines.append("")

    lines.append("## Selected LOC Outliers")
    lines.append("")
    lines.append("| Rank | Repo | Model | Attempt | Net LOC | Complexity | Success | Case ID |")
    lines.append("|---:|---|---|---:|---:|---:|---|---|")
    for idx, row in enumerate(loc_outliers, start=1):
        case_id = render_case_id(case_key_from_row(row))
        lines.append(
            "| "
            f"{idx} | {row['repo']} | {row['model_label']} | {row['attempt']} | "
            f"{row.get('net_loc_change')} | {row.get('complexity_change')} | "
            f"{row.get('success_status')} | {case_id} |"
        )
    lines.append("")

    lines.append("## Selected Complexity Outliers")
    lines.append("")
    lines.append("| Rank | Repo | Model | Attempt | Complexity | Net LOC | Success | Case ID |")
    lines.append("|---:|---|---|---:|---:|---:|---|---|")
    for idx, row in enumerate(complexity_outliers, start=1):
        case_id = render_case_id(case_key_from_row(row))
        lines.append(
            "| "
            f"{idx} | {row['repo']} | {row['model_label']} | {row['attempt']} | "
            f"{row.get('complexity_change')} | {row.get('net_loc_change')} | "
            f"{row.get('success_status')} | {case_id} |"
        )
    lines.append("")

    lines.append("## Cross-Model Case Comparison")
    lines.append("")
    lines.append(
        "| Metric Type | Case ID | Model | Exists | Success | Net LOC | Complexity | Patch Found | Fixed/Empty | Instance ID | Manifest |"
    )
    lines.append("|---|---|---|---|---|---:|---:|---|---|---|---|")

    for rec in sorted(cross_records, key=lambda r: (r["metric_type"], r["case_id"], r["model_label"])):
        fixed_count = rec.get("fixed_count")
        empty_fails = rec.get("empty_fails_count")
        fixed_ratio = ""
        if fixed_count is not None and empty_fails is not None:
            fixed_ratio = f"{fixed_count}/{empty_fails}"
        lines.append(
            "| "
            f"{rec['metric_type']} | {rec['case_id']} | {rec['model_label']} | {rec.get('exists')} | "
            f"{rec.get('success_status')} | {rec.get('net_loc_change')} | {rec.get('complexity_change')} | "
            f"{rec.get('patch_found')} | {fixed_ratio} | {rec.get('instance_id', '')} | {rec.get('manifest', '')} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract top patch-metric outliers and compare each case across models."
    )
    parser.add_argument(
        "--root-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root directory.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory containing *_test_comparison.json.",
    )
    parser.add_argument(
        "--metrics-dir",
        type=Path,
        default=Path("results") / "metrics",
        help="Directory containing *_patch_metrics.json.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of outliers to select for each metric type.",
    )
    parser.add_argument(
        "--exclude-repo",
        action="append",
        default=[],
        help="Repository ID to exclude from candidate rows. Can be provided multiple times.",
    )
    parser.add_argument(
        "--selection-output",
        type=Path,
        default=Path("results") / "outlier_selection.json",
        help="Output JSON containing selected outlier rows.",
    )
    parser.add_argument(
        "--cross-model-output",
        type=Path,
        default=Path("results") / "outlier_cross_model_comparison.json",
        help="Output JSON containing model-by-case patch comparison records.",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("results") / "outlier_cross_model_summary.md",
        help="Markdown summary output path.",
    )
    args = parser.parse_args()

    root_dir = args.root_dir.resolve()
    results_dir = (root_dir / args.results_dir).resolve()
    metrics_dir = (root_dir / args.metrics_dir).resolve()

    rows, model_ids = collect_metric_rows(metrics_dir)
    excluded_repos = set(args.exclude_repo or [])
    if excluded_repos:
        rows = [row for row in rows if row.get("repo") not in excluded_repos]

    success_lookup = load_success_lookup(results_dir)
    attach_success(rows, success_lookup)

    case_index = build_case_index(rows)
    eligible_patch_case_keys = eligible_case_keys_with_full_patch_coverage(case_index, model_ids, root_dir)
    eligible_success_case_keys = eligible_case_keys_with_full_success(case_index, model_ids)
    eligible_case_keys = eligible_patch_case_keys.intersection(eligible_success_case_keys)
    rows = [row for row in rows if case_key_from_row(row) in eligible_case_keys]

    loc_outliers, complexity_outliers = select_outliers(rows, args.top_n)
    selected_cases = [
        *[("loc", row) for row in loc_outliers],
        *[("complexity", row) for row in complexity_outliers],
    ]

    case_index = build_case_index(rows)
    cross_model_records = build_cross_model_records(selected_cases, case_index, model_ids, root_dir)

    selection_payload = {
        "config": {
            "top_n": args.top_n,
            "sort_policy": "absolute_magnitude",
            "scope": "global",
            "attempt_policy": "outlier_row_attempt",
            "excluded_repos": sorted(excluded_repos),
            "require_patch_for_all_models": True,
            "require_full_success_for_all_models": True,
        },
        "model_ids": model_ids,
        "model_labels": {mid: model_label(mid) for mid in model_ids},
        "loc_outliers": loc_outliers,
        "complexity_outliers": complexity_outliers,
    }

    cross_model_payload = {
        "config": selection_payload["config"],
        "model_ids": model_ids,
        "record_count": len(cross_model_records),
        "records": cross_model_records,
    }

    write_json((root_dir / args.selection_output).resolve(), selection_payload)
    write_json((root_dir / args.cross_model_output).resolve(), cross_model_payload)
    write_markdown_summary(
        (root_dir / args.summary_output).resolve(),
        loc_outliers,
        complexity_outliers,
        cross_model_records,
    )

    print(f"Total metric rows: {len(rows)}")
    print(f"Models discovered: {len(model_ids)}")
    print(f"LOC outliers selected: {len(loc_outliers)}")
    print(f"Complexity outliers selected: {len(complexity_outliers)}")
    print(f"Wrote {(root_dir / args.selection_output).resolve()}")
    print(f"Wrote {(root_dir / args.cross_model_output).resolve()}")
    print(f"Wrote {(root_dir / args.summary_output).resolve()}")


if __name__ == "__main__":
    main()