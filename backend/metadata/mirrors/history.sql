-- History is read from the sole writer's transactional live_log, never reconstructed.
ALTER TABLE source_mirror_state.mirrors ADD COLUMN IF NOT EXISTS retained_commit_seq bigint NOT NULL DEFAULT 0;
ALTER TABLE source_mirror_state.mirrors ADD COLUMN IF NOT EXISTS retained_entry_seq integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS source_mirror_state.history_invalidations (
 operation_id text PRIMARY KEY, transitions jsonb NOT NULL
);

CREATE OR REPLACE FUNCTION source_mirror_state.history_version()
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT 1
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.history_bound(mid text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE m source_mirror_state.mirrors; last_entry integer;
BEGIN
 SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = mid FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 -- The stream lock excludes uncommitted reservations from the upper prefix.
 SELECT coalesce(max(entry_seq), 0) INTO last_entry FROM source_mirror_state.live_log
 WHERE mirror_id = mid AND history_epoch = m.history_epoch AND commit_seq = m.commit_seq;
 RETURN jsonb_build_object('mirror_id', mid, 'source_id', m.source_id, 'history_epoch', m.history_epoch,
  'lower_bound', jsonb_build_object('mirror_id', mid, 'history_epoch', m.history_epoch,
   'commit_seq', m.retained_commit_seq, 'entry_seq', m.retained_entry_seq),
  'upper_bound', jsonb_build_object('mirror_id', mid, 'history_epoch', m.history_epoch,
   'commit_seq', m.commit_seq, 'entry_seq', last_entry));
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.history_page(mid text, after_position jsonb, through_position jsonb, page_limit integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE b jsonb; entries jsonb; next_position jsonb;
BEGIN
 IF page_limit IS NULL OR page_limit < 1 OR page_limit > 500 THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 b := source_mirror_state.history_bound(mid);
 IF after_position->>'mirror_id' IS DISTINCT FROM mid OR through_position->>'mirror_id' IS DISTINCT FROM mid
  OR after_position->>'history_epoch' IS DISTINCT FROM b->>'history_epoch'
  OR through_position->>'history_epoch' IS DISTINCT FROM b->>'history_epoch'
  OR after_position->>'commit_seq' IS NULL OR after_position->>'entry_seq' IS NULL
  OR through_position->>'commit_seq' IS NULL OR through_position->>'entry_seq' IS NULL
  OR ROW((after_position->>'commit_seq')::bigint, (after_position->>'entry_seq')::integer)
    < ROW((b->'lower_bound'->>'commit_seq')::bigint, (b->'lower_bound'->>'entry_seq')::integer)
  OR ROW((after_position->>'commit_seq')::bigint, (after_position->>'entry_seq')::integer)
    > ROW((through_position->>'commit_seq')::bigint, (through_position->>'entry_seq')::integer)
  OR ROW((through_position->>'commit_seq')::bigint, (through_position->>'entry_seq')::integer)
    > ROW((b->'upper_bound'->>'commit_seq')::bigint, (b->'upper_bound'->>'entry_seq')::integer)
 THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 SELECT coalesce(jsonb_agg(v.entry ORDER BY v.commit_seq, v.entry_seq), '[]'::jsonb) INTO entries FROM (
  SELECT l.commit_seq, l.entry_seq, jsonb_build_object(
   'position', jsonb_build_object('mirror_id', mid, 'history_epoch', l.history_epoch,
    'commit_seq', l.commit_seq, 'entry_seq', l.entry_seq),
   'source_id', b->>'source_id', 'capture_generation', l.capture_generation,
   'generation_id', l.generation_id, 'origin', l.origin, 'operation', l.operation,
   'typed_key', l.typed_key, 'before', l.before_image, 'after', l.after_image) AS entry
  FROM source_mirror_state.live_log l
  WHERE l.mirror_id = mid AND l.history_epoch = b->>'history_epoch' AND l.origin = 'live'
   AND ROW(l.commit_seq, l.entry_seq) > ROW((after_position->>'commit_seq')::bigint, (after_position->>'entry_seq')::integer)
   AND ROW(l.commit_seq, l.entry_seq) <= ROW((through_position->>'commit_seq')::bigint, (through_position->>'entry_seq')::integer)
  ORDER BY l.commit_seq, l.entry_seq LIMIT page_limit
 ) v;
 next_position := CASE WHEN jsonb_array_length(entries) = page_limit
  THEN entries->(page_limit - 1)->'position' ELSE through_position END;
 RETURN b || jsonb_build_object('entries', entries, 'next_position', next_position);
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.invalidate_history(op text, changes jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE change jsonb; m source_mirror_state.mirrors; previous jsonb;
BEGIN
 IF op IS NULL OR jsonb_typeof(changes) IS DISTINCT FROM 'array' OR jsonb_array_length(changes) = 0
 THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 -- Sorted stream locks match apply_batch and make multi-stream cleanup atomic.
 FOR change IN SELECT value FROM jsonb_array_elements(changes) ORDER BY value->>'mirror_id' LOOP
  PERFORM 1 FROM source_mirror_state.mirrors WHERE id = change->>'mirror_id' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 END LOOP;
 SELECT transitions INTO previous FROM source_mirror_state.history_invalidations WHERE operation_id = op;
 IF FOUND THEN
  IF previous IS DISTINCT FROM changes THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
  RETURN true;
 END IF;
 FOR change IN SELECT value FROM jsonb_array_elements(changes) ORDER BY value->>'mirror_id' LOOP
  SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = change->>'mirror_id';
  IF m.history_epoch IS DISTINCT FROM change->>'old_epoch'
   OR nullif(change->>'history_epoch', '') IS NULL OR change->>'history_epoch' = m.history_epoch
  THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
  UPDATE source_mirror_state.mirrors SET history_epoch = change->>'history_epoch', commit_seq = 0,
   retained_commit_seq = 0, retained_entry_seq = 0 WHERE id = m.id;
  DELETE FROM source_mirror_state.live_log WHERE mirror_id = m.id;
 END LOOP;
 INSERT INTO source_mirror_state.history_invalidations VALUES (op, changes);
 RETURN true;
END $$;
