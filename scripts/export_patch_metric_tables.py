#!/usr/bin/env python3
"""Export focused patch-metric summary tables as CSV files.

This script reuses the aggregated repo/model summary logic and writes four CSVs:
1. Attempt LOC comparison table
2. Attempt complexity comparison table
3. Success LOC comparison table
4. Success complexity comparison table
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from summarize_patch_metrics_by_repo_model import build_summary


MODEL_ORDER = [
    "Claude Haiku 4.5",
    "Claude Sonnet 4.6",
    "Qwen3 Coder 30B",
]


def round_average(value: object) -> object:
    if isinstance(value, (int, float)):
        return f"{value:.2f}"
    return value


def format_pair(loc_value: object, complexity_value: object) -> str:
    return f"{round_average(loc_value)} / {round_average(complexity_value)}"


def write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            writer.writerow(row)


def repo_display_name(repo: str) -> str:
    return repo.replace("__", " ").split(".", 1)[0]


def build_grouped_rows(
    by_repo: dict[str, dict[str, str]],
    subheaders: tuple[str, str],
) -> list[list[str]]:
    rows: list[list[str]] = []
    rows.append([
        "repository",
        "Claude Haiku 4.5",
        "",
        "Claude Sonnet 4.6",
        "",
        "Qwen3 Coder 30B",
        "",
    ])
    rows.append([
        "",
        subheaders[0],
        subheaders[1],
        subheaders[0],
        subheaders[1],
        subheaders[0],
        subheaders[1],
    ])

    for repo in sorted(by_repo.keys()):
        repo_values = by_repo[repo]
        row = [repo_display_name(repo)]
        for model_label in MODEL_ORDER:
            row.append(repo_values.get(f"{model_label}::{subheaders[0]}", ""))
            row.append(repo_values.get(f"{model_label}::{subheaders[1]}", ""))
        rows.append(row)

    return rows


def build_attempt_loc_rows(results: list[dict[str, object]]) -> list[list[str]]:
    by_repo: dict[str, dict[str, str]] = {}
    for item in results:
        repo = item["repo"]
        model_label = item["model_label"]
        attempt_stats = item["attempt_stats"]
        attempt_1 = attempt_stats["1"]
        attempt_2 = attempt_stats["2"]
        repo_rows = by_repo.setdefault(repo, {})
        repo_rows[f"{model_label}::Attempt 1"] = str(round_average(attempt_1["avg_net_loc_change"]))
        repo_rows[f"{model_label}::Attempt 2"] = str(round_average(attempt_2["avg_net_loc_change"]))

    return build_grouped_rows(by_repo, ("Attempt 1", "Attempt 2"))


def build_attempt_complexity_rows(results: list[dict[str, object]]) -> list[list[str]]:
    by_repo: dict[str, dict[str, str]] = {}
    for item in results:
        repo = item["repo"]
        model_label = item["model_label"]
        attempt_stats = item["attempt_stats"]
        attempt_1 = attempt_stats["1"]
        attempt_2 = attempt_stats["2"]
        repo_rows = by_repo.setdefault(repo, {})
        repo_rows[f"{model_label}::Attempt 1"] = str(
            round_average(attempt_1["avg_complexity_change"])
        )
        repo_rows[f"{model_label}::Attempt 2"] = str(
            round_average(attempt_2["avg_complexity_change"])
        )

    return build_grouped_rows(by_repo, ("Attempt 1", "Attempt 2"))


def build_success_loc_rows(results: list[dict[str, object]]) -> list[list[str]]:
    by_repo: dict[str, dict[str, str]] = {}
    for item in results:
        repo = item["repo"]
        model_label = item["model_label"]
        success_stats = item["success_stats"]
        successful = success_stats["successful"]
        unsuccessful = success_stats["unsuccessful"]
        repo_rows = by_repo.setdefault(repo, {})
        repo_rows[f"{model_label}::Successful"] = str(
            round_average(successful["avg_net_loc_change"])
        )
        repo_rows[f"{model_label}::Unsuccessful"] = str(
            round_average(unsuccessful["avg_net_loc_change"])
        )

    return build_grouped_rows(by_repo, ("Successful", "Unsuccessful"))


def build_success_complexity_rows(results: list[dict[str, object]]) -> list[list[str]]:
    by_repo: dict[str, dict[str, str]] = {}
    for item in results:
        repo = item["repo"]
        model_label = item["model_label"]
        success_stats = item["success_stats"]
        successful = success_stats["successful"]
        unsuccessful = success_stats["unsuccessful"]
        repo_rows = by_repo.setdefault(repo, {})
        repo_rows[f"{model_label}::Successful"] = str(
            round_average(successful["avg_complexity_change"])
        )
        repo_rows[f"{model_label}::Unsuccessful"] = str(
            round_average(unsuccessful["avg_complexity_change"])
        )

    return build_grouped_rows(by_repo, ("Successful", "Unsuccessful"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export focused attempt and success patch-metric summary tables as CSV files."
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
        "--attempt-loc-output",
        type=Path,
        default=Path("results") / "patch_metrics_attempt_loc_table.csv",
        help="CSV output path for the attempt LOC comparison table.",
    )
    parser.add_argument(
        "--attempt-complexity-output",
        type=Path,
        default=Path("results") / "patch_metrics_attempt_complexity_table.csv",
        help="CSV output path for the attempt complexity comparison table.",
    )
    parser.add_argument(
        "--success-loc-output",
        type=Path,
        default=Path("results") / "patch_metrics_success_loc_table.csv",
        help="CSV output path for the success LOC comparison table.",
    )
    parser.add_argument(
        "--success-complexity-output",
        type=Path,
        default=Path("results") / "patch_metrics_success_complexity_table.csv",
        help="CSV output path for the success complexity comparison table.",
    )
    args = parser.parse_args()

    payload = build_summary(args.results_dir, args.metrics_dir)
    results = payload["results"]

    attempt_loc_rows = build_attempt_loc_rows(results)
    attempt_complexity_rows = build_attempt_complexity_rows(results)
    success_loc_rows = build_success_loc_rows(results)
    success_complexity_rows = build_success_complexity_rows(results)

    write_csv(args.attempt_loc_output, attempt_loc_rows)
    write_csv(args.attempt_complexity_output, attempt_complexity_rows)
    write_csv(args.success_loc_output, success_loc_rows)
    write_csv(args.success_complexity_output, success_complexity_rows)

    print(f"Wrote {args.attempt_loc_output}")
    print(f"Wrote {args.attempt_complexity_output}")
    print(f"Wrote {args.success_loc_output}")
    print(f"Wrote {args.success_complexity_output}")
    print(f"Repo/model entries: {len(results)}")


if __name__ == "__main__":
    main()