"""Count how many empty-body function patches would be generated.

This script mimics the start of generate_empty_body_changes.py but only counts
the patches without actually generating or validating them.

Pipeline:
1) Clone repo profile and extract function entities.
2) Count how many empty-body patches would be generated per function.
3) Output the total count.

Usage:
  uv run python scripts/count_empty_body_patches.py \
      Instagram__MonkeyType.70c3acf6
"""

import argparse
import ast
import astor
from pathlib import Path
from swesmith.bug_gen.utils import generate_patch_fast
from swesmith.profiles import registry


def _empty_body_rewrite(src_code: str) -> str | None:
    """Rewrite top-level function body to `pass` while keeping signature untouched."""
    try:
        tree = ast.parse(src_code)
    except SyntaxError:
        return None

    if len(tree.body) == 0:
        return None

    node = tree.body[0]
    if not isinstance(node, ast.FunctionDef):
        return None

    node.body = [ast.Pass()]
    ast.fix_missing_locations(tree)
    return astor.to_source(tree).strip()


def main(repo: str, max_functions: int):
    rp = registry.get(repo)
    repo_dir, _ = rp.clone()

    entities = rp.extract_entities(exclude_tests=True)
    functions = [x for x in entities if getattr(x, "is_function", False)]
    if max_functions != -1:
        functions = functions[:max_functions]

    print(f"Total functions considered: {len(functions)}")

    patch_count = 0
    successful_rewrites = 0

    for idx, fn in enumerate(functions):
        rewrite = _empty_body_rewrite(fn.src_code)
        if not rewrite:
            continue

        successful_rewrites += 1
        bug = type("Bug", (), {"rewrite": rewrite})
        patch = generate_patch_fast(fn, bug, repo_dir)
        if patch:
            patch_count += 1

    print(f"Successful rewrites: {successful_rewrites}")
    print(f"Patches that would be generated: {patch_count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Count empty-body patches that would be generated."
    )
    parser.add_argument("repo", type=str, help="Repo key, e.g. Instagram__MonkeyType.70c3acf6")
    parser.add_argument(
        "--max_functions",
        type=int,
        default=-1,
        help="Limit number of functions for faster runs (-1 = all).",
    )
    args = parser.parse_args()
    main(**vars(args))
