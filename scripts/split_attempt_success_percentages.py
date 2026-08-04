"""Split compact attempt success data into scope-specific percentage CSV files.

Usage:
  uv run python scripts/split_attempt_success_percentages.py

Input defaults to:
  results/attempt_success_graphs/attempt_success_table_compact_full.csv

Outputs:
  results/attempt_success_graphs/attempt_success_percentages_full.csv
  results/attempt_success_graphs/attempt_success_percentages_combined.csv
  results/attempt_success_graphs/attempt_success_percentages_single.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


SCOPE_TO_OUTPUT_NAME = {
    "all": "full",
    "combined": "combined",
    "single": "single",
}


def write_scope_csv(
    rows: list[dict[str, str]],
    output_path: Path,
    fieldnames: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create three scope-specific CSV files from attempt_success_table_compact_full.csv "
            "that contain only percentage columns."
        )
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=Path("results") / "attempt_success_graphs" / "attempt_success_table_compact_full.csv",
        help="Path to attempt_success_table_compact_full.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results") / "attempt_success_graphs",
        help="Directory where split CSV files are written.",
    )
    args = parser.parse_args()

    if not args.input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {args.input_csv}")

    with args.input_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Input CSV is missing a header row.")

        percent_columns = [name for name in reader.fieldnames if name.endswith("_percent")]
        if not percent_columns:
            raise ValueError("No percentage columns found in input CSV.")

        required_columns = ["repo", "scope"]
        for col in required_columns:
            if col not in reader.fieldnames:
                raise ValueError(f"Input CSV is missing required column: {col}")

        output_fieldnames = ["repo"] + percent_columns
        rows_by_scope: dict[str, list[dict[str, str]]] = {scope: [] for scope in SCOPE_TO_OUTPUT_NAME}

        for row in reader:
            scope = row.get("scope", "")
            if scope not in rows_by_scope:
                continue

            reduced = {"repo": row.get("repo", "")}
            for col in percent_columns:
                reduced[col] = row.get(col, "")
            rows_by_scope[scope].append(reduced)

    written_files: list[Path] = []
    for scope, output_name in SCOPE_TO_OUTPUT_NAME.items():
        output_path = args.output_dir / f"attempt_success_percentages_{output_name}.csv"
        write_scope_csv(rows_by_scope[scope], output_path, output_fieldnames)
        written_files.append(output_path)

    print("Wrote split percentage CSV files:")
    for path in written_files:
        print(f"- {path}")


if __name__ == "__main__":
    main()