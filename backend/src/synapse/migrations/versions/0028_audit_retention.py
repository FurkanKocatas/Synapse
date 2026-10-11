"""Audit retention (ADR 0022): a question's text beside its event, the periods, and the one
function that removes what is past them.

- ``audit_texts``: an event's text (a chat question), which the event's hashed details name by
  its SHA-256 (``text_sha256``), so the text can go after its period without touching the
  chain. Written once and never changed, as the events are.
- ``audit_settings``: the periods, one row, written by the migrator from the installation's
  configuration (``synapse db migrate``). No runtime role reads or writes it, and the floors
  are constraints: events stay at least 90 days, a question's text at least 30.
- ``audit_prune(tenant)``: removes the texts past their period, then the events past theirs,
  oldest first and never from the middle, with their texts and checkpoints, and appends an
  ``audit.prune`` event naming the last removed event's sequence and hash; verification starts
  from it. A security definer: only ``synapse_retention`` may run it, and the setting it raises
  for the triggers is the only way past them.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

from synapse.migrations.sql_helpers import tenant_rls

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_texts (
            tenant_id uuid NOT NULL,
            event_id  uuid NOT NULL REFERENCES audit_events (id),
            text      text NOT NULL CHECK (length(text) <= 4000),
            PRIMARY KEY (tenant_id, event_id),
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        );
        CREATE TRIGGER audit_texts_immutable
            BEFORE UPDATE OR DELETE ON audit_texts
            FOR EACH ROW EXECUTE FUNCTION audit_events_reject_change();
        CREATE TRIGGER audit_texts_no_truncate
            BEFORE TRUNCATE ON audit_texts
            FOR EACH STATEMENT EXECUTE FUNCTION audit_events_reject_change();
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_texts FROM synapse_runtime;
    """)
    op.execute(tenant_rls("audit_texts"))
    op.execute("""
        CREATE TABLE audit_settings (
            singleton          boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            keep_events_days   integer NOT NULL CHECK (keep_events_days BETWEEN 90 AND 3650),
            keep_question_days integer NOT NULL CHECK (keep_question_days BETWEEN 30 AND 3650),
            CHECK (keep_question_days <= keep_events_days)
        );
        INSERT INTO audit_settings (keep_events_days, keep_question_days) VALUES (365, 183);
        REVOKE ALL ON audit_settings FROM synapse_runtime;

        -- A row of the audit tables goes only inside audit_prune(), which raises this setting
        -- for its own transaction. The runtime roles hold no DELETE on them, so the setting
        -- alone opens nothing; TRUNCATE is refused always.
        CREATE OR REPLACE FUNCTION audit_events_reject_change() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' AND current_setting('synapse.audit_prune', true) = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'audit events are immutable';
            END $$;
    """)
    # The audit.prune event is hashed as synapse.audit.chain hashes every event: the SHA-256 of
    # its canonical JSON (sorted keys, no spaces). Every value in it is a number, a hex string,
    # a UUID or a timestamp, so the JSON is written here as it is in Python, without escaping.
    # Straight to the driver: SQLAlchemy would take the JSONs and the time formats colons
    # (":null", ":MI") for bind parameters.
    op.get_bind().exec_driver_sql("""
        CREATE FUNCTION audit_prune(tenant uuid) RETURNS jsonb
            LANGUAGE plpgsql SECURITY DEFINER
            SET search_path = synapse, pg_catalog
            AS $$
            DECLARE
                periods audit_settings;
                started timestamptz := now();
                events_before timestamptz;
                texts_before timestamptz;
                head_seq bigint;
                head_hash bytea;
                first_seq bigint;
                through_seq bigint;
                through_hash bytea;
                removed bigint := 0;
                texts bigint := 0;
                details text;
                document text;
                event_id uuid := gen_random_uuid();
            BEGIN
                SELECT * INTO STRICT periods FROM audit_settings;
                events_before := started - make_interval(days => periods.keep_events_days);
                texts_before := started - make_interval(days => periods.keep_question_days);
                PERFORM set_config('app.tenant_id', tenant::text, true);
                PERFORM pg_advisory_xact_lock(
                    hashtextextended('synapse.audit:' || tenant::text, 0));

                SELECT seq, hash INTO head_seq, head_hash FROM audit_events
                    WHERE tenant_id = tenant ORDER BY seq DESC LIMIT 1;
                IF head_seq IS NULL THEN
                    RETURN jsonb_build_object('events', 0, 'texts', 0);
                END IF;
                SELECT min(seq) INTO first_seq FROM audit_events WHERE tenant_id = tenant;
                -- The events before the first one still within the period: a prefix.
                SELECT coalesce(min(seq) - 1, head_seq) INTO through_seq FROM audit_events
                    WHERE tenant_id = tenant AND occurred_at >= events_before;

                PERFORM set_config('synapse.audit_prune', 'on', true);
                DELETE FROM audit_texts t USING audit_events e
                    WHERE t.tenant_id = tenant AND e.tenant_id = tenant AND e.id = t.event_id
                      AND (e.occurred_at < texts_before OR e.seq <= through_seq);
                GET DIAGNOSTICS texts = ROW_COUNT;
                IF through_seq >= first_seq THEN
                    SELECT hash INTO STRICT through_hash FROM audit_events
                        WHERE tenant_id = tenant AND seq = through_seq;
                    DELETE FROM audit_checkpoints WHERE tenant_id = tenant AND seq <= through_seq;
                    DELETE FROM audit_events WHERE tenant_id = tenant AND seq <= through_seq;
                    GET DIAGNOSTICS removed = ROW_COUNT;
                ELSE
                    through_seq := NULL;
                END IF;
                PERFORM set_config('synapse.audit_prune', 'off', true);
                IF removed = 0 AND texts = 0 THEN
                    RETURN jsonb_build_object('events', 0, 'texts', 0);
                END IF;

                details := '{"count":' || removed
                    || ',"cutoff":"' || audit_timestamp(events_before)
                    || '","questions":' || texts
                    || ',"questions_before":"' || audit_timestamp(texts_before)
                    || '","through_hash":' || coalesce('"' || encode(through_hash, 'hex') || '"',
                                                       'null')
                    || ',"through_seq":' || coalesce(through_seq::text, 'null') || '}';
                document := '{"action":"audit.prune","actor_ip":null,"actor_user_id":null,'
                    || '"details":' || details
                    || ',"id":"' || event_id
                    || '","occurred_at":"' || audit_timestamp(started)
                    || '","outcome":"success","prev_hash":"' || encode(head_hash, 'hex')
                    || '","schema_version":1,"seq":' || (head_seq + 1)
                    || ',"target_id":null,"target_type":"audit","tenant_id":"' || tenant
                    || '"}';
                INSERT INTO audit_events (tenant_id, seq, id, occurred_at, actor_user_id,
                                          actor_ip, action, target_type, target_id, outcome,
                                          details, schema_version, prev_hash, hash)
                VALUES (tenant, head_seq + 1, event_id, started, NULL, NULL, 'audit.prune',
                        'audit', NULL, 'success', details::jsonb, 1, head_hash,
                        sha256(convert_to(document, 'UTF8')));
                RETURN jsonb_build_object('events', removed, 'texts', texts,
                                          'through_seq', through_seq);
            END $$;

        -- A time as synapse.audit.chain writes it: UTC, microseconds, a Z.
        CREATE FUNCTION audit_timestamp(moment timestamptz) RETURNS text
            LANGUAGE sql IMMUTABLE SET search_path = pg_catalog
            AS $$ SELECT to_char(moment AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') $$;

        REVOKE ALL ON FUNCTION audit_prune(uuid) FROM PUBLIC, synapse_runtime;
        GRANT EXECUTE ON FUNCTION audit_prune(uuid) TO synapse_retention;
        REVOKE ALL ON FUNCTION audit_timestamp(timestamptz) FROM PUBLIC, synapse_runtime;
    """)


def downgrade() -> None:
    # Downgrades are not supported; recovery is by restoring a backup (ADR 0012).
    raise NotImplementedError
