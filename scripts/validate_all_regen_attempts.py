#!/usr/bin/env python3
"""Run validation for all regen patch manifests under logs/bug_gen.

This script discovers files matching:
  logs/bug_gen/<repo>/<model_id>/<repo>_lm_regen_from_tests_attempt_<n>_patches.json

For each match, it runs:
  uv run python -m swesmith.harness.valid <manifest> --workers 8 --output_subdir <model_id>

Usage:
  uv run python scripts/validate_all_regen_attempts.py
  uv run python scripts/validate_all_regen_attempts.py --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ATTEMPT_RE = re.compile(r"_lm_regen_from_tests_attempt_(\d+)_patches\.json$")


@dataclass(frozen=True)
class Job:
    repo: str
    model_id: str
    attempt: int
    manifest: Path


def _parse_csv(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    values = {x.strip() for x in raw.split(",") if x.strip()}
    return values or None


def _parse_attempt_csv(raw: str | None) -> set[int] | None:
    if raw is None:
        return None
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.add(int(part))
    return values or None


def discover_jobs(
    bug_gen_root: Path,
    repo_filter: set[str] | None = None,
    model_filter: set[str] | None = None,
    attempt_filter: set[int] | None = None,
) -> list[Job]:
    jobs: list[Job] = []
    if not bug_gen_root.exists():
        raise FileNotFoundError(f"Not found: {bug_gen_root}")

    for repo_dir in sorted(p for p in bug_gen_root.iterdir() if p.is_dir()):
        repo = repo_dir.name
        if repo_filter is not None and repo not in repo_filter:
            continue

        for model_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
            model_id = model_dir.name
            if model_filter is not None and model_id not in model_filter:
                continue

            pattern = f"{repo}_lm_regen_from_tests_attempt_*_patches.json"
            for manifest in sorted(model_dir.glob(pattern)):
                match = ATTEMPT_RE.search(manifest.name)
                if match is None:
                    continue

                attempt = int(match.group(1))
                if attempt_filter is not None and attempt not in attempt_filter:
                    continue

                jobs.append(
                    Job(
                        repo=repo,
                        model_id=model_id,
                        attempt=attempt,
                        manifest=manifest,
                    )
                )

    jobs.sort(key=lambda j: (j.repo, j.model_id, j.attempt, str(j.manifest)))
    return jobs


def run_job(job: Job, workers: int, dry_run: bool) -> int:
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "swesmith.harness.valid",
        str(job.manifest),
        "--workers",
        str(workers),
        "--output_subdir",
        job.model_id,
        "--redo_existing",
    ]

    print(f"[{job.repo} | {job.model_id} | attempt {job.attempt}]")
    print("  " + " ".join(cmd))

    if dry_run:
        return 0

    completed = subprocess.run(cmd)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run validation for all repo/model/attempt regen manifests under logs/bug_gen.",
    )
    parser.add_argument(
        "--bug-gen-root",
        type=Path,
        default=Path("logs/bug_gen"),
        help="Root bug_gen directory.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Workers passed to swesmith.harness.valid.",
    )
    parser.add_argument(
        "--repos",
        type=str,
        default=None,
        help="Optional CSV repo filter.",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Optional CSV model_id filter.",
    )
    parser.add_argument(
        "--attempts",
        type=str,
        default=None,
        help="Optional CSV attempt filter, e.g. 1,2.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands only.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately if a command fails.",
    )
    args = parser.parse_args()

    repo_filter = _parse_csv(args.repos)
    model_filter = _parse_csv(args.models)

    try:
        attempt_filter = _parse_attempt_csv(args.attempts)
    except ValueError:
        print("Invalid --attempts value. Use comma-separated integers, e.g. 1,2", file=sys.stderr)
        return 2

    jobs = discover_jobs(
        bug_gen_root=args.bug_gen_root,
        repo_filter=repo_filter,
        model_filter=model_filter,
        attempt_filter=attempt_filter,
    )

    if not jobs:
        print("No matching manifests found.")
        return 0

    print(f"Discovered {len(jobs)} validation job(s).")

    failures = 0
    for job in jobs:
        code = run_job(job=job, workers=args.workers, dry_run=args.dry_run)
        if code != 0:
            failures += 1
            print(f"  FAILED (exit={code})")
            if args.stop_on_error:
                return code

    print(f"Done. jobs={len(jobs)} failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
