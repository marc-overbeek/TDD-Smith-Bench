#!/usr/bin/env python3
"""
Analyze cyclomatic complexity of original (empty-body) vs generated code.
"""

import json
import os
from radon.complexity import cc_visit


def get_original_code(func_name):
    """Get the original code from empty-body patches."""
    with open('/home/marc/Documents/SWE-smith/logs/bug_gen/Instagram__MonkeyType.70c3acf6_empty_body_from_scratch_patches.json', 'r') as f:
        patches = json.load(f)
    
    for patch in patches:
        patch_str = patch['patch']
        lines = patch_str.split('\n')
        if lines[0].startswith('--- a/'):
            file_path = lines[0][6:]
            if file_path in func_name:
                # Parse the diff to get original lines
                original_lines = []
                for line in lines:
                    if line.startswith('-') and not line.startswith('---'):
                        original_lines.append(line[1:])
                if original_lines:
                    return '\n'.join(original_lines)
    return "pass"


def get_generated_code(func_name):
    """Get the generated code from metadata."""
    file_path, func_name_only = func_name.split('::')
    file_encoded = file_path.replace('/', '__').replace('.', '_')
    base_dir = f'/home/marc/Documents/SWE-smith/logs/bug_gen/Instagram__MonkeyType.70c3acf6/Instagram__MonkeyType.70c3acf6__{file_encoded}/'
    
    if not os.path.exists(base_dir):
        return None
    
    # Find the subdir for the function
    for subdir in os.listdir(base_dir):
        if subdir.startswith(func_name_only + '_'):
            hash_val = subdir.split('_')[-1]
            metadata_path = f'{base_dir}{subdir}/metadata__lm_regen_from_tests__{hash_val}53.json'
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    data = json.load(f)
                    return data.get('rewrite', '')
    return None


def calculate_complexity(code):
    """Calculate cyclomatic complexity of the code."""
    if not code or code.strip() == "pass":
        return 1
    try:
        if code.startswith('def'):
            full_code = code
        else:
            # It's the body, already indented
            full_code = f"def func():\n{code}"
        results = cc_visit(full_code)
        if results:
            return results[0].complexity
        return 1
    except Exception as e:
        print(f"Error calculating complexity for code: {code[:100]}... Error: {e}")
        return 1


def main():
    comparison_file = '/home/marc/Documents/SWE-smith/Instagram__MonkeyType.70c3acf6_test_comparison.json'
    with open(comparison_file, 'r') as f:
        data = json.load(f)

    results = []
    for entry in data:
        func_name = entry['function']
        original_code = get_original_code(func_name)
        generated_code = get_generated_code(func_name)

        original_cc = calculate_complexity(original_code)
        generated_cc = calculate_complexity(generated_code)

        results.append({
            'function': func_name,
            'original_complexity': original_cc,
            'generated_complexity': generated_cc,
            'complexity_change': generated_cc - original_cc
        })

    # Print summary
    print(f"Total functions analyzed: {len(results)}")
    total_change = sum(r['complexity_change'] for r in results)
    avg_change = total_change / len(results)
    print(f"Average complexity change: {avg_change:.2f}")

    # Save detailed results
    with open('/home/marc/Documents/SWE-smith/complexity_comparison.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Detailed results saved to complexity_comparison.json")


if __name__ == '__main__':
    main()