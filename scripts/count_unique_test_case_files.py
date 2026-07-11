#!/usr/bin/env python3
"""Print the number of test cases and unique file paths in each repository's _test_case_map.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGE_LOG_ROOT = ROOT / "logs" / "change_logs"


def main() -> None:
    repo_dirs = sorted([p for p in CHANGE_LOG_ROOT.iterdir() if p.is_dir()])
    if not repo_dirs:
        raise SystemExit(f"No repository directories found under {CHANGE_LOG_ROOT}")

    for repo_dir in repo_dirs:
        test_map_path = repo_dir / "_test_case_map.json"
        if not test_map_path.exists():
            print(f"{repo_dir.name}: no _test_case_map.json")
            continue

        with test_map_path.open() as f:
            test_map = json.load(f)

        unique_paths = {entry.get("file_path") for entry in test_map.values() if entry.get("file_path")}
        print(f"{repo_dir.name}: {len(test_map)} test cases, {len(unique_paths)} unique file paths")


if __name__ == "__main__":
    main()
