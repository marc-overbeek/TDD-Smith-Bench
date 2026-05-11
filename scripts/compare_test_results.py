import json
import argparse
from pathlib import Path


def _get_base_hash(repo: str, instance_id: str) -> str:
    """Extract the suffix after the repo name to use as base_hash for regen instance IDs."""
    prefix = f"{repo}."
    if instance_id.startswith(prefix):
        return instance_id[len(prefix):]
    return instance_id


def _load_all_regen_reports(val_dir: Path, repo: str, base_hash: str) -> dict[int, list[str]]:
    """Load all regen attempt reports and return attempt_num -> broken_tests mapping."""
    reports = {}
    prefix = f"{repo}.lm_regen_from_tests__{base_hash}"
    if not val_dir.exists():
        return reports
    
    for child in val_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name == prefix:
            report_path = child / "report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text())
                reports[0] = report.get("FAIL_TO_PASS", [])
            continue
        if child.name.startswith(prefix + "__attempt_"):
            try:
                attempt_str = child.name.rsplit("__attempt_", 1)[1]
                attempt = int(attempt_str)
            except ValueError:
                continue
            report_path = child / "report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text())
                reports[attempt] = report.get("FAIL_TO_PASS", [])
    
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=str)
    args = parser.parse_args()

    repo = args.repo
    val_dir = Path("logs/run_validation") / repo
    change_dir = Path("logs/change_logs") / repo

    map_file = change_dir / "_function_map.json"
    if not map_file.exists():
        print(f"No function map found at {map_file}")
        return

    fn_map = json.loads(map_file.read_text())
    
    results = []

    for empty_inst_id, fn_info in fn_map.items():
        empty_report_path = val_dir / empty_inst_id / "report.json"
        if not empty_report_path.exists():
            continue

        empty_report = json.loads(empty_report_path.read_text())
        empty_broken = empty_report.get("FAIL_TO_PASS", [])
        if len(empty_broken) == 0:
            continue

        base_hash = _get_base_hash(repo, empty_inst_id)
        regen_reports = _load_all_regen_reports(val_dir, repo, base_hash)
        
        attempt_results = []
        if not regen_reports:
            attempt_results.append({
                "attempt": None,
                "regen_broken": ["<NO_VALIDATION_REPORT_FOUND>"],
            })
        else:
            for attempt in sorted(regen_reports.keys()):
                regen_broken = regen_reports[attempt]
                fixed_tests = set(empty_broken) - set(regen_broken)
                still_broken = set(empty_broken).intersection(set(regen_broken))
                new_broken = set(regen_broken) - set(empty_broken)
                
                attempt_results.append({
                    "attempt": attempt,
                    "regen_broken": regen_broken,
                    "fixed_count": len(fixed_tests),
                    "still_broken_count": len(still_broken),
                    "new_broken_count": len(new_broken),
                })

        results.append({
            "function": f"{fn_info['file_path']}::{fn_info['function_name']}",
            "empty_fails_count": len(empty_broken),
            "empty_broken": empty_broken,
            "attempts": attempt_results,
        })

    # Display console summary
    total_fixed = 0
    total_originally_broken = 0
    
    for r in results:
        print(f"🔸 {r['function']}")
        print(f"   [Empty Body] Broken tests : {r['empty_fails_count']}")
        for empty_test in r['empty_broken']:
            print(f"      - {empty_test}")
        
        for attempt_data in r['attempts']:
            attempt = attempt_data['attempt']
            regen_broken = attempt_data['regen_broken']
            
            if regen_broken == ["<NO_VALIDATION_REPORT_FOUND>"]:
                attempt_label = "Regenerated" if attempt is None else f"Regenerated, attempt {attempt}"
                print(f"   [{attempt_label}] No validation report found (Maybe generation failed or patch didn't apply).")
            else:
                attempt_label = "Regenerated" if attempt is None else f"Regenerated, attempt {attempt}"
                fixed = attempt_data['fixed_count']
                still = attempt_data['still_broken_count']
                new = attempt_data['new_broken_count']
                print(f"   [{attempt_label}] Broken tests: {len(regen_broken)} ({fixed} fixed, {still} still broken, {new} new regressions)")
                if len(regen_broken) > 0:
                    for bad_test in regen_broken:
                        print(f"      - {bad_test}")
        print()
        
        total_originally_broken += r['empty_fails_count']
        
        # Only count the best (final) result for each function to avoid double-counting
        valid_attempts = [a for a in r['attempts'] if a['regen_broken'] != ["<NO_VALIDATION_REPORT_FOUND>"]]
        if valid_attempts:
            # Find the attempt with the fewest broken tests (best result)
            best_attempt = min(valid_attempts, key=lambda a: len(a['regen_broken']))
            total_fixed += best_attempt['fixed_count']
            
    print(f"========================================")
    print(f"Total originally broken tests  : {total_originally_broken}")
    print(f"Total tests fixed by LLM regen : {total_fixed}")
    
    out_file = f"{repo}_test_comparison.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed JSON saved to {out_file}")

if __name__ == "__main__":
    main()
