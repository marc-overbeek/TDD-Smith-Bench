import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


RESULT_SUFFIX = "_test_comparison.json"
SKIP_PREFIXES = ("pyupio__",)


def parse_results_filename(path: Path) -> tuple[str, str] | None:
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


def format_model_name(model: str) -> str:
    if model.endswith("wxnknl6gvktb"):
        return "Haiku"
    if model.endswith("gewiaj6mtzjm"):
        return "Qwen"
    if model.endswith("ql4mbrrqznnz"):
        return "Sonnet"
    return model


def analyze_attempts(file_path: Path, output_dir: Path) -> Path:
    with file_path.open("r") as file:
        data = json.load(file)

    parsed = parse_results_filename(file_path)
    if parsed is None:
        raise ValueError(f"Unexpected result filename: {file_path.name}")
    repo, model = parsed

    # Categories: single, combined
    # We want to track percentage of tests still broken relative to empty_fails_count
    stats = {
        'single': {'a1_pct': [], 'a2_pct': []},
        'combined': {'a1_pct': [], 'a2_pct': []}
    }

    for result in data:
        func_name = result.get('function', '')
        cat = 'combined' if func_name.startswith("combined:") else 'single'
        empty_fails = result.get('empty_fails_count', 0)
        
        if empty_fails == 0:
            continue
            
        attempts = result.get('attempts', [])
        a1 = next((a for a in attempts if a['attempt'] == 1), None)
        a2 = next((a for a in attempts if a['attempt'] == 2), None)
        
        if a1:
            stats[cat]['a1_pct'].append(a1['still_broken_count'] / empty_fails)
            
            # Logic for attempt 2:
            if a2:
                stats[cat]['a2_pct'].append(a2['still_broken_count'] / empty_fails)
            elif a1['still_broken_count'] == 0:
                # If a1 fixed everything, a2 has 0 broken
                stats[cat]['a2_pct'].append(0.0)
            else:
                # If no a2 but a1 still had broken tests, we assume it stayed broken
                stats[cat]['a2_pct'].append(a1['still_broken_count'] / empty_fails)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    bins = np.linspace(0, 100, 11)

    # Plot 1: Single Attempts Distribution
    s_a1 = np.array(stats['single']['a1_pct']) * 100
    s_a2 = np.array(stats['single']['a2_pct']) * 100
    ax1.hist([s_a1, s_a2], bins=bins, label=['Attempt 1', 'Attempt 2'], color=['skyblue', 'salmon'], rwidth=0.8)
    ax1.set_xlabel('% Still Broken')
    ax1.set_ylabel('Count of Functions')
    ax1.set_title('Single: Count of % Still Broken appearing')
    ax1.set_xticks(bins)
    ax1.legend()
    ax1.grid(axis='y', linestyle='--', alpha=0.7)

    # Plot 2: Combined Attempts Distribution
    c_a1 = np.array(stats['combined']['a1_pct']) * 100
    c_a2 = np.array(stats['combined']['a2_pct']) * 100
    ax2.hist([c_a1, c_a2], bins=bins, label=['Attempt 1', 'Attempt 2'], color=['skyblue', 'salmon'], rwidth=0.8)
    ax2.set_xlabel('% Still Broken')
    ax2.set_ylabel('Count of Functions')
    ax2.set_title('Combined: Count of % Still Broken appearing')
    ax2.set_xticks(bins)
    ax2.legend()
    ax2.grid(axis='y', linestyle='--', alpha=0.7)

    plt.tight_layout()
    output_file = output_dir / f"{repo}_{format_model_name(model)}_percentage_broken_tests.png"
    plt.savefig(output_file)
    plt.close(fig)
    return output_file


def iter_result_files(results_dir: Path):
    for path in sorted(results_dir.glob(f"*{RESULT_SUFFIX}")):
        if any(path.name.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        yield path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create per-result attempt success histograms from results/*.json files."
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
        default=Path("results") / "percentage_broken_tests",
        help="Directory where plot images are written.",
    )
    args = parser.parse_args()

    if not args.results_dir.exists():
        raise FileNotFoundError(f"Results directory not found: {args.results_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for result_file in iter_result_files(args.results_dir):
        generated.append(analyze_attempts(result_file, args.output_dir))

    if not generated:
        print("No matching result files found.")
        return

    for output_file in generated:
        print(f"Comparison plot saved to {output_file}")


if __name__ == "__main__":
    main()
