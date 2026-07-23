"""Revalidate existing patches using model-specific instance IDs.

This script reads patches from logs/bug_gen/<repo>/<model>/*_patches.json
and writes them to logs/run_validation using model-tagged instance IDs,
then runs the validation harness to populate report.json files.

Usage:
  uv run python scripts/revalidate_with_model_ids.py <repo>
  uv run python scripts/revalidate_with_model_ids.py <repo> --model <model_id>
  uv run python scripts/revalidate_with_model_ids.py <repo> --dry-run
"""

import argparse
import json
from pathlib import Path
from typing import Optional
import subprocess


def _get_model_id(model: str) -> str:
    """Extract a filesystem-safe model identifier from a model string."""
    model_id = model.replace("/", "_").replace(":", "_").replace("-", "_")
    return model_id


def _regen_instance_id(
    repo: str, base_hash: str, attempt: int, model_id: str | None = None
) -> str:
    """Generate regen instance ID matching new schema."""
    if model_id:
        return f"{repo}.lm_regen_from_tests__{base_hash}__model_{model_id}__attempt_{attempt}"
    return f"{repo}.lm_regen_from_tests__{base_hash}__attempt_{attempt}"


def discover_model_manifests(repo: str) -> dict[str, list[Path]]:
    """Find all patch manifest files grouped by model."""
    bug_gen_dir = Path("logs/bug_gen") / repo
    model_manifests: dict[str, list[Path]] = {}

    if not bug_gen_dir.exists():
        return model_manifests

    for model_dir in bug_gen_dir.iterdir():
        if not model_dir.is_dir():
            continue

        model_id = model_dir.name
        manifests = sorted(model_dir.glob("*_lm_regen_from_tests_attempt_*_patches.json"))
        if manifests:
            model_manifests[model_id] = manifests

    return model_manifests


def prepare_patches_for_validation(
    repo: str,
    model_id: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    """Prepare patches for revalidation with model-specific IDs."""
    model_manifests = discover_model_manifests(repo)

    if not model_manifests:
        print(f"No patch manifests found for {repo}")
        return 0

    models_to_process = (
        {model_id: model_manifests[model_id]}
        if model_id and model_id in model_manifests
        else model_manifests
    )

    total_prepared = 0
    total_counted = 0

    for current_model_id, manifests in sorted(models_to_process.items()):
        run_validation_dir = Path("logs/run_validation") / repo / current_model_id
        print(f"\n{current_model_id}:")
        print(f"  Found {len(manifests)} manifest file(s)")

        for manifest_path in manifests:
            try:
                entries = json.loads(manifest_path.read_text())
            except Exception as e:
                print(f"  ⚠ Failed to read {manifest_path.name}: {e}")
                continue

            if not isinstance(entries, list):
                print(f"  ⚠ {manifest_path.name} is not a list, skipping")
                continue

            for entry in entries:
                instance_id = entry.get("instance_id")
                patch = entry.get("patch")

                if not instance_id or not isinstance(patch, str):
                    continue

                # Create new model-tagged instance ID
                # instance_id format: repo.lm_regen_from_tests__<base_hash>__attempt_<n>
                # Extract base_hash and attempt from legacy ID
                if ".lm_regen_from_tests__" not in instance_id:
                    continue

                try:
                    parts = instance_id.split(".lm_regen_from_tests__", 1)[1]
                    if "__attempt_" not in parts:
                        continue

                    base_hash, attempt_str = parts.rsplit("__attempt_", 1)
                    attempt = int(attempt_str)
                except (ValueError, IndexError):
                    continue

                new_instance_id = _regen_instance_id(repo, base_hash, attempt, current_model_id)
                val_instance_dir = run_validation_dir / new_instance_id
                total_counted += 1

                if dry_run:
                    if total_counted <= 5 or total_counted % 50 == 0:
                        print(f"  [DRY] {new_instance_id}: patch.diff")
                else:
                    val_instance_dir.mkdir(parents=True, exist_ok=True)
                    patch_path = val_instance_dir / "patch.diff"
                    patch_path.write_text(patch)
                    total_prepared += 1

    if dry_run:
        print(f"\n[DRY RUN] Would prepare {total_counted} patches for validation")
        print("Run without --dry-run to actually prepare patches and optionally validate")
    else:
        print(f"\n✓ Prepared {total_prepared} patches for validation")
    return total_prepared if not dry_run else total_counted


def create_validation_manifest(repo: str, model_id: Optional[str] = None) -> int:
    """Create aggregated manifest for validation harness from prepared patches."""
    if model_id is None:
        print("Model ID is required to build a model-scoped validation manifest")
        return 0

    run_validation_dir = Path("logs/run_validation") / repo / model_id
    
    if not run_validation_dir.exists():
        print("No prepared patches found in logs/run_validation")
        return 0
    
    # Collect all prepared patches from the model-scoped validation folder
    all_patches = []
    for instance_dir in sorted(run_validation_dir.iterdir()):
        if not instance_dir.is_dir():
            continue
        
        patch_file = instance_dir / "patch.diff"
        if patch_file.exists():
            all_patches.append({
                "instance_id": instance_dir.name,
                "repo": repo,  # Add repo field expected by harness
                "patch": patch_file.read_text(),
            })
    
    if not all_patches:
        print("No model-specific patches found in logs/run_validation")
        return 0
    
    # Write manifest that harness expects
    manifest_path = run_validation_dir / "_all_patches_model_specific.json"
    manifest_path.write_text(json.dumps(all_patches, indent=2))
    print(f"✓ Created validation manifest: {manifest_path} ({len(all_patches)} patches)")
    return len(all_patches)


def run_validation(repo: str, model_id: Optional[str] = None, max_concurrent: int = 200) -> None:
    """Run validation harness on prepared patches."""
    print(f"\nRunning validation harness for {repo}...")

    models_to_run: list[str]
    if model_id is not None:
        models_to_run = [model_id]
    else:
        run_validation_repo_dir = Path("logs/run_validation") / repo
        if not run_validation_repo_dir.exists():
            print("No prepared patches found in logs/run_validation")
            return
        models_to_run = sorted([p.name for p in run_validation_repo_dir.iterdir() if p.is_dir()])

    for current_model_id in models_to_run:
        manifest_count = create_validation_manifest(repo, current_model_id)
        if manifest_count == 0:
            print(f"[{current_model_id}] No patches to validate")
            continue

        cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "swesmith.harness.valid",
            str(
                Path("logs/run_validation")
                / repo
                / current_model_id
                / "_all_patches_model_specific.json"
            ),
            "--output_subdir",
            current_model_id,
        ]

        try:
            subprocess.run(cmd, check=True)
            print(f"✓ Validation complete for {current_model_id}")
        except subprocess.CalledProcessError as e:
            print(f"✗ Validation failed for {current_model_id}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revalidate existing patches using model-specific instance IDs."
    )
    parser.add_argument("repo", type=str, help="Repository ID (e.g., 'tkrajina__gpxpy.09fc46b3')")
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional: process only a specific model ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=200,
        help="Max concurrent tests (passed to harness)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Prepare patches but skip running the validation harness",
    )
    args = parser.parse_args()

    prepared = prepare_patches_for_validation(
        repo=args.repo,
        model_id=args.model,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"\n[DRY RUN] Would prepare {prepared} patches for validation")
        print("Run without --dry-run to actually prepare patches and optionally validate")
        return

    if prepared == 0:
        print("No patches were prepared; skipping validation")
        return

    if not args.skip_validation:
        run_validation(args.repo, model_id=args.model, max_concurrent=args.max_concurrent)


if __name__ == "__main__":
    main()
