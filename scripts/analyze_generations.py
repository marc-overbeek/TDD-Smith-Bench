"""Analyze test comparison JSON files and generate graphs of generation success rates by attempt.

Usage:
  uv run python scripts/analyze_generations.py file1.json file2.json ...

This script loads multiple test_comparison.json files (from different model runs),
analyzes generation success for each attempt (1, 2, 3), categorizing each attempt as:
- Full success: All originally failing tests were fixed (fixed_count == empty_fails_count)
- Partial success: Some but not all originally failing tests were fixed (0 < fixed_count < empty_fails_count)
- No success: No tests were fixed (fixed_count == 0)

It generates bar charts showing both cumulative success rates (any improvement) and 
cumulative full success rates (complete fixes only) across attempts.
"""

import argparse
import json
import matplotlib.pyplot as plt
from pathlib import Path


def analyze_attempt_success(entries):
    """Analyze success rates across attempts 1, 2, and 3 with three categories."""
    attempt_stats = {
        1: {"full_success": 0, "partial_success": 0, "no_success": 0, "total": 0}, 
        2: {"full_success": 0, "partial_success": 0, "no_success": 0, "total": 0}
    }
    
    # Track cumulative success at each attempt level (any improvement)
    cumulative_at_attempt = {1: 0, 2: 0}
    # Track cumulative full success at each attempt level
    full_cumulative_at_attempt = {1: 0, 2: 0}
    total_functions = 0
    
    for entry in entries:
        # Skip if no attempts data
        if "attempts" not in entry:
            continue
            
        total_functions += 1
        empty_fails_count = entry.get("empty_fails_count", 0)
        function_fixed_by_attempt = {1: False, 2: False}
        function_fully_fixed_by_attempt = {1: False, 2: False}
        
        for attempt_data in entry["attempts"]:
            attempt_num = attempt_data.get("attempt", 0)
            
            # Only track attempts 1, 2
            if attempt_num in [1, 2]:
                attempt_stats[attempt_num]["total"] += 1
                fixed_count = attempt_data.get("fixed_count", 0)
                
                if fixed_count == 0:
                    attempt_stats[attempt_num]["no_success"] += 1
                elif fixed_count == empty_fails_count:
                    attempt_stats[attempt_num]["full_success"] += 1
                    function_fully_fixed_by_attempt[attempt_num] = True
                else:
                    attempt_stats[attempt_num]["partial_success"] += 1
                
                if fixed_count > 0:
                    function_fixed_by_attempt[attempt_num] = True
        
        # Calculate cumulative success up to each attempt (any improvement)
        for attempt in [1, 2]:
            if any(function_fixed_by_attempt[i] for i in range(1, attempt + 1)):
                cumulative_at_attempt[attempt] += 1
        
        # Calculate cumulative full success up to each attempt
        for attempt in [1, 2]:
            if any(function_fully_fixed_by_attempt[i] for i in range(1, attempt + 1)):
                full_cumulative_at_attempt[attempt] += 1

    return attempt_stats, cumulative_at_attempt, full_cumulative_at_attempt, total_functions


