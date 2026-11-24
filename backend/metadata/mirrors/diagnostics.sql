-- Read-only telemetry functions never take lifecycle row locks or acquire pins.
CREATE OR REPLACE FUNCTION source_mirror_state.diagnostic_progress(gid text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT jsonb_build_object(
  'mirror_id', m.id, 'generation_id', g.id, 'capture_generation', g.capture_generation,
  'authority', m.authority, 'partition_identity', g.partition_identity,
  'applied_offset', g.applied_offset, 'processed_events', g.processed_events,
  'processed_batches', g.processed_batches, 'last_target_commit_at', g.last_target_commit_at,
  'processed_bytes', CASE WHEN g.byte_coverage THEN g.processed_bytes ELSE NULL END)
 FROM source_mirror_state.generations g JOIN source_mirror_state.mirrors m ON m.id = g.mirror_id
 WHERE g.id = gid AND NOT g.cleanup_pending AND NOT g.write_closed
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.diagnostic_row_count(mid text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE g source_mirror_state.generations; n bigint; sampled_at timestamptz;
BEGIN
 SELECT gen.* INTO g FROM source_mirror_state.mirrors m
 JOIN source_mirror_state.generations gen ON gen.id = m.published_generation_id AND gen.mirror_id = m.id
 WHERE m.id = mid AND gen.status = 'published' AND NOT gen.cleanup_pending;
 IF NOT FOUND THEN RETURN NULL; END IF;
 sampled_at := clock_timestamp();
 -- AccessShare permits DML. DDL may wait only until the caller's short transaction
 -- finishes. Never acquire Mirror/generation rows after taking this relation lock.
 EXECUTE format('SELECT count(*) FROM source_mirror.%I', g.table_name) INTO n;
 RETURN jsonb_build_object('generation_id', g.id, 'row_count', n, 'observed_at', sampled_at);
END $$;
REVOKE ALL ON FUNCTION source_mirror_state.diagnostic_progress(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION source_mirror_state.diagnostic_row_count(text) FROM PUBLIC;
