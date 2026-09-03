-- Runs once, by the postgres entrypoint, against an empty data directory.
-- Re-running compose over an existing pgdata volume does not execute this, so
-- the statements are idempotent and the migrations in T1.3 do not depend on
-- having been created here.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
