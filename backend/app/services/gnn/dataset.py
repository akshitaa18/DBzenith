from __future__ import annotations

import json
from pathlib import Path

from .contracts import GraphSample


def save_jsonl(samples: list[GraphSample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample.__dict__, separators=(",", ":")) + "\n")


def load_jsonl(path: Path) -> list[GraphSample]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out.append(GraphSample(**d))
    return out
