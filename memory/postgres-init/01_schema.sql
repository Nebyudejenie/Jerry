-- =====================================================================
-- Terry AI OS — core schema
-- Loaded on first boot by the postgres container.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Roles (least privilege) ──────────────────────────────────────────
-- The default POSTGRES_USER owns the schema. Specialized roles below are
-- bound to specific tables for least-privilege access by services.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'terry_app') THEN
        CREATE ROLE terry_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'terry_audit_writer') THEN
        CREATE ROLE terry_audit_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'terry_audit_reader') THEN
        CREATE ROLE terry_audit_reader NOLOGIN;
    END IF;
END $$;

-- ── Monitoring inventory ─────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.targets (
    target_id        TEXT PRIMARY KEY,
    kind             TEXT NOT NULL CHECK (kind IN ('http','tcp','ssh','api')),
    endpoint         TEXT NOT NULL,
    expected         TEXT,
    interval_seconds INT NOT NULL DEFAULT 300,
    severity_on_fail TEXT NOT NULL DEFAULT 'warn' CHECK (severity_on_fail IN ('info','warn','crit')),
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    tags             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.status (
    target_id   TEXT NOT NULL REFERENCES monitoring.targets(target_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    status      TEXT NOT NULL CHECK (status IN ('up','down','degraded','unknown')),
    latency_ms  INT,
    evidence    TEXT,
    PRIMARY KEY (target_id, ts)
);
CREATE INDEX IF NOT EXISTS status_by_ts ON monitoring.status (ts DESC);

-- ── Incidents ────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.incidents (
    incident_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('info','warn','crit')),
    state        TEXT NOT NULL CHECK (state IN ('open','triaging','remediating','verifying','closed')),
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at    TIMESTAMPTZ,
    target_id    TEXT REFERENCES monitoring.targets(target_id),
    rca          JSONB,
    resolution   TEXT
);

CREATE TABLE IF NOT EXISTS ops.incident_events (
    event_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id  UUID NOT NULL REFERENCES ops.incidents(incident_id) ON DELETE CASCADE,
    ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor        TEXT NOT NULL,
    kind         TEXT NOT NULL,        -- observation|hypothesis|action|verdict|note
    payload      JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS incident_events_by_incident ON ops.incident_events (incident_id, ts);

-- ── Agent memory (episodic) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ops.agent_memory (
    session_id   TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    turn_idx     INT  NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content      TEXT NOT NULL,
    tokens       INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, agent_id, turn_idx)
);
CREATE INDEX IF NOT EXISTS agent_memory_by_agent_session ON ops.agent_memory (agent_id, session_id, created_at DESC);

-- ── Audit ledger (append-only + hash chain) ──────────────────────────
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.audit_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,
    target        TEXT,
    command       TEXT,
    exit_code     INT,
    evidence      JSONB,
    incident_id   UUID REFERENCES ops.incidents(incident_id),
    approver      TEXT,
    payload_hash  TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    row_hash      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_log_by_ts        ON audit.audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS audit_log_by_incident  ON audit.audit_log (incident_id);
CREATE INDEX IF NOT EXISTS audit_log_by_actor     ON audit.audit_log (actor);

-- Enforce append-only at the DB level: no UPDATE, no DELETE.
CREATE OR REPLACE FUNCTION audit.deny_modify() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit.audit_log is append-only';
END $$;

DROP TRIGGER IF EXISTS audit_no_update ON audit.audit_log;
CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.deny_modify();

DROP TRIGGER IF EXISTS audit_no_delete ON audit.audit_log;
CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.deny_modify();

-- ── Approvals (single-use, TTL-enforced) ─────────────────────────────
CREATE TABLE IF NOT EXISTS ops.approvals (
    approval_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id   UUID REFERENCES ops.incidents(incident_id),
    command       TEXT NOT NULL,
    target        TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by    TEXT,
    granted_at    TIMESTAMPTZ,
    consumed_at   TIMESTAMPTZ,
    ttl_seconds   INT NOT NULL DEFAULT 300,
    state         TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','granted','rejected','expired','consumed'))
);

-- ── Freeze switch ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ops.system_freeze (
    id           INT PRIMARY KEY DEFAULT 1,
    frozen       BOOLEAN NOT NULL DEFAULT FALSE,
    set_by       TEXT,
    set_at       TIMESTAMPTZ,
    reason       TEXT,
    CHECK (id = 1)
);
INSERT INTO ops.system_freeze (id) VALUES (1) ON CONFLICT DO NOTHING;

-- ── Grants ───────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA monitoring, ops TO terry_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA monitoring, ops TO terry_app;

GRANT USAGE ON SCHEMA audit TO terry_audit_writer, terry_audit_reader;
GRANT INSERT ON audit.audit_log TO terry_audit_writer;
GRANT SELECT ON audit.audit_log TO terry_audit_reader, terry_app;
