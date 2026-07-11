#!/usr/bin/env python3
"""Plot task statistics for each repository in logs/change_logs.

For each repository directory containing _summary.json and _test_case_map.json,
this script creates one PNG with:
1. A bar chart of the number of regular tasks vs combined tasks.
2. A second bar chart showing the instance count for each combined task.

The instance count is taken from the "instance_count" field in the test-case
map, which matches the per-task count requested in the analysis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = ROOT / "logs" / "change_logs"
BUG_GEN_ROOT = ROOT / "logs" / "bug_gen"
OUTPUT_DIR = ROOT / "logs" / "plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_repo_stats(repo_dir: Path) -> dict[str, Any]:
    summary_path = repo_dir / "_summary.json"
    test_map_path = repo_dir / "_test_case_map.json"
    repo_name = repo_dir.name

    summary: dict[str, Any] = {}
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())

    single_patch_path = BUG_GEN_ROOT / f"{repo_name}_empty_body_from_scratch_patches.json"
    combined_patch_path = BUG_GEN_ROOT / f"{repo_name}_empty_body_from_test_case_patches.json"

    single_tasks = 0
    if single_patch_path.exists():
        single_tasks = len(json.loads(single_patch_path.read_text()))

    combined_tasks = 0
    if combined_patch_path.exists():
        combined_tasks = len(json.loads(combined_patch_path.read_text()))

    combined_task_counts: list[int] = []
    combined_task_names: list[str] = []
    if test_map_path.exists():
        test_map = json.loads(test_map_path.read_text())
        combined_task_names = list(test_map.keys())
        combined_task_counts = [int(entry.get("instance_count", 0)) for entry in test_map.values()]

    return {
        "repo": repo_name,
        "regular_tasks": single_tasks,
        "combined_tasks": combined_tasks,
        "combined_task_names": combined_task_names,
        "combined_task_counts": combined_task_counts,
    }


def plot_repo_stats(stats: dict[str, Any], output_path: Path) -> None:
    repo = stats["repo"]
    regular_tasks = stats["regular_tasks"]
    combined_tasks = stats["combined_tasks"]

    fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)

    ax.bar(["tasks", "combined tasks"], [regular_tasks, combined_tasks], color=["#4C78A8", "#F58518"])
    ax.set_title(f"{repo}: task counts")
    ax.set_ylabel("count")
    ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.suptitle(f"Task statistics for {repo}", fontsize=12)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_combined_repo_stats(stats_list: list[dict[str, Any]], output_path: Path) -> None:
    if not stats_list:
        return

    ncols = 5
    nrows = (len(stats_list) + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3.2 * nrows), constrained_layout=True, sharey=True)
    axes = axes.flatten() if nrows > 1 or ncols > 1 else [axes]

    max_count = max(max(stats["regular_tasks"], stats["combined_tasks"]) for stats in stats_list)
    y_limit = max(1, max_count * 1.15)

    totaltasks = 0
    totalcombinedtasks = 0
    for stats in enumerate(stats_list):
        totaltasks += stats[1]["regular_tasks"]
        totalcombinedtasks += stats[1]["combined_tasks"]
    
    print(f"Total regular tasks across all repositories: {totaltasks}")
    print(f"Total combined tasks across all repositories: {totalcombinedtasks}")

    for idx, stats in enumerate(stats_list):
        ax = axes[idx]
        repo = stats["repo"]
        regular_tasks = stats["regular_tasks"]
        combined_tasks = stats["combined_tasks"]

        bars = ax.bar(["tasks", "combined tasks"], [regular_tasks, combined_tasks], color=["#4C78A8", "#F58518"])
        ax.set_title(repo, fontsize=9)
        ax.set_ylim(0, y_limit)
        ax.grid(axis="y", linestyle="--", alpha=0.3)

        for bar, value in zip(bars, [regular_tasks, combined_tasks]):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(1, y_limit * 0.01), str(value), ha="center", va="bottom", fontsize=7)

    for idx in range(len(stats_list), len(axes)):
        axes[idx].axis("off")

    fig.suptitle("Task counts across repositories", fontsize=13)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    repo_dirs = sorted([p for p in LOG_ROOT.iterdir() if p.is_dir()])
    if not repo_dirs:
        raise SystemExit(f"No repository directories found under {LOG_ROOT}")

    stats_list: list[dict[str, Any]] = []
    for repo_dir in repo_dirs:
        stats = load_repo_stats(repo_dir)
        stats_list.append(stats)
        output_path = OUTPUT_DIR / f"{stats['repo']}_task_stats.png"
        plot_repo_stats(stats, output_path)
        print(f"Saved {output_path}")

    combined_output_path = OUTPUT_DIR / "all_repositories_task_counts.png"
    plot_combined_repo_stats(stats_list, combined_output_path)
    print(f"Saved {combined_output_path}")


if __name__ == "__main__":
    main()
