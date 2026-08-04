import json
import matplotlib.pyplot as plt
from collections import Counter
from pathlib import Path

def plot_results(file_path, output_file):
    with open(file_path, 'r') as file:
        data = json.load(file)

    combined_fails = []
    single_fails = []

    for result in data:
        fails = result.get("empty_fails_count", 0)
        if result['function'].startswith("combined:"):
            combined_fails.append(fails)
        else:
            single_fails.append(fails)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

    def create_histogram(ax, data, title, color, group_size=None):
        if not data:
            ax.text(0.5, 0.5, 'No data', ha='center', va='center')
            ax.set_title(title)
            return
        
        if group_size:
            # Grouping: 0-5, 6-10, 11-15...
            # We map: 0-5 -> 5, 6-10 -> 10, 11-15 -> 15
            def get_group_upper_bound(x):
                if x <= group_size:
                    return group_size
                return ((x - 1) // group_size + 1) * group_size
            
            counts = Counter(get_group_upper_bound(x) for x in data)
            max_val = max(counts.keys())
            
            all_labels = []
            all_values = []
            for upper in range(group_size, max_val + 1, group_size):
                all_labels.append(str(upper))
                all_values.append(counts.get(upper, 0))
            
            ax.bar(all_labels, all_values, color=color, alpha=0.7)
            ax.tick_params(axis='x', labelsize=8)
            if len(all_labels) > 10:
                ax.tick_params(axis='x', rotation=90)
        else:
            counts = Counter(data)
            if not counts:
                 ax.set_title(title)
                 return
                 
            # Ensure we have all values from 0 to max to make the plot look like a proper distribution
            min_val = min(counts.keys())
            max_val = max(counts.keys())
            all_labels = list(range(min_val, max_val + 1))
            all_values = [counts.get(i, 0) for i in all_labels]
            
            ax.bar(all_labels, all_values, color=color, alpha=0.7)
            ax.tick_params(axis='x', labelsize=8)

        ax.set_title(f"{title} (N={len(data)})")
        ax.set_xlabel('empty_fails_count' if not group_size else f'empty_fails_count (ranges of {group_size})')
        ax.set_ylabel('Frequency')
        ax.grid(axis='y', linestyle='--', alpha=0.7)

    create_histogram(ax1, single_fails, 'Single Functions', 'skyblue')
    create_histogram(ax2, combined_fails, 'Combined Functions', 'salmon', group_size=5)

    plt.tight_layout()
    plt.savefig(output_file)
    plt.close(fig)
    print(f"Plot saved to {output_file}")

if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    results_dir = repo_root / "results"
    output_dir = results_dir / "empty_fails_distribution"
    output_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(results_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files found in {results_dir}")
    else:
        for json_file in json_files:
            output_file = output_dir / f"{json_file.stem}.png"
            plot_results(json_file, output_file)
