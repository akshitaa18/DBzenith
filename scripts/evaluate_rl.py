"""CLI script to run actual experiments comparing RL agent against baseline policies."""

import argparse
import json
import sys
from pathlib import Path

# Ensure backend is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services.rl.baseline import BaselinePolicy, RandomPolicy
from app.services.rl.evaluate import compare_policies
from app.services.rl.persistence import load_rl_artifacts


def main():
    parser = argparse.ArgumentParser(description="Evaluate DBZenith RL vs Baseline")
    parser.add_argument("--episodes", type=int, default=50, help="Number of evaluation episodes")
    parser.add_argument("--model-dir", type=str, default="ai/rl/models/v0.8.0", help="Directory containing trained model")
    parser.add_argument("--seed", type=int, default=99999, help="Evaluation random seed")
    parser.add_argument("--output-json", type=str, default="ai/rl/models/v0.8.0/comparison_report.json")
    args = parser.parse_args()

    print(f"=== DBZenith RL vs Baseline Evaluation ({args.episodes} held-out episodes) ===")
    agent, metadata = load_rl_artifacts(args.model_dir)
    baseline = BaselinePolicy()
    random_policy = RandomPolicy(seed=args.seed)

    results = compare_policies(
        agent=agent,
        baseline=baseline,
        random_policy=random_policy,
        num_episodes=args.episodes,
        seed_offset=args.seed,
    )

    print("\n" + results["markdown_table"])

    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed evaluation report saved to: {out_path.resolve()}")


if __name__ == "__main__":
    main()
