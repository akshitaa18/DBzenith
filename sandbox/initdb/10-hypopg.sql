-- Installed in the isolated sandbox database only. The Docker entrypoint runs
-- this as the PostgreSQL bootstrap superuser during first initialization.
CREATE EXTENSION IF NOT EXISTS hypopg;
