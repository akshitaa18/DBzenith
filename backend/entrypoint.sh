#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn app.main:app --host "${BACKEND_HOST:-0.0.0.0}" --port "${BACKEND_PORT:-8000}"
