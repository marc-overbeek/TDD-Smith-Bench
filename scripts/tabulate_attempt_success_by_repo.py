"""Generate table outputs for attempt success data used by plot_attempt_success_by_repo.

Usage:
  uv run python scripts/tabulate_attempt_success_by_repo.py

This script reads the same *_test_comparison.json files as
scripts/plot_attempt_success_by_repo.py and writes:
- a long-form table with one row per (repo, scope, model, attempt)
- a compact table with one row per (repo, scope) and model/attempt columns
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from plot_attempt_success_by_repo import (
    ATTEMPTS,
    combine_repo_stats,
    format_model_label,
    gather_attempt_stats,
)


def to_rate(success: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return (100.0 * success) / total


def build_scope_stats(results_dir: Path, success_metric: str) -> dict[str, dict]:
    all_stats = gather_attempt_stats(results_dir, success_metric, task_filter="all")
    single_stats = gather_attempt_stats(results_dir, success_metric, task_filter="single")
    combined_stats = gather_attempt_stats(results_dir, success_metric, task_filter="combined")

    scopes: dict[str, dict] = {
        "all": all_stats,
        "single": single_stats,
        "combined": combined_stats,
    }

    combined_repo_name = "combined_excluding_pyupio"
    combined_all = combine_repo_stats(all_stats, exclude_prefixes=("pyupio__",))
    combined_single = combine_repo_stats(single_stats, exclude_prefixes=("pyupio__",))
    combined_combined = combine_repo_stats(combined_stats, exclude_prefixes=("pyupio__",))

    if combined_all:
        scopes["all"][combined_repo_name] = combined_all
    if combined_single:
        scopes["single"][combined_repo_name] = combined_single
    if combined_combined:
        scopes["combined"][combined_repo_name] = combined_combined

    return scopes


def build_long_rows(scopes: dict[str, dict]) -> list[dict[str, str | int | float]]:
    rows: list[dict[str, str | int | float]] = []
    for scope_name in ("all", "single", "combined"):
        repo_stats = scopes.get(scope_name, {})
        for repo in sorted(repo_stats.keys()):
            for model_id in sorted(repo_stats[repo].keys()):
                model = format_model_label(model_id)
                for attempt in ATTEMPTS:
                    success = repo_stats[repo][model_id][attempt]["success"]
                    total = repo_stats[repo][model_id][attempt]["total"]
                    rows.append(
                        {
                            "repo": repo,
                            "scope": scope_name,
                            "model": model,
                            "model_id": model_id,
                            "attempt": attempt,
                            "success": success,
                            "total": total,
                            "rate_percent": round(to_rate(success, total), 4),
                            "ratio": f"{success}/{total}",
                        }
                    )
    return rows


def build_compact_rows(long_rows: list[dict[str, str | int | float]]) -> tuple[list[dict[str, str | int | float]], list[str]]:
    models = sorted({str(row["model"]) for row in long_rows})
    key_order = [(model, attempt) for model in models for attempt in ATTEMPTS]

    by_repo_scope: dict[tuple[str, str], dict[str, str | int | float]] = {}
    for row in long_rows:
        repo = str(row["repo"])
        scope = str(row["scope"])
        model = str(row["model"])
        attempt = int(row["attempt"])
        rate = float(row["rate_percent"])
        ratio = str(row["ratio"])

        key = (repo, scope)
        target = by_repo_scope.setdefault(key, {"repo": repo, "scope": scope})
        target[f"{model}_attempt_{attempt}_percent"] = round(rate, 4)
        target[f"{model}_attempt_{attempt}_ratio"] = ratio

    compact_fieldnames = ["repo", "scope"]
    for model, attempt in key_order:
        compact_fieldnames.append(f"{model}_attempt_{attempt}_percent")
        compact_fieldnames.append(f"{model}_attempt_{attempt}_ratio")

    compact_rows = [by_repo_scope[k] for k in sorted(by_repo_scope.keys())]
    return compact_rows, compact_fieldnames


def write_csv(rows: list[dict[str, str | int | float]], fieldnames: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_markdown(rows: list[dict[str, str | int | float]], fieldnames: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["| " + " | ".join(fieldnames) + " |", "| " + " | ".join(["---"] * len(fieldnames)) + " |"]
    for row in rows:
        values = [str(row.get(name, "")) for name in fieldnames]
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tabulate attempt success values used in attempt_success_graphs plots."
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results"),
        help="Directory containing *_test_comparison.json files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results") / "attempt_success_graphs",
        help="Directory where table files are written.",
    )
    parser.add_argument(
        "--success-metric",
        choices=["any", "full"],
        default="full",
        help="Count success as any fixed test ('any') or only complete fixes ('full').",
    )
    args = parser.parse_args()

    if not args.results_dir.exists():
        raise FileNotFoundError(f"Results directory not found: {args.results_dir}")

    scopes = build_scope_stats(args.results_dir, args.success_metric)
    long_rows = build_long_rows(scopes)

    if not long_rows:
        print("No result files found or no attempt data available.")
        return

    long_fieldnames = [
        "repo",
        "scope",
        "model",
        "model_id",
        "attempt",
        "success",
        "total",
        "rate_percent",
        "ratio",
    ]
    compact_rows, compact_fieldnames = build_compact_rows(long_rows)

    metric_suffix = args.success_metric
    long_csv = args.output_dir / f"attempt_success_table_long_{metric_suffix}.csv"
    long_md = args.output_dir / f"attempt_success_table_long_{metric_suffix}.md"
    compact_csv = args.output_dir / f"attempt_success_table_compact_{metric_suffix}.csv"
    compact_md = args.output_dir / f"attempt_success_table_compact_{metric_suffix}.md"

    write_csv(long_rows, long_fieldnames, long_csv)
    write_markdown(long_rows, long_fieldnames, long_md)
    write_csv(compact_rows, compact_fieldnames, compact_csv)
    write_markdown(compact_rows, compact_fieldnames, compact_md)

    print("Wrote attempt success tables:")
    print(f"- {long_csv}")
    print(f"- {long_md}")
    print(f"- {compact_csv}")
    print(f"- {compact_md}")


if __name__ == "__main__":
    main()