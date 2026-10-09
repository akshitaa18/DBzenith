"""Comprehensive Workload & Telemetry Generator CLI for DBZenith v0.7.

Delegates to backend service app.services.workload.generator to guarantee
100% feature and code synchronization across CLI and web application endpoints.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Setup path to import backend app modules
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.services.workload.generator import (
    COMPREHENSIVE_QUERIES,
    generate_comprehensive_workload,
    auto_seed_if_empty,
    ensure_ecommerce_tables,
)

__all__ = [
    "COMPREHENSIVE_QUERIES",
    "generate_comprehensive_workload",
    "auto_seed_if_empty",
    "ensure_ecommerce_tables",
]

if __name__ == "__main__":
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    generate_comprehensive_workload(db_arg)
