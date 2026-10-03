"""Model persistence and artifact serialization for the DBZenith RL Optimization Engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import torch

from app.services.rl.agent import TrainableRLAgent


DEFAULT_ARTIFACT_DIR = Path("ai/rl/models/v0.8.0")


def save_rl_artifacts(
    agent: TrainableRLAgent,
    directory: Path | str = DEFAULT_ARTIFACT_DIR,
    metrics: dict[str, Any] | None = None,
    extra_config: dict[str, Any] | None = None,
) -> Path:
    """Saves model weights, configuration, and training metrics."""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)

    weights_path = target_dir / "agent.pt"
    torch.save(agent.save_weights(), weights_path)

    config_data = {
        "model_type": "DQN",
        "state_dim": int(agent.state_dim),
        "action_dim": int(agent.action_dim),
        "gamma": float(agent.gamma),
        "epsilon_final": float(agent.epsilon),
        "train_steps": int(agent.train_steps),
        "episodes": int(agent.episodes),
        "version": "v0.8.0",
    }
    if extra_config:
        config_data.update(extra_config)

    config_path = target_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

    if metrics:
        metrics_path = target_dir / "metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

    return target_dir


def load_rl_artifacts(
    directory: Path | str = DEFAULT_ARTIFACT_DIR,
    device: str = "cpu",
) -> tuple[TrainableRLAgent, dict[str, Any]]:
    """Loads agent and metadata from a versioned directory."""
    target_dir = Path(directory)
    weights_path = target_dir / "agent.pt"
    config_path = target_dir / "config.json"

    if not weights_path.exists():
        raise FileNotFoundError(f"RL weights not found at {weights_path}")

    config_data = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

    state_dim = config_data.get("state_dim", 38)
    action_dim = config_data.get("action_dim", 6)

    agent = TrainableRLAgent(state_dim=state_dim, action_dim=action_dim, device=device)
    checkpoint = torch.load(weights_path, map_location=device)
    agent.load_weights(checkpoint)

    return agent, config_data
