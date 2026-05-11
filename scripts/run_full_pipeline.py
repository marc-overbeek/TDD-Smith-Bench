#!/usr/bin/env python3
"""
Complete LLM Function Regeneration Pipeline

This script runs the full workflow to:
1. Generate empty-body patches and validate them
2. Use LLM to regenerate function bodies from failing tests
3. Validate the regenerated patches
4. Compare results and generate analysis

Usage:
  uv run python scripts/run_full_pipeline.py Instagram__MonkeyType.70c3acf6 --model ollama/gpt-oss:120b
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> None:
    """Run a command with logging."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"Command: {' '.join(cmd)}")
    print('='*60)

    try:
        result = subprocess.run(cmd, check=True, capture_output=False, text=True)
        print(f"{description} completed successfully")
    except subprocess.CalledProcessError as e:
        print(f"{description} failed with exit code {e.returncode}")
        print(f"Error output: {e.stderr}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete LLM function regeneration pipeline"
    )
    parser.add_argument("repo", help="Repository key (e.g., Instagram__MonkeyType.70c3acf6)")
    parser.add_argument(
        "--model",
        default="claude-3-5-sonnet-20241022",
        help="LLM model to use for regeneration"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of workers for validation"
    )
    parser.add_argument(
        "--max-functions",
        type=int,
        default=-1,
        help="Limit number of functions to process (-1 for all)"
    )
    parser.add_argument(
        "--max-bugs",
        type=int,
        default=-1,
        help="Limit number of bugs to regenerate (-1 for all)"
    )
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=-1,
        help="Limit number of tasks/functions to generate and process through the full pipeline (-1 for all)."
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=1,
        help="Maximum number of regeneration attempts for still-failing functions."
    )

    args = parser.parse_args()
    repo = args.repo

    print(f"Starting complete LLM regeneration pipeline for {repo}")
    print(f"Model: {args.model}")
    print(f"Workers: {args.workers}")
    print(f"Max tasks: {args.max_tasks}")
    print(f"Max attempts: {args.max_attempts}")

    # Step 1: Generate empty-body patches and run initial validation
    run_command([
        "uv", "run", "python", "scripts/generate_empty_body_changes.py",
        repo,
        "--workers", str(args.workers),
        "--max_functions", str(
            args.max_tasks if args.max_tasks != -1 else args.max_functions
        )
    ], "Generate empty-body patches and validate")

    # Step 2: Generate LLM-regenerated patches
    run_command([
        "uv", "run", "python", "scripts/generate_regen_from_tests.py",
        repo,
        "--model", args.model,
        "--max_bugs", str(args.max_bugs),
        "--max_attempts", str(args.max_attempts),
        "--workers", str(args.workers),
    ], "Generate LLM-regenerated function bodies")

    # Step 3: Collect regenerated patches for validation
    run_command([
        "uv", "run", "python", "-m", "swesmith.bug_gen.collect_patches",
        f"logs/bug_gen/{repo}",
        "--type", "lm_regen_from_tests"
    ], "Collect regenerated patches")

    # Step 4: Run validation on regenerated patches
    patches_file = f"logs/bug_gen/{repo}_lm_regen_from_tests_patches.json"
    if not Path(patches_file).exists():
        print(f"Patches file {patches_file} not found")
        sys.exit(1)

    run_command([
        "uv", "run", "python", "-m", "swesmith.harness.valid",
        patches_file,
        "--workers", str(args.workers)
    ], "Validate regenerated patches")

    # Step 5: Compare validation results
    run_command([
        "uv", "run", "python", "scripts/compare_test_results.py",
        repo
    ], "Compare empty-body vs regenerated results")

    # Step 6: Generate analysis graphs
    comparison_file = f"{repo}_test_comparison.json"
    if Path(comparison_file).exists():
        run_command([
            "uv", "run", "python", "scripts/analyze_generations.py",
            comparison_file
        ], "Generate success rate analysis")

        run_command([
            "uv", "run", "python", "scripts/analyze_test_case_failures.py",
            comparison_file,
            "--top", "20"
        ], "Generate test case failure analysis")

        run_command([
            "uv", "run", "python", "scripts/analyze_complexity.py"
        ], "Generate complexity comparison")

    print(f"\nPipeline completed successfully for {repo}!")
    print(f"Results saved to: {repo}_test_comparison.json")
    print("Analysis graphs: generation_success_analysis.png, test_case_failure_analysis.png")
    print("Complexity data: complexity_comparison.json")


if __name__ == "__main__":
    main()