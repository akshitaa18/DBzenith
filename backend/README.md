# DBZenith Backend

FastAPI service with PostgreSQL connectivity, SQLAlchemy, Alembic, structured logging, versioned API routes, and explicit error handling.

## Local development

Create a Python 3.12 virtual environment, install `requirements-dev.txt`, copy the root `.env.example` to `.env`, start PostgreSQL, run `alembic upgrade head`, then start Uvicorn.
