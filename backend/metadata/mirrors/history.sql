-- History is read from the sole writer's transactional live_log, never reconstructed.
ALTER TABLE source_mirror_state.mirrors ADD COLUMN IF NOT EXISTS retained_commit_seq bigint NOT NULL DEFAULT 0;
ALTER TABLE source_mirror_state.mirrors ADD COLUMN IF NOT EXISTS retained_entry_seq integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS source_mirror_state.history_invalidations (
 operation_id text PRIMARY KEY, transitions jsonb NOT NULL
);
ALTER TABLE source_mirror_state.history_invalidations ADD COLUMN IF NOT EXISTS excluded_lineages jsonb;

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

CREATE OR REPLACE FUNCTION source_mirror_state.observe_committed_publication(
 requested_mirror text, requested_operation text, requested_generation text, expected_authority jsonb, expected_epoch text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE mirror_row source_mirror_state.mirrors; generation_row source_mirror_state.generations;
 certificate_row source_mirror_state.certificates;
 allocation jsonb; bound jsonb; certified_offset numeric; start_offset numeric;
BEGIN
 SELECT * INTO mirror_row FROM source_mirror_state.mirrors WHERE id = requested_mirror FOR SHARE;
 IF NOT FOUND OR mirror_row.published_generation_id IS DISTINCT FROM requested_generation
  OR mirror_row.authority IS DISTINCT FROM expected_authority
  OR mirror_row.source_id IS DISTINCT FROM expected_authority->>'source_id'
  OR mirror_row.history_epoch IS DISTINCT FROM expected_epoch THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 SELECT * INTO generation_row FROM source_mirror_state.generations
 WHERE id = requested_generation AND mirror_id = requested_mirror AND operation_id = requested_operation FOR SHARE;
 IF NOT FOUND OR generation_row.status <> 'published' OR generation_row.cleanup_pending
  OR generation_row.capture_generation IS DISTINCT FROM expected_authority->>'capture_generation'
  OR generation_row.capture_generation = ANY(mirror_row.excluded_capture_generations) THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 SELECT * INTO certificate_row FROM source_mirror_state.certificates
 WHERE operation_id = requested_operation AND generation_id = requested_generation FOR SHARE;
 IF NOT FOUND OR NOT certificate_row.published OR certificate_row.authority IS DISTINCT FROM expected_authority
  OR certificate_row.verified_by = ''
  OR certificate_row.evidence->>'operation_id' IS DISTINCT FROM requested_operation
  OR certificate_row.evidence->>'generation_id' IS DISTINCT FROM requested_generation
  OR certificate_row.evidence->>'table_identity' IS DISTINCT FROM mirror_row.table_identity
  OR certificate_row.evidence->>'capture_generation' IS DISTINCT FROM generation_row.capture_generation
  OR certificate_row.evidence->>'schema_fingerprint' IS DISTINCT FROM generation_row.schema_fingerprint
  OR certificate_row.evidence->'partition_identity' IS DISTINCT FROM generation_row.partition_identity
  OR jsonb_typeof(certificate_row.evidence->'end_offset') IS DISTINCT FROM 'number'
  OR certificate_row.evidence->>'end_offset' !~ '^-?[0-9]+$' THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 allocation := source_mirror_state.delivery_metadata(generation_row.id);
 IF jsonb_typeof(allocation->'start_offset') IS DISTINCT FROM 'number'
  OR allocation->>'start_offset' !~ '^-?[0-9]+$' THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 certified_offset := (certificate_row.evidence->>'end_offset')::numeric;
 start_offset := (allocation->>'start_offset')::numeric;
 IF start_offset < -1 OR certified_offset < start_offset OR generation_row.applied_offset < certified_offset THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 bound := source_mirror_state.history_bound(mirror_row.id);
 IF ROW(mirror_row.retained_commit_seq, mirror_row.retained_entry_seq)
  > ROW(mirror_row.commit_seq, (bound->'upper_bound'->>'entry_seq')::integer) THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 RETURN jsonb_build_object('published_generation_id', mirror_row.published_generation_id, 'allocation', allocation,
  'certificate', jsonb_build_object('operation_id', certificate_row.operation_id,
   'generation_id', certificate_row.generation_id, 'authority', certificate_row.authority,
   'evidence', certificate_row.evidence, 'verified_by', certificate_row.verified_by, 'published', certificate_row.published),
  'applied_offset', generation_row.applied_offset, 'history_bound', bound);
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

CREATE OR REPLACE FUNCTION source_mirror_state.reset_history(op text, changes jsonb, history_loss boolean, replay_only boolean)
RETURNS boolean LANGUAGE plpgsql SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE change jsonb; m source_mirror_state.mirrors; previous source_mirror_state.history_invalidations;
 excluded_lineages jsonb;
BEGIN
 IF op IS NULL OR jsonb_typeof(changes) IS DISTINCT FROM 'array' OR jsonb_array_length(changes) = 0
 THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 -- Sorted stream locks match apply_batch and make multi-stream cleanup atomic.
 FOR change IN SELECT value FROM jsonb_array_elements(changes) ORDER BY value->>'mirror_id' LOOP
  PERFORM 1 FROM source_mirror_state.mirrors WHERE id = change->>'mirror_id' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 END LOOP;
 SELECT * INTO previous FROM source_mirror_state.history_invalidations WHERE operation_id = op;
 IF FOUND THEN
  IF previous.transitions IS DISTINCT FROM changes OR (previous.excluded_lineages IS NOT NULL) <> history_loss
  THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
  RETURN true;
 END IF;
 IF replay_only THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
 IF history_loss THEN excluded_lineages := '{}'::jsonb; END IF;
 FOR change IN SELECT value FROM jsonb_array_elements(changes) ORDER BY value->>'mirror_id' LOOP
  SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = change->>'mirror_id';
  IF m.history_epoch IS DISTINCT FROM change->>'old_epoch'
   OR nullif(change->>'history_epoch', '') IS NULL OR change->>'history_epoch' = m.history_epoch
  THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
  IF history_loss THEN
   IF nullif(m.authority->>'capture_generation', '') IS NULL THEN RAISE EXCEPTION 'MIRROR_HISTORY_INVALID'; END IF;
   m.excluded_capture_generations := ARRAY(
    SELECT lineage FROM (
     SELECT m.authority->>'capture_generation' AS lineage
     UNION SELECT unnest(m.excluded_capture_generations)
     UNION SELECT capture_generation FROM source_mirror_state.generations WHERE mirror_id = m.id
    ) lineages ORDER BY lineage);
   excluded_lineages := excluded_lineages || jsonb_build_object(m.id, m.excluded_capture_generations);
  END IF;
  UPDATE source_mirror_state.mirrors SET history_epoch = change->>'history_epoch', commit_seq = 0,
   retained_commit_seq = 0, retained_entry_seq = 0,
   excluded_capture_generations = m.excluded_capture_generations WHERE id = m.id;
  DELETE FROM source_mirror_state.live_log WHERE mirror_id = m.id;
 END LOOP;
 INSERT INTO source_mirror_state.history_invalidations(operation_id, transitions, excluded_lineages)
 VALUES (op, changes, excluded_lineages);
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.invalidate_history(op text, changes jsonb)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT source_mirror_state.reset_history(op, changes, false, false)
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.invalidate_lost_history(op text, changes jsonb, replay_only boolean)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT source_mirror_state.reset_history(op, changes, true, coalesce(replay_only, true))
$$;