def main(json_files):
    # Load and combine all data
    all_entries = []
    single_task_entries = []
    combined_task_entries = []
    for json_file in json_files:
        with open(json_file) as f:
            data = json.load(f)
            all_entries.extend(data)
            for entry in data:
                if entry["function"].startswith("combined::"):
                    combined_task_entries.append(entry)
                else:
                    single_task_entries.append(entry)



    # Analyze attempt success rates
    attempt_stats, cumulative_at_attempt, full_cumulative_at_attempt, total_functions = analyze_attempt_success(all_entries)
    single_stats, single_cumulative, single_full_cumulative, single_total_functions = analyze_attempt_success(single_task_entries)
    combined_stats, combined_cumulative, combined_full_cumulative, combined_total_functions = analyze_attempt_success(combined_task_entries)



    # Prepare data for plotting - cumulative success rates (any improvement)
    attempts = [1, 2]
    cumulative_rates = [(cumulative_at_attempt[i] / total_functions * 100) if total_functions > 0 else 0 for i in attempts]
    cumulative_counts = [cumulative_at_attempt[i] for i in attempts]
    
    single_cumulative_rates = [(single_cumulative[i] / single_total_functions * 100) if single_total_functions > 0 else 0 for i in attempts]
    single_cumulative_counts = [single_cumulative[i] for i in attempts]

    combined_cumulative_rates = [(combined_cumulative[i] / combined_total_functions * 100) if combined_total_functions > 0 else 0 for i in attempts]
    combined_cumulative_counts = [combined_cumulative[i] for i in attempts]


    # Prepare data for plotting - cumulative full success rates
    full_cumulative_rates = [(full_cumulative_at_attempt[i] / total_functions * 100) if total_functions > 0 else 0 for i in attempts]
    full_cumulative_counts = [full_cumulative_at_attempt[i] for i in attempts]

    single_full_cumulative_rates = [(single_full_cumulative[i] / single_total_functions * 100) if single_total_functions > 0 else 0 for i in attempts]
    single_full_cumulative_counts = [single_full_cumulative[i] for i in attempts]

    combined_full_cumulative_rates = [(combined_full_cumulative[i] / combined_total_functions * 100) if combined_total_functions > 0 else 0 for i in attempts]
    combined_full_cumulative_counts = [combined_full_cumulative[i] for i in attempts]


    # Print summary
    print("Generation Success Analysis by Attempt:")
    print(f"Total function generations analyzed: {len(all_entries)}")
    print(f"Total functions with attempt data: {total_functions}")
    print()
    
    for attempt in attempts:
        full = attempt_stats[attempt]["full_success"]
        partial = attempt_stats[attempt]["partial_success"]
        none = attempt_stats[attempt]["no_success"]
        total = attempt_stats[attempt]["total"]

        single_full = single_stats[attempt]["full_success"]
        single_partial = single_stats[attempt]["partial_success"]
        single_none = single_stats[attempt]["no_success"]
        single_total = single_stats[attempt]["total"]

        combined_full = combined_stats[attempt]["full_success"]
        combined_partial = combined_stats[attempt]["partial_success"]
        combined_none = combined_stats[attempt]["no_success"]
        combined_total = combined_stats[attempt]["total"]
        
        full_rate = (full / total * 100) if total > 0 else 0
        partial_rate = (partial / total * 100) if total > 0 else 0
        none_rate = (none / total * 100) if total > 0 else 0
        
        print(f"Attempt {attempt}:")
        print(f"  Full success: {full}/{total} ({full_rate:.1f}%)")
        print(f"  Partial success: {partial}/{total} ({partial_rate:.1f}%)")
        print(f"  No success: {none}/{total} ({none_rate:.1f}%)")
    
    print()
    for attempt in attempts:
        cumulative_successful = cumulative_at_attempt[attempt]
        cumulative_rate = cumulative_rates[attempt-1]
        print(f"Cumulative after attempt {attempt}: {cumulative_successful}/{total_functions} functions improved ({cumulative_rate:.1f}%)")
        
        full_cumulative_successful = full_cumulative_at_attempt[attempt]
        full_cumulative_rate = full_cumulative_rates[attempt-1]
        print(f"Cumulative full success after attempt {attempt}: {full_cumulative_successful}/{total_functions} functions fully fixed ({full_cumulative_rate:.1f}%)")
    




    # Create bar chart showing cumulative success (any improvement)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Left plot: Any improvement
    bars1 = ax1.bar([f"After Attempt {i}" for i in attempts], cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax1.set_ylabel('Cumulative Success Rate (%)')
    ax1.set_title('Cumulative LLM Function Regeneration Success\n(Any Improvement)')
    ax1.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars1, cumulative_rates, cumulative_counts):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{total_functions})', ha='center', va='bottom')
    
    # Right plot: Full success only
    bars2 = ax2.bar([f"After Attempt {i}" for i in attempts], full_cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax2.set_ylabel('Cumulative Full Success Rate (%)')
    ax2.set_title('Cumulative LLM Function Regeneration Success\n(Full Fixes Only)')
    ax2.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars2, full_cumulative_rates, full_cumulative_counts):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{total_functions})', ha='center', va='bottom')

    plt.tight_layout()
    
    # Save plot
    output_file = "generation_cumulative_success.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nGraph saved to {output_file}")

    # Show plot (optional, comment out if running headless)
    # plt.show()




    # Create bar chart showing cumulative success for single tasks only
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Left plot: Any improvement
    bars1 = ax1.bar([f"After Attempt {i}" for i in attempts], single_cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax1.set_ylabel('Cumulative Success Rate (%)')
    ax1.set_title('Cumulative LLM Function Regeneration Success\n(Any Improvement)')
    ax1.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars1, single_cumulative_rates, single_cumulative_counts):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{single_total_functions})', ha='center', va='bottom')
    
    # Right plot: Full success only
    bars2 = ax2.bar([f"After Attempt {i}" for i in attempts], single_full_cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax2.set_ylabel('Cumulative Full Success Rate (%)')
    ax2.set_title('Cumulative LLM Function Regeneration Success\n(Full Fixes Only)')
    ax2.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars2, single_full_cumulative_rates, single_full_cumulative_counts):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{single_total_functions})', ha='center', va='bottom')

    plt.tight_layout()
    
    # Save plot
    output_file = "single_task_generation_cumulative_success.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nGraph saved to {output_file}")




    # Create bar chart showing cumulative success for combined tasks only
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Left plot: Any improvement
    bars1 = ax1.bar([f"After Attempt {i}" for i in attempts], combined_cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax1.set_ylabel('Cumulative Success Rate (%)')
    ax1.set_title('Cumulative LLM Function Regeneration Success\n(Any Improvement)')
    ax1.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars1, combined_cumulative_rates, combined_cumulative_counts):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{combined_total_functions})', ha='center', va='bottom')
    
    # Right plot: Full success only
    bars2 = ax2.bar([f"After Attempt {i}" for i in attempts], combined_full_cumulative_rates, 
                    color=['skyblue', 'lightgreen', 'lightcoral'])
    ax2.set_ylabel('Cumulative Full Success Rate (%)')
    ax2.set_title('Cumulative LLM Function Regeneration Success\n(Full Fixes Only)')
    ax2.set_ylim(0, 100)
    
    # Add value labels on bars
    for bar, rate, count in zip(bars2, combined_full_cumulative_rates, combined_full_cumulative_counts):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{rate:.1f}%\n({count}/{combined_total_functions})', ha='center', va='bottom')

    plt.tight_layout()
    
    # Save plot
    output_file = "combined_task_generation_cumulative_success.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nGraph saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze LLM generation success from test comparison files.")
    parser.add_argument("json_files", nargs="+", help="Path to test_comparison.json files")
    args = parser.parse_args()
    main(args.json_files)