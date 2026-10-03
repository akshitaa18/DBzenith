"""Training pipeline for the DBZenith RL Optimization Engine."""

from __future__ import annotations

from typing import Any
import numpy as np

from app.services.rl.agent import TrainableRLAgent
from app.services.rl.contracts import ActionType
from app.services.rl.environment import DatabaseOptimizationEnv


def train_rl_agent(
    env: DatabaseOptimizationEnv | None = None,
    agent: TrainableRLAgent | None = None,
    num_episodes: int = 150,
    max_steps_per_episode: int = 15,
    seed: int = 20261004,
    verbose: bool = True,
) -> tuple[TrainableRLAgent, dict[str, Any]]:
    """Trains the DQN optimization agent on the Gymnasium environment."""
    if env is None:
        env = DatabaseOptimizationEnv(max_steps_per_episode=max_steps_per_episode, seed=seed)
    if agent is None:
        agent = TrainableRLAgent(state_dim=env.observation_space.shape[0], action_dim=env.action_space.n)

    episode_rewards: list[float] = []
    episode_losses: list[float] = []
    action_counts: dict[str, int] = {action.name: 0 for action in ActionType}
    regression_counts: int = 0
    total_steps: int = 0

    for ep in range(1, num_episodes + 1):
        state, _ = env.reset(seed=seed + ep)
        ep_reward = 0.0
        ep_loss_list: list[float] = []

        for _ in range(max_steps_per_episode):
            total_steps += 1
            action = agent.select_action(state, deterministic=False)
            action_counts[action.name] += 1

            next_state, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            if info.get("measured_result", {}).get("regression_detected", False):
                regression_counts += 1

            agent.replay_buffer.push(state, int(action), reward, next_state, done)
            loss = agent.step_learning()
            if loss is not None:
                ep_loss_list.append(loss)

            state = next_state
            ep_reward += reward

            if done:
                break

        agent.decay_epsilon()
        episode_rewards.append(round(ep_reward, 3))
        if ep_loss_list:
            episode_losses.append(round(float(np.mean(ep_loss_list)), 4))

        if verbose and (ep % 25 == 0 or ep == num_episodes):
            avg_20 = np.mean(episode_rewards[-20:]) if len(episode_rewards) >= 20 else np.mean(episode_rewards)
            print(
                f"Episode {ep:3d}/{num_episodes} | "
                f"Return: {ep_reward:6.2f} | "
                f"Avg(20): {avg_20:6.2f} | "
                f"Epsilon: {agent.epsilon:5.3f} | "
                f"Buffer: {len(agent.replay_buffer):5d}"
            )

    history = {
        "num_episodes": num_episodes,
        "total_steps": total_steps,
        "episode_rewards": episode_rewards,
        "mean_final_reward": round(float(np.mean(episode_rewards[-20:])), 3),
        "mean_training_loss": round(float(np.mean(episode_losses[-20:])), 4) if episode_losses else 0.0,
        "action_distribution": action_counts,
        "total_regressions": regression_counts,
        "final_epsilon": round(float(agent.epsilon), 4),
    }

    return agent, history
