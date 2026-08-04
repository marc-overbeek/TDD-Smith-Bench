"""Plot attempt 1 vs attempt 2 success rates by model for each repo.

Usage:
  uv run python scripts/plot_attempt_success_by_repo.py

By default this script reads all *_test_comparison.json files from results/ and
creates three grouped bar charts per repo in repo-specific subfolders under
results/attempt_success_graphs/:
- all tasks
- single tasks only
- combined tasks only
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ATTEMPTS = (1, 2)
RESULT_SUFFIX = "_test_comparison.json"
TASK_FILTERS = ("all", "single", "combined")


def parse_results_filename(path: Path) -> tuple[str, str] | None:
    """Extract (repo, model) from a comparison result filename."""
    name = path.name
    if not name.endswith(RESULT_SUFFIX):
        return None

    stem = name[: -len(RESULT_SUFFIX)]
    parts = stem.split("__", 2)
    if len(parts) != 3:
        return None

    repo = f"{parts[0]}__{parts[1]}"
    model = parts[2]
    return repo, model


def format_repo_label(repo: str) -> str:
    """Convert a raw repo key into a cleaner plot title label."""
    return repo.replace("__", " ").split(".", 1)[0]


def format_model_label(model: str) -> str:
    """Convert raw model identifiers into readable labels."""
    if model.endswith("wxnknl6gvktb"):
        return "Claude Haiku 4.5"
    if model.endswith("gewiaj6mtzjm"):
        return "Qwen3 Coder 30B"
    if model.endswith("ql4mbrrqznnz"):
        return "Claude Sonnet 4.6"
    return model


def is_success(attempt_data: dict, empty_fails_count: int, success_metric: str) -> bool:
    """Return True when an attempt counts as successful under chosen metric."""
    fixed_count = attempt_data.get("fixed_count")
    if not isinstance(fixed_count, int):
        return False

    if success_metric == "any":
        return fixed_count > 0
    return fixed_count == empty_fails_count


def task_group(function_name: str) -> str:
    """Classify a task as single or combined based on function prefix."""
    return "combined" if function_name.startswith("combined:") else "single"


def gather_attempt_stats(results_dir: Path, success_metric: str, task_filter: str = "all") -> dict:
    """Collect cumulative success/total counts for attempts 1 and 2 by (repo, model)."""
    if task_filter not in TASK_FILTERS:
        raise ValueError(f"Unsupported task filter: {task_filter}")

    stats = defaultdict(
        lambda: defaultdict(
            lambda: {
                1: {"success": 0, "total": 0},
                2: {"success": 0, "total": 0},
            }
        )
    )

    for result_file in sorted(results_dir.glob(f"*{RESULT_SUFFIX}")):
        parsed = parse_results_filename(result_file)
        if parsed is None:
            continue
        repo, model = parsed

        try:
            entries = json.loads(result_file.read_text())
        except json.JSONDecodeError:
            print(f"Skipping unreadable JSON: {result_file}")
            continue

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            function_name = entry.get("function")
            if not isinstance(function_name, str):
                continue

            if task_filter != "all" and task_group(function_name) != task_filter:
                continue

            empty_fails_count = entry.get("empty_fails_count", 0)
            if not isinstance(empty_fails_count, int):
                continue

            attempts = entry.get("attempts", [])
            if not isinstance(attempts, list):
                continue

            total_counted = False
            success_by_attempt = {1: False, 2: False}

            for attempt_data in attempts:
                if not isinstance(attempt_data, dict):
                    continue
                attempt_num = attempt_data.get("attempt")
                if attempt_num not in ATTEMPTS:
                    continue

                if is_success(attempt_data, empty_fails_count, success_metric):
                    success_by_attempt[attempt_num] = True

                if not total_counted:
                    stats[repo][model][1]["total"] += 1
                    stats[repo][model][2]["total"] += 1
                    total_counted = True

            if success_by_attempt[1]:
                stats[repo][model][1]["success"] += 1
            if success_by_attempt[1] or success_by_attempt[2]:
                stats[repo][model][2]["success"] += 1

    # Use a shared denominator per repo so model comparisons are on the same total.
    for repo_stats in stats.values():
        max_total = 0
        for model_stats in repo_stats.values():
            max_total = max(max_total, model_stats[1]["total"], model_stats[2]["total"])

        if max_total == 0:
            continue

        for model_stats in repo_stats.values():
            model_stats[1]["total"] = max_total
            model_stats[2]["total"] = max_total

    return stats


def sanitize_filename(name: str) -> str:
    """Make repo names safe for output image filenames."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def combine_repo_stats(stats_by_repo: dict, exclude_prefixes: tuple[str, ...] = ()) -> dict:
    """Combine per-repo stats into one model-level aggregate, with optional repo exclusions."""
    combined = defaultdict(
        lambda: {
            1: {"success": 0, "total": 0},
            2: {"success": 0, "total": 0},
        }
    )

    for repo, repo_stats in stats_by_repo.items():
        if any(repo.startswith(prefix) for prefix in exclude_prefixes):
            continue

        for model, model_attempts in repo_stats.items():
            for attempt in ATTEMPTS:
                combined[model][attempt]["success"] += model_attempts[attempt]["success"]
                combined[model][attempt]["total"] += model_attempts[attempt]["total"]

    if not combined:
        return {}

    # Keep denominator consistent across models for side-by-side comparison.
    max_total = 0
    for model_attempts in combined.values():
        max_total = max(max_total, model_attempts[1]["total"], model_attempts[2]["total"])

    if max_total > 0:
        for model_attempts in combined.values():
            model_attempts[1]["total"] = max_total
            model_attempts[2]["total"] = max_total

    return dict(combined)


