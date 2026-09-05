import { Injectable } from '@nestjs/common';
import { PoolClient } from 'pg';
import {
  AccountType,
  LedgerEntryDraft,
  TransactionKind,
  TransactionView,
} from './domain/types';
import {
  IdempotencyKeyConflictException,
  UnbalancedTransactionException,
} from './domain/errors';

const SYSTEM_ACCOUNT_TYPES: ReadonlySet<AccountType> = new Set<AccountType>([
  'SYSTEM_DEPOSIT',
  'SYSTEM_PAYOUT',
  'SYSTEM_HOUSE',
]);

export interface LockedBalance {
  accountId: string;
  balance: bigint;
}

export interface ClaimKeyParams {
  idempotencyKey: string;
  requestHash: string;
  kind: TransactionKind;
  playerId: string | null;
  reference: string | null;
  metadata: Record<string, unknown>;
}

export interface ClaimKeyOutcome {
  transactionId: string;
  /**
   * Populated when this exact request was already processed. The caller must
   * return it as-is and perform no further writes.
   */
  replayedResult: Record<string, unknown> | null;
}

/**
 * All raw SQL lives here. The service layer above expresses business rules and
 * never writes a query, so the two concerns can be reviewed independently — and
 * so every write to the ledger goes through one small, auditable surface.
 */
@Injectable()
export class LedgerRepository {
  /**
   * Resolves an account, creating it on first use.
   *
   * The partial unique indexes on `accounts` make this safe under concurrency:
   * if two transactions race to create a player's first wallet, one INSERT
   * wins, the other's ON CONFLICT DO NOTHING blocks until the winner commits
   * and then falls through to the SELECT.
   */
  async getOrCreateAccount(
    client: PoolClient,
    playerId: string | null,
    type: AccountType,
    currency: string,
  ): Promise<string> {
    const inserted = await client.query<{ id: string }>(
      `INSERT INTO accounts (player_id, type, currency)
       VALUES ($1, $2, $3)
       ON CONFLICT DO NOTHING
       RETURNING id`,
      [playerId, type, currency],
    );

    if (inserted.rows.length > 0) {
      const accountId = inserted.rows[0].id;
      await client.query(
        `INSERT INTO account_balances (account_id, allow_negative) VALUES ($1, $2)`,
        [accountId, SYSTEM_ACCOUNT_TYPES.has(type)],
      );
      return accountId;
    }

    // IS NOT DISTINCT FROM treats NULL = NULL as true, so one query serves both
    // player accounts and system accounts (which have player_id IS NULL).
    const existing = await client.query<{ id: string }>(
      `SELECT id FROM accounts
       WHERE player_id IS NOT DISTINCT FROM $1 AND type = $2 AND currency = $3`,
      [playerId, type, currency],
    );
    return existing.rows[0].id;
  }

  /**
   * Takes row-level write locks on the given accounts and returns their current
   * balances.
   *
   * Locks are acquired in a deterministic order (sorted by account id) because
   * that is what prevents deadlocks: two transactions touching the same pair of
   * accounts in opposite orders will deadlock, and Postgres will kill one of
   * them. Sorting removes the cycle entirely.
   *
   * Until this transaction commits or rolls back, no other transaction can read
   * these rows FOR UPDATE — which is exactly how a concurrent bet is prevented
   * from spending a balance that is already being spent.
   */
  async lockBalances(client: PoolClient, accountIds: string[]): Promise<Map<string, bigint>> {
    const ordered = [...new Set(accountIds)].sort();

    const { rows } = await client.query<{ account_id: string; balance: string }>(
      `SELECT account_id, balance
       FROM account_balances
       WHERE account_id = ANY($1::uuid[])
       ORDER BY account_id
       FOR UPDATE`,
      [ordered],
    );

    // node-postgres returns BIGINT as a string, deliberately: an int8 does not
    // fit in a JS number. Parsing to BigInt here keeps the arithmetic exact.
    return new Map(rows.map((row) => [row.account_id, BigInt(row.balance)]));
  }

  /**
   * Writes one double-entry transaction: appends the entries to the immutable
   * log, then folds them into the derived balances.
   *
   * Callers must already hold locks on every account touched here.
   */
  async applyEntries(
    client: PoolClient,
    transactionId: string,
    entries: LedgerEntryDraft[],
    currency: string,
  ): Promise<void> {
    const sum = entries.reduce((acc, entry) => acc + entry.amount, 0n);
    if (sum !== 0n) {
      // Belt and braces: the service layer builds balanced transactions, but a
      // future code path that does not must fail here rather than quietly mint
      // or destroy money.
      throw new UnbalancedTransactionException(sum);
    }

    await client.query(
      `INSERT INTO ledger_entries (transaction_id, account_id, amount, currency)
       SELECT $1, account_id, amount, $4
       FROM unnest($2::uuid[], $3::bigint[]) AS t(account_id, amount)`,
      [
        transactionId,
        entries.map((entry) => entry.accountId),
        entries.map((entry) => entry.amount.toString()),
        currency,
      ],
    );

    // The ledger keeps one row per leg for audit granularity, but the balance
    // update must see one delta per account: UPDATE ... FROM applies a single
    // matching row per target, so duplicate account ids would silently drop a
    // leg. Aggregating first makes that impossible.
    const deltaByAccount = new Map<string, bigint>();
    for (const entry of entries) {
      deltaByAccount.set(entry.accountId, (deltaByAccount.get(entry.accountId) ?? 0n) + entry.amount);
    }

    // account_balances_non_negative aborts the whole transaction here if this
    // would overdraw a player account.
    await client.query(
      `UPDATE account_balances AS b
       SET balance = b.balance + t.amount,
           version = b.version + 1,
           updated_at = now()
       FROM unnest($1::uuid[], $2::bigint[]) AS t(account_id, amount)
       WHERE b.account_id = t.account_id`,
      [
        [...deltaByAccount.keys()],
        [...deltaByAccount.values()].map((amount) => amount.toString()),
      ],
    );
  }

