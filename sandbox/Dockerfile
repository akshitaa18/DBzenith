FROM postgres:17-bookworm

# The official postgres:17-bookworm image already configures the PGDG repository.
# Do not add another PGDG source/key: that causes Signed-By conflicts.
# HypoPG is installed only in this isolated simulation database.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-hypopg \
    && rm -rf /var/lib/apt/lists/*
