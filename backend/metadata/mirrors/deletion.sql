-- A retired identity can never be allocated again, including after a lost reply.
CREATE TABLE IF NOT EXISTS source_mirror_state.deletions (
 mirror_id text PRIMARY KEY,
 operation_id text NOT NULL UNIQUE,
 proof jsonb NOT NULL,
 purged boolean NOT NULL DEFAULT true
);
ALTER TABLE source_mirror_state.deletions ADD COLUMN IF NOT EXISTS purged boolean NOT NULL DEFAULT true;

CREATE OR REPLACE FUNCTION source_mirror_state.reject_deleted_mirror()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, source_mirror_state AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.id, 0));
 IF EXISTS (SELECT 1 FROM source_mirror_state.deletions WHERE mirror_id = NEW.id) THEN
  RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER reject_deleted_mirror BEFORE INSERT ON source_mirror_state.mirrors
FOR EACH ROW EXECUTE FUNCTION source_mirror_state.reject_deleted_mirror();

-- Managed allocation also supports a preinstalled fence, which skips the Mirror INSERT.
CREATE OR REPLACE FUNCTION source_mirror_state.reject_deleted_generation()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, source_mirror_state AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM source_mirror_state.deletions WHERE mirror_id = NEW.mirror_id) THEN
  RAISE EXCEPTION 'MIRROR_CONTROL_CONFLICT';
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER reject_deleted_generation BEFORE INSERT ON source_mirror_state.generations
FOR EACH ROW EXECUTE FUNCTION source_mirror_state.reject_deleted_generation();

CREATE OR REPLACE FUNCTION source_mirror_state.guard_deletion(mid text, op text, proof jsonb)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE target source_mirror_state.mirrors; receipt source_mirror_state.deletions;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(mid, 0));
 SELECT * INTO receipt FROM source_mirror_state.deletions WHERE mirror_id = mid;
 IF FOUND THEN
  IF receipt.operation_id <> op OR receipt.proof <> proof THEN RETURN 'stale'; END IF;
  RETURN CASE WHEN receipt.purged THEN 'completed' ELSE 'sealed' END;
 END IF;
 SELECT * INTO target FROM source_mirror_state.mirrors WHERE id = mid FOR UPDATE;
 IF NOT FOUND THEN
  RETURN CASE WHEN proof->'allow_absent' = 'true'::jsonb THEN 'ready' ELSE 'stale' END;
 END IF;
 IF target.source_id IS DISTINCT FROM proof->>'source_id'
  OR target.table_identity IS DISTINCT FROM proof->>'table_identity'
  OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(proof->'fences') AS fence
    JOIN source_mirror_state.fence_receipts f ON f.operation_id = fence->>'operation_id'
    WHERE f.mirror_id = mid AND f.request->'authority' = target.authority AND fence->'authority' = target.authority
     AND (fence->>'receipt' IS NULL OR f.receipt_ref = fence->>'receipt')) THEN
  RETURN 'stale';
 END IF;
 IF EXISTS (SELECT 1 FROM source_mirror_state.reader_pins WHERE mirror_id = mid) THEN RETURN 'pinned'; END IF;
 RETURN 'ready';
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.seal_deletion(mid text, op text, proof jsonb)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE status text;
BEGIN
 status := source_mirror_state.guard_deletion(mid, op, proof);
 IF status <> 'ready' THEN RETURN status; END IF;
 -- acquire_pin and all publication and apply paths honor these flags under the same row locks.
 UPDATE source_mirror_state.generations SET cleanup_pending = true, write_closed = true WHERE mirror_id = mid;
 INSERT INTO source_mirror_state.deletions(mirror_id, operation_id, proof, purged) VALUES(mid, op, proof, false);
 RETURN 'sealed';
END $$;

CREATE OR REPLACE FUNCTION source_mirror_state.purge_mirror(mid text, op text, proof jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state AS $$
DECLARE status text; generation source_mirror_state.generations;
BEGIN
 status := source_mirror_state.guard_deletion(mid, op, proof);
 IF status = 'completed' THEN RETURN; END IF;
 IF status <> 'sealed' THEN RAISE EXCEPTION 'MIRROR_IN_USE'; END IF;
 FOR generation IN SELECT * FROM source_mirror_state.generations WHERE mirror_id = mid ORDER BY id FOR UPDATE LOOP
  EXECUTE format('DROP TABLE source_mirror.%I', generation.table_name);
  DELETE FROM source_mirror_state.retained_deliveries WHERE generation_id = generation.id;
  DELETE FROM source_mirror_state.certificates WHERE generation_id = generation.id;
 END LOOP;
 DELETE FROM source_mirror_state.live_log WHERE mirror_id = mid;
 DELETE FROM source_mirror_state.generations WHERE mirror_id = mid;
 DELETE FROM source_mirror_state.fence_receipts WHERE mirror_id = mid;
 DELETE FROM source_mirror_state.mirrors WHERE id = mid;
 UPDATE source_mirror_state.deletions SET purged = true WHERE mirror_id = mid;
END $$;
