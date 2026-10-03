"""CLI script to train the DBZenith Reinforcement Learning Optimization Agent."""

import argparse
import sys
from pathlib import Path

# Ensure backend is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services.rl.agent import TrainableRLAgent
from app.services.rl.environment import DatabaseOptimizationEnv
from app.services.rl.persistence import save_rl_artifacts
from app.services.rl.train import train_rl_agent


def main():
    parser = argparse.ArgumentParser(description="Train DBZenith RL Optimization Agent")
    parser.add_argument("--episodes", type=int, default=150, help="Number of training episodes")
    parser.add_argument("--steps", type=int, default=15, help="Max steps per episode")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--gamma", type=float, default=0.95, help="Discount factor")
    parser.add_argument("--seed", type=int, default=20261004, help="Random seed")
    parser.add_argument("--output-dir", type=str, default="ai/rl/models/v0.8.0", help="Directory to save model")
    args = parser.parse_args()

    print(f"=== DBZenith RL Engine Training (Episodes: {args.episodes}) ===")
    env = DatabaseOptimizationEnv(max_steps_per_episode=args.steps, seed=args.seed)
    agent = TrainableRLAgent(
        state_dim=int(env.observation_space.shape[0]),
        action_dim=int(env.action_space.n),
        learning_rate=args.lr,
        gamma=args.gamma,
    )

    trained_agent, history = train_rl_agent(
        env=env,
        agent=agent,
        num_episodes=args.episodes,
        max_steps_per_episode=args.steps,
        seed=args.seed,
        verbose=True,
    )

    save_dir = Path(args.output_dir)
    save_rl_artifacts(
        agent=trained_agent,
        directory=save_dir,
        metrics=history,
        extra_config={"learning_rate": args.lr, "max_steps": args.steps},
    )
    print(f"\nTraining complete! Artifacts saved to: {save_dir.resolve()}")
    print(f"Mean Final Return (last 20 ep): {history['mean_final_reward']}")
    print(f"Action Distribution: {history['action_distribution']}")


if __name__ == "__main__":
    main()
