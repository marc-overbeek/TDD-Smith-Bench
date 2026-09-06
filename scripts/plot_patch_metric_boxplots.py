#!/usr/bin/env python3
"""Create model/repository plots for patch metric deltas split by success labels.

Outputs are written to results/boxplots by default:
1. LOC change pooled across all repositories, excluding pyupio by default.
2. Complexity hurdle plot pooled across all repositories, excluding pyupio by default.
3. LOC change by repository, excluding pyupio by default.
4. Complexity hurdle plot by repository, excluding pyupio by default.

Both plots compare successful vs unsuccessful generations for each model.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib.pyplot as plt

from summarize_patch_metrics_by_repo_model import (
    METRICS_SUFFIX,
    RESULT_SUFFIX,
    build_normalized_rows,
    format_model_label,
    full_success_lookup,
    parse_repo_model_filename,
)


STATUS_ORDER = ["successful", "unsuccessful"]
STATUS_COLORS = {"successful": "#1f77b4", "unsuccessful": "#d62728"}
MODEL_ORDER = ["Claude Haiku 4.5", "Claude Sonnet 4.6", "Qwen3 Coder 30B"]
SIGN_BUCKETS = ["negative", "zero", "positive"]
SIGN_COLORS = {"negative": "#4c72b0", "zero": "#b5b5b5", "positive": "#dd8452"}


def collect_rows(results_dir: Path, metrics_dir: Path) -> list[dict[str, object]]:
    comparison_files = {
        parsed: path
        for path in sorted(results_dir.glob(f"*{RESULT_SUFFIX}"))
        if (parsed := parse_repo_model_filename(path, RESULT_SUFFIX)) is not None
    }

    collected: list[dict[str, object]] = []
    for metrics_file in sorted(metrics_dir.glob(f"*{METRICS_SUFFIX}")):
        parsed = parse_repo_model_filename(metrics_file, METRICS_SUFFIX)
        if parsed is None:
            continue
        repo, model = parsed
        comparison_file = comparison_files.get((repo, model))
        if comparison_file is None:
            continue

        lookup = full_success_lookup(comparison_file)
        normalized_rows, _coverage = build_normalized_rows(metrics_file, lookup)
        model_label = format_model_label(model)

        for row in normalized_rows:
            full_success = row.get("full_success")
            if full_success is None:
                continue
            row_copy: dict[str, object] = dict(row)
            row_copy["repo"] = repo
            row_copy["model_label"] = model_label
            row_copy["status"] = "successful" if full_success is True else "unsuccessful"
            collected.append(row_copy)

    return collected


def draw_combined_metric_boxplot(
    rows: list[dict[str, object]],
    metric_key: str,
    ylabel: str,
    title: str,
    output_path: Path,
    excluded_repos: set[str],
) -> None:
    filtered = [
        row for row in rows if isinstance(row.get("repo"), str) and row["repo"] not in excluded_repos
    ]

    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    width = 0.30
    x_positions = list(range(len(MODEL_ORDER)))

    for status_index, status in enumerate(STATUS_ORDER):
        status_shift = (-0.5 + status_index) * width
        data_series: list[list[float]] = []
        box_positions: list[float] = []

        for model_index, model in enumerate(MODEL_ORDER):
            values = [
                float(row[metric_key])
                for row in filtered
                if row.get("model_label") == model
                and row.get("status") == status
                and isinstance(row.get(metric_key), (int, float))
            ]
            if values:
                data_series.append(values)
                box_positions.append(x_positions[model_index] + status_shift)

        if not data_series:
            continue

        bp = ax.boxplot(
            data_series,
            positions=box_positions,
            widths=width * 0.9,
            patch_artist=True,
            showfliers=False,
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(STATUS_COLORS[status])
            patch.set_alpha(0.55)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(MODEL_ORDER)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    handles = [
        plt.Line2D([0], [0], color=STATUS_COLORS[status], lw=8, alpha=0.7)
        for status in STATUS_ORDER
    ]
    ax.legend(
        handles,
        [s.title() for s in STATUS_ORDER],
        loc="upper center",
        bbox_to_anchor=(0.5, 1.16),
        ncol=2,
        frameon=False,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def draw_per_repo_metric_boxplot(
    rows: list[dict[str, object]],
    metric_key: str,
    ylabel: str,
    title: str,
    output_path: Path,
    excluded_repos: set[str],
) -> None:
    filtered = [
        row for row in rows if isinstance(row.get("repo"), str) and row["repo"] not in excluded_repos
    ]
    repos = sorted({str(row["repo"]) for row in filtered if isinstance(row.get("repo"), str)})
    if not repos:
        return

    ncols = 3
    nrows = math.ceil(len(repos) / ncols)
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(6.0 * ncols, 3.8 * nrows),
        squeeze=False,
        constrained_layout=True,
    )

    width = 0.30
    x_positions = list(range(len(MODEL_ORDER)))

    for idx, repo in enumerate(repos):
        ax = axes[idx // ncols][idx % ncols]

        for status_index, status in enumerate(STATUS_ORDER):
            status_shift = (-0.5 + status_index) * width
            data_series: list[list[float]] = []
            box_positions: list[float] = []

            for model_index, model in enumerate(MODEL_ORDER):
                values = [
                    float(row[metric_key])
                    for row in filtered
                    if row.get("repo") == repo
                    and row.get("model_label") == model
                    and row.get("status") == status
                    and isinstance(row.get(metric_key), (int, float))
                ]
                if values:
                    data_series.append(values)
                    box_positions.append(x_positions[model_index] + status_shift)

            if not data_series:
                continue

            bp = ax.boxplot(
                data_series,
                positions=box_positions,
                widths=width * 0.9,
                patch_artist=True,
                showfliers=False,
            )
            for patch in bp["boxes"]:
                patch.set_facecolor(STATUS_COLORS[status])
                patch.set_alpha(0.55)

        repo_label = repo.replace("__", " ").split(".", 1)[0]
        ax.set_title(repo_label, fontsize=10)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(MODEL_ORDER, rotation=15, ha="right", fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.25)
        if idx % ncols == 0:
            ax.set_ylabel(ylabel)

    for idx in range(len(repos), nrows * ncols):
        axes[idx // ncols][idx % ncols].axis("off")

    handles = [
        plt.Line2D([0], [0], color=STATUS_COLORS[status], lw=8, alpha=0.7)
        for status in STATUS_ORDER
    ]
    fig.legend(
        handles,
        [s.title() for s in STATUS_ORDER],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
        ncol=2,
        frameon=False,
    )
    fig.suptitle(title, fontsize=14, y=1.06)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _complexity_group_values(
    rows: list[dict[str, object]],
    repo: str | None,
) -> dict[tuple[str, str], list[float]]:
    grouped: dict[tuple[str, str], list[float]] = {}
    for model in MODEL_ORDER:
        for status in STATUS_ORDER:
            grouped[(model, status)] = []

    for row in rows:
        row_repo = row.get("repo")
        if repo is not None and row_repo != repo:
            continue
        model = row.get("model_label")
        status = row.get("status")
        value = row.get("complexity_change")
        if not isinstance(model, str) or not isinstance(status, str):
            continue
        if (model, status) not in grouped:
            continue
        if isinstance(value, (int, float)):
            grouped[(model, status)].append(float(value))

    return grouped


def _draw_hurdle_axes(
    ax_top: plt.Axes,
    ax_bottom: plt.Axes,
    grouped_values: dict[tuple[str, str], list[float]],
    title: str,
    ylabel_bottom: str,
    show_bottom_xticks: bool,
) -> None:
    width = 0.30
    x_positions = list(range(len(MODEL_ORDER)))

    for status_index, status in enumerate(STATUS_ORDER):
        status_shift = (-0.5 + status_index) * width
        for model_index, model in enumerate(MODEL_ORDER):
            values = grouped_values.get((model, status), [])
            total = len(values)
            if total == 0:
                continue

            negative = sum(1 for v in values if v < 0) / total
            zero = sum(1 for v in values if v == 0) / total
            positive = sum(1 for v in values if v > 0) / total
            xpos = x_positions[model_index] + status_shift

            ax_top.bar(xpos, negative, width=width * 0.9, color=SIGN_COLORS["negative"])
            ax_top.bar(
                xpos,
                zero,
                width=width * 0.9,
                bottom=negative,
                color=SIGN_COLORS["zero"],
            )
            ax_top.bar(
                xpos,
                positive,
                width=width * 0.9,
                bottom=negative + zero,
                color=SIGN_COLORS["positive"],
            )

            # No status-colored border rectangle; keep hurdle bars fill-only.

    ax_top.set_ylim(0, 1)
    ax_top.set_ylabel("Share")
    ax_top.set_title(title)
    ax_top.grid(axis="y", linestyle="--", alpha=0.25)
    ax_top.set_xticks(x_positions)
    ax_top.set_xticklabels([])
    for xpos in x_positions:
        ax_top.text(
            xpos,
            -0.16,
            "Successful (left) | Unsuccessful (right)",
            transform=ax_top.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=7,
            color="#444444",
        )

    for status_index, status in enumerate(STATUS_ORDER):
        status_shift = (-0.5 + status_index) * width
        data_series: list[list[float]] = []
        box_positions: list[float] = []

        for model_index, model in enumerate(MODEL_ORDER):
            values = [v for v in grouped_values.get((model, status), []) if v != 0]
            if values:
                data_series.append(values)
                box_positions.append(x_positions[model_index] + status_shift)

        if not data_series:
            continue

        bp = ax_bottom.boxplot(
            data_series,
            positions=box_positions,
            widths=width * 0.9,
            patch_artist=True,
            showfliers=True,
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(STATUS_COLORS[status])
            patch.set_alpha(0.55)

    ax_bottom.set_ylabel(ylabel_bottom)
    ax_bottom.grid(axis="y", linestyle="--", alpha=0.25)
    ax_bottom.set_xticks(x_positions)
    if show_bottom_xticks:
        ax_bottom.set_xticklabels(MODEL_ORDER, rotation=15, ha="right", fontsize=8)
    else:
        ax_bottom.set_xticklabels([])


def draw_combined_complexity_hurdle_plot(
    rows: list[dict[str, object]],
    title: str,
    output_path: Path,
    excluded_repos: set[str],
) -> None:
    filtered = [
        row for row in rows if isinstance(row.get("repo"), str) and row["repo"] not in excluded_repos
    ]
    grouped = _complexity_group_values(filtered, repo=None)

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(10, 8),
        constrained_layout=True,
        gridspec_kw={"height_ratios": [1, 1.2]},
    )

    _draw_hurdle_axes(
        ax_top=axes[0],
        ax_bottom=axes[1],
        grouped_values=grouped,
        title=title,
        ylabel_bottom="Non-zero complexity change",
        show_bottom_xticks=True,
    )

    sign_handles = [
        plt.Line2D([0], [0], color=SIGN_COLORS[bucket], lw=8) for bucket in SIGN_BUCKETS
    ]
    fig.legend(
        sign_handles,
        [b.title() for b in SIGN_BUCKETS],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
        ncol=3,
        frameon=False,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def draw_per_repo_complexity_hurdle_plot(
    rows: list[dict[str, object]],
    title: str,
    output_path: Path,
    excluded_repos: set[str],
) -> None:
    filtered = [
        row for row in rows if isinstance(row.get("repo"), str) and row["repo"] not in excluded_repos
    ]
    repos = sorted({str(row["repo"]) for row in filtered if isinstance(row.get("repo"), str)})
    if not repos:
        return

    ncols = 3
    repo_rows = math.ceil(len(repos) / ncols)
    fig, axes = plt.subplots(
        repo_rows * 2,
        ncols,
        figsize=(6.2 * ncols, 6.2 * repo_rows),
        squeeze=False,
        constrained_layout=True,
        gridspec_kw={"height_ratios": [1, 1.2] * repo_rows},
    )

    for idx, repo in enumerate(repos):
        row_block = idx // ncols
        col = idx % ncols
        ax_top = axes[row_block * 2][col]
        ax_bottom = axes[row_block * 2 + 1][col]
        grouped = _complexity_group_values(filtered, repo=repo)
        repo_label = repo.replace("__", " ").split(".", 1)[0]

        _draw_hurdle_axes(
            ax_top=ax_top,
            ax_bottom=ax_bottom,
            grouped_values=grouped,
            title=repo_label,
            ylabel_bottom="Non-zero change",
            show_bottom_xticks=True,
        )

    total_slots = repo_rows * ncols
    for idx in range(len(repos), total_slots):
        row_block = idx // ncols
        col = idx % ncols
        axes[row_block * 2][col].axis("off")
        axes[row_block * 2 + 1][col].axis("off")

    fig.suptitle(title, fontsize=14)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate pooled patch-metric boxplots for successful vs unsuccessful "
            "generations per model."
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
        "--output-dir",
        type=Path,
        default=Path("results") / "boxplots",
        help="Directory where all boxplot PNGs will be written.",
    )
    parser.add_argument(
        "--exclude-repo-prefix",
        action="append",
        default=["pyupio__safety"],
        help="Repo prefix to exclude from pooled plots. Can be passed multiple times.",
    )
    args = parser.parse_args()

    rows = collect_rows(args.results_dir, args.metrics_dir)
    if not rows:
        raise SystemExit("No matched rows found to plot.")

    repos = sorted({str(row["repo"]) for row in rows if isinstance(row.get("repo"), str)})
    excluded_repos = {
        repo
        for repo in repos
        if any(repo.startswith(prefix) for prefix in args.exclude_repo_prefix)
    }

    draw_combined_metric_boxplot(
        rows=rows,
        metric_key="net_loc_change",
        ylabel="Net LOC change",
        title="LOC Change (All Repositories Combined, Excluding pyupio)",
        output_path=args.output_dir / "loc_change_combined_success_vs_unsuccessful_excluding_pyupio.png",
        excluded_repos=excluded_repos,
    )

    draw_combined_complexity_hurdle_plot(
        rows=rows,
        title="Complexity Hurdle Plot (All Repositories Combined, Excluding pyupio)",
        output_path=args.output_dir
        / "complexity_change_combined_success_vs_unsuccessful_excluding_pyupio.png",
        excluded_repos=excluded_repos,
    )

    draw_per_repo_metric_boxplot(
        rows=rows,
        metric_key="net_loc_change",
        ylabel="Net LOC change",
        title="LOC Change by Repository (Successful vs Unsuccessful, Excluding pyupio)",
        output_path=args.output_dir
        / "loc_change_per_repo_success_vs_unsuccessful_excluding_pyupio.png",
        excluded_repos=excluded_repos,
    )

    draw_per_repo_complexity_hurdle_plot(
        rows=rows,
        title="Complexity Hurdle Plot by Repository (Successful vs Unsuccessful, Excluding pyupio)",
        output_path=args.output_dir
        / "complexity_change_per_repo_success_vs_unsuccessful_excluding_pyupio.png",
        excluded_repos=excluded_repos,
    )

    print(f"Wrote plots to: {args.output_dir}")


if __name__ == "__main__":
    main()
