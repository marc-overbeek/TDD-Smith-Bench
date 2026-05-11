#!/usr/bin/env python3
"""
Analyze test case failure frequency across regenerated function comparisons.

This script reads one or more `*_test_comparison.json` files, counts how many
times each test was originally broken, fixed, or still broken by the
regenerated patch, and produces a bar chart for the most frequent test cases.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def aggregate_test_case_counts(json_files, top_n=30):
    broken_counts = defaultdict(int)
    fixed_counts = defaultdict(int)
    still_broken_counts = defaultdict(int)
    unknown_counts = defaultdict(int)

    for json_file in json_files:
        with open(json_file, 'r') as f:
            data = json.load(f)

        for entry in data:
            empty_broken = entry.get('empty_broken', [])
            regen_broken = entry.get('regen_broken', [])
            regen_report_missing = entry.get('regen_fails_count', -1) == -1

            regen_broken_set = set(regen_broken)
            for test_name in empty_broken:
                broken_counts[test_name] += 1
                if regen_report_missing or '<NO_VALIDATION_REPORT_FOUND>' in regen_broken_set:
                    unknown_counts[test_name] += 1
                elif test_name in regen_broken_set:
                    still_broken_counts[test_name] += 1
                else:
                    fixed_counts[test_name] += 1

    # Choose top tests by original broken frequency
    top_tests = sorted(broken_counts.keys(), key=lambda t: broken_counts[t], reverse=True)[:top_n]
    return top_tests, broken_counts, fixed_counts, still_broken_counts, unknown_counts


def plot_test_case_counts(output_path, top_tests, broken_counts, fixed_counts, still_broken_counts, unknown_counts):
    labels = top_tests
    x = list(range(len(labels)))

    fixed = [fixed_counts[t] for t in labels]
    still_broken = [still_broken_counts[t] for t in labels]
    unknown = [unknown_counts[t] for t in labels]

    fig, ax = plt.subplots(figsize=(max(12, len(labels) * 0.3), 8))

    ax.bar(x, fixed, label='Fixed', color='#4CAF50')
    ax.bar(x, still_broken, bottom=fixed, label='Still Broken', color='#F44336')
    if any(unknown):
        bottom_unknown = [fixed[i] + still_broken[i] for i in range(len(labels))]
        ax.bar(x, unknown, bottom=bottom_unknown, label='Unknown', color='#9E9E9E')

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=90, fontsize=8)
    ax.set_ylabel('Occurrences')
    ax.set_title('Test Case Broken/Fixed Counts Across Regenerated Functions')
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.4)

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.35)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Analyze per-test-case broken/fixed counts from LLM regen comparisons.'
    )
    parser.add_argument('json_files', nargs='+', help='One or more test comparison JSON files')
    parser.add_argument('--top', type=int, default=30, help='Number of top test cases to plot')
    parser.add_argument('--output', type=Path, default=Path('test_case_failure_analysis.png'))
    args = parser.parse_args()

    top_tests, broken_counts, fixed_counts, still_broken_counts, unknown_counts = aggregate_test_case_counts(
        args.json_files,
        top_n=args.top,
    )

    if not top_tests:
        print('No test cases found in the provided JSON files.')
        return

    output_path = plot_test_case_counts(
        args.output,
        top_tests,
        broken_counts,
        fixed_counts,
        still_broken_counts,
        unknown_counts,
    )

    summary = [
        {
            'test_name': test_name,
            'broken': broken_counts[test_name],
            'fixed': fixed_counts[test_name],
            'still_broken': still_broken_counts[test_name],
            'unknown': unknown_counts[test_name],
        }
        for test_name in top_tests
    ]

    summary_path = args.output.with_suffix('.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f'Plotted top {len(top_tests)} test cases to {output_path}')
    print(f'Summary data saved to {summary_path}')


if __name__ == '__main__':
    main()
