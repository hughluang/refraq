CREATE TABLE IF NOT EXISTS source_mirror_state.version (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), version integer NOT NULL);
INSERT INTO source_mirror_state.version VALUES (true, 1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS source_mirror_state.mirrors (
 id text PRIMARY KEY, source_id text NOT NULL, table_identity text NOT NULL,
 authority jsonb NOT NULL, published_generation_id text,
 history_epoch text NOT NULL, commit_seq bigint NOT NULL DEFAULT 0,
 UNIQUE(source_id, table_identity)
);
ALTER TABLE source_mirror_state.mirrors
 ADD COLUMN IF NOT EXISTS excluded_capture_generations text[] NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS source_mirror_state.fence_receipts (
 mirror_id text NOT NULL REFERENCES source_mirror_state.mirrors,
 operation_id text NOT NULL, request jsonb NOT NULL, receipt_ref text NOT NULL,
 PRIMARY KEY (mirror_id, operation_id)
);
CREATE TABLE IF NOT EXISTS source_mirror_state.generations (
 id text PRIMARY KEY, mirror_id text NOT NULL REFERENCES source_mirror_state.mirrors,
 capture_generation text NOT NULL, operation_id text UNIQUE NOT NULL,
 table_name text UNIQUE NOT NULL, schema_fingerprint text NOT NULL,
 key_columns text[] NOT NULL, column_names text[] NOT NULL,
 partition_identity jsonb NOT NULL, applied_offset bigint NOT NULL,
 status text NOT NULL CHECK(status IN ('building','catching_up','complete','published','retired')),
 cleanup_pending boolean NOT NULL DEFAULT false
);
ALTER TABLE source_mirror_state.generations
 ADD COLUMN IF NOT EXISTS anchored_profile jsonb,
 ADD COLUMN IF NOT EXISTS anchored_coverage jsonb,
 ADD COLUMN IF NOT EXISTS anchored_publication jsonb;
CREATE TABLE IF NOT EXISTS source_mirror_state.live_log (
 mirror_id text NOT NULL REFERENCES source_mirror_state.mirrors,
 history_epoch text NOT NULL, commit_seq bigint NOT NULL, entry_seq integer NOT NULL,
 generation_id text NOT NULL, capture_generation text NOT NULL,
 origin text NOT NULL CHECK(origin = 'live'), operation text NOT NULL,
 typed_key jsonb NOT NULL, before_image jsonb, after_image jsonb,
 PRIMARY KEY(mirror_id, history_epoch, commit_seq, entry_seq)
);
CREATE TABLE IF NOT EXISTS source_mirror_state.certificates (
 operation_id text PRIMARY KEY, generation_id text NOT NULL UNIQUE REFERENCES source_mirror_state.generations,
 authority jsonb NOT NULL, evidence jsonb NOT NULL, verified_by text NOT NULL,
 published boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS source_mirror_state.reader_pins (
 run_id text NOT NULL, mirror_id text NOT NULL REFERENCES source_mirror_state.mirrors,
 generation_id text NOT NULL REFERENCES source_mirror_state.generations,
 PRIMARY KEY(run_id, mirror_id)
);

CREATE OR REPLACE FUNCTION source_mirror_state.target_version()
RETURNS integer LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT version FROM source_mirror_state.version WHERE singleton
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.delivery_metadata(gid text)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT jsonb_build_object(
  'generation_id', g.id, 'authority', m.authority, 'table_identity', m.table_identity,
  'mirror_id', m.id, 'operation_id', g.operation_id, 'history_epoch', m.history_epoch,
  'fence_receipt', (
   SELECT r.receipt_ref FROM source_mirror_state.fence_receipts r
   WHERE r.mirror_id = m.id AND r.request->'authority' = m.authority
     AND r.request->>'history_epoch' = m.history_epoch),
  'start_offset', obj_description(target.oid, 'pg_class')::jsonb->'start_offset',
  'capture_generation', g.capture_generation, 'schema_fingerprint', g.schema_fingerprint,
  'key_columns', CASE WHEN g.key_columns = (
   SELECT array_agg(a.attname::text ORDER BY k.ordinality) FROM pg_constraint pk
   CROSS JOIN LATERAL unnest(pk.conkey) WITH ORDINALITY k(attnum, ordinality)
   JOIN pg_attribute a ON a.attrelid = target.oid AND a.attnum = k.attnum
   WHERE pk.conrelid = target.oid AND pk.contype = 'p') THEN g.key_columns END,
  'column_names', g.column_names,
  'partition_identity', g.partition_identity, 'cleanup_pending', g.cleanup_pending,
  'status', g.status, 'native_types', (
   SELECT jsonb_object_agg(a.attname, format_type(a.atttypid, a.atttypmod))
   FROM pg_attribute a WHERE a.attrelid = target.oid AND a.attnum > 0 AND NOT a.attisdropped))
 || CASE WHEN g.anchored_profile IS NOT NULL THEN jsonb_build_object(
  'anchored_profile', g.anchored_profile, 'anchored_coverage', g.anchored_coverage,
  'anchored_seal', g.anchored_publication->'seal') ELSE '{}'::jsonb END
 FROM source_mirror_state.generations g
 JOIN source_mirror_state.mirrors m ON m.id = g.mirror_id
 LEFT JOIN pg_class target ON target.relnamespace = 'source_mirror'::regnamespace AND target.relname = g.table_name
 WHERE g.id = gid
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.apply_batch(a jsonb, gid text, p jsonb, records jsonb,
                                                         profile jsonb, scan jsonb, resume jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE
 m source_mirror_state.mirrors; g source_mirror_state.generations;
 certified source_mirror_state.certificates; seal_proof jsonb; sealed_end bigint;
 r jsonb; old_row jsonb; new_row jsonb; candidate jsonb; typed_key jsonb;
 predicate text; columns_sql text; updates_sql text; k text; n bigint;
 entries integer := 0; seq bigint; previous_offset bigint := NULL;
 scan_end bigint; bounds jsonb; pre_stable bigint; pre_high bigint;
 sealed boolean := coalesce(scan ? 'eof', false);
BEGIN
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid;
 IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT'; END IF;
 SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = g.mirror_id FOR UPDATE;
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid FOR UPDATE;
 IF m.id IS NULL OR g.id IS NULL
 OR m.authority IS DISTINCT FROM a OR g.capture_generation IS DISTINCT FROM a->>'capture_generation'
 OR g.capture_generation = ANY(m.excluded_capture_generations)
 OR g.partition_identity IS DISTINCT FROM p OR g.cleanup_pending
 OR g.status NOT IN ('building','catching_up','published') THEN
  RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT';
 END IF;
 IF profile IS DISTINCT FROM g.anchored_profile OR (profile IS NULL AND scan IS NOT NULL) THEN
  RAISE EXCEPTION 'MIRROR_COVERAGE_PROFILE_MISMATCH';
 END IF;
 IF resume IS NOT NULL AND (profile IS NULL OR scan IS NULL OR sealed) THEN
  RAISE EXCEPTION 'MIRROR_RESUME_BLOCKED';
 END IF;
 IF profile IS NOT NULL THEN
  IF profile->>'kind' IS DISTINCT FROM 'disposable_read_committed_v1'
   OR jsonb_typeof(profile->'leader_epoch') IS DISTINCT FROM 'number'
   OR profile->>'leader_epoch' !~ '^[0-9]+$'
   OR (g.applied_offset = -1 AND g.anchored_coverage IS NOT NULL
    AND g.anchored_coverage->'eof' IS DISTINCT FROM '0'::jsonb)
   OR ((g.applied_offset <> -1 OR g.anchored_coverage IS NOT NULL)
    AND g.anchored_coverage->'end' IS DISTINCT FROM to_jsonb(g.applied_offset + 1)) THEN
   RAISE EXCEPTION 'MIRROR_COVERAGE_PROFILE_MISMATCH';
  END IF;
  IF records = '[]'::jsonb AND scan IS NULL THEN
   RETURN jsonb_build_object('offset', g.applied_offset, 'commit_seq', m.commit_seq);
  END IF;
  IF resume IS NOT NULL THEN
   SELECT * INTO certified FROM source_mirror_state.certificates
   WHERE operation_id = g.operation_id AND generation_id = gid FOR SHARE;
   seal_proof := g.anchored_publication->'seal';
   IF NOT FOUND OR NOT certified.published OR certified.verified_by = ''
    OR certified.evidence IS DISTINCT FROM resume->'certificate'
    OR certified.authority IS DISTINCT FROM a OR m.source_id IS DISTINCT FROM a->>'source_id'
    OR certified.evidence->>'operation_id' IS DISTINCT FROM g.operation_id
    OR certified.evidence->>'generation_id' IS DISTINCT FROM gid
    OR certified.evidence->>'table_identity' IS DISTINCT FROM m.table_identity
    OR certified.evidence->>'schema_fingerprint' IS DISTINCT FROM g.schema_fingerprint
    OR certified.evidence->>'capture_generation' IS DISTINCT FROM g.capture_generation
    OR certified.evidence->'partition_identity' IS DISTINCT FROM p
    OR p->'partition' IS DISTINCT FROM '0'::jsonb
    OR m.published_generation_id IS DISTINCT FROM gid OR g.status <> 'published'
    OR g.anchored_publication->>'history_epoch' IS DISTINCT FROM m.history_epoch
    OR resume->>'history_epoch' IS DISTINCT FROM m.history_epoch
    OR seal_proof IS NULL OR seal_proof IS DISTINCT FROM certified.evidence->'ordered_delivery_proof'
    OR seal_proof->'authority' IS DISTINCT FROM a
    OR seal_proof->'eof' IS DISTINCT FROM seal_proof->'end'
    OR seal_proof->'before'->'leader_epoch' IS DISTINCT FROM profile->'leader_epoch'
    OR seal_proof->'after'->'leader_epoch' IS DISTINCT FROM profile->'leader_epoch'
    OR jsonb_typeof(seal_proof->'eof') IS DISTINCT FROM 'number'
    OR seal_proof->>'eof' !~ '^[0-9]+$' THEN
    RAISE EXCEPTION 'MIRROR_RESUME_BLOCKED';
   END IF;
   sealed_end := (seal_proof->>'eof')::bigint;
   bounds := g.anchored_coverage->'after';
   IF certified.evidence->'end_offset' IS DISTINCT FROM to_jsonb(sealed_end - 1)
    OR g.applied_offset < sealed_end - 1
    OR g.anchored_coverage->'authority' IS DISTINCT FROM a
    OR (g.applied_offset = sealed_end - 1 AND g.anchored_coverage IS DISTINCT FROM seal_proof)
    OR (g.applied_offset >= sealed_end AND (g.anchored_coverage ? 'eof'
     OR ((g.anchored_coverage->>'start')::bigint >= sealed_end) IS NOT TRUE
     OR bounds->'low' IS DISTINCT FROM '0'::jsonb
     OR bounds->'leader_epoch' IS DISTINCT FROM profile->'leader_epoch'
     OR jsonb_typeof(bounds->'stable') IS DISTINCT FROM 'number'
     OR jsonb_typeof(bounds->'high') IS DISTINCT FROM 'number'
     OR bounds->>'stable' !~ '^[0-9]+$' OR bounds->>'high' !~ '^[0-9]+$'
     OR (bounds->>'stable')::bigint < g.applied_offset + 1
     OR (bounds->>'high')::bigint < (bounds->>'stable')::bigint)) THEN
    RAISE EXCEPTION 'MIRROR_RESUME_BLOCKED';
   END IF;
  ELSIF g.status = 'published' THEN
   RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
  END IF;
  IF jsonb_typeof(scan) IS DISTINCT FROM 'object'
   OR jsonb_typeof(records) IS DISTINCT FROM 'array'
   OR (NOT sealed AND records = '[]'::jsonb)
   OR scan->'start' IS DISTINCT FROM to_jsonb(g.applied_offset + 1)
   OR jsonb_typeof(scan->'end') IS DISTINCT FROM 'number'
   OR scan->>'end' !~ '^[0-9]+$'
   OR jsonb_typeof(scan->'offsets') IS DISTINCT FROM 'array'
   OR scan->'offsets' IS DISTINCT FROM coalesce((
    SELECT jsonb_agg(record->'offset' ORDER BY ordinal)
    FROM jsonb_array_elements(records) WITH ORDINALITY AS batch(record, ordinal)), '[]'::jsonb) THEN
   RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
  END IF;
  scan_end := (scan->>'end')::bigint;
  IF sealed AND (g.status NOT IN ('building', 'catching_up')
   OR scan_end < g.applied_offset + 1 OR scan->'eof' IS DISTINCT FROM scan->'end') THEN
   RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
  END IF;
  pre_stable := (g.anchored_coverage->'after'->>'stable')::bigint;
  pre_high := (g.anchored_coverage->'after'->>'high')::bigint;
  FOREACH bounds IN ARRAY ARRAY[scan->'before', scan->'after'] LOOP
   IF bounds->'low' IS DISTINCT FROM '0'::jsonb
    OR bounds->'leader_epoch' IS DISTINCT FROM profile->'leader_epoch'
    OR jsonb_typeof(bounds->'stable') IS DISTINCT FROM 'number'
    OR jsonb_typeof(bounds->'high') IS DISTINCT FROM 'number'
    OR bounds->>'stable' !~ '^[0-9]+$' OR bounds->>'high' !~ '^[0-9]+$'
    OR (bounds->>'stable')::bigint < scan_end
    OR (bounds->>'stable')::bigint > (bounds->>'high')::bigint
    OR (sealed AND (bounds->'stable' IS DISTINCT FROM scan->'end'
     OR bounds->'high' IS DISTINCT FROM scan->'end'))
    OR (bounds->>'stable')::bigint < pre_stable OR (bounds->>'high')::bigint < pre_high THEN
    RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
   END IF;
   pre_stable := (bounds->>'stable')::bigint;
   pre_high := (bounds->>'high')::bigint;
  END LOOP;
  IF resume IS NULL AND g.anchored_coverage ? 'eof' THEN
   IF NOT sealed OR scan->'end' IS DISTINCT FROM g.anchored_coverage->'end'
    OR g.anchored_coverage->'authority' IS DISTINCT FROM a OR records <> '[]'::jsonb THEN
    RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
   END IF;
   RETURN jsonb_build_object('offset', g.applied_offset, 'commit_seq', m.commit_seq);
  END IF;
 END IF;
 seq := m.commit_seq + 1;
 SELECT string_agg(format('t.%1$I IS NOT DISTINCT FROM k.%1$I', c), ' AND ') INTO predicate FROM unnest(g.key_columns) c;
 SELECT string_agg(format('%I', c), ', '), string_agg(format('%1$I = EXCLUDED.%1$I', c), ', ')
 INTO columns_sql, updates_sql FROM unnest(g.column_names) c;
 FOR r IN SELECT value FROM jsonb_array_elements(records) LOOP
  n := (r->>'offset')::bigint;
  IF scan IS NULL THEN
   IF n < 0 OR (previous_offset IS NOT NULL AND n <> previous_offset + 1) THEN
    RAISE EXCEPTION 'MIRROR_DELIVERY_GAP';
   END IF;
   previous_offset := n;
   IF n <= g.applied_offset THEN CONTINUE; END IF;
   IF n <> g.applied_offset + 1 THEN RAISE EXCEPTION 'MIRROR_DELIVERY_GAP'; END IF;
  ELSIF jsonb_typeof(r->'offset') IS DISTINCT FROM 'number'
   OR r->>'offset' !~ '^[0-9]+$' OR n <= g.applied_offset OR n >= scan_end THEN
   RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
  END IF;
  IF r->>'table_identity' IS DISTINCT FROM m.table_identity
   OR r->>'capture_generation' IS DISTINCT FROM g.capture_generation
   OR r->>'origin' NOT IN ('live','baseline','recovery')
   OR r->>'operation' NOT IN ('upsert','delete','control','tombstone')
   OR r->>'operation' IS NULL OR r->>'origin' IS NULL THEN
   RAISE EXCEPTION 'MIRROR_ENVELOPE_INVALID';
  END IF;
  IF r->>'operation' IN ('upsert','delete') THEN
   IF g.status = 'published' AND r->>'origin' <> 'live' THEN RAISE EXCEPTION 'MIRROR_ENVELOPE_INVALID'; END IF;
   IF jsonb_typeof(r->'key') IS DISTINCT FROM 'object'
    OR (SELECT count(*) FROM jsonb_object_keys(r->'key')) <> cardinality(g.key_columns) THEN
    RAISE EXCEPTION 'MIRROR_KEY_INVALID';
   END IF;
   FOREACH k IN ARRAY g.key_columns LOOP
    IF NOT (r->'key' ? k) OR r->'key'->k = 'null'::jsonb THEN RAISE EXCEPTION 'MIRROR_KEY_INVALID'; END IF;
   END LOOP;
   EXECUTE format('SELECT to_jsonb(v) FROM jsonb_populate_record(NULL::source_mirror.%I, $1) v', g.table_name)
    INTO typed_key USING r->'key';
   SELECT jsonb_object_agg(c, typed_key->c) INTO typed_key FROM unnest(g.key_columns) c;
   IF EXISTS(SELECT 1 FROM jsonb_each(typed_key) WHERE value = 'null'::jsonb) THEN
    RAISE EXCEPTION 'MIRROR_KEY_INVALID';
   END IF;
   EXECUTE format('SELECT to_jsonb(t) FROM source_mirror.%1$I t, jsonb_populate_record(NULL::source_mirror.%1$I, $1) k WHERE %2$s', g.table_name, predicate)
    INTO old_row USING typed_key;
   new_row := NULL;
   IF r->>'operation' = 'upsert' THEN
    IF jsonb_typeof(r->'values') IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'MIRROR_ROW_INVALID'; END IF;
    candidate := r->'values';
    FOR k IN SELECT jsonb_array_elements_text(r->'unchanged_columns') LOOP
     IF old_row IS NULL OR NOT (k = ANY(g.column_names)) OR k = ANY(g.key_columns) THEN
      RAISE EXCEPTION 'MIRROR_UNCHANGED_VALUE_UNAVAILABLE';
     END IF;
     candidate := jsonb_set(candidate, ARRAY[k], old_row->k);
    END LOOP;
    IF (SELECT array_agg(c ORDER BY c) FROM jsonb_object_keys(candidate) c)
      IS DISTINCT FROM (SELECT array_agg(c ORDER BY c) FROM unnest(g.column_names) c) THEN
     RAISE EXCEPTION 'MIRROR_ROW_INVALID';
    END IF;
    EXECUTE format('SELECT to_jsonb(v) FROM jsonb_populate_record(NULL::source_mirror.%I, $1) v', g.table_name)
     INTO new_row USING candidate;
    FOREACH k IN ARRAY g.key_columns LOOP
     IF new_row->k IS DISTINCT FROM typed_key->k THEN RAISE EXCEPTION 'MIRROR_KEY_INVALID'; END IF;
    END LOOP;
    IF old_row IS DISTINCT FROM new_row THEN
     EXECUTE format('INSERT INTO source_mirror.%1$I (%2$s) SELECT %2$s FROM jsonb_populate_record(NULL::source_mirror.%1$I, $1) ON CONFLICT (%3$s) DO UPDATE SET %4$s',
      g.table_name, columns_sql, (SELECT string_agg(format('%I', c), ', ') FROM unnest(g.key_columns) c), updates_sql) USING candidate;
    END IF;
   ELSE
    EXECUTE format('DELETE FROM source_mirror.%1$I t USING jsonb_populate_record(NULL::source_mirror.%1$I, $1) k WHERE %2$s', g.table_name, predicate) USING r->'key';
   END IF;
   IF old_row IS DISTINCT FROM new_row AND r->>'origin' = 'live' THEN
    entries := entries + 1;
    INSERT INTO source_mirror_state.live_log VALUES
     (m.id, m.history_epoch, seq, entries, gid, g.capture_generation, 'live', r->>'operation', typed_key, old_row, new_row);
   END IF;
  END IF;
  g.applied_offset := n;
 END LOOP;
 IF sealed THEN
  g.applied_offset := scan_end - 1;
 ELSIF scan IS NOT NULL AND g.applied_offset <> scan_end - 1 THEN
  RAISE EXCEPTION 'MIRROR_COVERAGE_INVALID';
 END IF;
 UPDATE source_mirror_state.generations SET applied_offset = g.applied_offset,
  anchored_coverage = scan || jsonb_build_object('authority', a)
 WHERE id = gid;
 IF entries > 0 THEN
  UPDATE source_mirror_state.mirrors SET commit_seq = seq WHERE id = m.id;
 ELSE seq := m.commit_seq;
 END IF;
 RETURN jsonb_build_object('offset', g.applied_offset, 'commit_seq', seq);
END $$;
REVOKE EXECUTE ON FUNCTION source_mirror_state.apply_batch(jsonb,text,jsonb,jsonb,jsonb,jsonb,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION source_mirror_state.apply_batch(a jsonb, gid text, p jsonb, records jsonb,
                                                         profile jsonb, scan jsonb)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT source_mirror_state.apply_batch(a, gid, p, records, profile, scan, NULL::jsonb)
$$;
REVOKE EXECUTE ON FUNCTION source_mirror_state.apply_batch(jsonb,text,jsonb,jsonb,jsonb,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION source_mirror_state.apply_batch(a jsonb, gid text, p jsonb, records jsonb)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT source_mirror_state.apply_batch(a, gid, p, records, NULL::jsonb, NULL::jsonb)
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.publish_generation(op text, a jsonb, gid text, cert jsonb)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE m source_mirror_state.mirrors; g source_mirror_state.generations; c source_mirror_state.certificates;
BEGIN
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid;
 IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED'; END IF;
 SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = g.mirror_id FOR UPDATE;
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid FOR UPDATE;
 SELECT * INTO c FROM source_mirror_state.certificates WHERE operation_id = op FOR UPDATE;
 IF NOT FOUND OR c.generation_id <> gid OR c.evidence IS DISTINCT FROM cert
  OR c.authority IS DISTINCT FROM a OR m.authority IS DISTINCT FROM a
  OR g.capture_generation IS DISTINCT FROM a->>'capture_generation'
  OR g.capture_generation = ANY(m.excluded_capture_generations)
  OR cert->>'schema_fingerprint' IS DISTINCT FROM g.schema_fingerprint
  OR cert->'partition_identity' IS DISTINCT FROM g.partition_identity
  OR cert->>'capture_generation' IS DISTINCT FROM g.capture_generation
  OR cert->>'table_identity' IS DISTINCT FROM m.table_identity
  OR cert->>'operation_id' IS DISTINCT FROM g.operation_id
  OR cert->>'generation_id' IS DISTINCT FROM gid
  OR cert->>'end_offset' IS NULL
  OR g.cleanup_pending THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 IF c.published THEN
  IF m.published_generation_id IS DISTINCT FROM gid
   OR g.status IS DISTINCT FROM 'published'
   OR g.applied_offset < (cert->>'end_offset')::bigint THEN
   RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
  END IF;
  RETURN gid;
 END IF;
 IF m.published_generation_id IS NOT DISTINCT FROM gid
  OR g.applied_offset <> (cert->>'end_offset')::bigint
  OR g.status NOT IN ('building','catching_up','complete') THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 IF g.anchored_profile IS NOT NULL AND (c.verified_by = ''
  OR g.anchored_coverage->'eof' IS DISTINCT FROM to_jsonb(g.applied_offset + 1)
  OR g.anchored_coverage->'eof' IS DISTINCT FROM g.anchored_coverage->'end'
  OR g.anchored_coverage->'authority' IS DISTINCT FROM a
  OR g.anchored_coverage IS DISTINCT FROM cert->'ordered_delivery_proof') THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 IF m.published_generation_id IS NOT NULL THEN
  UPDATE source_mirror_state.generations SET status = 'retired' WHERE id = m.published_generation_id;
 END IF;
 UPDATE source_mirror_state.generations SET status = 'published',
  anchored_publication = CASE WHEN g.anchored_profile IS NOT NULL
   THEN jsonb_build_object('seal', g.anchored_coverage, 'history_epoch', m.history_epoch) END
 WHERE id = gid;
 UPDATE source_mirror_state.mirrors SET published_generation_id = gid WHERE id = m.id;
 UPDATE source_mirror_state.certificates SET published = true WHERE operation_id = op;
 RETURN gid;
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.acquire_pin(run text, mid text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE m source_mirror_state.mirrors; g source_mirror_state.generations; gid text;
BEGIN
 SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = mid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_READ_UNAVAILABLE'; END IF;
 SELECT generation_id INTO gid FROM source_mirror_state.reader_pins WHERE run_id = run AND mirror_id = mid;
 gid := coalesce(gid, m.published_generation_id);
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid FOR UPDATE;
 IF NOT FOUND OR g.cleanup_pending OR g.status NOT IN ('published','retired') THEN RAISE EXCEPTION 'MIRROR_READ_UNAVAILABLE'; END IF;
 INSERT INTO source_mirror_state.reader_pins VALUES(run, mid, gid) ON CONFLICT DO NOTHING;
 RETURN jsonb_build_object('run_id', run, 'mirror_id', mid, 'generation_id', gid, 'source_id', m.source_id);
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.resolve_source(mid text)
RETURNS text LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 SELECT source_id FROM source_mirror_state.mirrors WHERE id = mid
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.read_page(run text, mid text, after_key jsonb, page_limit integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE pinned_generation record; rows jsonb; cols text; key_sql text; last_key jsonb;
BEGIN
 IF page_limit < 1 OR page_limit > 500 THEN RAISE EXCEPTION 'MIRROR_PAGE_INVALID'; END IF;
 SELECT generation.id, generation.cleanup_pending, generation.key_columns, generation.table_name,
  CASE WHEN generation.status <> 'published' OR generation.capture_generation = ANY(mirror.excluded_capture_generations)
   THEN 'stale' ELSE 'unknown' END AS freshness
 INTO pinned_generation FROM source_mirror_state.reader_pins pin
 JOIN source_mirror_state.generations generation ON generation.id = pin.generation_id
 JOIN source_mirror_state.mirrors mirror ON mirror.id = pin.mirror_id
 WHERE pin.run_id = run AND pin.mirror_id = mid;
 IF NOT FOUND OR pinned_generation.cleanup_pending THEN RAISE EXCEPTION 'MIRROR_READ_UNAVAILABLE'; END IF;
 SELECT string_agg(format('t.%I', c), ', ') INTO cols FROM unnest(pinned_generation.key_columns) c;
 SELECT string_agg(format('k.%I', c), ', ') INTO key_sql FROM unnest(pinned_generation.key_columns) c;
 EXECUTE format('SELECT coalesce(jsonb_agg(to_jsonb(v)), ''[]''::jsonb) FROM (SELECT t.* FROM source_mirror.%1$I t, jsonb_populate_record(NULL::source_mirror.%1$I, $1) k WHERE $1 IS NULL OR ROW(%2$s) > ROW(%3$s) ORDER BY %2$s LIMIT $2) v', pinned_generation.table_name, cols, key_sql)
 INTO rows USING after_key, page_limit;
 SELECT jsonb_object_agg(c, rows->(jsonb_array_length(rows)-1)->c) INTO last_key FROM unnest(pinned_generation.key_columns) c;
 RETURN jsonb_build_object('rows', rows, 'next_key', CASE WHEN jsonb_array_length(rows) = page_limit THEN last_key ELSE NULL END,
 'generation_id', pinned_generation.id, 'freshness', pinned_generation.freshness);
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.release_run_pins(run text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
 DELETE FROM source_mirror_state.reader_pins WHERE run_id = run
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.close_generation(gid text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE g source_mirror_state.generations;
BEGIN
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid;
 IF NOT FOUND THEN RETURN; END IF;
 PERFORM 1 FROM source_mirror_state.mirrors WHERE id = g.mirror_id FOR UPDATE;
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid FOR UPDATE;
 IF g.status <> 'retired' OR EXISTS(SELECT 1 FROM source_mirror_state.reader_pins WHERE generation_id = gid) THEN
  RAISE EXCEPTION 'MIRROR_IN_USE';
 END IF;
 UPDATE source_mirror_state.generations SET cleanup_pending = true WHERE id = gid;
END $$;
