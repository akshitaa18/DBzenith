from __future__ import annotations

from .train import _metrics, _tensor


def validate(model, samples, normalizer):
    """Run the held-out evaluation pipeline without changing model weights."""
    return _metrics(model, samples, normalizer)
