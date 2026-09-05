-- =============================================================================
-- 002_audit_ordering.sql — make the audit trail orderable
--
-- 001 defaulted created_at to now(), which in PostgreSQL is
-- transaction_timestamp(): every row written inside one transaction gets the
-- SAME timestamp. A bet that completes a wagering requirement writes two
-- transactions — the BET and the BONUS_CONVERT it triggers — so the audit trail
-- could not say which came first, and ORDER BY created_at returned them in
-- arbitrary order.
--
-- Two changes, because they solve different halves of the problem:
--
--  * clock_timestamp() makes the recorded times actually distinct, so
--    timestamps mean what a reader assumes they mean.
--
--  * seq is the ordering the audit trail should actually be read by. Wall
--    clocks are not monotonic — NTP steps them, and they can go backwards —
--    so an audit log must not depend on one to know what happened first.
-- =============================================================================

ALTER TABLE ledger_transactions ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE ledger_entries      ALTER COLUMN created_at SET DEFAULT clock_timestamp();
ALTER TABLE accounts            ALTER COLUMN created_at SET DEFAULT clock_timestamp();

-- Strictly increasing insertion order. Gaps are expected (a rolled-back
-- transaction consumes a value); only the relative order is meaningful.
ALTER TABLE ledger_transactions ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY;

CREATE UNIQUE INDEX ledger_transactions_seq_uq ON ledger_transactions (seq);
CREATE INDEX ledger_transactions_player_seq_idx ON ledger_transactions (player_id, seq DESC);