def plot_repo(
    repo: str,
    model_stats: dict,
    output_path: Path,
    success_metric: str,
    scope_label: str,
) -> Path:
    """Create one grouped bar chart for a single repo."""
    models = sorted(model_stats.keys())
    display_repo = format_repo_label(repo)

    rates_by_attempt = {1: [], 2: []}
    labels_by_attempt = {1: [], 2: []}

    for model in models:
        for attempt in ATTEMPTS:
            success = model_stats[model][attempt]["success"]
            total = model_stats[model][attempt]["total"]
            rate = (100.0 * success / total) if total > 0 else 0.0
            rates_by_attempt[attempt].append(rate)
            labels_by_attempt[attempt].append(f"{success}/{total}")

    width = 0.38
    x_positions = list(range(len(models)))
    x_attempt1 = [x - width / 2 for x in x_positions]
    x_attempt2 = [x + width / 2 for x in x_positions]

    fig_width = max(12, len(models) * 1.8)
    fig, ax = plt.subplots(figsize=(fig_width, 7))

    bars1 = ax.bar(x_attempt1, rates_by_attempt[1], width=width, label="Attempt 1", color="#2a9d8f")
    bars2 = ax.bar(x_attempt2, rates_by_attempt[2], width=width, label="Attempt 2", color="#e76f51")

    for bars, attempt in ((bars1, 1), (bars2, 2)):
        for idx, bar in enumerate(bars):
            label = labels_by_attempt[attempt][idx]
            y = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                y + 1.0,
                f"{y:.1f}%\n({label})",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    metric_label = "Any Fix" if success_metric == "any" else "Full Fix"
    ax.set_title(
        f"{display_repo}: Cumulative Attempt Success Rate by Model ({metric_label}, {scope_label})"
    )
    ax.set_ylabel("Success Rate (%)")
    ax.set_xlabel("Model")
    ax.set_ylim(0, 100)
    ax.set_xticks(x_positions)
    ax.set_xticklabels([format_model_label(model) for model in models], rotation=30, ha="right")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    plt.tight_layout()

    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create per-repo charts with attempt 1 and 2 success rates by model."
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
        help="Directory where chart images are written.",
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

    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_stats = gather_attempt_stats(args.results_dir, args.success_metric, task_filter="all")
    single_stats = gather_attempt_stats(args.results_dir, args.success_metric, task_filter="single")
    combined_stats = gather_attempt_stats(args.results_dir, args.success_metric, task_filter="combined")

    if not all_stats:
        print("No result files found or no attempt data available.")
        return

    generated = []
    for repo in sorted(all_stats.keys()):
        repo_dir = args.output_dir / sanitize_filename(repo)
        repo_dir.mkdir(parents=True, exist_ok=True)

        generated.append(
            plot_repo(
                repo,
                all_stats[repo],
                repo_dir / f"{sanitize_filename(repo)}_attempt_success.png",
                args.success_metric,
                "All Tasks",
            )
        )

        if repo in single_stats:
            generated.append(
                plot_repo(
                    repo,
                    single_stats[repo],
                    repo_dir / f"{sanitize_filename(repo)}_attempt_success_single.png",
                    args.success_metric,
                    "Single Tasks",
                )
            )

        if repo in combined_stats:
            generated.append(
                plot_repo(
                    repo,
                    combined_stats[repo],
                    repo_dir / f"{sanitize_filename(repo)}_attempt_success_combined.png",
                    args.success_metric,
                    "Combined Tasks",
                )
            )

    combined_category_name = "combined_excluding_pyupio"
    combined_all = combine_repo_stats(all_stats, exclude_prefixes=("pyupio__",))
    combined_single = combine_repo_stats(single_stats, exclude_prefixes=("pyupio__",))
    combined_combined = combine_repo_stats(combined_stats, exclude_prefixes=("pyupio__",))

    if combined_all:
        combined_dir = args.output_dir / combined_category_name
        combined_dir.mkdir(parents=True, exist_ok=True)

        generated.append(
            plot_repo(
                combined_category_name,
                combined_all,
                combined_dir / f"{combined_category_name}_attempt_success.png",
                args.success_metric,
                "All Tasks",
            )
        )

        if combined_single:
            generated.append(
                plot_repo(
                    combined_category_name,
                    combined_single,
                    combined_dir / f"{combined_category_name}_attempt_success_single.png",
                    args.success_metric,
                    "Single Tasks",
                )
            )

        if combined_combined:
            generated.append(
                plot_repo(
                    combined_category_name,
                    combined_combined,
                    combined_dir / f"{combined_category_name}_attempt_success_combined.png",
                    args.success_metric,
                    "Combined Tasks",
                )
            )

    print(f"Generated {len(generated)} graph(s):")
    for path in generated:
        print(f"- {path}")


if __name__ == "__main__":
    main()
