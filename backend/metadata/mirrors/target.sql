CREATE TABLE IF NOT EXISTS source_mirror_state.version (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), version integer NOT NULL);
INSERT INTO source_mirror_state.version VALUES (true, 1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS source_mirror_state.mirrors (
 id text PRIMARY KEY, source_id text NOT NULL, table_identity text NOT NULL,
 authority jsonb NOT NULL, published_generation_id text,
 history_epoch text NOT NULL, commit_seq bigint NOT NULL DEFAULT 0,
 UNIQUE(source_id, table_identity)
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
  'capture_generation', g.capture_generation, 'schema_fingerprint', g.schema_fingerprint,
  'key_columns', g.key_columns, 'column_names', g.column_names,
  'partition_identity', g.partition_identity, 'cleanup_pending', g.cleanup_pending,
  'status', g.status, 'native_types', (
   SELECT jsonb_object_agg(a.attname, format_type(a.atttypid, a.atttypmod))
   FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
   JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'source_mirror' AND c.relname = g.table_name
    AND a.attnum > 0 AND NOT a.attisdropped))
 FROM source_mirror_state.generations g
 JOIN source_mirror_state.mirrors m ON m.id = g.mirror_id WHERE g.id = gid
$$;

CREATE OR REPLACE FUNCTION source_mirror_state.apply_batch(a jsonb, gid text, p jsonb, records jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE
 m source_mirror_state.mirrors; g source_mirror_state.generations;
 r jsonb; old_row jsonb; new_row jsonb; candidate jsonb; typed_key jsonb;
 predicate text; columns_sql text; updates_sql text; k text; n bigint;
 entries integer := 0; seq bigint; previous_offset bigint := NULL;
BEGIN
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid;
 IF NOT FOUND THEN RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT'; END IF;
 SELECT * INTO m FROM source_mirror_state.mirrors WHERE id = g.mirror_id FOR UPDATE;
 SELECT * INTO g FROM source_mirror_state.generations WHERE id = gid FOR UPDATE;
 IF m.authority IS DISTINCT FROM a OR g.capture_generation IS DISTINCT FROM a->>'capture_generation'
 OR g.partition_identity IS DISTINCT FROM p OR g.cleanup_pending
 OR g.status NOT IN ('building','catching_up','published') THEN
  RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT';
 END IF;
 seq := m.commit_seq + 1;
 SELECT string_agg(format('t.%1$I IS NOT DISTINCT FROM k.%1$I', c), ' AND ') INTO predicate FROM unnest(g.key_columns) c;
 SELECT string_agg(format('%I', c), ', '), string_agg(format('%1$I = EXCLUDED.%1$I', c), ', ')
 INTO columns_sql, updates_sql FROM unnest(g.column_names) c;
 FOR r IN SELECT value FROM jsonb_array_elements(records) LOOP
  n := (r->>'offset')::bigint;
  IF n < 0 OR (previous_offset IS NOT NULL AND n <> previous_offset + 1) THEN
   RAISE EXCEPTION 'MIRROR_DELIVERY_GAP';
  END IF;
  previous_offset := n;
  IF n <= g.applied_offset THEN CONTINUE; END IF;
  IF n <> g.applied_offset + 1 THEN RAISE EXCEPTION 'MIRROR_DELIVERY_GAP'; END IF;
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
 UPDATE source_mirror_state.generations SET applied_offset = g.applied_offset WHERE id = gid;
 IF entries > 0 THEN
  UPDATE source_mirror_state.mirrors SET commit_seq = seq WHERE id = m.id;
 ELSE seq := m.commit_seq;
 END IF;
 RETURN jsonb_build_object('offset', g.applied_offset, 'commit_seq', seq);
END $$;

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
  OR cert->>'schema_fingerprint' IS DISTINCT FROM g.schema_fingerprint
  OR cert->'partition_identity' IS DISTINCT FROM g.partition_identity
  OR cert->>'capture_generation' IS DISTINCT FROM g.capture_generation
  OR cert->>'table_identity' IS DISTINCT FROM m.table_identity
  OR cert->>'operation_id' IS DISTINCT FROM g.operation_id
  OR cert->>'generation_id' IS DISTINCT FROM gid
  OR cert->>'end_offset' IS NULL
  OR g.applied_offset <> (cert->>'end_offset')::bigint OR g.cleanup_pending THEN
  RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED';
 END IF;
 IF c.published THEN RETURN gid; END IF;
 IF g.status NOT IN ('building','catching_up','complete') THEN RAISE EXCEPTION 'MIRROR_PUBLICATION_BLOCKED'; END IF;
 IF m.published_generation_id IS NOT NULL THEN
  UPDATE source_mirror_state.generations SET status = 'retired' WHERE id = m.published_generation_id;
 END IF;
 UPDATE source_mirror_state.generations SET status = 'published' WHERE id = gid;
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
DECLARE g source_mirror_state.generations; rows jsonb; cols text; key_sql text; last_key jsonb;
BEGIN
 IF page_limit < 1 OR page_limit > 500 THEN RAISE EXCEPTION 'MIRROR_PAGE_INVALID'; END IF;
 SELECT gen.* INTO g FROM source_mirror_state.generations gen JOIN source_mirror_state.reader_pins pin ON pin.generation_id = gen.id
 WHERE pin.run_id = run AND pin.mirror_id = mid;
 IF NOT FOUND OR g.cleanup_pending THEN RAISE EXCEPTION 'MIRROR_READ_UNAVAILABLE'; END IF;
 SELECT string_agg(format('t.%I', c), ', ') INTO cols FROM unnest(g.key_columns) c;
 SELECT string_agg(format('k.%I', c), ', ') INTO key_sql FROM unnest(g.key_columns) c;
 EXECUTE format('SELECT coalesce(jsonb_agg(to_jsonb(v)), ''[]''::jsonb) FROM (SELECT t.* FROM source_mirror.%1$I t, jsonb_populate_record(NULL::source_mirror.%1$I, $1) k WHERE $1 IS NULL OR ROW(%2$s) > ROW(%3$s) ORDER BY %2$s LIMIT $2) v', g.table_name, cols, key_sql)
 INTO rows USING after_key, page_limit;
 SELECT jsonb_object_agg(c, rows->(jsonb_array_length(rows)-1)->c) INTO last_key FROM unnest(g.key_columns) c;
 RETURN jsonb_build_object('rows', rows, 'next_key', CASE WHEN jsonb_array_length(rows) = page_limit THEN last_key ELSE NULL END,
 'generation_id', g.id, 'freshness', CASE WHEN g.status = 'published' THEN 'unknown' ELSE 'stale' END);
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
