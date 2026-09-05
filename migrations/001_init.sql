-- =============================================================================
-- 001_init.sql — core wallet schema
--
-- Design notes (the "why", so this file reads as documentation too):
--
--  * Money is stored as BIGINT in MINOR UNITS (cents). Never floats — 0.1 + 0.2
--    is not 0.3 in binary floating point, and a wallet that loses a cent per
--    million operations is a wallet nobody trusts.
--
--  * ledger_entries is the SOURCE OF TRUTH: an append-only, double-entry log.
--    account_balances is a DERIVED cache kept in the same DB transaction so
--    reads stay O(1). Both must always agree — see scripts/reconcile or the
--    invariant assertions in the test suite.
--
--  * Every invariant that can be enforced by the database IS enforced by the
--    database. Application code has bugs; CHECK constraints do not.
-- =============================================================================

CREATE TYPE account_type AS ENUM (
  'PLAYER_REAL',    -- withdrawable player money
  'PLAYER_BONUS',   -- bonus money, locked until wagering is met
  'SYSTEM_DEPOSIT', -- counterparty for money entering the system
  'SYSTEM_PAYOUT',  -- counterparty for money leaving the system
  'SYSTEM_HOUSE'    -- counterparty for bets, wins and bonus grants
);

CREATE TYPE transaction_kind AS ENUM (
  'DEPOSIT',
  'WITHDRAWAL',
  'BET',
  'WIN',
  'BONUS_GRANT',
  'BONUS_CONVERT'   -- bonus balance released to real after wagering completes
);

CREATE TYPE bonus_status AS ENUM ('ACTIVE', 'COMPLETED', 'FORFEITED');

-- -----------------------------------------------------------------------------
-- accounts
-- -----------------------------------------------------------------------------
CREATE TABLE accounts (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id  uuid,                    -- NULL for system accounts
  type       account_type NOT NULL,
  currency   char(3)      NOT NULL,
  created_at timestamptz  NOT NULL DEFAULT now(),

  -- system accounts have no player, player accounts must have one
  CONSTRAINT accounts_player_id_matches_type CHECK (
    (type IN ('PLAYER_REAL', 'PLAYER_BONUS') AND player_id IS NOT NULL) OR
    (type IN ('SYSTEM_DEPOSIT', 'SYSTEM_PAYOUT', 'SYSTEM_HOUSE') AND player_id IS NULL)
  )
);

-- A player has at most one account of each type per currency. This unique index
-- is what makes "get or create account" safe under concurrency: two parallel
-- first-deposits race, one wins, the other retries and finds the existing row.
CREATE UNIQUE INDEX accounts_player_type_currency_uq
  ON accounts (player_id, type, currency) WHERE player_id IS NOT NULL;

CREATE UNIQUE INDEX accounts_system_type_currency_uq
  ON accounts (type, currency) WHERE player_id IS NULL;

-- -----------------------------------------------------------------------------
-- account_balances — derived cache of SUM(ledger_entries.amount)
-- -----------------------------------------------------------------------------
CREATE TABLE account_balances (
  account_id     uuid PRIMARY KEY REFERENCES accounts (id) ON DELETE CASCADE,
  balance        bigint      NOT NULL DEFAULT 0,
  -- System accounts represent the outside world and legitimately run negative
  -- (the deposit account goes negative as money flows in). Player accounts
  -- must never go below zero — that would be credit we never extended.
  allow_negative boolean     NOT NULL DEFAULT false,
  version        bigint      NOT NULL DEFAULT 0,
  updated_at     timestamptz NOT NULL DEFAULT now(),

  -- The last line of defence against overdraft. Even if the service layer
  -- forgets to check, or a new code path is added carelessly, the transaction
  -- aborts here instead of handing a player money that does not exist.
  CONSTRAINT account_balances_non_negative CHECK (allow_negative OR balance >= 0)
);

-- -----------------------------------------------------------------------------
-- ledger_transactions — one row per business operation
-- -----------------------------------------------------------------------------
CREATE TABLE ledger_transactions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Caller-supplied key that makes an operation replay-safe. The unique index
  -- below is the whole idempotency mechanism: the database, not the
  -- application, decides who wins a race between two identical requests.
  idempotency_key text NOT NULL,

  -- Hash of the request payload. Same key + same payload => return the stored
  -- result. Same key + DIFFERENT payload => the caller has a bug, so we reject
  -- it loudly instead of silently returning someone else's outcome.
  request_hash    text NOT NULL,

  kind            transaction_kind NOT NULL,
  player_id       uuid,
  reference       text,   -- external id: round id, PSP payment id, ...
  metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- Snapshot of the response, replayed verbatim on a duplicate request.
  result          jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX ledger_transactions_idempotency_key_uq
  ON ledger_transactions (idempotency_key);

CREATE INDEX ledger_transactions_player_created_idx
  ON ledger_transactions (player_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- ledger_entries — append-only double-entry log
-- -----------------------------------------------------------------------------
CREATE TABLE ledger_entries (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  transaction_id uuid    NOT NULL REFERENCES ledger_transactions (id) ON DELETE RESTRICT,
  account_id     uuid    NOT NULL REFERENCES accounts (id) ON DELETE RESTRICT,

  -- Signed delta applied to this account: > 0 credit, < 0 debit.
  -- The entries of one transaction must sum to exactly zero — that is the
  -- double-entry invariant, asserted in code and by the test suite.
  amount         bigint  NOT NULL,
  currency       char(3) NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ledger_entries_amount_nonzero CHECK (amount <> 0)
);

CREATE INDEX ledger_entries_account_idx     ON ledger_entries (account_id, id DESC);
CREATE INDEX ledger_entries_transaction_idx ON ledger_entries (transaction_id);

-- -----------------------------------------------------------------------------
-- bonuses — wagering requirement tracking
-- -----------------------------------------------------------------------------
CREATE TABLE bonuses (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id           uuid    NOT NULL,
  currency            char(3) NOT NULL,
  granted_amount      bigint  NOT NULL,
  wagering_multiplier int     NOT NULL,

  -- granted_amount * wagering_multiplier, denormalised so the rule that applied
  -- at grant time survives later changes to the bonus campaign.
  wagering_required   bigint  NOT NULL,
  wagering_progress   bigint  NOT NULL DEFAULT 0,

  status              bonus_status NOT NULL DEFAULT 'ACTIVE',
  created_at          timestamptz  NOT NULL DEFAULT now(),
  completed_at        timestamptz,

  CONSTRAINT bonuses_amounts_positive CHECK (granted_amount > 0 AND wagering_multiplier > 0),
  CONSTRAINT bonuses_progress_non_negative CHECK (wagering_progress >= 0)
);

-- A player may hold only one active bonus per currency at a time. Enforced
-- here rather than in code so a concurrent double-grant cannot slip through.
CREATE UNIQUE INDEX bonuses_one_active_per_player_uq
  ON bonuses (player_id, currency) WHERE status = 'ACTIVE';
