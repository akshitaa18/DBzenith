"""Trainable Reinforcement Learning Agent for DBZenith database optimization.

Implements Deep Q-Network (DQN) with experience replay, target network stabilization,
and multi-objective reward optimization over sanitized state vectors.
"""

from __future__ import annotations

import collections
import random
from typing import Any
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

from app.services.rl.contracts import ActionType, SanitizedState


class QNetwork(nn.Module):
    """Deep Q-Network mapping sanitized 38-dim state to action Q-values."""

    def __init__(self, state_dim: int = 38, action_dim: int = 6, hidden_dim: int = 128) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, action_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class ReplayBuffer:
    """Fixed-size circular experience replay buffer for off-policy DQN training."""

    def __init__(self, capacity: int = 20_000) -> None:
        self.buffer = collections.deque(maxlen=capacity)

    def push(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        self.buffer.append((state, action, reward, next_state, done))

    def sample(
        self,
        batch_size: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)

        return (
            torch.tensor(np.array(states), dtype=torch.float32),
            torch.tensor(actions, dtype=torch.long).unsqueeze(1),
            torch.tensor(rewards, dtype=torch.float32).unsqueeze(1),
            torch.tensor(np.array(next_states), dtype=torch.float32),
            torch.tensor(dones, dtype=torch.float32).unsqueeze(1),
        )

    def __len__(self) -> int:
        return len(self.buffer)


class TrainableRLAgent:
    """Trainable DQN Agent for database optimization."""

    def __init__(
        self,
        state_dim: int = 38,
        action_dim: int = 6,
        learning_rate: float = 1e-3,
        gamma: float = 0.95,
        epsilon_start: float = 1.0,
        epsilon_end: float = 0.05,
        epsilon_decay: float = 0.992,
        buffer_capacity: int = 20_000,
        batch_size: int = 64,
        target_update_freq: int = 5,
        name: str = "dqn_optimization_agent",
        device: str = "cpu",
    ) -> None:
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon_start
        self.epsilon_end = epsilon_end
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_update_freq = target_update_freq
        self.name = name
        self.device = torch.device(device)

        self.q_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net = QNetwork(state_dim, action_dim).to(self.device)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.q_net.parameters(), lr=learning_rate)
        self.criterion = nn.SmoothL1Loss()
        self.replay_buffer = ReplayBuffer(buffer_capacity)

        self.train_steps: int = 0
        self.episodes: int = 0

    def select_action(
        self,
        state: SanitizedState | np.ndarray,
        deterministic: bool = False,
    ) -> ActionType:
        """Selects an action using epsilon-greedy or greedy policy."""
        if isinstance(state, SanitizedState):
            state_vec = state.to_vector()
        else:
            state_vec = np.asarray(state, dtype=np.float32)

        if not deterministic and random.random() < self.epsilon:
            action_idx = random.randrange(self.action_dim)
            return ActionType(action_idx)

        with torch.no_grad():
            state_tensor = torch.tensor(state_vec, dtype=torch.float32).unsqueeze(0).to(self.device)
            q_values = self.q_net(state_tensor)
            action_idx = int(q_values.argmax(dim=1).item())

        return ActionType(action_idx)

    def step_learning(self) -> float | None:
        """Performs a gradient descent optimization step on a sampled replay batch."""
        if len(self.replay_buffer) < self.batch_size:
            return None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(self.batch_size)
        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current Q-values for chosen actions
        q_current = self.q_net(states).gather(1, actions)

        # Double DQN / Standard DQN target calculation
        with torch.no_grad():
            next_q_values = self.target_net(next_states).max(1, keepdim=True)[0]
            q_target = rewards + (1.0 - dones) * self.gamma * next_q_values

        loss = self.criterion(q_current, q_target)

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_net.parameters(), max_norm=1.0)
        self.optimizer.step()

        self.train_steps += 1
        if self.train_steps % (self.target_update_freq * 10) == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())

        return float(loss.item())

    def decay_epsilon(self) -> float:
        """Decays epsilon exploration rate after an episode."""
        self.epsilon = max(self.epsilon_end, self.epsilon * self.epsilon_decay)
        self.episodes += 1
        if self.episodes % self.target_update_freq == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())
        return self.epsilon

    def save_weights(self) -> dict[str, Any]:
        """Exports state dict and hyperparameter metadata for serialization."""
        return {
            "q_net_state": self.q_net.state_dict(),
            "target_net_state": self.target_net.state_dict(),
            "epsilon": self.epsilon,
            "train_steps": self.train_steps,
            "episodes": self.episodes,
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
        }

    def load_weights(self, checkpoint: dict[str, Any]) -> None:
        """Loads state dict and hyperparameter metadata."""
        self.q_net.load_state_dict(checkpoint["q_net_state"])
        self.target_net.load_state_dict(checkpoint.get("target_net_state", checkpoint["q_net_state"]))
        self.epsilon = checkpoint.get("epsilon", self.epsilon_end)
        self.train_steps = checkpoint.get("train_steps", 0)
        self.episodes = checkpoint.get("episodes", 0)
