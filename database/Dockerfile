# syntax=docker/dockerfile:1
# The PostgreSQL server of compose.yml: the official image with pgvector, whose type holds the article index's vectors.
# The image already reads the PostgreSQL project's repository (PGDG) for its own server, and PGDG builds pgvector for
# that server's major version and Debian release, so nothing is compiled here.

FROM postgres:18.7

# Only the extension's files. The database gets the extension from `just db-migrate` (version 13 to 14) or at its first
# start. The version is pinned like the image's, so a rebuild never takes another pgvector by itself.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-18-pgvector=0.8.7-1.pgdg13+2 \
    && rm -rf /var/lib/apt/lists/*
