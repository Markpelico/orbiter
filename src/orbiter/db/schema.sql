-- ORBITER schema. Applied idempotently on startup (Phase 1); Alembic arrives
-- when the schema starts evolving under it (see ADR-0006, forthcoming).

CREATE TABLE IF NOT EXISTS jobs (
    id               UUID PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    payload          JSONB NOT NULL,
    state            TEXT NOT NULL,
    attempts         INT NOT NULL DEFAULT 0,
    -- Fencing: the newest lease token whose write we have accepted. Writes
    -- carrying an older token are rejected in the UPDATE's WHERE clause.
    fence_token      BIGINT NOT NULL DEFAULT 0,
    result           JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only audit trail. jobs.state is a cached projection of this log.
CREATE TABLE IF NOT EXISTS job_events (
    id       BIGSERIAL PRIMARY KEY,
    job_id   UUID NOT NULL REFERENCES jobs(id),
    event    TEXT NOT NULL,
    attempt  INT NOT NULL DEFAULT 0,
    detail   JSONB NOT NULL DEFAULT '{}'::jsonb,
    at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_events_job_id_idx ON job_events (job_id, id);

-- Transactional outbox: written in the SAME transaction as the job row, so
-- there is no crash window between "job exists" and "job will be published".
CREATE TABLE IF NOT EXISTS outbox (
    id            BIGSERIAL PRIMARY KEY,
    job_id        UUID NOT NULL REFERENCES jobs(id),
    subject       TEXT NOT NULL,
    payload       JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox (id) WHERE published_at IS NULL;
