-- =====================================================================
-- Periodic cleanup helpers + retention.
-- Designed to be called from n8n cron workflows; idempotent.
-- =====================================================================

-- ── Expire stale approvals ──────────────────────────────────────────
CREATE OR REPLACE FUNCTION ops.expire_stale_approvals() RETURNS TABLE(expired_count INT) AS $$
DECLARE n INT;
BEGIN
    UPDATE ops.approvals
       SET state = 'expired'
     WHERE state = 'pending'
       AND requested_at < now() - (ttl_seconds * INTERVAL '1 second');
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN QUERY SELECT n;
END;
$$ LANGUAGE plpgsql;

-- ── Trim very old monitoring.status rows ────────────────────────────
-- Keep last 30 days at full resolution; partition-style cleanup.
CREATE OR REPLACE FUNCTION monitoring.trim_status(retain_days INT DEFAULT 30)
RETURNS TABLE(deleted INT) AS $$
DECLARE n INT;
BEGIN
    DELETE FROM monitoring.status WHERE ts < now() - make_interval(days => retain_days);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN QUERY SELECT n;
END;
$$ LANGUAGE plpgsql;

-- ── Auto-close incidents that have been "verifying" + green for >1h ─
-- (the Commander normally closes them; this is a safety net)
CREATE OR REPLACE FUNCTION ops.auto_close_stuck_incidents() RETURNS TABLE(closed_count INT) AS $$
DECLARE n INT;
BEGIN
    UPDATE ops.incidents
       SET state = 'closed', closed_at = now(),
           resolution = COALESCE(resolution, 'auto-closed: verifying + no events for 1h')
     WHERE state = 'verifying'
       AND incident_id NOT IN (
           SELECT incident_id FROM ops.incident_events
            WHERE ts > now() - INTERVAL '1 hour'
       );
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN QUERY SELECT n;
END;
$$ LANGUAGE plpgsql;

-- ── Convenience: scheduled-job entrypoint that runs all three ───────
CREATE OR REPLACE FUNCTION ops.nightly_maintenance() RETURNS JSONB AS $$
DECLARE
    expired INT;
    trimmed INT;
    closed  INT;
BEGIN
    SELECT expired_count INTO expired FROM ops.expire_stale_approvals();
    SELECT deleted       INTO trimmed FROM monitoring.trim_status(30);
    SELECT closed_count  INTO closed  FROM ops.auto_close_stuck_incidents();
    RETURN jsonb_build_object(
        'expired_approvals', expired,
        'trimmed_status_rows', trimmed,
        'auto_closed_incidents', closed,
        'ran_at', now()
    );
END;
$$ LANGUAGE plpgsql;
