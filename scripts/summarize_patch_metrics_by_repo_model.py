#!/usr/bin/env python3
"""Build a single JSON summary from patch metrics and test comparison results.

This script joins patch-level LOC/complexity metrics from results/metrics with
full-fix success labels derived from results/*_test_comparison.json, then writes
one aggregate JSON file keyed by repository and model.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


ATTEMPTS = (1, 2)
METRICS_SUFFIX = "_patch_metrics.json"
RESULT_SUFFIX = "_test_comparison.json"


CSV_FIELDNAMES = [
    "repo",
    "model",
    "model_label",
    "success_definition",
    "attempt_1_count",
    "attempt_1_avg_net_loc_change",
    "attempt_1_avg_complexity_change",
    "attempt_1_complexity_row_count",
    "attempt_1_matched_row_count",
    "attempt_1_validation_row_count",
    "attempt_2_count",
    "attempt_2_avg_net_loc_change",
    "attempt_2_avg_complexity_change",
    "attempt_2_complexity_row_count",
    "attempt_2_matched_row_count",
    "attempt_2_validation_row_count",
    "attempt_delta_avg_net_loc_change",
    "attempt_delta_avg_complexity_change",
    "successful_count",
    "successful_avg_net_loc_change",
    "successful_avg_complexity_change",
    "successful_complexity_row_count",
    "successful_matched_row_count",
    "successful_validation_row_count",
    "unsuccessful_count",
    "unsuccessful_avg_net_loc_change",
    "unsuccessful_avg_complexity_change",
    "unsuccessful_complexity_row_count",
    "unsuccessful_matched_row_count",
    "unsuccessful_validation_row_count",
    "success_delta_avg_net_loc_change",
    "success_delta_avg_complexity_change",
    "coverage_rows_considered",
    "coverage_rows_matched",
    "coverage_rows_unmatched",
    "coverage_rows_with_complexity",
    "coverage_rows_without_complexity",
    "coverage_rows_with_validation_report",
    "coverage_rows_unmatched_missing_validation",
    "coverage_rows_unmatched_missing_attempt_label",
    "coverage_rows_unmatched_missing_join_key",
]


def parse_repo_model_filename(path: Path, suffix: str) -> tuple[str, str] | None:
    name = path.name
    if not name.endswith(suffix):
        return None

    stem = name[: -len(suffix)]
    parts = stem.split("__", 2)
    if len(parts) != 3:
        return None

    repo = f"{parts[0]}__{parts[1]}"
    model = parts[2]
    return repo, model


def format_model_label(model: str) -> str:
    if model.endswith("wxnknl6gvktb"):
        return "Claude Haiku 4.5"
    if model.endswith("gewiaj6mtzjm"):
        return "Qwen3 Coder 30B"
    if model.endswith("ql4mbrrqznnz"):
        return "Claude Sonnet 4.6"
    return model


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def full_success_lookup(result_file: Path) -> dict[tuple[str, int], bool]:
    payload = load_json(result_file)
    if not isinstance(payload, list):
        raise ValueError(f"Expected list in {result_file}")

    lookup: dict[tuple[str, int], bool] = {}
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
            if attempt not in ATTEMPTS or not isinstance(fixed_count, int):
                continue
            lookup[(function_name, attempt)] = fixed_count == empty_fails_count

    return lookup


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


def build_normalized_rows(
    metrics_file: Path,
    success_lookup: dict[tuple[str, int], bool],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = load_json(metrics_file)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"Expected rows list in {metrics_file}")

    normalized: list[dict[str, Any]] = []
    unmatched_examples: list[dict[str, Any]] = []
    considered_rows = 0
    unmatched_missing_validation = 0
    unmatched_missing_attempt_label = 0
    unmatched_missing_join_key = 0

    for row in rows:
        if not isinstance(row, dict):
            continue

        attempt = row.get("attempt")
        if attempt not in ATTEMPTS:
            continue

        considered_rows += 1
        join_key = metric_join_key(row)
        full_success = None
        if join_key is not None:
            full_success = success_lookup.get((join_key, attempt))

        validation_report_found = bool(row.get("validation_report_found"))

        if full_success is None:
            if not validation_report_found:
                unmatched_missing_validation += 1
            elif join_key is None:
                unmatched_missing_join_key += 1
            else:
                unmatched_missing_attempt_label += 1

        if full_success is None and len(unmatched_examples) < 10:
            unmatched_examples.append(
                {
                    "instance_id": row.get("instance_id"),
                    "attempt": attempt,
                    "join_key": join_key,
                    "is_combined_patch": row.get("is_combined_patch", False),
                    "validation_report_found": validation_report_found,
                }
            )

        complexity_change = row.get("complexity_change")
        normalized.append(
            {
                "repo": row.get("repo"),
                "model": row.get("model"),
                "attempt": attempt,
                "instance_id": row.get("instance_id"),
                "join_key": join_key,
                "join_matched": full_success is not None,
                "full_success": full_success,
                "net_loc_change": row.get("net_loc_change"),
                "complexity_change": complexity_change,
                "has_complexity": isinstance(complexity_change, int),
                "validation_report_found": validation_report_found,
            }
        )

    coverage = {
        "rows_considered": considered_rows,
        "rows_matched": sum(1 for row in normalized if row["join_matched"]),
        "rows_unmatched": sum(1 for row in normalized if not row["join_matched"]),
        "rows_with_complexity": sum(1 for row in normalized if row["has_complexity"]),
        "rows_without_complexity": sum(1 for row in normalized if not row["has_complexity"]),
        "rows_with_validation_report": sum(
            1 for row in normalized if row["validation_report_found"]
        ),
        "rows_unmatched_missing_validation": unmatched_missing_validation,
        "rows_unmatched_missing_attempt_label": unmatched_missing_attempt_label,
        "rows_unmatched_missing_join_key": unmatched_missing_join_key,
        "unmatched_examples": unmatched_examples,
    }
    return normalized, coverage


def average_int(values: list[int]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize_bucket(rows: list[dict[str, Any]]) -> dict[str, Any]:
    loc_values = [row["net_loc_change"] for row in rows if isinstance(row["net_loc_change"], int)]
    complexity_values = [row["complexity_change"] for row in rows if row["has_complexity"]]
    return {
        "count": len(rows),
        "avg_net_loc_change": average_int(loc_values),
        "avg_complexity_change": average_int(complexity_values),
        "complexity_row_count": len(complexity_values),
        "matched_row_count": sum(1 for row in rows if row["join_matched"]),
        "validation_row_count": sum(1 for row in rows if row["validation_report_found"]),
    }


def diff_values(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def aggregate_repo_model(
    repo: str,
    model: str,
    rows: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    attempt_rows = {attempt: [row for row in rows if row["attempt"] == attempt] for attempt in ATTEMPTS}
    attempt_stats = {str(attempt): summarize_bucket(attempt_rows[attempt]) for attempt in ATTEMPTS}

    matched_rows = [row for row in rows if row["join_matched"]]
    successful_rows = [row for row in matched_rows if row["full_success"] is True]
    unsuccessful_rows = [row for row in matched_rows if row["full_success"] is False]

    success_stats = {
        "successful": summarize_bucket(successful_rows),
        "unsuccessful": summarize_bucket(unsuccessful_rows),
    }

    return {
        "repo": repo,
        "model": model,
        "model_label": format_model_label(model),
        "attempt_stats": attempt_stats,
        "attempt_delta": {
            "avg_net_loc_change": diff_values(
                attempt_stats["2"]["avg_net_loc_change"],
                attempt_stats["1"]["avg_net_loc_change"],
            ),
            "avg_complexity_change": diff_values(
                attempt_stats["2"]["avg_complexity_change"],
                attempt_stats["1"]["avg_complexity_change"],
            ),
        },
        "success_definition": "full_fix",
        "success_stats": success_stats,
        "success_delta": {
            "avg_net_loc_change": diff_values(
                success_stats["successful"]["avg_net_loc_change"],
                success_stats["unsuccessful"]["avg_net_loc_change"],
            ),
            "avg_complexity_change": diff_values(
                success_stats["successful"]["avg_complexity_change"],
                success_stats["unsuccessful"]["avg_complexity_change"],
            ),
        },
        "coverage": coverage,
    }


def build_summary(results_dir: Path, metrics_dir: Path) -> dict[str, Any]:
    comparison_files = {
        parsed: path
        for path in sorted(results_dir.glob(f"*{RESULT_SUFFIX}"))
        if (parsed := parse_repo_model_filename(path, RESULT_SUFFIX)) is not None
    }

    results: list[dict[str, Any]] = []
    missing_comparison_files: list[str] = []

    for metrics_file in sorted(metrics_dir.glob(f"*{METRICS_SUFFIX}")):
        parsed = parse_repo_model_filename(metrics_file, METRICS_SUFFIX)
        if parsed is None:
            continue

        repo, model = parsed
        comparison_file = comparison_files.get((repo, model))
        if comparison_file is None:
            missing_comparison_files.append(metrics_file.name)
            continue

        success_lookup = full_success_lookup(comparison_file)
        normalized_rows, coverage = build_normalized_rows(metrics_file, success_lookup)
        results.append(aggregate_repo_model(repo, model, normalized_rows, coverage))

    results.sort(key=lambda item: (item["repo"], item["model"]))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "success_definition": "full_fix",
        "attempts_included": list(ATTEMPTS),
        "source_paths": {
            "results_dir": str(results_dir),
            "metrics_dir": str(metrics_dir),
        },
        "summary": {
            "repo_model_count": len(results),
            "missing_comparison_file_count": len(missing_comparison_files),
            "missing_comparison_files": missing_comparison_files,
            "total_rows_considered": sum(item["coverage"]["rows_considered"] for item in results),
            "total_rows_matched": sum(item["coverage"]["rows_matched"] for item in results),
            "total_rows_unmatched": sum(item["coverage"]["rows_unmatched"] for item in results),
        },
        "results": results,
    }


def build_csv_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in results:
        attempt_1 = item["attempt_stats"]["1"]
        attempt_2 = item["attempt_stats"]["2"]
        successful = item["success_stats"]["successful"]
        unsuccessful = item["success_stats"]["unsuccessful"]
        coverage = item["coverage"]

        rows.append(
            {
                "repo": item["repo"],
                "model": item["model"],
                "model_label": item["model_label"],
                "success_definition": item["success_definition"],
                "attempt_1_count": attempt_1["count"],
                "attempt_1_avg_net_loc_change": attempt_1["avg_net_loc_change"],
                "attempt_1_avg_complexity_change": attempt_1["avg_complexity_change"],
                "attempt_1_complexity_row_count": attempt_1["complexity_row_count"],
                "attempt_1_matched_row_count": attempt_1["matched_row_count"],
                "attempt_1_validation_row_count": attempt_1["validation_row_count"],
                "attempt_2_count": attempt_2["count"],
                "attempt_2_avg_net_loc_change": attempt_2["avg_net_loc_change"],
                "attempt_2_avg_complexity_change": attempt_2["avg_complexity_change"],
                "attempt_2_complexity_row_count": attempt_2["complexity_row_count"],
                "attempt_2_matched_row_count": attempt_2["matched_row_count"],
                "attempt_2_validation_row_count": attempt_2["validation_row_count"],
                "attempt_delta_avg_net_loc_change": item["attempt_delta"]["avg_net_loc_change"],
                "attempt_delta_avg_complexity_change": item["attempt_delta"]["avg_complexity_change"],
                "successful_count": successful["count"],
                "successful_avg_net_loc_change": successful["avg_net_loc_change"],
                "successful_avg_complexity_change": successful["avg_complexity_change"],
                "successful_complexity_row_count": successful["complexity_row_count"],
                "successful_matched_row_count": successful["matched_row_count"],
                "successful_validation_row_count": successful["validation_row_count"],
                "unsuccessful_count": unsuccessful["count"],
                "unsuccessful_avg_net_loc_change": unsuccessful["avg_net_loc_change"],
                "unsuccessful_avg_complexity_change": unsuccessful["avg_complexity_change"],
                "unsuccessful_complexity_row_count": unsuccessful["complexity_row_count"],
                "unsuccessful_matched_row_count": unsuccessful["matched_row_count"],
                "unsuccessful_validation_row_count": unsuccessful["validation_row_count"],
                "success_delta_avg_net_loc_change": item["success_delta"]["avg_net_loc_change"],
                "success_delta_avg_complexity_change": item["success_delta"]["avg_complexity_change"],
                "coverage_rows_considered": coverage["rows_considered"],
                "coverage_rows_matched": coverage["rows_matched"],
                "coverage_rows_unmatched": coverage["rows_unmatched"],
                "coverage_rows_with_complexity": coverage["rows_with_complexity"],
                "coverage_rows_without_complexity": coverage["rows_without_complexity"],
                "coverage_rows_with_validation_report": coverage["rows_with_validation_report"],
                "coverage_rows_unmatched_missing_validation": coverage[
                    "rows_unmatched_missing_validation"
                ],
                "coverage_rows_unmatched_missing_attempt_label": coverage[
                    "rows_unmatched_missing_attempt_label"
                ],
                "coverage_rows_unmatched_missing_join_key": coverage[
                    "rows_unmatched_missing_join_key"
                ],
            }
        )

    return rows


def write_csv_output(path: Path, results: list[dict[str, Any]]) -> None:
    rows = build_csv_rows(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate patch metrics into one JSON file with attempt deltas and "
            "successful-vs-unsuccessful comparisons."
        )
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory containing *_test_comparison.json files.",
    )
    parser.add_argument(
        "--metrics-dir",
        type=Path,
        default=Path("results") / "metrics",
        help="Directory containing *_patch_metrics.json files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results") / "patch_metrics_summary_by_repo_model.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=None,
        help="Optional CSV output path. Defaults to the JSON output path with a .csv suffix.",
    )
    args = parser.parse_args()

    if not args.results_dir.exists():
        raise FileNotFoundError(f"Results directory not found: {args.results_dir}")
    if not args.metrics_dir.exists():
        raise FileNotFoundError(f"Metrics directory not found: {args.metrics_dir}")

    payload = build_summary(args.results_dir, args.metrics_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    csv_output = args.csv_output or args.output.with_suffix(".csv")
    write_csv_output(csv_output, payload["results"])

    print(f"Wrote {args.output}")
    print(f"Wrote {csv_output}")
    print(f"Repo/model entries: {payload['summary']['repo_model_count']}")
    print(f"Matched rows: {payload['summary']['total_rows_matched']}")
    print(f"Unmatched rows: {payload['summary']['total_rows_unmatched']}")


if __name__ == "__main__":
    main()