  /**
   * Reserves the idempotency key for this operation.
   *
   * This is the entire idempotency mechanism, and it is the database that
   * enforces it. Two identical requests arriving at once both try to INSERT;
   * the unique index lets exactly one through, and the loser blocks on the
   * index until the winner commits, then reads back the stored result.
   */
  async claimIdempotencyKey(client: PoolClient, params: ClaimKeyParams): Promise<ClaimKeyOutcome> {
    const inserted = await client.query<{ id: string }>(
      `INSERT INTO ledger_transactions (idempotency_key, request_hash, kind, player_id, reference, metadata)
       VALUES ($1, $2, $3, $4, $5, $6::jsonb)
       ON CONFLICT (idempotency_key) DO NOTHING
       RETURNING id`,
      [
        params.idempotencyKey,
        params.requestHash,
        params.kind,
        params.playerId,
        params.reference,
        JSON.stringify(params.metadata),
      ],
    );

    if (inserted.rows.length > 0) {
      return { transactionId: inserted.rows[0].id, replayedResult: null };
    }

    const existing = await client.query<{
      id: string;
      request_hash: string;
      result: Record<string, unknown>;
    }>(
      `SELECT id, request_hash, result FROM ledger_transactions WHERE idempotency_key = $1`,
      [params.idempotencyKey],
    );

    const row = existing.rows[0];
    if (row.request_hash !== params.requestHash) {
      throw new IdempotencyKeyConflictException(params.idempotencyKey);
    }

    return { transactionId: row.id, replayedResult: row.result };
  }

  /** Snapshots the response so a later replay of the same request returns it verbatim. */
  async storeResult(
    client: PoolClient,
    transactionId: string,
    result: Record<string, unknown>,
  ): Promise<void> {
    await client.query(`UPDATE ledger_transactions SET result = $2::jsonb WHERE id = $1`, [
      transactionId,
      JSON.stringify(result),
    ]);
  }

  /**
   * A player's operations with the entries that make up each one, in insertion
   * order. Ordered by seq, not created_at: two transactions written inside one
   * database transaction share a timestamp — see migration 002.
   */
  async listTransactions(
    client: PoolClient,
    playerId: string,
    limit = 100,
  ): Promise<TransactionView[]> {
    const { rows } = await client.query<{
      seq: string;
      kind: TransactionKind;
      reference: string | null;
      created_at: Date;
      entries: { account: AccountType; amount: string }[];
    }>(
      `SELECT t.seq, t.kind, t.reference, t.created_at,
              json_agg(
                json_build_object('account', a.type, 'amount', e.amount::text)
                ORDER BY e.id
              ) AS entries
       FROM ledger_transactions t
       JOIN ledger_entries e ON e.transaction_id = t.id
       JOIN accounts a       ON a.id = e.account_id
       WHERE t.player_id = $1
       GROUP BY t.seq, t.id, t.kind, t.reference, t.created_at
       ORDER BY t.seq
       LIMIT $2`,
      [playerId, limit],
    );

    return rows.map((row) => ({
      seq: Number(row.seq),
      kind: row.kind,
      reference: row.reference,
      createdAt: row.created_at.toISOString(),
      entries: row.entries,
    }));
  }

  async getBalances(
    client: PoolClient,
    playerId: string,
    currency: string,
  ): Promise<{ real: bigint; bonus: bigint }> {
    const { rows } = await client.query<{ type: AccountType; balance: string }>(
      `SELECT a.type, b.balance
       FROM accounts a
       JOIN account_balances b ON b.account_id = a.id
       WHERE a.player_id = $1 AND a.currency = $2`,
      [playerId, currency],
    );

    let real = 0n;
    let bonus = 0n;
    for (const row of rows) {
      if (row.type === 'PLAYER_REAL') real = BigInt(row.balance);
      if (row.type === 'PLAYER_BONUS') bonus = BigInt(row.balance);
    }
    return { real, bonus };
  }

  /**
   * Recomputes a balance from the immutable log. Used by the reconciliation
   * check and by tests to assert the cache never drifts from the ledger.
   */
  async sumEntriesForAccount(client: PoolClient, accountId: string): Promise<bigint> {
    const { rows } = await client.query<{ sum: string | null }>(
      `SELECT COALESCE(SUM(amount), 0)::text AS sum FROM ledger_entries WHERE account_id = $1`,
      [accountId],
    );
    return BigInt(rows[0].sum ?? '0');
  }
}
